# ClaimSense Failure and Fix Report

## Docker with real tools, case retry and settlement repeats, 24 to 27 November 2026

| Item | Detail |
|---|---|
| Document | CS-OPS-FR-001, Issue 1 |
| Date | 27 November 2026 |
| Author | Sanjay Singh (solo; all owner roles) |
| Status | For review |
| Scope | The real-tools Docker stack, stopped cases and retry, repeated settlement calls, the Docker build, the real-API start |
| Writing standard | ASD-STE100 Simplified Technical English (adapted) |
| Source file | `docs/FAILURE_AND_FIX_REPORT.md` |
| Code state | The working tree of 27 November 2026 |
| Check of this report | Three independent checkers compared each statement with the code, the build logs and the session record. We applied each confirmed correction. |

## 1. Summary

From 24 to 27 November 2026 we made the full stack run in Docker with real agents and real
tools. During this work, eleven failures occurred. Each section below gives the symptom, the
code that had the error, the cause and the fix.

Four failures were in the product code and one was in its tests. Three were in the Docker
build. Three were in the local set-up: the secret, the ports and the API key. We fixed ten
failures fully. We fixed one failure (F6) in part.

**Result.** The stack now runs in Docker with real agents and real tools. The UI shows
"agents: real · tools: real". Grafana and Prometheus read the API metrics. All the checks pass.

| No. | Failure | Type | Status |
|---|---|---|---|
| F1 | The UI showed stub agents in the "real" stack | Set-up | Fixed |
| F2 | A refused settlement left the case stuck as "running" | Product code | Fixed |
| F3 | Seven defects in the first fix for F2 (review) | Product code | Fixed |
| F4 | A repeat of a settlement passed without an approval | Product code | Fixed |
| F5 | One approval could spend the record of a different approval | Product code | Fixed |
| F6 | Each Docker build downloaded the packages and models again | Build | Fixed in part |
| F7 | The build failed with "pull access denied" | Build | Fixed |
| F8 | A package download failed its checksum after 11.5 hours | Build | Fixed |
| F9 | Prometheus and Grafana did not start: port 9090 was in use | Set-up | Fixed |
| F10 | A case stopped with `OpenAIAuthenticationError` | Set-up | Fixed |
| F11 | Two tool-use cases and DeepEval failed after F4 and F5 | Test | Fixed |

## 2. Failures in the product code and its tests

### F2. A refused settlement left the case stuck as "running"

**Symptom.** Our own check found this failure, in Docker MCP mode with stub agents. The check
case CLM-0004-mcp-1125b was a second case for claim CLM-0004. The case did not end. The API
gave status "running" with no review pending. A new decision got HTTP 409: "no decision is
pending on this case". Thus the case could not continue.

**Code.** `src/claimsense/graph/nodes.py`, nodes `settle` and `repudiate`. The claims database
refused the payment with `PermissionError`:

```
claim CLM-0004 already has a final decision (settled); a claim is settled or repudiated once
```

The persistent `case-data` volume kept CLM-0004 from an earlier run. The database refusal was
correct. The error was in the nodes: they did not catch the refusal, and the run stopped
part-way. Then `src/claimsense/api/runner.py`, function `summarize`, gave the last status in
the checkpoint. That status was "running".

**Cause.** There were two gaps. No node changed a database refusal into a decision for a
person. The API had no "stopped" status and could not continue a stopped run.

**Fix.** The user chose the full fix. We made these changes:

| Change | File and function |
|---|---|
| A database refusal at settle or repudiate escalates the claim. The reason is a fixed text, never the error text. The node logs a warning. | `graph/nodes.py`: `_refused`, `_REFUSAL_REASONS` |
| A scope refusal (`ToolScopeError`) escalates too. Any other `ToolPermissionError` (ACL) still stops the run. | `graph/nodes.py`: `_refused` |
| Extraction flags a claim id in the documents when this id differs from the claim id of the case. | `graph/nodes.py`: `extract` |
| A run that stops part-way shows `status: stopped`, `stopped_at` (step names), `stopped_error` (class name only) and `retryable`. | `api/runner.py`: `summarize`, `stop_error` |
| The API does not allow a retry after a security or configuration stop. | `api/runner.py`: `NOT_RETRYABLE` |
| New route `POST /claims/{case_id}/retry` continues a stopped run. It gives HTTP 409 when the case is busy, when no run stopped, or when the API does not allow a retry. | `api/runner.py`: `CaseService.retry`; `api/cases.py` |
| The UI shows a Retry button. When the API does not allow a retry, the UI shows a message for a person instead. | `ui/app.py`: `stopped`; `ui/client.py`: `retry` |

Rule 4 applies. A stopped case shows only step names and the error class name. It never
shows the error message, because the message can quote a document.

### F3. Seven defects in the first fix for F2

**Symptom.** An adversarial review of the F2 fix gave 14 findings. We put them into seven
defects. The reviewers reproduced the six code defects with probes or AppTest runs. They found
the stale documents when they read the files.

| Defect | Effect | Fix |
|---|---|---|
| A lost reply after a committed payment | On the retry, the database found the settlement row and refused a second decision. The paid claim was escalated with no receipt, and its claim history was not written. | `claims_db.py`: `_repeat` gives the stored receipt (see F4) |
| Error runs counted as outcomes | `claimsense_claims_processed` counted a stopped run as an outcome. A retry then counted the claim a second time. | `api/metrics.py`: new counter `claimsense_run_errors`; `OUTCOMES` has no "error" |
| A retried first run | The retry of a first run did not record the route metric. | `api/runner.py`: `CaseService.retry` calls `_segment` with `first=True` when the case has no review decision |
| The escalation reason was hidden | The UI did not show why a claim was escalated. | `ui/app.py`: "Escalated" panel with the reason |
| The wrong reason for void approvals | The UI marked the approvals of an escalated claim void, with the wrong reason: "the worksheet changed after it". | `ui/app.py`: `approvals(..., escalated=...)` gives "void: the claim was escalated" |
| An ACL stop looked retryable | A security stop showed a Retry button. | `api/runner.py`: `NOT_RETRYABLE` |
| Stale documents | The API README, the UI README and CLAUDE.md did not describe the new behaviour. | Updated |

### F4. A repeat of a settlement passed without an approval

**Symptom.** After the F3 fix, one product test failed:

```
FAILED tests/orchestration/test_mcp_services.py::
       test_settlement_over_mcp_needs_the_signed_approval_for_this_worksheet
E       Failed: DID NOT RAISE PermissionError
```

**Code.** `src/claimsense/mcp_servers/claims_db.py`, `settle_claim` and `record_repudiation`.
The F3 fix called `_repeat` before the approval check:

```python
with self._lock:
    if repeat := self._repeat(claim_id, "settled", ws_hash):
        return repeat  # returned with no approval check
    self._refuse_second_decision(claim_id, ws_hash)
```

**Cause.** Each caller that sent the same worksheet got the "settled" receipt. A call with no
approval passed. A second case for the same claim could show "settled". Thus that case did not
go to a person. The database did not pay a claim twice, because `_repeat` writes no row. But
the rule "one final decision" became weaker.

**Fix.** We wrote the failing tests first, then changed the code.

1. New function `approvals.spent_by`. It is true only when the caller presents the approval
   that the written decision spent.
2. `settle_claim` and `record_repudiation` give the receipt only when `spent_by` is true.
   Any other repeat goes to `_refuse_second_decision`, and this function refuses it.
3. `spent_by` runs before the database lock. The approval store uses the same lock, and the
   lock is not re-entrant.

```python
spent = appr.spent_by(claim_id, tokens, appr.SETTLE, ws_hash, store=resolved_store)
with self._lock:
    if spent and (repeat := self._repeat(claim_id, "settled", ws_hash)):
        return repeat
    self._refuse_second_decision(claim_id, ws_hash)
```

We also changed the test that failed. That test expected a refusal for a second settlement
with the same approval. After F4, that repeat is correct: it gets the same receipt and writes
no row. The test now makes sure that this repeat gives the same receipt. It also makes sure
that the database refuses a repeat with no approval.

New tests in `tests/mcp_servers/test_settlement_safety.py`:
`test_a_repeat_without_the_spent_approval_is_refused` and
`test_a_repudiation_repeat_without_the_spent_approval_is_refused`.

### F5. One approval could spend the record of a different approval

**Symptom.** A second adversarial review of the F4 fix reproduced this sequence:

1. Adjudicator A approves case X for claim C. Case X stops before it settles.
2. Adjudicator A approves case Y, a second case for claim C and the same worksheet.
3. Case Y settles. The database spends the approval record of **case X**, not of case Y.
4. Case X retries. `spent_by` finds the approval record of case X spent and gives the receipt.
   Thus the duplicate case shows "settled".
5. If the reply to case Y is lost, the database refuses the retry of case Y. Thus case Y, which
   wrote the decision, goes to a person.

**Code.** `src/claimsense/mcp_servers/approvals.py`, `_find_signed_record`. It found a record
by claim, worksheet hash, level and approver only:

```python
if (
    rec.purpose == purpose
    and rec.token.level == token.level
    and rec.token.approver_id == token.approver_id
    and not store.is_consumed(rec)
    and rec.signature_valid()
):
    return rec  # the first record of this approver, not the record of this token
```

**Cause.** An approval token has no nonce. Two approvals by one person for one worksheet have
the same level and approver. Only `decided_at` is different.

**Fix.** `_find_signed_record` now requires the full token to be equal, `decided_at` included:
`rec.token == token`. The token has exactly the five fields that the record keeps, so the
comparison is exact. A third review examined each place that makes or carries a token: JSON
over MCP, LangGraph checkpoints and SQLite. The review found no correct approval that the new
comparison refuses.

New tests: `test_a_settlement_spends_the_presented_approval_not_an_older_one` (in-memory and
SQLite stores) and `test_a_repudiation_spends_the_presented_approval_not_an_older_one`.

### F11. Two tool-use cases and DeepEval failed after F4 and F5

**Symptom.** In the full check run, three stages failed:

```
FAILED eval/agentic/tests/test_cases.py::test_tool_case[settle-replayed-token]
FAILED eval/agentic/tests/test_cases.py::test_tool_case[repudiate-replayed]
FAILED eval/agentic/tests/test_runs.py::test_dev_trajectory_metrics_are_clean
UnicodeEncodeError: 'charmap' codec can't encode character '⚠'     (DeepEval)
```

**Cause.**

1. Two cases in `eval/agentic/tool_cases.jsonl` expected a refusal for a repeat with the same
   approval. After F4, the correct result is the receipt, with one row. The third test failed
   because those two cases failed.
2. DeepEval printed a warning sign. The Windows console uses cp1252, and cp1252 does not have
   this sign.

**Fix.**

1. The two cases now expect `ok` with one row. Two new cases in `eval/agentic/tool_cases.jsonl`
   expect a refusal for a new approval of the same worksheet: `settle-duplicate-approval` and
   `repudiate-duplicate-approval`. Their scenarios are `settle_duplicate_approval` and
   `repudiate_duplicate_approval` in `eval/agentic/tool_eval.py`. Tool cases: 64 of 64 pass.
2. We ran DeepEval with `PYTHONUTF8=1`. Result: 74 of 74 pass.

We did not make a safety rule weaker. A repeat still writes no second row. Only the caller that
holds the spent approval gets the receipt.

## 3. Failures in the Docker build

### F6. Each Docker build downloaded the packages and models again

**Symptom.** Each code change ran the package step and the model step again. The two search
models were downloaded again each time. The first real build downloads about 1 GB, and the
connection was slow (about 18 KB/s at times). One build started to download torch 2.15.0
(209.5 MB) again.

**Code.** `Dockerfile` and `Dockerfile.ui`. The Dockerfiles did not pin the package versions.
The builds did not keep the pip and model caches.

**Cause.**

1. PyPI connections timed out.
2. The model step downloaded the search models again after each change in the code.
3. The PyTorch index moved its files to `download-r2.pytorch.org`. pip uses the URL as the key
   for each file in its cache. Thus the cached torch file did not match the new URL.
4. A new release on PyPI could change the versions and cause new downloads.

**Fix.**

| Change | Where |
|---|---|
| A BuildKit cache mount keeps the pip downloads (`/root/.cache/pip`). A second cache mount keeps the search models (`/hf-cache`), in the API image only. | `Dockerfile` (both mounts), `Dockerfile.ui` (pip cache only) |
| pip tries again ten times, with a 300 s timeout | both Dockerfiles |
| The torch step comes before the step that copies the code | `Dockerfile` |
| Each package is pinned to the version in the last working image | `docker/constraints-api.txt` (177 lines), `docker/constraints-ui.txt` (51 lines) |
| Build argument `BASE` lets a code-only rebuild start from the last real image | `Dockerfile`; `CLAIMSENSE_DOCKER_BASE` in `docker-compose.real.yml` |
| The build copies the models from the old image into an empty model cache | `Dockerfile`, last `RUN` |

After this fix, three rebuilds from the last real image downloaded nothing.

**Limit of the fix.** The pip cache mount did not keep the files after the failed build in F8.
The retry in F8 found no file in the pip cache and downloaded all the packages again. The
Docker layer cache kept the torch step, but the pip cache did not. Section 8 has this item.

### F7. The build failed with "pull access denied"

**Symptom.**

```
ERROR [api internal] load metadata for docker.io/library/claimsense-insurance-api-real:latest
failed to solve: ... pull access denied, repository does not exist or may require authorization
```

**Code.** `FROM ${BASE}` in `Dockerfile`, with `CLAIMSENSE_DOCKER_BASE=claimsense-insurance-api-real`.

**Cause.** All the ClaimSense images, and `python:3.12-slim`, were removed from Docker between
25 November (about 20:30 IST) and 26 November (about 20:55 IST). We do not know what removed
them. `docker compose down` does not remove images. When the base image is not local, Docker
looks for the image on Docker Hub. The image is not on Docker Hub. The build cache (20.8 GB)
and the volumes stayed on the machine.

**Fix.**

1. We built without `BASE`, from `python:3.12-slim`. The UI image came from the build cache.
   The API build downloaded torch (209.5 MB) and the packages again. F8 describes that build.
2. `docker-compose.real.yml` and `docs/CI_CD_PIPELINE.md` now say: use `CLAIMSENSE_DOCKER_BASE`
   only when `docker images` lists that image.

### F8. A package download failed its checksum after 11.5 hours

**Symptom.** The clean build ran for 41,566 s (11.5 hours) in the package step. Then:

```
ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.
    unknown package:
        Expected sha256 99e1074c4b2197accd5073052a465361be17b89c093b8ffb6e6bd8f986c52df8
             Got        2883f4bf0555f33c8d8531545d9b58be12e456b200e108c6e642584fd7f05119
```

**Code.** `Dockerfile`, the `pip install -c /tmp/constraints.txt -e ".[$EXTRAS]"` step.

**Cause.** The connection to PyPI was very slow and stopped for long periods. One request
waited about 80 minutes before pip tried again. Two downloads stopped for hours: onnxruntime
for about 4 hours and scipy for about 5 hours. One file arrived damaged. pip compares each file
with the hash that PyPI publishes. pip refused the damaged file. pip operated correctly, and
the fault was not in pip.

**Fix.** We built again. A scan of the pip cache found no files, so the damaged file was not in
the cache. pip downloaded all the packages again. The connection was fast at that time (2 to
3 MB/s), so the build took about 10 minutes: packages 270 s, search index 75.5 s, export
219 s. The API image is 3.09 GB.

## 4. Failures at the start of the real stack

### F1. The UI showed stub agents in the "real" stack

**Symptom.** The user started Docker for real agents. The UI showed "agents: stub".

**Code.** `docker-compose.real.yml`, which was new. Its comment said that it needs
`OPENROUTER_API_KEY` and `CLAIMSENSE_APPROVAL_SECRET` from `.env`. But it checked only the
secret:

```yaml
CLAIMSENSE_APPROVAL_SECRET: ${CLAIMSENSE_APPROVAL_SECRET:?set CLAIMSENSE_APPROVAL_SECRET in .env (a long random value)}
```

**Cause.** `.env` did not have `CLAIMSENSE_APPROVAL_SECRET`. The overlay refused to start. The
user then started the plain `docker-compose.yml`. That file runs stub agents by default.

**Fix.**

1. We added `CLAIMSENSE_APPROVAL_SECRET=` to `.env.example`.
2. The overlay always sets `CLAIMSENSE_LLM: real`. A `CLAIMSENSE_LLM=stub` value in a shell or in
   `.env` cannot change it.
3. After F1, we added the same check for `OPENROUTER_API_KEY`. The overlay now refuses to start
   without the key.
4. The user added a random secret to `.env`.

### F9. Prometheus and Grafana did not start: port 9090 was in use

**Symptom.**

```
Container claimsense-insurance-prometheus-1  Error response from daemon: ports are not available:
exposing port TCP 127.0.0.1:9090 ... bind: Only one usage of each socket address ... is normally permitted.
```

**Cause.** An earlier `eval.monitoring` drill did not stop its own Prometheus and Grafana. They
continued to run on the host, outside Docker:

| Port | Process |
|---|---|
| 9090 | `~/.claimsense/monitoring_stack/prometheus/.../prometheus.exe` (3.13.4) |
| 3000 | `~/.claimsense/monitoring_stack/grafana/.../grafana.exe` (12.4.12) |

The API and the UI started. Prometheus and Grafana in Docker did not start.

**Fix.**

```powershell
python -m eval.monitoring down
docker compose -f docker-compose.yml -f docker-compose.real.yml up -d --no-deps prometheus grafana
```

With `--no-deps`, Docker Compose does not restart the API and the UI. They continue to run.

### F10. A case stopped with `OpenAIAuthenticationError`

**Symptom.** Cases CLM-9006 and CLM-9029 stopped at the coverage step:

```
The last run stopped at coverage (OpenAIAuthenticationError). Retry runs it again from that step.
```

This stop shows that the F2 fix operates correctly. The case stopped with a clear status and a
Retry button.

**Cause, part 1.** OpenRouter refused the API key (HTTP 401). We examined the key in the
container. The check printed only these facts, never the key:

```
set: True | looks like an OpenRouter key (sk-or-): True | has quotes: False | has spaces: False
OpenRouter answers: 401
```

The key had the correct form, but OpenRouter did not accept it.

**Cause, part 2.** The user put a new key in `.env`. The container still got the old key.
OpenRouter again gave HTTP 401. The user ran a check:

```
key lines in .env:          1
terminal has its own key:   True
terminal key same as .env:  False
OpenRouter accepts the .env key: 200
```

VS Code copies `.env` into a terminal only when the terminal opens. When the terminal and
`.env` both have a value, Docker Compose uses the value from the terminal. Thus Docker Compose
sent the old key from the old terminal.

**Fix.**

```powershell
Remove-Item Env:OPENROUTER_API_KEY
docker compose -f docker-compose.yml -f docker-compose.real.yml up -d --force-recreate api
```

Then, in the UI, select the **Open a case** tab and open the case. Push **Retry**. Do not push
**Start** for a case that exists. **Start** gives HTTP 409 ("case exists").

## 5. Errors in our own method

These errors did not go into the code. They used time. We record them to prevent them again.

| Error | Effect | Correct method |
|---|---|---|
| A Python script edited the Dockerfile. A backslash before a new line became a line join. | The script applied no edit. | Edit files with the editor tool, not with a script. |
| A UI test used scene 1. Scene 1 never shows an approval. | The test could not fail. | Use the scene 3 flow: an approval, then a refused settlement. |
| A seeder test passed without the leak. | The test did not prove the fix. | Make sure that each new test fails before the fix. |
| We told the user to use `CLAIMSENSE_DOCKER_BASE`. We did not first make sure that the image exists. | F7. | Examine `docker images` first. |
| We told the user that the pip cache kept torch and the other downloads. | The retry in F8 downloaded all the packages again. | Report a cache hit only when the log shows "Using cached" or "CACHED". |
| The first fix for the lost reply (F3) gave a receipt before the approval check. | F4. | Do an adversarial review of each change to the money path. |
| A build watch filter found no line for 30 minutes. | The build looked stopped. It was not stopped. | Read the log directly when a watch gives no events. |

## 6. Verification

After the last fix, we ran all the checks in stub mode (no model, no cost).

| Check | Result |
|---|---|
| Product tests (`pytest`) | Pass |
| API tests with `LANGGRAPH_STRICT_MSGPACK=true` | Pass |
| `mypy` | Pass |
| Tool pins | Pass |
| Harness suite (`eval.harness.suite`) | Pass |
| Eval tests (`eval/tests`) | Pass |
| Tool-use eval (`eval.agentic.run --label check-1125`, 25 November; we deleted the output after the check) | Tools 64/64, hooks 36/36, controls 13/13, 0 open defects |
| Ship, experiment and calibration tests | Pass |
| DeepEval suite | 74 of 74 pass |
| `ruff check`, `ruff format --check` | Pass |

Docker checks, with stub agents and real tools:

| Mode | Claim | Result |
|---|---|---|
| Real tools | CLM-0005 | Settled, Rs 76,886.60 |
| Real tools | CLM-0009 | Settled, Rs 56,078.11 |
| Real tools | CLM-0004, a second case | Escalated: "settle refused: the claim already has its final decision" |
| MCP tools | CLM-0010 | Settled, Rs 1,07,538.62 |
| MCP tools | CLM-0005, a second case | Escalated, with the same reason |
| Real tools, after the rebuild | CLM-9002 (red-team) | Repudiated; no stop, no error |

The real stack: `/health` gives `"llm":"real","tools":"real"`. The UI, Grafana and Prometheus
give an answer. After the key fix, real claims run.

## 7. Procedure: start the real stack

1. Make sure that `.env` has `OPENROUTER_API_KEY` and `CLAIMSENSE_APPROVAL_SECRET`.
2. After each change to `.env`, open a new terminal. As an alternative, remove the old key from
   the current terminal: `Remove-Item Env:OPENROUTER_API_KEY`.
3. If an earlier drill did not stop its monitoring stack, stop it: `python -m eval.monitoring down`.
4. Start the stack: `docker compose -f docker-compose.yml -f docker-compose.real.yml up -d`.
5. Examine the mode: `curl.exe http://127.0.0.1:8000/health`. Make sure that the response shows
   `"llm":"real"`.
6. Open the UI (http://127.0.0.1:8501), Grafana (http://127.0.0.1:3000) and Prometheus
   (http://127.0.0.1:9090).
7. Start a case for a claim that is not in the `case-data` volume.
   NOTE: A second case for a paid claim goes to a person.
8. If a case stops, open the case. Then push **Retry**. Do not push **Start** again.

**CAUTION:** Do not run `docker image prune -a` or "Clean up" in Docker Desktop. A rebuild
without the images can take many hours on a slow connection.

## 8. Open items

| Item | Effect | Recommendation |
|---|---|---|
| The pip cache mount did not keep the files after a failed build | A failed build can cause a full download again | Find the cause in BuildKit. As an alternative, keep a local wheel folder and install from it. |
| Containers run as root | A fault in the API has more access than necessary | Add a non-root user to both Dockerfiles |
| Model revisions are not pinned | A new model version on the hub can change the search results | Pin the revision of each search model |
| The real overlay accepts the demo reviewer tokens | Each person on the machine can approve | Require `CLAIMSENSE_REVIEWERS` in the real overlay |
| CI does not examine the real overlay | Only a person finds a fault in `docker-compose.real.yml` | Commit the file, then add a `docker compose config` step |
| Constraints files are a snapshot | A dependency change in `pyproject.toml` needs new pins | Make the files again with the command in their header |
| Jaeger is not in Docker Compose | Traces need the local `eval.observability` stack | Add a Jaeger service, or document the OTLP endpoint |
