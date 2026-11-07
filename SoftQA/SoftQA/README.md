# SOFT QA — AI-Powered Software Quality Assurance Assistant

Upload Python source, get static analysis, security scanning, AI code review, AI-generated pytest tests,
sandboxed test execution with coverage, and a QA report (PDF/JSON).

> **Status: written but largely UNVERIFIED.** The code was produced in an offline environment with no
> network, no Docker and no dependencies installed. See [Verification status](#verification-status) before trusting anything.

## Verification status

| Area | State |
|---|---|
| ZIP/upload safety (`archive.py`), generated-test validator, line/evidence checks, Bug Hunter, Evaluator | **Tested**: stdlib unit tests (55 passed, 3 skipped in the offline authoring environment; see checklist item 1) |
| `reviewer.py` / `test_engineer.py` against the real Pydantic schemas | Tests written (`RealSchemaTests`) but **skipped here** (Pydantic not installed); they run on your machine |
| Whole backend byte-compiles; DB model / schema / frontend type field names cross-checked by script | **Checked** (syntax and field names only) |
| FastAPI routes, SQLAlchemy models at runtime, background pipeline, PDF export | **Written, never run** (`tests/test_api.py` exists but has not been executed) |
| Gemini integration (`google-genai`, JSON-schema output) | Config loading/precedence, status logic, request construction, response parsing, error classification, retries and key redaction **tested against a scripted fake SDK**. **Never run against the real Gemini API or the real `google-genai` SDK.** |
| Ruff / Semgrep integration (CLI JSON parsing) | **Written, never run** |
| Docker sandbox (pytest + coverage) | **Written, never run**; disabled automatically if Docker is missing |
| React frontend | **Written, never compiled** (`npm run build` not run; TypeScript errors are possible) |

## Features

Implemented (pending your verification): upload `.py`/`.zip` with size limits and path-traversal/symlink/zip-bomb rejection;
project tree and viewer with line numbers, highlighting and inline finding markers; Ruff lint; Semgrep scan (bundled offline rules + registry rulesets);
AST bug-hunter heuristics; AI review (Google Gemini) with line-range and evidence validation; AI test generation with AST validation and human approval;
Docker-sandboxed pytest + coverage; deterministic evaluator (dedupe, confirmed vs potential, documented heuristic score); report with PDF/JSON export; dashboard with 7 pages.

Not implemented: JavaScript analysis (ESLint/Vitest; extension point is `ANALYZERS_BY_LANGUAGE` in `analyzers.py`), PostgreSQL migrations (schema is portable, no Alembic), authentication, a persistent job queue (analysis runs as a FastAPI background task and is lost on restart), per-line AI findings in files beyond the first 15.

## Architecture

```
Upload -> archive.py (validate, safe extract) -> DB + data/projects/<id>/src
   -> pipeline.py (background task)
        Ruff (analyzers.py) -> Bug Hunter AST (agents/bug_hunter.py) -> Semgrep (analyzers.py)
        -> AI review, 1 call/file (agents/reviewer.py; hints from tools; lines+evidence validated)
        -> Evaluator (agents/evaluator.py: merge/dedupe, confirmed vs potential)
   -> POST /tests/{id}/generate (agents/test_engineer.py, 1 call) -> AST validation
   -> human approval -> POST /tests/{id}/execute -> sandbox.py (Docker) -> results + coverage
   -> reports.py -> JSON / PDF
```
Design rules: deterministic tools do deterministic checks; the LLM is used for review and test design only (2 LLM entry points, not 5).
**Confirmed** = reported by Ruff/Semgrep or a syntax error. **Potential** = AI or heuristic only. An AI finding that overlaps a tool finding
of the same category is merged into it and recorded under `corroborated_by`. Security findings come only from Semgrep rules.
Quality score (internal heuristic, not a standard): `100 - sum(weights)`; critical 15, high 8, medium 3, low 1; potential counts half.

## Windows setup (PowerShell)

Prerequisites: Python 3.12 (python.org), Node.js 20+, Docker Desktop with WSL2 backend (for sandbox), Git.

```powershell
# --- Backend ---
cd aura-qa\backend
py -3.12 -m venv .venv
# If activation is blocked:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item ..\.env.example .env
notepad .env          # set GEMINI_API_KEY (and optionally GEMINI_MODEL)
uvicorn app.main:app --reload --port 8000
```
```powershell
# --- Frontend (second terminal) ---
cd aura-qa\frontend
npm install
npm run build         # type-checks and builds (first real verification of the UI code)
npm run dev           # http://localhost:5173
```
```powershell
# --- Sandbox image (needs Docker Desktop running) ---
docker build -t aura-qa-sandbox:latest backend\sandbox
```
**Semgrep on Windows:** native Windows is not officially supported. SOFT QA automatically falls back to the `semgrep/semgrep`
Docker image (source mounted read-only; first run pulls the image). Alternatively run the backend in WSL2 and `pip install -r requirements-semgrep.txt`.

Without an API key the app still starts; AI features report "unavailable" and static analysis works.
API docs: http://localhost:8000/docs . Status check: http://localhost:8000/api/system/status

## Configuring Gemini
1. Create a key in Google AI Studio (https://aistudio.google.com/apikey).
2. In `backend\.env` set `GEMINI_API_KEY=<your key>`; optionally `GEMINI_MODEL` (default `gemini-3.8-flash`). Never commit `.env`.
3. Restart the backend. `GET /api/system/status` should show `ai_configured: true`.
4. Failure messages you may see in a run's warnings (or as HTTP 429/503 on test generation): invalid/expired key, permission denied,
   quota exhausted (not retried), rate limited (retried 2x with backoff), model not found, service overloaded, timeout, blocked content,
   truncated or malformed output. All leave the non-AI features (Ruff, Semgrep, heuristics, reports) working.
5. `backend\.env` is the single source of truth: its values **override** same-named variables already set in your shell/Windows environment. Findings and test-case schemas are unchanged.

### Verify that Gemini is really being used
```powershell
# 1) Provider/model/diagnostics (no network call; key is never shown)
Invoke-RestMethod http://localhost:8000/api/system/status | Select-Object ai_configured, ai_provider, ai_model, ai_message
# expected: ai_configured True, ai_provider google_gemini, ai_model gemini-3.8-flash

# 2) Live test: ONE tiny real Gemini request (uses a little quota)
Invoke-RestMethod -Method Post http://localhost:8000/api/system/ai-check
# expected: ok True, reply "OK". Otherwise `kind` and `message` explain why (invalid_key, quota_exceeded, ...)
```
Also watch the backend console: on startup it logs `AI provider=google_gemini model=... configured=...`.
`ai_configured` means: key present, `google-genai` installed and a client can be created. Google only validates the key on a real request, which is what `ai-check` does.

### Troubleshooting a status that does not match your `.env`
- `ai_provider` missing from `/api/system/status`, or an unexpected model name: you are running an **old copy** of the code or an old server process. Stop every `uvicorn`/`python` process, re-extract the latest zip into a clean folder, recreate the venv, and start again from that folder.
- Editing `backend\.env` needs a **backend restart**; `--reload` watches Python files, not `.env`.
- `ai_message` tells you which `.env` path was read and whether it exists. The file must be `backend\.env` (not the repo root).

### Choosing a model
The code default is `gemini-3.8-flash` (`DEFAULT_GEMINI_MODEL` in `app/config.py`, `.env.example`, `tests/constants.py`; `test_repo_hygiene` fails if they drift apart). Set `GEMINI_MODEL` in `backend\.env` to use another model your key can access. Tests check the *code* default, never your local choice. **Model availability is decided by Google, not by this repo:** if `ai-check` returns `model_not_found`, the model name is not available to your key; check it in Google AI Studio (https://aistudio.google.com) and set `GEMINI_MODEL` accordingly.

### If `ai-check` returns `network_error`, `timeout` or `tls_error`
These mean the request never got a normal answer from Google, so the cause is usually the network path from your PC, not the key or model. The `message` and `detail` fields now show the root cause (for example a DNS failure or a certificate error). For a layer-by-layer diagnosis (proxy settings, DNS, TCP 443, TLS certificate, HTTPS, then the SDK):
```powershell
cd aura-qa\backend
python scripts\diagnose_gemini.py --skip-sdk   # network layers only, no API request
python scripts\diagnose_gemini.py              # adds one tiny real Gemini request
```
The first failing layer is the lead: DNS fails -> DNS/VPN/offline; TCP fails -> firewall (allow python.exe) or a required proxy; TLS certificate fails -> antivirus/proxy re-signing HTTPS (set `SSL_CERT_FILE` to a CA bundle containing its root certificate); only the SDK layer fails -> send me its `cause chain` lines. `network_error` and `timeout` are retried (up to 3 attempts); `tls_error` is not, because retrying cannot fix a certificate problem.

## Using the app
New Analysis -> upload and start -> watch stage/warnings -> Findings / Security Center / Code Explorer -> Test Center:
Generate tests, **review the code**, Approve, Run in sandbox -> Reports: export PDF/JSON.

## API
| Method & path | Purpose |
|---|---|
| `POST /api/projects/upload` (multipart `file`) | Upload `.py`/`.zip` |
| `GET /api/projects`, `GET /api/projects/{id}`, `GET /api/projects/{id}/files/{file_id}` | Projects, tree, file content |
| `POST /api/analysis/{project_id}/start` (body: `use_ai, run_ruff, run_semgrep, max_ai_files`) | Start background analysis (202) |
| `GET /api/analysis`, `GET /api/analysis/{id}`, `GET /api/analysis/{id}/findings?severity=&category=` | Runs and findings |
| `POST /api/tests/{analysis_id}/generate`, `GET /api/tests/{analysis_id}` | Generate/list test cases |
| `POST /api/tests/{test_id}/approve` (`{approved}`) | `test_id` = numeric DB id (`TestCase.id`) |
| `POST /api/tests/{analysis_id}/execute`, `GET /api/tests/{analysis_id}/executions` | Sandboxed run (503 if Docker missing) |
| `GET /api/reports/{analysis_id}`, `GET /api/reports/{analysis_id}/export?format=pdf\|json` | Report |
| `GET /api/system/status`, `GET /api/stats`, `POST /api/system/sandbox/build` | Capabilities, dashboard stats, build sandbox image |

## Security considerations
- Uploaded code is never imported or executed by the backend. Ruff and Semgrep only parse it.
- Upload: extension allow-list, size limits, entry/total-size/ratio limits, `..`/absolute/drive-letter paths rejected, symlinks and encrypted entries rejected, real read size bounded.
- Generated tests are untrusted: AST allow-list (imports, no `open/eval/exec`, no dunder access, one `test_*` function, must assert), human approval, re-validation before run. This is defense in depth only.
- Sandbox: `--network none`, non-root (65534), `--cap-drop ALL`, `no-new-privileges`, read-only root FS, read-only source/test mounts, 64 MB tmpfs, CPU/memory/pids limits, wall-clock timeout with forced `docker rm -f`. **No host fallback**: without Docker, execution is disabled.
- Docker containers share the host kernel; a kernel escape is out of scope. For hostile multi-tenant use add gVisor/Firecracker, auth and rate limiting.
- The API has **no authentication** and is intended for local use. API keys live only in `backend/.env`.
- The Semgrep Docker fallback and registry rulesets use the network (source is mounted read-only; Semgrep metrics are off).

## Known limitations / risks to check
- LLM output can still be wrong. Line numbers are validated; semantic correctness is not. Failing AI-written tests may be bad tests.
- Only Python is analyzed. Coverage is only for code touched by approved generated tests.
- Gemini structured output (`response_schema` with Pydantic models) needs a recent `google-genai` and a model that supports JSON schema; adjust `GEMINI_MODEL` if requests fail. The free tier has tight rate/daily limits: the app retries rate limits and transient errors up to 3 times, never retries quota/auth errors, and reports each failure type in the run's warnings.
- Semgrep `--config` registry sets (`p/python`, etc.) need network; on failure it retries with bundled rules and records a warning.

## Screenshots
_Add screenshots here after you run the UI (`docs/screenshots/`)._

## Roadmap
ESLint/Vitest analyzers; Alembic + PostgreSQL; auth and per-user projects; job queue (RQ/Celery) with SSE progress; gVisor sandbox; diff-based re-analysis; SARIF export.

## Verification checklist (run locally)
1. `cd backend; python -m unittest tests.test_archive tests.test_validation tests.test_agents tests.test_llm tests.test_ai_config tests.test_repo_hygiene -v` (58 tests; with Pydantic installed all 58 should run and pass, without it 3 are skipped). The suite is isolated from your real `backend\.env` and from GEMINI_*/AURA_* variables in your shell or Windows environment (`tests/__init__.py`), so changing your local model or key never changes test results
2. `pip install -r requirements-dev.txt; python -m pytest -q` (runs `test_api.py`: upload, invalid files, traversal, no-AI degradation)
3. `ruff --version`; `docker version`; `GET /api/system/status` reports the right capabilities
4. `cd frontend; npm install; npm run build` — fix any TypeScript errors
5. Upload a `.py` file with `x / y`, a hardcoded password and `eval(...)`; confirm Ruff, bundled Semgrep rules and heuristic findings appear with correct lines
6. Upload a ZIP containing `../evil.py` and one with a symlink: both must be rejected with HTTP 400
7. Without `GEMINI_API_KEY`: analysis completes with an "AI analysis unavailable" warning; test generation returns 503 with a clear message
8. With a key: AI findings appear as `potential`, with source lines in Evidence; no finding points past end of file
9. Generate tests; confirm a test importing `os` shows "rejected by validation" and cannot be approved
10. With Docker: build the image, approve a test, run it; check pass/fail, coverage, and that `import socket; socket.create_connection(...)` inside the container fails (no network)
11. Stop Docker: the Run button is disabled and `/execute` returns 503 (no host execution)
12. Export the PDF and JSON for a completed analysis and open both
