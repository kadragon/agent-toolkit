#!/usr/bin/env node

/**
 * Dependabot PR Consolidator
 * Automates the process of consolidating multiple dependabot PRs into a single PR
 *
 * This script is in CommonJS format (.cjs) to ensure compatibility with both
 * CommonJS and ES module projects.
 *
 * Note: Uses execSync with shell commands intentionally — all inputs are from
 * gh CLI output (PR numbers, package names) not user input. This is a CLI
 * automation script, not a web service.
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const BRANCH_NAME = 'chore/deps-combined-update';

// Execute command and return output
function exec(cmd, options = {}) {
  try {
    const result = execSync(cmd, {
      encoding: 'utf-8',
      stdio: options.silent ? 'pipe' : 'inherit',
      ...options
    });
    // When stdio is 'inherit', execSync returns null
    if (result === null) return '';
    return result.trim();
  } catch (error) {
    if (options.ignoreError) return '';
    throw error;
  }
}

// Safely switch back to main and clean up branch
function cleanupAndExit(exitCode) {
  exec('git checkout -- .', { ignoreError: true });
  exec('git checkout main', { ignoreError: true });
  exec(`git branch -D ${BRANCH_NAME}`, { ignoreError: true });
  process.exit(exitCode);
}

// Get all open dependabot PRs
function getDependabotPRs() {
  const output = exec('gh pr list --state open --author "app/dependabot" --json number,title,headRefName,body', { silent: true });
  if (!output) return [];
  return JSON.parse(output);
}

// Parse package update from PR title (single-package PRs only)
function parsePackageUpdate(title) {
  // Format: "build(deps-dev): Bump @package/name from X to Y"
  const match = title.match(/Bump (.+?) from (.+?) to (.+?)$/i);
  if (!match) return null;

  return {
    package: match[1],
    oldVersion: match[2],
    newVersion: match[3]
  };
}

// Parse a grouped PR's body for its per-package updates.
// Grouped PR titles ("Bump the X group with N updates") don't carry versions,
// so the title regex returns nothing — the real updates live in the body as
// Dependabot's canonical "Updates `pkg` from A to B" lines. Anchor on that exact
// phrasing (capital "Updates", backticked package) so we skip the lowercase
// "bump tornado from ..." noise in nested changelog excerpts. Last occurrence
// per package wins (Dependabot lists the final target last).
function parseGroupPrBody(body) {
  const seen = new Map();
  // Version tokens are word chars, dots, hyphens, and '+' (PEP 440 local
  // versions; semver pre-release like 2.0.0-beta.3). The token must END in a
  // word char ([\w.+-]*\w): a real version never ends in a dot, so this drops
  // trailing markdown punctuation ("... to 1.4.7.") while keeping internal dots
  // — something neither \S+ nor a flat [\w.+-]+ class can do.
  const re = /Updates `(.+?)` from ([\w.+-]*\w) to ([\w.+-]*\w)/g;
  let m;
  while ((m = re.exec(body || '')) !== null) {
    seen.set(m[1], { package: m[1], oldVersion: m[2], newVersion: m[3] });
  }
  return Array.from(seen.values());
}

// Detect version prefix from existing value (^, ~, >=, etc.)
function detectVersionPrefix(currentValue) {
  if (!currentValue) return '^';
  const match = currentValue.match(/^([^\d]*)/);
  return match ? match[1] : '';
}

// Update package.json with new versions, preserving existing version prefixes
function updatePackageJson(updates) {
  const packageJsonPath = path.join(process.cwd(), 'package.json');
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8'));

  let updated = false;

  updates.forEach(({ package: pkg, newVersion }) => {
    // Check in dependencies
    if (packageJson.dependencies && packageJson.dependencies[pkg]) {
      const prefix = detectVersionPrefix(packageJson.dependencies[pkg]);
      packageJson.dependencies[pkg] = `${prefix}${newVersion}`;
      updated = true;
    }

    // Check in devDependencies
    if (packageJson.devDependencies && packageJson.devDependencies[pkg]) {
      const prefix = detectVersionPrefix(packageJson.devDependencies[pkg]);
      packageJson.devDependencies[pkg] = `${prefix}${newVersion}`;
      updated = true;
    }
  });

  if (updated) {
    fs.writeFileSync(packageJsonPath, JSON.stringify(packageJson, null, 2) + '\n');
  }

  return updated;
}

// Main execution
async function main() {
  console.log('Fetching dependabot PRs...');
  const prs = getDependabotPRs();

  if (prs.length === 0) {
    console.log('No open dependabot PRs found');
    process.exit(0);
  }

  console.log(`Found ${prs.length} dependabot PRs`);

  // Parse updates. Single-package PRs carry versions in the title; grouped PRs
  // ("Bump the X group with N updates") carry them only in the body. Try the
  // title first, then fall back to the body so grouped PRs aren't silently
  // dropped — a PR that parses as neither is reported loudly, never skipped in
  // silence (that would consolidate a partial set and look complete).
  const updates = [];
  prs.forEach(pr => {
    const parsed = parsePackageUpdate(pr.title);
    if (parsed) {
      updates.push({ pr: pr.number, branch: pr.headRefName, ...parsed });
      return;
    }

    const bodyUpdates = parseGroupPrBody(pr.body);
    if (bodyUpdates.length > 0) {
      bodyUpdates.forEach(bu => updates.push({ pr: pr.number, branch: pr.headRefName, ...bu }));
      return;
    }

    console.error(
      `WARNING: PR #${pr.number} ("${pr.title}") parsed from neither title nor ` +
      `body — SKIPPING. Consolidate it manually or its updates will be missing ` +
      `from the combined PR.`
    );
  });

  if (updates.length === 0) {
    console.log('Could not parse any package updates');
    process.exit(1);
  }

  // Display updates
  console.log('\nUpdates to apply:');
  updates.forEach(u => {
    console.log(`   - ${u.package}: ${u.oldVersion} -> ${u.newVersion} (PR #${u.pr})`);
  });

  // Clean up any leftover branch from a previous failed run
  exec(`git branch -D ${BRANCH_NAME}`, { ignoreError: true });

  // Create branch
  console.log('\nCreating consolidated branch...');
  exec(`git checkout -b ${BRANCH_NAME}`);

  // Update package.json
  console.log('Updating package.json...');
  const updated = updatePackageJson(updates);

  if (!updated) {
    console.log('No packages were updated in package.json');
    cleanupAndExit(1);
  }

  // Install dependencies
  console.log('Installing dependencies...');
  try {
    exec('npm install');
  } catch (error) {
    console.error('Failed to install dependencies');
    cleanupAndExit(1);
  }

  // Run tests
  console.log('Running tests...');
  try {
    exec('npm test');
  } catch (error) {
    console.error('Tests failed');
    console.log('You may want to exclude problematic packages and retry');
    cleanupAndExit(1);
  }

  // Commit changes using temp file to avoid shell escaping issues
  console.log('Committing changes...');
  const updatesList = updates.map(u => `- ${u.package}: ${u.oldVersion} -> ${u.newVersion}`).join('\n');

  const commitMsgFile = path.join(process.cwd(), '.commit-msg-tmp');
  fs.writeFileSync(commitMsgFile, `chore(deps): update dependencies

${updatesList}

Co-Authored-By: Claude <noreply@anthropic.com>`);

  try {
    exec('git add package.json package-lock.json');
    // Stage dependabot.yml if it has uncommitted changes (grouped updates from Step 0.1)
    const ymlChanged = exec('git diff --name-only .github/dependabot.yml', { silent: true, ignoreError: true });
    if (ymlChanged) {
      exec('git add .github/dependabot.yml');
    }
    exec(`git commit -F "${commitMsgFile}"`);
  } finally {
    if (fs.existsSync(commitMsgFile)) {
      fs.unlinkSync(commitMsgFile);
    }
  }

  // Push branch (force-delete remote branch if leftover from a previous failed run)
  console.log('Pushing to remote...');
  exec(`git push origin --delete ${BRANCH_NAME}`, { ignoreError: true });
  exec(`git push -u origin ${BRANCH_NAME}`);

  // Create PR using temp file for body
  console.log('Creating consolidated PR...');
  const prSummary = updates.map(u => `- Update ${u.package} from ${u.oldVersion} to ${u.newVersion}`).join('\n');
  const prRelated = updates.map(u => `- #${u.pr}: ${u.package}`).join('\n');

  const prBodyFile = path.join(process.cwd(), '.pr-body-tmp');
  fs.writeFileSync(prBodyFile, `## Summary
${prSummary}

## Related PRs
${prRelated}

## Test plan
- [x] All tests passing
- [x] Dependencies installed successfully`);

  let prUrl;
  try {
    prUrl = exec(`gh pr create --title "chore(deps): update dependencies" --body-file "${prBodyFile}"`, { silent: true });
  } finally {
    if (fs.existsSync(prBodyFile)) {
      fs.unlinkSync(prBodyFile);
    }
  }

  if (!prUrl || !prUrl.trim()) {
    console.error('Failed to create PR - no URL returned');
    process.exit(1);
  }

  console.log(`PR created: ${prUrl}`);

  // Get PR number from URL
  const prNumberMatch = prUrl.match(/\/pull\/(\d+)$/);
  if (!prNumberMatch) {
    console.error('Could not extract PR number from URL:', prUrl);
    process.exit(1);
  }
  const prNumber = prNumberMatch[1];

  // Close individual PRs. A grouped PR contributes one entry per package, all
  // sharing the same PR number — dedupe so we close (and log) each PR once
  // instead of N times.
  console.log('\nClosing individual dependabot PRs...');
  const closedPrNumbers = [...new Set(updates.map(u => u.pr))];
  closedPrNumbers.forEach(prNum => {
    exec(`gh pr close ${prNum} -c "Consolidated into #${prNumber}"`, { ignoreError: true });
    console.log(`   Closed PR #${prNum}`);
  });

  console.log('\nConsolidation complete!');
  console.log(`\nNext steps:`);
  console.log(`   1. Review PR: ${prUrl}`);
  console.log(`   2. Merge when ready: gh pr merge ${prNumber} --squash --delete-branch`);

  return {
    prNumber,
    prUrl,
    updates,
    closedPRs: closedPrNumbers
  };
}

// Exercise parseGroupPrBody against a canonical Dependabot grouped-PR body fixture.
// The fixture covers: two real "Updates `pkg`" lines, a lowercase changelog-noise
// line that must be ignored, a trailing-dot version that must be stripped, a
// pre-release version that must survive intact, and a duplicate package entry
// where the last occurrence must win.
function runSelftest() {
  const fixture = [
    'Updates `foo` from 1.0.0 to 1.1.0',
    'bump tornado from 6.0 to 6.1',           // lowercase → must be ignored
    'Updates `baz` from 1.0 to 1.4.7.',       // trailing dot → stripped by regex
    'Updates `bar` from 2.0.0 to 2.0.0-beta.1',  // pre-release → intact
    'Updates `foo` from 1.0.0 to 1.2.0',     // duplicate foo → last wins
  ].join('\n');

  const results = Object.fromEntries(
    parseGroupPrBody(fixture).map(r => [r.package, r])
  );

  // Two real packages parsed
  if (!results['foo']) throw new Error('foo missing from parsed results');
  if (!results['baz']) throw new Error('baz missing from parsed results');
  if (!results['bar']) throw new Error('bar missing from parsed results');

  // tornado (lowercase bump line) must be ignored
  if (results['tornado']) throw new Error('tornado should be ignored (lowercase bump line)');

  // foo: last-occurrence wins (1.2.0, not 1.1.0)
  if (results['foo'].newVersion !== '1.2.0')
    throw new Error(`foo newVersion should be 1.2.0 (last occurrence wins), got ${results['foo'].newVersion}`);
  if (results['foo'].oldVersion !== '1.0.0')
    throw new Error(`foo oldVersion should be 1.0.0, got ${results['foo'].oldVersion}`);

  // baz: trailing dot stripped → 1.4.7
  if (results['baz'].newVersion !== '1.4.7')
    throw new Error(`baz newVersion should be 1.4.7 (no trailing dot), got ${results['baz'].newVersion}`);

  // bar: pre-release intact
  if (results['bar'].newVersion !== '2.0.0-beta.1')
    throw new Error(`bar newVersion should be 2.0.0-beta.1, got ${results['bar'].newVersion}`);

  console.log('selftest OK');
}

// Run if called directly
if (require.main === module) {
  if (process.argv.includes('--selftest')) {
    // Explicit exit codes — don't rely on Node's default uncaught-exception
    // handler for the non-zero exit; a CI wrapper could swallow the throw.
    try {
      runSelftest();
      process.exit(0);
    } catch (e) {
      console.error(e.message);
      process.exit(1);
    }
  }
  main().catch(error => {
    console.error('Error:', error.message);
    process.exit(1);
  });
}

module.exports = { main, getDependabotPRs, parsePackageUpdate, parseGroupPrBody, updatePackageJson, runSelftest };
