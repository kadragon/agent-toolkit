#!/usr/bin/env python3
"""Regression tests for merge-and-cleanup.sh -- local branch and worktree cleanup.

The script is the single owner of local cleanup: `hub.sh merge` merges and deletes the
remote head only, on both GitHub and Forgejo. These cases pin the outcomes: deleted by
the script, a branch that never existed, a real failure (both must warn), a worktree
holding the feature branch (removed first, so the branch delete succeeds), and a base
checkout that fails after the remote merge (JSON still printed, cleanup skipped).

The real hub.sh is replaced by a stub next to a copy of the script, so no network is touched.

Run: python3 dev/skills/task-review-cycle/scripts/test_merge_and_cleanup.py
Exits 0 on success, 1 on the first failure.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "merge-and-cleanup.sh"
HUB = Path(__file__).resolve().parent / "hub.sh"
FEATURE = "feat/x"

# Stub hub.sh: report a successful merge and leave every local ref alone, as the real one does.
HUB_STUB = """#!/usr/bin/env bash
echo '{"merge_ok": true, "merge_output": "stub"}'
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def make_repo(tmp):
    repo = Path(tempfile.mkdtemp(dir=tmp))
    git(repo, "init", "-q", "-b", "main", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "a.md").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "[TEST] init")
    git(repo, "checkout", "-q", "-b", FEATURE)
    for branch in (FEATURE, "feat/typo", "feat/other"):
        slot = repo / ".git/task-cycle" / hashlib.sha256(branch.encode()).hexdigest()
        slot.mkdir(parents=True, exist_ok=True)
        (slot / "contract.md").write_text(
            "**Approval source:** user-invoked: fixture workflow\n"
            "**Allowed Git actions:** base-merge\n**Git limits:** none\n")
    return repo


def make_script_dir(tmp):
    d = Path(tempfile.mkdtemp(dir=tmp)) / "skills/task-review-cycle/scripts"
    d.mkdir(parents=True)
    shutil.copy(SCRIPT, d / "merge-and-cleanup.sh")
    shutil.copy(SCRIPT.with_name("broker-cleanup.py"), d)
    shutil.copy(SCRIPT.parent / "git-authority.sh", d / "git-authority.sh")
    state = d / "../../task-next/scripts/cycle_state.py"
    state.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT.parent / "../../task-next/scripts/cycle_state.py", state)
    shutil.copy(SCRIPT.parent / "../../task-next/scripts/worktree_sweep.py", state.parent)
    (d / "hub.sh").write_text(HUB_STUB, newline="\n")
    return d


def run(case, repo, script_dir, branch=FEATURE, base="main", worktree=None):
    args = ["bash", str(script_dir / "merge-and-cleanup.sh"), "1", base, branch, '{"squash":true}']
    if worktree:
        args.append(str(worktree))
    proc = subprocess.run(args, cwd=repo, check=False, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        fail(case, f"script exit {proc.returncode}, stderr: {proc.stderr.strip()!r}")
    out = json.loads(proc.stdout)
    if out["merge_ok"] is not True:
        fail(case, f"stub merge should report merge_ok true, got {out!r}")
    return out


def branch_exists(repo):
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{FEATURE}"], cwd=repo
    ).returncode == 0


def fail(case, detail):
    print(f"FAIL {case}: {detail}")
    sys.exit(1)


def case_hub_never_deletes_local(_tmp):
    # Two owners raced for the local branch (PR #280): gh's --delete-branch deleted it on GitHub,
    # the Forgejo path never did. Local cleanup now has one owner -- this script.
    code = [ln for ln in HUB.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
    if any("--delete-branch" in ln for ln in code):
        fail("hub_never_deletes_local", "hub.sh still passes --delete-branch to gh pr merge")
    print("ok hub_never_deletes_local")


def case_deleted_by_script(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    out = run("deleted_by_script", repo, d)
    msg = out["cleanup_message"]
    if msg != f"Local branch '{FEATURE}' deleted" or branch_exists(repo):
        fail("deleted_by_script", f"got {msg!r}, branch exists={branch_exists(repo)}")
    print("ok deleted_by_script")


def case_real_failure_still_warns(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # A branch checked out in another worktree cannot be deleted -- a genuine cleanup failure.
    git(repo, "checkout", "-q", "main")
    other = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(other), FEATURE)
    out = run("real_failure_still_warns", repo, d)
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or not branch_exists(repo):
        fail("real_failure_still_warns", f"got {msg!r}")
    git(repo, "worktree", "remove", "--force", str(other))
    print("ok real_failure_still_warns")


def case_unknown_branch_warns(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # A mistyped name never existed locally; its absence after the merge is not a success.
    out = run("unknown_branch_warns", repo, d, branch="feat/typo")
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or "not found" not in msg:
        fail("unknown_branch_warns", f"got {msg!r}")
    print("ok unknown_branch_warns")


def case_worktree_holding_branch(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # The worktree passed for removal holds the feature branch; deleting the branch first
    # always failed ("checked out at ..."), leaving it behind with a WARNING.
    git(repo, "checkout", "-q", "main")
    wt = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(wt), FEATURE)
    out = run("worktree_holding_branch", repo, d, worktree=wt)
    msg, wmsg = out["cleanup_message"], out["worktree_message"]
    if "WARNING" in msg or "WARNING" in wmsg or branch_exists(repo) or wt.exists():
        fail("worktree_holding_branch", f"got cleanup={msg!r} worktree={wmsg!r}")
    print("ok worktree_holding_branch")


def case_base_checkout_fails(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # The remote merge already landed; a failed local checkout must not swallow the result JSON.
    out = run("base_checkout_fails", repo, d, base="no-such-base")
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or "no-such-base" not in msg or not branch_exists(repo):
        fail("base_checkout_fails", f"got {msg!r}")
    print("ok base_checkout_fails")


# Stub gh for the real hub.sh: `pr merge` exits 0, `pr view` prints $GH_VIEW, `api` logs its args
# to $GH_LOG and exits $GH_API_RC (printing $GH_API_ERR on failure).
GH_STUB = """#!/usr/bin/env bash
case "$1 $2" in
  "pr merge") echo "merged or enqueued"; exit 0 ;;
  "pr view") [ "$GH_VIEW" = "null" ] && exit 1; echo "$GH_VIEW"; exit 0 ;;
esac
if [ "$1" = "api" ]; then
  printf '%s\\n' "$*" >> "$GH_LOG"
  [ "${GH_API_RC:-0}" = 0 ] || { echo "$GH_API_ERR" >&2; exit "$GH_API_RC"; }
  exit 0
fi
exit 1
"""


def run_hub_merge(tmp, view, api_rc=0, api_err=""):
    """Run the real hub.sh merge against a stub gh; return (json, api calls)."""
    repo = make_repo(tmp)
    git(repo, "remote", "add", "origin", "git@github.com:o/r.git")
    bindir = Path(tempfile.mkdtemp(dir=tmp))
    (bindir / "gh").write_text(GH_STUB, newline="\n")
    (bindir / "gh").chmod(0o755)
    log = bindir / "api.log"
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
               GH_VIEW=json.dumps(view), GH_LOG=str(log),
               GH_API_RC=str(api_rc), GH_API_ERR=api_err)
    proc = subprocess.run(["bash", str(HUB), "merge", "1", "squash"], cwd=repo, env=env,
                          check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        fail("hub_merge", f"exit {proc.returncode}: {proc.stderr.strip()!r}")
    calls = log.read_text().splitlines() if log.exists() else []
    return json.loads(proc.stdout), calls


def case_hub_remote_delete_when(tmp):
    # The remote head is deleted only once the PR is MERGED from a same-repo branch.
    merged = {"state": "MERGED", "headRefName": "feat/x", "isCrossRepository": False, "headRefOid": "a" * 40}
    out, calls = run_hub_merge(tmp, merged)
    if out["merge_ok"] is not True or out.get("queued") is not False:
        fail("hub_remote_delete_when", f"MERGED: got {out!r}")
    if out.get("head_sha") != merged["headRefOid"]:
        fail("hub_remote_delete_when", f"MERGED head not returned: {out!r}")
    if calls != ["api -X DELETE repos/{owner}/{repo}/git/refs/heads/feat/x"]:
        fail("hub_remote_delete_when", f"MERGED: api calls {calls!r}")
    _, calls = run_hub_merge(tmp, dict(merged, isCrossRepository=True))
    if calls:
        fail("hub_remote_delete_when", f"cross-repository head was deleted: {calls!r}")
    print("ok hub_remote_delete_when")


def case_hub_merge_queue_is_not_merged(tmp):
    # Under a merge queue gh exits 0 on enqueue; the PR is still OPEN, so nothing merged yet.
    out, calls = run_hub_merge(tmp, {"state": "OPEN", "headRefName": "feat/x",
                                     "isCrossRepository": False})
    if out["merge_ok"] is not False or out.get("queued") is not True or calls:
        fail("hub_merge_queue_is_not_merged", f"got {out!r}, api calls {calls!r}")
    print("ok hub_merge_queue_is_not_merged")


def case_merge_matches_reviewed_head(tmp):
    case = "merge_matches_reviewed_head"
    for remote_moved in (True, False):
        repo, scripts = make_repo(tmp), make_script_dir(tmp)
        shutil.copy(HUB, scripts / "hub.sh")
        git(repo, "remote", "add", "origin", "git@github.com:o/r.git")
        reviewed = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "checkout", "-qb", "feat/other")
        worktree = Path(tmp) / f"pinned-worktree-{remote_moved}"
        git(repo, "worktree", "add", "-q", str(worktree), FEATURE)

        bindir = Path(tempfile.mkdtemp(dir=tmp))
        gh = bindir / "gh"
        gh.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr merge")
    if [[ "$5" == --match-head-commit && "$6" != "$GH_REMOTE_HEAD" ]]; then
      echo "Head SHA changed" >&2
      exit 1
    fi
    ;;
  "pr view") echo '{"state":"MERGED","headRefName":"feat/x","isCrossRepository":false}' ;;
esac
""", encoding="utf-8", newline="\n")
        gh.chmod(0o755)
        log = bindir / "gh.log"
        env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
                   GH_LOG=str(log), GH_REMOTE_HEAD="1" * 40 if remote_moved else reviewed)
        proc = subprocess.run(
            ["bash", str(scripts / "merge-and-cleanup.sh"), "1", "main", FEATURE, '{"squash":true}',
             str(worktree), "--expected-head", reviewed],
            cwd=worktree, env=env, capture_output=True, text=True, check=True,
        )
        out = json.loads(proc.stdout)
        calls = log.read_text(encoding="utf-8").splitlines()
        if remote_moved:
            if (out["merge_ok"] or "Head SHA changed" not in out["merge_output"]
                    or not worktree.exists() or not branch_exists(repo) or len(calls) != 1):
                fail(case, f"the remote changed after CI but merge or cleanup proceeded: {out!r}, {calls!r}")
        elif not out["merge_ok"] or worktree.exists() or branch_exists(repo):
            fail(case, f"matching head should merge and clean up: {out!r}, {calls!r}")
        if calls[0] != f"pr merge 1 --squash --match-head-commit {reviewed}":
            fail(case, f"the reviewed SHA did not reach the merge command: {calls!r}")
    print("ok merge matches the reviewed head and preserves recovery when it moves")


def case_forgejo_expected_head_is_rejected(tmp):
    case = "forgejo_expected_head_is_rejected"
    repo = make_repo(tmp)
    git(repo, "remote", "add", "origin", "https://forgejo.example/o/r.git")
    bindir = Path(tempfile.mkdtemp(dir=tmp))
    log = bindir / "curl.log"
    curl = bindir / "curl"
    curl.write_text("#!/usr/bin/env bash\necho called >> \"$CURL_LOG\"\n"
                    "if [[ $3 == GET ]]; then printf '%s\\n200' \"$PR_RESPONSE\"; else printf '{}\\n200'; fi\n",
                    encoding="utf-8", newline="\n")
    curl.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
               FORGEJO_TOKEN="stub", CURL_LOG=str(log))
    args = ["bash", str(HUB), "merge", "1", "squash", FEATURE]
    reviewed = git(repo, "rev-parse", "HEAD").stdout.strip()
    proc = subprocess.run(args + [reviewed], cwd=repo, env=env, capture_output=True, text=True, check=True)
    out = json.loads(proc.stdout)
    if out["merge_ok"] or log.exists():
        fail(case, f"the hub allowed an explicitly pinned Forgejo merge: {out!r}")
    env["PR_RESPONSE"] = json.dumps({"merged": True, "head": {"sha": reviewed}})
    proc = subprocess.run(args, cwd=repo, env=env, capture_output=True, text=True, check=True)
    out = json.loads(proc.stdout)
    if not out["merge_ok"] or out.get("head_sha") != reviewed or not log.exists():
        fail(case, f"the existing Forgejo merge no longer reaches the API: {proc.stdout!r}")
    print("ok Forgejo keeps its existing merge and rejects an explicit GitHub-only SHA pin")


def case_hub_ref_is_encoded_and_failure_reported(tmp):
    # A raw `#` or `%` in the ref would target a different path; `/` separates segments.
    view = {"state": "MERGED", "headRefName": "feat/a#b%c", "isCrossRepository": False}
    out, calls = run_hub_merge(tmp, view, api_rc=1, api_err="HTTP 403: forbidden")
    if calls != ["api -X DELETE repos/{owner}/{repo}/git/refs/heads/feat/a%23b%25c"]:
        fail("hub_ref_is_encoded", f"api calls {calls!r}")
    if out["merge_ok"] is not True or "HTTP 403: forbidden" not in out["merge_output"]:
        fail("hub_delete_failure_reported", f"got {out!r}")
    print("ok hub_ref_is_encoded_and_failure_reported")


def case_cleanup_reports_queued(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    (d / "hub.sh").write_text(
        "#!/usr/bin/env bash\necho '{\"merge_ok\": false, \"queued\": true, \"merge_output\": \"q\"}'\n",
        newline="\n")
    proc = subprocess.run(["bash", str(d / "merge-and-cleanup.sh"), "1", "main", FEATURE,
                           '{"squash":true}'], cwd=repo, check=False, capture_output=True, text=True)
    out = json.loads(proc.stdout)
    if out["merge_ok"] is not False or out.get("queued") is not True \
            or "queued" not in out["merge_message"] or not branch_exists(repo):
        fail("cleanup_reports_queued", f"got {out!r}")
    print("ok cleanup_reports_queued")


def case_run_from_inside_worktree(tmp):
    # The caller's shell sits in the linked worktree being removed; base is checked out in the
    # main worktree, so checking it out here failed and skipped every cleanup step.
    repo, d = make_repo(tmp), make_script_dir(tmp)
    git(repo, "checkout", "-q", "main")
    wt = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(wt), FEATURE)
    proc = subprocess.run(["bash", "-c", 'bash "$@"; result=$?; cd /; exit "$result"', "caller",
                           str(d / "merge-and-cleanup.sh"), "1", "main", FEATURE, '{"squash":true}', "."],
                          cwd=wt, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        fail("run_from_inside_worktree", f"exit {proc.returncode}: {proc.stderr.strip()!r}")
    out = json.loads(proc.stdout)
    msg, wmsg = out["cleanup_message"], out["worktree_message"]
    if "WARNING" in msg or not wmsg or "WARNING" in wmsg or branch_exists(repo) or wt.exists():
        fail("run_from_inside_worktree", f"got cleanup={msg!r} worktree={wmsg!r}")
    print("ok run_from_inside_worktree")


def case_already_removed_worktree_does_not_keep_branch(tmp):
    repo, scripts = make_repo(tmp), make_script_dir(tmp)
    gone = Path(tmp) / "already-removed"
    out = run("already_removed_worktree", repo, scripts, worktree=gone)
    if branch_exists(repo) or "deleted" not in out["cleanup_message"]:
        fail("already_removed_worktree", f"got {out!r}")
    print("ok already_removed_worktree")


def case_inside_worktree_keeps_main_branch(tmp):
    # Moving to the main worktree must never switch the branch someone else has checked out there.
    repo, d = make_repo(tmp), make_script_dir(tmp)
    git(repo, "checkout", "-q", "-b", "feat/other", "main")
    wt = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(wt), FEATURE)
    proc = subprocess.run(["bash", "-c", 'bash "$@"; result=$?; cd /; exit "$result"', "caller",
                           str(d / "merge-and-cleanup.sh"), "1", "main", FEATURE, '{"squash":true}', "."],
                          cwd=wt, check=False, capture_output=True, text=True)
    out = json.loads(proc.stdout)
    current = git(repo, "branch", "--show-current").stdout.strip()
    if current != "feat/other" or wt.exists() or branch_exists(repo) \
            or "not updated" not in out["cleanup_message"]:
        fail("inside_worktree_keeps_main_branch", f"main checkout on {current!r}, got {out!r}")
    print("ok inside_worktree_keeps_main_branch")


def case_linked_worktree_without_path_stays(tmp):
    # No worktree_path: the script is not removing this worktree, so it does not leave it either.
    repo, d = make_repo(tmp), make_script_dir(tmp)
    git(repo, "checkout", "-q", "-b", "feat/other", "main")
    wt = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(wt), FEATURE)
    proc = subprocess.run(["bash", str(d / "merge-and-cleanup.sh"), "1", "main", FEATURE,
                           '{"squash":true}'], cwd=wt, check=False, capture_output=True, text=True)
    out = json.loads(proc.stdout)
    if git(repo, "branch", "--show-current").stdout.strip() != "feat/other":
        fail("linked_worktree_without_path_stays", f"main checkout switched: {out!r}")
    print("ok linked_worktree_without_path_stays")


def case_hub_merge_state_unconfirmed(tmp):
    # gh pr view failing after a successful merge is an unknown state, not a failed merge.
    out, calls = run_hub_merge(tmp, None)
    if out["merge_ok"] is not False or out.get("unconfirmed") is not True \
            or out.get("queued") is not False or calls:
        fail("hub_merge_state_unconfirmed", f"got {out!r}, api calls {calls!r}")
    print("ok hub_merge_state_unconfirmed")


def _force_remove(func, path, _exc):
    # git writes read-only object files; Windows refuses to delete them until they are writable.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def case_unauthorized_merge_never_calls_hub(tmp):
    for limit in ("pr-only", "no-push", "implementation-only", "unknown"):
        repo, d = make_repo(tmp), make_script_dir(tmp)
        slot = repo / ".git/task-cycle" / hashlib.sha256(FEATURE.encode()).hexdigest() / "contract.md"
        slot.write_text(slot.read_text().replace("**Git limits:** none", f"**Git limits:** {limit}"))
        marker = d / "called"
        (d / "hub.sh").write_text(f"#!/bin/bash\ntouch '{marker}'\n")
        proc = subprocess.run(["bash", str(d / "merge-and-cleanup.sh"), "1", "main", FEATURE,
                               '{"squash":true}'], cwd=repo, capture_output=True, text=True)
        if proc.returncode == 0 or marker.exists() or not branch_exists(repo):
            fail("unauthorized_merge", f"hub called or recovery lost with {limit}")
    print("ok unauthorized merge denied before hub and cleanup")


def case_hub_writes_check_authority(tmp):
    for subcommand, args in (("pr-create", ["--base", "main", "--title", "test"]),
                            ("merge", ["1", "squash"])):
        repo = make_repo(tmp)
        git(repo, "remote", "add", "origin", "git@github.com:o/r.git")
        slot = repo / ".git/task-cycle" / hashlib.sha256(FEATURE.encode()).hexdigest() / "contract.md"
        slot.write_text("**Approval source:** --from task-next --auto\n"
                        "**Allowed Git actions:** pr-write, base-merge\n**Git limits:** none\n")
        bindir = Path(tempfile.mkdtemp(dir=tmp))
        log = bindir / "writes"
        (bindir / "gh").write_text(f"#!/bin/bash\necho called >> '{log}'\n")
        (bindir / "gh").chmod(0o755)
        proc = subprocess.run(["bash", str(HUB), subcommand, *args], cwd=repo,
                              env=dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}"),
                              capture_output=True, text=True)
        if proc.returncode == 0 or log.exists():
            fail("hub authority", f"{subcommand} reached gh with flag-only source")
    print("ok hub create/merge deny before remote CLI")


def _repo_behind_origin(tmp):
    # Main checkout on base with origin/main one commit ahead, so a fast-forward is observable.
    repo, d = make_repo(tmp), make_script_dir(tmp)
    git(repo, "checkout", "-q", "main")
    bare = Path(tempfile.mkdtemp(dir=tmp)) / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    other = Path(tempfile.mkdtemp(dir=tmp)) / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True)
    git(other, "config", "user.email", "test@example.com")
    git(other, "config", "user.name", "test")
    git(other, "config", "commit.gpgsign", "false")
    (other / "b.md").write_text("b\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "[TEST] ahead")
    git(other, "push", "-q", "origin", "main")
    return repo, d


def _merge_stderr(repo, d, env=None, script=None):
    proc = subprocess.run(["bash", script or str(d / "merge-and-cleanup.sh"), "1", "main", FEATURE,
                           '{"squash":true}'], cwd=repo, check=False, capture_output=True,
                          text=True, env=env)
    return proc


def case_dirty_main_checkout_not_fast_forwarded(tmp):
    # A dirty main checkout (left as is by task-next --tree) must not move; a clean one still does.
    repo, d = _repo_behind_origin(tmp)
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "a.md").write_text("dirty\n")
    proc = _merge_stderr(repo, d)
    out = json.loads(proc.stdout)
    if (proc.returncode != 0 or git(repo, "rev-parse", "HEAD").stdout.strip() != head
            or "uncommitted" not in proc.stderr or out["merge_ok"] is not True
            or branch_exists(repo)):
        fail("dirty_main_checkout_not_fast_forwarded",
             f"rc {proc.returncode}, stderr {proc.stderr!r}, out {out!r}")
    repo, d = _repo_behind_origin(tmp)
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "scratch.txt").write_text("untracked\n")  # untracked only: still clean for the guard
    proc = _merge_stderr(repo, d)
    if proc.returncode != 0 or git(repo, "rev-parse", "HEAD").stdout.strip() == head:
        fail("dirty_main_checkout_not_fast_forwarded", f"clean checkout did not move: {proc.stderr!r}")
    print("ok dirty_main_checkout_not_fast_forwarded")


def case_script_dir_ignores_cdpath(tmp):
    # Relative invocation with CDPATH naming a dir that holds the same relative path: an unguarded
    # `cd` prints the resolved path twice, so SCRIPT_DIR holds two lines and `source` fails.
    repo, d = make_repo(tmp), make_script_dir(tmp)
    git(repo, "checkout", "-q", "main")
    rel = ".git/sd/skills"
    shutil.copytree(d.parents[1], repo / rel)
    decoy = Path(tempfile.mkdtemp(dir=tmp))
    (decoy / rel / "task-review-cycle/scripts").mkdir(parents=True)
    script = f"{rel}/task-review-cycle/scripts/merge-and-cleanup.sh"
    proc = _merge_stderr(repo, d, env={**os.environ, "CDPATH": str(decoy)}, script=script)
    if proc.returncode != 0 or not proc.stdout.strip():
        fail("script_dir_ignores_cdpath", f"rc {proc.returncode}, stderr {proc.stderr!r}")
    if json.loads(proc.stdout)["merge_ok"] is not True:
        fail("script_dir_ignores_cdpath", f"got {proc.stdout!r}")
    print("ok script_dir_ignores_cdpath")


def case_dispatch_records_only_confirmed_merge(tmp):
    repo, scripts = make_repo(tmp), make_script_dir(tmp)
    dispatch = scripts / "../../dispatch/scripts"
    dispatch.mkdir(parents=True)
    for name in ("dispatch.py", "phase_timing.py", "pinned_wave.py", "codex_app_server.py"):
        shutil.copy(SCRIPT.parent / "../../dispatch/scripts" / name, dispatch)
    receipt = scripts / "run.json"
    receipt.write_text('{"address": "t7"}', encoding="utf-8")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    command = ["bash", str(scripts / "merge-and-cleanup.sh"), "1", "main", FEATURE,
               '{"squash":true}', "--dispatch-run", str(receipt)]
    measurements = receipt.with_name("timing.json")
    case = "dispatch_records_only_confirmed_merge"
    for response in ({"merge_ok": False, "queued": True}, {"merge_ok": False, "unconfirmed": True},
                     {"merge_ok": True, "head_sha": head}):
        (scripts / "hub.sh").write_text(f"echo '{json.dumps(response)}'\n", encoding="utf-8")
        proc = subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True)
        if json.loads(proc.stdout)["merge_ok"] != response["merge_ok"]:
            fail(case, f"unexpected merge response: {proc.stdout}")
        if measurements.exists() != response["merge_ok"]:
            fail(case, f"timing file does not match merge confirmation: {response}")
    recorded = json.loads(measurements.read_text(encoding="utf-8"))["merge"]
    if recorded["head"] != head or not isinstance(recorded["confirmed_ms"], int):
        fail(case, f"invalid merge timing: {recorded}")
    print(f"ok {case}")


def main():
    tmp = tempfile.mkdtemp(prefix="merge-cleanup-")
    try:
        case_hub_writes_check_authority(tmp)
        case_unauthorized_merge_never_calls_hub(tmp)
        case_hub_never_deletes_local(tmp)
        case_deleted_by_script(tmp)
        case_real_failure_still_warns(tmp)
        case_unknown_branch_warns(tmp)
        case_worktree_holding_branch(tmp)
        case_base_checkout_fails(tmp)
        case_hub_remote_delete_when(tmp)
        case_hub_merge_queue_is_not_merged(tmp)
        case_merge_matches_reviewed_head(tmp)
        case_forgejo_expected_head_is_rejected(tmp)
        case_hub_ref_is_encoded_and_failure_reported(tmp)
        case_cleanup_reports_queued(tmp)
        case_run_from_inside_worktree(tmp)
        case_already_removed_worktree_does_not_keep_branch(tmp)
        case_inside_worktree_keeps_main_branch(tmp)
        case_linked_worktree_without_path_stays(tmp)
        case_hub_merge_state_unconfirmed(tmp)
        case_dirty_main_checkout_not_fast_forwarded(tmp)
        case_script_dir_ignores_cdpath(tmp)
        case_dispatch_records_only_confirmed_merge(tmp)
    finally:
        shutil.rmtree(tmp, onerror=_force_remove)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
