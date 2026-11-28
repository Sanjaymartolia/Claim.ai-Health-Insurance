# ClaimSense Work Report, 23 to 28 November 2026

| Item | Detail |
|---|---|
| Document | CS-WORK-RPT-001, Issue 1 |
| Date | 28 November 2026 |
| Author | Sanjay Singh (solo; all owner roles), with Claude Code |
| Status | For review |
| Scope | All work from 23 to 28 November 2026: defect fixes, the app audit, housekeeping, Docker with real tools, case retry, the new repository, CI/CD and the CI trust audit |
| Writing standard | ASD-STE100 Simplified Technical English, adapted: short sentences and active voice, normal technical terms |
| Detail reports | `docs/FAILURE_AND_FIX_REPORT.md` (Docker, retry, settlement repeats), `docs/CI_TRUST_AUDIT.md` (CI trust audit), `eval/agentic/REPORT.md` section 6 (tool-use defects) |

## 1. Summary

In six days we fixed 15 defects in the agents, graph, tools and guardrails (section 3.1), the
code findings of a repository audit (section 3.3), and the case-retry and settlement defects
(section 3.5). We found 3 more "open" defects already fixed, and we cleaned the repository. We made the full stack run in Docker with real agents and real tools. We moved the
project to a new repository with a working CI/CD pipeline, and we audited that pipeline.

**Results.**

- **Tool use is clean.** 0 defects are open (AGENTIC-01 to -14 are fixed). Tool cases 64/64, hook
  cases 36/36, control cases 13/13.
- **All tests pass.** Product tests 499 passed and 3 skipped in CI. DeepEval 74/74. CI run #3 in
  the new repository passed all four jobs, the real-model release gate included.
- **The real stack runs.** In Docker, `/health` gives `"llm":"real","tools":"real"`. The UI,
  Grafana and Prometheus answer, and real claims settle.
- **CI is in place,** but the audit shows that a green run proves less than it seems (section 6).

**The most important open items.**

1. The held-out set and its gold answers are public in the old repository (rule 5).
2. A rounding change in the calculator passes the whole pipeline (no test pins the rounding).
3. CI blocks nothing: `main` has no protection.
4. The local `main` branch is 14 days old. The new work is on `fresh-main` (section 7).

## 2. What we did, in order

| Date | Work | Result |
|---|---|---|
| 23 Nov | Survey of open problems. CLAUDE.md now says the project is solo. | Done |
| 23 Nov | "Solve all the problems one by one": 15 defects fixed, 3 found already fixed | Section 3.1 |
| 23 to 24 Nov | Whole-repository audit, plus Chrome screenshots of each UI state | 82 + 78 candidate findings; UI and code fixes (sections 3.2, 3.3) |
| 24 Nov | Safety and correctness fixes; housekeeping; course kit and stale reports removed | Sections 3.3, 3.4 |
| 24 to 25 Nov | Docker with real tools; MCP mode in Docker; real agents in Docker | `FAILURE_AND_FIX_REPORT.md` F1, F6 |
| 25 Nov | Stuck cases: "stopped" status, retry route, UI Retry button | F2 to F5 |
| 26 to 27 Nov | Docker rebuild after the images were deleted (11.5 h download, checksum failure) | F7, F8 |
| 27 Nov | Real stack started: port conflict and an old API key fixed | F9, F10 |
| 27 Nov | Failure and fix report (checked against code and logs by three readers) | `FAILURE_AND_FIX_REPORT.md` |
| 27 Nov | New repository `Claim.ai-Health-Insurance`: one clean commit, no held-out data | Section 3.5 |
| 27 Nov | CI/CD in the new repository; real-model release gate with a repository secret | CI runs #1 to #4 green |
| 27 to 28 Nov | CI trust audit: 8 planted regressions, rerun, `actionlint`, `zizmor`, trend of 150 runs | `CI_TRUST_AUDIT.md` |
| 28 Nov | CI: `promtool` rule tests; manual Jaeger trace workflow | Section 3.5 |

## 3. Problems found and fixed in the code

### 3.1 Agents, graph, tools and guardrails (23 to 24 November)

| ID | Problem | Code | Fix | Test |
|---|---|---|---|---|
| AGENTIC-14 | After a settlement, the claim's status column stayed unchanged (0/140 writes) | `mcp_servers/claims_db.py` `record_history` | Takes the status from the settlement row | `test_settlement_safety.py` (2 tests); run: 140/140 |
| AGENTIC-11 | The patient-mismatch check flagged ordinary prose ("Patient discharged…") | `guardrails/guardrails.py` `_PATIENT_RE`, `check_consistency` | Reads only a labelled id that holds a digit | `test_guardrails_l15.py` (3 tests) |
| AGENTIC-09 | The flat 40-call budget stopped bills of about 30 lines | `hooks/hooks.py` `BudgetState`; `config/models.yaml` | Ceiling = 40 + 2 per bill line; DeepEval rule changed to match (24 Nov) | `test_tool_hooks.py` (60-line bill) |
| CFG-PATH | Hooks and the approval threshold read `models.yaml` from a missing folder and used hidden defaults | `hooks/hooks.py`, `mcp_servers/approvals.py` | Both use `config_path()` | 2 tests read the real config |
| AGENTIC-12 | A not-admissible claim skipped the fraud screen; a duplicate bill was not shown | `graph/nodes.py` `admissibility` | Runs the fraud screen (your ruling; ADR-0010 addendum) | 4 of 4 duplicate attacks flagged |
| AGENTIC-13 | A room line with no days was paid as 1 day, silently | `agents/fraud.py` | Never guess: the claim goes to a person (your ruling) | `test_fraud_checks.py` (2 tests) |
| AGENTIC-08 | The history write bypassed the tool belt: no permission check, no budget, no audit | `graph/nodes.py` `memory_update` | Writes through the settlement belt; new pin `record_history` | `test_tool_hooks.py` (2 tests) |
| MON-01 | One failed tariff lookup crashed the whole claim (86 of 192 in the drill) | `agents/fraud.py` `FraudAgent.run` | The failure becomes a flag; security errors still stop | 3 tests; drill: 0 crashes |
| AGT-08 | The 36-month waiting period was 1,080 days, not 36 calendar months | `agents/coverage.py` | `_add_months(first_inception, 36)` | boundary test |
| AGT-07 | An empty search result crashed coverage (`ps[0]`) | `agents/coverage.py` | Falls back to the hospitalisation clause | 1 test |
| AGT-04 | Bill text, diagnosis and clause text reached the model without data tags (rule 2) | `agents/coverage.py` `_ask_model`; `agents/critic.py` | All wrapped with `as_data` | 2 tests (real-model effect not measured) |
| AGT-05 | A rewrite table changed the bill wording and pushed the right clause out of the top 5 | `agents/coverage.py` `REWRITE` | Table removed; search uses its own glossary | 29/29 lines keep the gold clause |
| AGT-06 | Clause text was cut at 400 characters, before the operative words | `agents/coverage.py` `CANDIDATE_CHARS` | 2,000 characters (your choice) | 1 test (cost not measured yet) |
| PII-NAMES | Names and addresses were not masked before the model; raw ids were kept in memory | `guardrails/input_guardrails.py` `mask_pii` | Labelled names, honorifics and address lines masked; `hash_mapping` removed | 2 tests; seeds PII-06, PII-07 |
| CALC-CLAUSE2 | The product calculator paid an out-of-period claim in full (Rs 1,12,904 instead of Rs 0) | `calc/adjudication.py` `FULLY_DEDUCTED` | Clause 2 added; eval now scores the product calculator | 3 hand-worked cases in `tests/calc` |

Three items in the reports were already fixed in the code: the maternity mapping in
`CLAIM_REASONS`, the RT-012 spelt-out injection, and the made-up citation `policy_schedule:period`.

### 3.2 The app audit (23 to 24 November)

We drove the UI in Chrome through 20 states. There were no errors in the console. We found 5
large problems of hierarchy and density, and fixed 4:

1. The decision panel showed its warning far from the buttons. The warning is now inside the panel.
2. The start panel hid the case. It now folds after a start.
3. The header cut the status ("awaiting revi…"). The status is now in the title.
4. *Not changed:* amounts repeat 3 to 4 times, and long clause ids squeeze the text.
5. The empty dashboard drew rows of zeros. It now says "No claim decided yet".

### 3.3 Code fixes from the repository audit (24 November)

The first audit workflow stopped on a usage limit, so we verified its 82 candidate findings by
hand. A second pass with four more readers gave 78 findings, and we fixed 14 of them. Fixed:

- One injected note was reported twice. Now it is reported once per place.
- The link stripper left broken markup.
- Error runs were counted in turnaround and fraud-flag metrics.
- `seed_dev_policies --dry-run` created a database.
- The DSPy prompt drifted from the coverage prompt. Both now use shared render helpers.
- `as_data` let text close its own data wrapper.
- Traces kept full exception text. Now they keep only the exception type (rule 4).
- A blocking `harness-suite` stage was added to `eval.ship`.
- Dead code was deleted.

### 3.4 Housekeeping (24 November)

We deleted 84 tracked files: the course kit (26 files), replaced reports, duplicate guides,
orphan documents and stale run outputs. The product, eval, DeepEval and harness checks passed
after the removal.

### 3.5 Case retry, Docker, repository and CI (24 to 28 November)

| Area | Problem | Fix | Detail |
|---|---|---|---|
| Case API | A refused settlement left a case "running" with no way forward | "stopped" status, `POST /claims/{id}/retry`, UI Retry button; a refusal escalates | F2, F3 |
| Settlement | A repeat of a payment passed without an approval | Receipt only for the caller that holds the spent approval (`approvals.spent_by`) | F4 |
| Settlement | One approval could spend the record of another approval | `_find_signed_record` compares the whole token | F5 |
| Docker | Each build downloaded about 1 GB again | Pinned packages, BuildKit caches, `BASE` argument | F6 (in part) |
| Docker | The build failed: "pull access denied" | Build without `BASE` when the old image is gone | F7 |
| Docker | A damaged download failed its checksum after 11.5 hours | Built again | F8 |
| Start | Port 9090 in use; an old API key in the terminal | `eval.monitoring down`; new terminal | F9, F10 |
| Repository | The held-out set was in the old public repository | New repository with one clean commit and no held-out files; `.gitignore` excludes them | 27 Nov |
| CI | No real-model gate in the new repository | Secret `OPENROUTER_API_KEY` added; run #3 passed all four jobs | 27 Nov |
| CI | A loaded alert rule was not proof that it fires | `promtool test rules` in job `compose` (fails when the rule's `for:` changes) | 28 Nov |
| CI | No check of the traces | Manual workflow `observability.yml`: claims traced into Jaeger and read back | 28 Nov |
| CI | The planted rule-4 leak printed synthetic claim text into a public log | Log of run #9 deleted (the run record stays) | 28 Nov |

## 4. Where we hit actual problems

| Problem | Effect | What we do now |
|---|---|---|
| Our own fix caused a defect: the first lost-reply fix gave a receipt before the approval check | F4 | An adversarial review of each change to the money path |
| A second review found that a duplicate case could spend another case's approval | F5 | Compare the whole token |
| We told you that the pip cache kept torch; the log later showed 0 cache hits | Wrong advice | Report a cache hit only when the log shows it |
| We gave a `CLAIMSENSE_DOCKER_BASE` command without a check that the image exists | F7 | Examine `docker images` first |
| Workflow agents stopped on usage limits (144 of 146 in the first audit; 1 of 3 today) | Findings verified by hand | Keep the work resumable; do the rest inline |
| Scripted Python edits broke on backslashes | No edit was applied | Edit files with the editor tool |
| The post-edit `ruff --fix` hook removed imports that were unused for a moment | Imports restored by hand | Add the import and its use in one edit |
| The network was slow (about 18 KB/s at times) and dropped connections | Builds of many hours | Pinned packages; build from cache |
| The Docker images were deleted between 25 and 26 November (cause unknown) | Full rebuild | Do not prune images |
| VS Code kept the old API key in an open terminal | Every real call got HTTP 401 | Open a new terminal after a change to `.env` |

## 5. Your decisions

| Item | Decision |
|---|---|
| AGENTIC-12 | Run the fraud screen on not-admissible claims |
| AGENTIC-13 | Send a room line with no days to a person; do not guess |
| AGT-06 | Show 2,000 characters of each clause; measure the cost later |
| AGT-12 (contract fields) | Skip |
| Sub-limits from claim history | Skip (it touches `calc/`, where you write the cases first) |
| Stuck cases | Full fix: stopped status, retry route, Retry button |
| New repository | Fresh start: one commit, no held-out files, no run outputs |
| Run #9 log | Deleted |

## 6. What still needs code, or a decision

Each item was checked against the working tree on 28 November.

### Critical and high

| ID | What is missing | Where | Next step | Needs you |
|---|---|---|---|---|
| HO-1 | The held-out set and gold were exposed in the old repository | the old repository's history; local `main` still tracks 2 files | Done 28 Nov: the old repository is private. Still to do: treat the set as seen and regenerate it. Untrack the files locally (`git rm -r --cached`). Add the CI check from `CI_TRUST_AUDIT.md` C1 | Yes |
| GIT-1 | Local `main` is at 14 Nov with 283 uncommitted entries; the new work is on `fresh-main` | git branches | Make `fresh-main` (tracks `new/main`) your working branch. Do not commit the 283 entries onto the old `main` | Yes |
| CI-H1 | No test pins the rounding; a rounding change passes CI | `calc/adjudication.py:81`; `tests/calc/test_adjudication.py` | You write hand-worked tie cases, e.g. 10 % co-pay on Rs 1,234.45 = Rs 123.45 | Yes (the numbers) |
| CI-H2 | **Done 28 Nov.** Ruleset `main-gate`: pull request required; `test`, `compose`, `eval-gate` required. A direct push to `main` is refused (verified) | GitHub settings | None | — |
| CI-H3 | The real-model gate scores what the stub scores | `eval/harness/scorecard.py:155`; `eval/agent_suite/gate.yaml` | Add a gated model metric (clause match), run `eval-real` on agent changes, pin the prompts | Yes (paid) |
| SEC-1 | `get_llm('guard')` and `get_llm('judge')` silently use the coverage model | `agents/llm.py:17` `ROLES`, `:57` | Add `guard` and `judge` to `ROLES`; start with a failing test | No |

### Medium

| ID | What is missing | Where | Next step |
|---|---|---|---|
| CI-M1 | CI packages float; CI and the image differ | `ci.yml` installs; `docker/constraints-*.txt` | One hashed lock for CI and Docker |
| CI-M2 | Actions not pinned by hash; no `permissions:`; `ubuntu-latest` | `ci.yml` | Apply the hardening that `observability.yml` already uses |
| CI-M3 | `docker-compose.real.yml`, `eval/tests` (319) and DeepEval (74) are not in CI | `ci.yml` | Add the overlay check and both test suites |
| CI-M4 | The composite never moves; severity-high thresholds are not enforced | `scorecard.py:155` | Per-case baseline file; an ADR: enforce or rename |
| SEC-2 | A guard-model error reads as "clean" | `guardrails/guardrails.py:462-464` | Return a warning finding, as MON-01 does |
| SEC-3 | Two injection patterns can flag honest documents | `guardrails/guardrails.py:155, :162` | Narrow them; measure the false-block rate |
| SEC-7 | The eval never runs with tool hooks, so the scope check is not scored | `graph/build.py`; eval adapter | A hooks-on eval variant |
| DOCKER-3 | The real overlay accepts the demo reviewer tokens | `docker-compose.real.yml` | `CLAIMSENSE_REVIEWERS: ${CLAIMSENSE_REVIEWERS:?…}` |
| DOCKER-1, -2 | Containers run as root; search-model revisions not pinned | `Dockerfile*`; `retrieval/index.py:55, :67` | Non-root user; `revision=` |
| RET-1 | The hybrid retriever is not the default; p95 30.2 s against 30 s | `eval/harness/real_retrieval.py`; `policy_kb` | Faster re-ranker, then make it the default |
| RUB-D6 | No cost ceiling in product code; no response cache | `hooks/hooks.py:10-13` | Enforce `max_cost_usd_per_claim`; add a cache |
| MON-02, MON-04 | The tool-error alert fires late; one threshold sits inside normal noise | `eval/monitoring/alert_rules.yml` | New window and limit from a real baseline (paid) |
| DOC-STALE | Several reports still list fixed items as open | `EVALUATION_REPORT.md`, `SECURITY_REPORT_CARD.md`, `AGENT_SUITE_REPORT.md`, `MODEL_CARD.md`, `FRAMEWORK_RUBRIC_SCORE.md` | Update the `.md` files; rebuild DOCX/PDF with the builders |

### Low, partly done, or a decision only

- **CI-L1, CI-L2:**
  - The rule-4 test prints the leaked value (`tests/api/test_cases.py:182`).
  - There is no direct bare-token test.
  - `pytest` runs without `-rs`.
  - Artifact names lack `run_attempt`.
- **SEC-4:** an unlabelled name in free prose is not masked (no NER).
- **AGT-06:** the cost and accuracy of the longer clause text are not measured with a real model.
- **UI item 4:** repeated amounts and long clause ids.
- **DOCKER-4:** the pip cache mount did not keep files after a failed build. Cause not found.
- **DOCKER-5:** Jaeger is not a Docker Compose service.
- **RUB-D8:** `mypy` skips six packages.
- **RUB-D1:** the critic sends the worksheet back only once (the brief says once).
- **DRIFT-PROMPTS:** the prompts are inline, and REF-16 blocks moving them.
- **ADR-0002:** the contract gap (two fixture mappings).
- **Data:** the gold and the 49 retrieval labels are drafts until the Domain lead verifies them.
- **Paid runs that only you can start:** E1 and E4 real runs, a learning pass with approved lessons, judge calibration round 2, three held-out repeats (after HO-1), a scored online run.

## 7. State on 28 November

| Item | State |
|---|---|
| Local branch `main` | At `1b2c255` (14 Nov), 283 uncommitted entries (119 modified, 84 deleted, 80 new); still tracks 2 held-out files |
| Branch `fresh-main` | Tracks `new/main`; 5 commits, tip `90c0c85`; no held-out files |
| New repository | `Sanjaymartolia/Claim.ai-Health-Insurance`, public; `main` protected by ruleset `main-gate` (changes only through a pull request with green `test`, `compose` and `eval-gate`) |
| Old repository | `Sanjaymartolia/ClaimSense-Insurance`, private since 28 Nov |
| Docker | `claimsense-insurance-api-real` 3.09 GB and `claimsense-insurance-ui` 870 MB present; real stack verified |
| Secrets | `OPENROUTER_API_KEY` in `.env` and as a repository secret; `CLAIMSENSE_APPROVAL_SECRET` in `.env` |

## 8. Evidence

| Check | Result |
|---|---|
| Product tests (CI) | 499 passed, 3 skipped; strict API tests 59 passed |
| Eval package tests (CI) | 214 passed |
| Tool-use eval | Tools 64/64, hooks 36/36, controls 13/13, 0 open defects |
| DeepEval (stub) | 74/74 |
| CI run #3 (manual) | `test`, `compose`, `eval-gate`, `eval-real` all passed; real-model composite 0.984 |
| Rerun of run #4 | Same scorecard and same packages |
| Planted regressions | 5 of 6 caught (approvals, injection, tool pins, rule 4, Docker); rounding missed; 2 gap controls stayed green |
| `promtool` | Rule tests pass on both rule copies; fail when the alert's `for:` changes (local). On GitHub: CI run #13 (`90c0c85`) passed every job, the new step included |
| Jaeger check | `observability` run #1 on GitHub: 44/44 traces, 907/907 spans, no attribute off the redaction allowlist, all 7 checks ok (the same as the local trial) |

## 9. Recommended order

1. Plan a new held-out set (HO-1; the old repository is already private).
2. Make `fresh-main` your working branch (GIT-1).
3. ~~Apply the `main` ruleset (CI-H2).~~ Done 28 November.
4. Write the hand-worked rounding cases (CI-H1).
5. Fix `ROLES` for the guard and judge models (SEC-1).
6. Pin the CI packages and actions (CI-M1, CI-M2), and add the real overlay and the eval suites to CI (CI-M3).
7. Update the stale reports (DOC-STALE).
8. Then the paid runs, in the order you choose.
