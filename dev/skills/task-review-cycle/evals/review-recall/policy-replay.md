# Review-cycle policy replay

Apply the supplied review-cycle policy to each isolated case. Assume each defect is verified.
Assume a GitHub PR and comment authority are available unless the case says otherwise.
For a finding, state its category and
whether it blocks, gets fixed, is queued, or goes to a PR comment. For an operational case,
state the next action in one sentence. Return one row per ID.

| ID | Case |
|----|------|
| p01 | The contract requires dry runs to preserve output files. The initial review shows that dry run truncates an existing output before deciding whether to save. |
| p02 | The contract requires retries to reuse the same request key. The first reviewer found that each attempt generates a new key. A late source reports the same still-unfixed defect after the general re-review has been used. |
| p03 | The contract requires the new command to support old-format records. A panel result arrives during pre-merge reclaim after the general re-review and shows that old records now fail to load. No earlier source reported this. |
| p04 | The contract requires stream errors to return failure. During a focused confirmation after the general re-review, current evidence shows that a newly changed reader still returns success for one stream error. The original confirmation concerned a different failure path. |
| p05 | A focused confirmation of the single fix for a contract finding shows that its original acceptance criterion still fails. |
| p06 | A late source arrives after the general re-review. It reports a new P1 behavior defect outside the Sprint Contract that has no security implications. |
| p07 | A late source arrives after the general re-review. It reports a new P1 security defect introduced by this branch. |
| p08 | One general re-review has completed. A resume starts on a new head, and CI requires a logic repair. The defect has no contract or security implications. Decide whether to launch another general review. |
| p09 | An intermediate review repair changes a single parser path. The narrowed parser tests pass and another accepted repair remains. Decide which local checks to run now. |
| p10 | All repairs and reclaim are settled, and CI for the final head is green. Only intermediate targeted checks are recorded locally. Decide whether the PR can be reported ready. |
| p11 | The full local suite passed on an earlier tree. A late repair changed a file the suite covers. Decide whether to reuse the old result for the final candidate. |
| p12 | A P2 bug in a path the PR reads also fails on the base. A synthetic test shows failure for a checkout named with a trailing tab. No normal workflow produces that name, and no user has reported the failure. |
| p13 | A P2 bug in touched code also fails on the base. A normal invocation using the default checkout path triggers it. |
| p14 | A P2 bug in code the PR reads also fails on the base. The input is unusual, but a user reported it from a real run and supplied logs that reproduce the failure. |
| p15 | The PR introduces a P2 bug. It has no contract or security implications and the author leaves it unresolved. |
| p16 | A pre-existing P3 nit in touched code affects the default workflow and has a real user report. |
| p17 | An introduced ordinary P1 fix fails its targeted check twice. The fix is withdrawn, and the remaining candidate still meets the contract and passes final checks. |
| p18 | An `--auto` run finds an introduced P2 defect in scope. The user approved the sprint but gave no specific approval for this optional review fix. |
| p19 | In a local-only `--auto` run with no PR, the advisory pass finds a `must-kill` comment explaining a workaround. Removing the workaround would require a code reshape. |

## Filing expectations

When running the replay, give the reviewer only the scenarios above. Score the new rows
against these candidate outcomes. The same threshold applies to GitHub and the file queue.

| ID | Expected outcome |
|----|------------------|
| p12 | PR comment only. A synthetic reproduction verifies the bug but does not establish everyday exposure. |
| p13 | Queue-eligible because the failure occurs on an everyday path. |
| p14 | Queue-eligible because the reproduction comes from real use. |
| p15 | PR comment only. An unresolved introduced P2 stays in the PR. |
| p16 | At most a PR comment. Exposure does not make P3 eligible for filing. |
| p17 | Queue the finding under the existing failed-fix deferral rule. |
| p18 | Leave a PR comment. The automatic blocking gate supplies no P2 fix approval. |
| p19 | Keep the source comment and record the advisory finding in the final cycle report and dispositions. |
