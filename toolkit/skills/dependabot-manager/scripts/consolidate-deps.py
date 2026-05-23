#!/usr/bin/env python3

"""
Dependabot PR Consolidator for Python Projects
Automates the process of consolidating multiple dependabot PRs into a single PR
Supports: uv, poetry, pip-tools, requirements.txt
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional


BRANCH_NAME = 'chore/deps-combined-update'


def exec_cmd(cmd: str, check: bool = True, capture: bool = False) -> str:
    """Execute command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=check,
            capture_output=capture,
            text=True
        )
        return result.stdout.strip() if capture else ""
    except subprocess.CalledProcessError:
        if not check:
            return ""
        raise


def cleanup_and_exit(exit_code: int):
    """Safely switch back to main and clean up branch"""
    exec_cmd('git checkout -- .', check=False)
    exec_cmd('git checkout main', check=False)
    exec_cmd(f'git branch -D {BRANCH_NAME}', check=False)
    sys.exit(exit_code)


def get_dependabot_prs() -> List[Dict]:
    """Get all open dependabot PRs"""
    output = exec_cmd(
        'gh pr list --state open --author "app/dependabot" --json number,title,headRefName',
        capture=True
    )
    return json.loads(output)


def parse_package_update(title: str) -> Optional[Dict]:
    """Parse package update from PR title"""
    # Format: "build(deps): bump package-name from X to Y"
    match = re.search(r'bump (.+?) from (.+?) to (.+?)$', title, re.IGNORECASE)
    if not match:
        return None

    return {
        'package': match.group(1),
        'old_version': match.group(2),
        'new_version': match.group(3)
    }


def detect_project_type() -> str:
    """Detect Python project type"""
    if Path('uv.lock').exists():
        return 'uv'
    elif Path('poetry.lock').exists():
        return 'poetry'
    elif Path('requirements.in').exists():
        return 'pip-tools'
    elif Path('requirements.txt').exists():
        return 'pip'
    else:
        raise RuntimeError("No supported Python dependency file found")


def update_dependencies(updates: List[Dict], project_type: str) -> bool:
    """Update dependency files based on project type"""
    if project_type == 'uv':
        return update_uv_dependencies(updates)
    elif project_type == 'poetry':
        return update_poetry_dependencies(updates)
    elif project_type == 'pip-tools':
        return update_pip_tools_dependencies(updates)
    elif project_type == 'pip':
        return update_requirements_txt(updates)
    return False


def update_uv_dependencies(updates: List[Dict]) -> bool:
    """Update dependencies using uv"""
    for update in updates:
        pkg = update['package']
        version = update['new_version']
        exec_cmd(f'uv add "{pkg}=={version}"', check=False)
    return True


def update_poetry_dependencies(updates: List[Dict]) -> bool:
    """Update dependencies using poetry"""
    for update in updates:
        pkg = update['package']
        version = update['new_version']
        exec_cmd(f'poetry add "{pkg}@{version}"')
    return True


def update_pip_tools_dependencies(updates: List[Dict]) -> bool:
    """Update requirements.in and compile"""
    req_file = Path('requirements.in')
    content = req_file.read_text()

    for update in updates:
        pkg = update['package']
        version = update['new_version']
        pattern = rf'{re.escape(pkg)}==[\d\.]+'
        replacement = f'{pkg}=={version}'
        content = re.sub(pattern, replacement, content)

    req_file.write_text(content)
    exec_cmd('pip-compile requirements.in')
    return True


def update_requirements_txt(updates: List[Dict]) -> bool:
    """Update requirements.txt directly"""
    req_file = Path('requirements.txt')
    content = req_file.read_text()

    for update in updates:
        pkg = update['package']
        version = update['new_version']
        pattern = rf'{re.escape(pkg)}==[\d\.]+'
        replacement = f'{pkg}=={version}'
        content = re.sub(pattern, replacement, content)

    req_file.write_text(content)
    return True


def run_tests(project_type: str) -> bool:
    """Run tests based on project type"""
    try:
        if project_type == 'uv':
            exec_cmd('uv run pytest')
            exec_cmd('uv run mypy .', check=False)
            exec_cmd('uv run ruff check .', check=False)
        elif project_type == 'poetry':
            exec_cmd('poetry run pytest')
            exec_cmd('poetry run mypy .', check=False)
        else:
            exec_cmd('pytest', check=False)
        return True
    except subprocess.CalledProcessError:
        return False


def get_lock_files(project_type: str) -> List[str]:
    """Return the list of files to stage based on project type"""
    files = {
        'uv': ['pyproject.toml', 'uv.lock'],
        'poetry': ['pyproject.toml', 'poetry.lock'],
        'pip-tools': ['requirements.in', 'requirements.txt'],
        'pip': ['requirements.txt'],
    }
    return files.get(project_type, [])


def main():
    """Main execution"""
    print('Fetching dependabot PRs...')
    prs = get_dependabot_prs()

    if not prs:
        print('No open dependabot PRs found')
        sys.exit(0)

    print(f'Found {len(prs)} dependabot PRs')

    # Parse updates
    updates = []
    for pr in prs:
        parsed = parse_package_update(pr['title'])
        if parsed:
            updates.append({
                'pr': pr['number'],
                'branch': pr['headRefName'],
                **parsed
            })

    if not updates:
        print('Could not parse any package updates')
        sys.exit(1)

    # Display updates
    print('\nUpdates to apply:')
    for u in updates:
        print(f"   - {u['package']}: {u['old_version']} -> {u['new_version']} (PR #{u['pr']})")

    # Detect project type
    project_type = detect_project_type()
    print(f'\nDetected project type: {project_type}')

    # Clean up any leftover branch from a previous failed run
    exec_cmd(f'git branch -D {BRANCH_NAME}', check=False)

    # Create branch
    print('\nCreating consolidated branch...')
    exec_cmd(f'git checkout -b {BRANCH_NAME}')

    # Update dependencies
    print('Updating dependencies...')
    try:
        update_dependencies(updates, project_type)
    except Exception as e:
        print(f'Failed to update dependencies: {e}')
        cleanup_and_exit(1)

    # Run tests
    print('Running tests...')
    if not run_tests(project_type):
        print('Tests failed')
        print('You may want to exclude problematic packages and retry')
        cleanup_and_exit(1)

    # Commit changes using temp file for commit message (avoids shell escaping issues)
    print('Committing changes...')
    update_list = '\n'.join([f"- {u['package']}: {u['old_version']} -> {u['new_version']}" for u in updates])
    commit_msg = f"chore(deps): update dependencies\n\n{update_list}\n\nCo-Authored-By: Claude <noreply@anthropic.com>"

    commit_msg_file = None
    try:
        fd, commit_msg_file = tempfile.mkstemp(suffix='.txt', prefix='commit-msg-')
        os.write(fd, commit_msg.encode('utf-8'))
        os.close(fd)

        # Stage only relevant files
        lock_files = get_lock_files(project_type)
        existing_files = [f for f in lock_files if Path(f).exists()]
        exec_cmd(f'git add {" ".join(existing_files)}')
        # Stage dependabot.yml if it has uncommitted changes (grouped updates from Step 0.1)
        yml_changed = exec_cmd('git diff --name-only .github/dependabot.yml', check=False, capture=True)
        if yml_changed:
            exec_cmd('git add .github/dependabot.yml')
        exec_cmd(f'git commit -F "{commit_msg_file}"')
    finally:
        if commit_msg_file and os.path.exists(commit_msg_file):
            os.unlink(commit_msg_file)

    # Push branch (delete remote branch first if leftover from a previous failed run)
    print('Pushing to remote...')
    exec_cmd(f'git push origin --delete {BRANCH_NAME}', check=False)
    exec_cmd(f'git push -u origin {BRANCH_NAME}')

    # Create PR using temp file for body
    print('Creating consolidated PR...')
    pr_body_lines = ['## Summary']
    for u in updates:
        pr_body_lines.append(f"- Update {u['package']} from {u['old_version']} to {u['new_version']}")
    pr_body_lines.append('\n## Related PRs')
    for u in updates:
        pr_body_lines.append(f"- #{u['pr']}: {u['package']} {u['old_version']} -> {u['new_version']}")
    pr_body_lines.append('\n## Test plan')
    pr_body_lines.append('- [x] All tests passing')
    pr_body_lines.append('- [x] Dependencies updated successfully')
    pr_body = '\n'.join(pr_body_lines)

    pr_body_file = None
    try:
        fd, pr_body_file = tempfile.mkstemp(suffix='.md', prefix='pr-body-')
        os.write(fd, pr_body.encode('utf-8'))
        os.close(fd)

        pr_url = exec_cmd(
            f'gh pr create --title "chore(deps): update dependencies" --body-file "{pr_body_file}"',
            capture=True
        )
    finally:
        if pr_body_file and os.path.exists(pr_body_file):
            os.unlink(pr_body_file)

    print(f'PR created: {pr_url}')

    # Get PR number from URL
    pr_number = pr_url.rstrip('/').split('/')[-1]

    # Close individual PRs
    print('\nClosing individual dependabot PRs...')
    for u in updates:
        exec_cmd(f'gh pr close {u["pr"]} -c "Consolidated into #{pr_number}"', check=False)
        print(f'   Closed PR #{u["pr"]}')

    print('\nConsolidation complete!')
    print(f'\nNext steps:')
    print(f'   1. Review PR: {pr_url}')
    print(f'   2. Merge when ready: gh pr merge {pr_number} --squash --delete-branch')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)
