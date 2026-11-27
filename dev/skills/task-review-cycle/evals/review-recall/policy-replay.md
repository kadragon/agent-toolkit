# Review-cycle policy replay

Apply the supplied review-cycle policy to each isolated case. Assume every reported defect is
reproducible, in scope, and adequately supported. For a finding, state its category and whether
it blocks or is queued. For an operational case, state the next action in one sentence. Return
one row per ID.

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
