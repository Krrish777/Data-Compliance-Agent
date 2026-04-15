# Code Quality, Security & Production Readiness Review — Data Compliance Agent

**Date:** 2026-04-11
**Reviewer persona:** Senior AI engineer (security & ops focus)
**Scope:** `src/agents/tools/database/`, `src/utils/`, `src/stages/`, `src/docs_processing/docs_processor.py`, `src/embedding/embedding.py`, `pyproject.toml`, `main.py`, `run_hi_small.py`, `run_scan.py`, `run_intercept.py`, `tests/unit/`.

---

## 1. SECURITY — SQL INJECTION

**POSITIVE CLAIM:** The vast majority of queries use SQLAlchemy `text()` with named `:param` binding. `violations_store.py` `log_violation()` (line 123–133), all `get_violations_*` functions, and all `postgres_connector.py` schema queries are fully parameterized. The `sqlite_connector.py` schema queries at line 30 use `text()` without interpolation.

**GAP 1 (Confidence: 100):** `violations_store.py:179–184` — `update_violation_status` builds the `WHERE id IN (...)` clause by string-concatenating caller-supplied IDs:

```python
ids_csv = ",".join(str(i) for i in violation_ids)
sql = text(f"""
    UPDATE violations_log
       SET review_status = :status, ...
     WHERE id IN ({ids_csv})          # <-- f-string injection
""")
```

`violation_ids` comes from callers. If any caller derives these IDs from unsanitized external input (e.g. a future API endpoint), this is a direct SQL injection vector. Even in the current codebase this is a style violation that will escalate in severity the moment an HTTP layer is added.

**MIGRATION:**
```python
# Replace f-string IN clause with individual bound params
placeholders = ", ".join(f":id_{i}" for i in range(len(violation_ids)))
sql = text(f"UPDATE violations_log SET review_status = :status, "
           f"reviewer_notes = :notes, reviewed_at = :reviewed_at "
           f"WHERE id IN ({placeholders})")
params = {"status": status, "notes": reviewer_notes, "reviewed_at": reviewed_ts}
params.update({f"id_{i}": v for i, v in enumerate(violation_ids)})
session.exec(sql, params=params)
```

**GAP 2 (Confidence: 95):** `query_builder.py:73–99` — `_build_rule_condition` constructs `LIKE`, regex, and `IN` clause values using manual quote-escaping (`str(value).replace("'", "''")`) instead of parameterized binding. This applies specifically to the LIKE and IN branches (lines 76–98). While the `'` → `''` escape is SQLite-standard, it fails for dialects that use `$1`-style placeholders and is fragile against multi-byte characters. SQLAlchemy's `text()` with `:param` should be used consistently.

**WHY IT MATTERS:** OWASP A03:2021 (Injection) — the moment the rule values come from an untrusted source (user-uploaded PDF → LLM → StructuredRule), the escape path is the only barrier.

**REFERENCE:** https://owasp.org/Top10/A03_2021-Injection/

---

## 2. SECURITY — PROMPT INJECTION VECTOR (FILE INGESTION)

**POSITIVE CLAIM:** `docs_processor.py` uses PyMuPDF (`pymupdf.open`), which does not execute embedded JavaScript by default. The `process_pdf` method checks file existence and extension before opening (lines 109–115).

**GAP 1 (Confidence: 95):** There is no page count or file size limit. A malicious or accidental 2,000-page PDF will cause `_process_pdf` (line 148) to iterate every page, extract text, chunk it, and potentially cache all of it in Redis (up to 500 MB in-memory fallback). During a live demo, ingesting a large PDF hangs the pipeline with no timeout and no progress feedback.

**MIGRATION:**

```python
MAX_PAGES = 200
MAX_FILE_MB = 50

def _process_pdf(self, file_path: Path) -> List[DocumentChunk]:
    stat_mb = file_path.stat().st_size / 1024 / 1024
    if stat_mb > MAX_FILE_MB:
        raise ValueError(f"PDF too large: {stat_mb:.1f} MB (limit {MAX_FILE_MB} MB)")
    doc = pymupdf.open(file_path)
    if len(doc) > MAX_PAGES:
        log.warning(f"Truncating PDF to {MAX_PAGES} pages (was {len(doc)})")
    pages_to_scan = range(min(len(doc), MAX_PAGES))
    ...
```

**GAP 2 (Confidence: 90):** Filenames are passed directly into `chunk_id` via `self.source_file` (line 40: `f"{self.source_file}_{self.chunk_index}_{content_hash}"`). A crafted filename like `../../etc/passwd_0_deadbeef` leaks a path traversal string into every log line and the chunk ID embedded in Qdrant. While this does not directly cause a traversal attack (the file was already opened by absolute path), it persists attacker-controlled strings into the audit database.

**MIGRATION:** Sanitize `source_file` in `DocumentChunk.__post_init__`: use `Path(self.source_file).name` to strip any directory components before forming the `chunk_id`.

**WHY IT MATTERS:** Craft a PDF filename with path separator characters and every log entry, every Qdrant payload, and every report carries the injected string — violating the principle that the audit trail itself must not be tamper-injectable.

**REFERENCE:** https://owasp.org/www-project-web-security-testing-guide/v42/4-Web_Application_Security_Testing/07-Input_Validation_Testing/11.1-Testing_for_Local_File_Inclusion

---

## 3. SECURITY — SECRETS & CONFIG

**POSITIVE CLAIM:** `run_intercept.py:32` calls `load_dotenv()` before importing anything from `src/`. `run_intercept.py:62` warns visibly — without crashing — when `GROQ_API_KEY` is absent. No hardcoded API key string appears in any reviewed file.

**GAP 1 (Confidence: 100):** `baseconnector.py:53` logs the full connection string on every `connect()` call:

```python
log.info(f"Connected to database: {self.connection_string}")
```

For `PostgresConnector`, the connection string is built at `postgres_connector.py:11` as:

```python
f"postgresql://{user}:{password}@{host}:{port}/{database}"
```

The password is therefore emitted verbatim to the console (via RichHandler) and to every timestamped log file in `/logs/`. Log files are not gitignored by default if they are created in the repo directory.

**MIGRATION:**

```python
import re
_safe = re.sub(r":[^:@]+@", ":***@", self.connection_string)
log.info(f"Connected to database: {_safe}")
```

**GAP 2 (Confidence: 90):** `pyproject.toml` does not list `python-dotenv` — it lists `dotenv>=0.9.9` (line 8). The package name on PyPI is `python-dotenv`; `dotenv` is a different, unmaintained package. `uv` will install the wrong package unless the dev runs `uv pip install python-dotenv` manually. This is a latent CI/demo breakage.

**MIGRATION:** In `pyproject.toml` change `"dotenv>=0.9.9"` to `"python-dotenv>=1.0.1"`.

**GAP 3 (Confidence: 85):** `main.py:17` hardcodes a relative path `"data/HI-Small_Trans.db"` — any caller from a different working directory silently connects to a non-existent file. This is a demo reliability issue, not a secret leak, but the local username appears in the resolved absolute path in logs (Windows: `C:\Users\777kr\...`), which leaks machine identity if logs are shared.

**WHY IT MATTERS:** Password-in-log is OWASP A02:2021 (Cryptographic Failures) — credentials in plaintext log files are a standard audit finding at any security review.

**REFERENCE:** https://owasp.org/Top10/A02_2021-Cryptographic_Failures/

---

## 4. ERROR HANDLING

**POSITIVE CLAIM:** `query_executor.py:65–85` does structured error classification (column-missing, permission, timeout, syntax) before returning a typed error tuple instead of raising. `data_scanning.py:178–182` catches scan-level exceptions, marks status as "failed", and re-raises so the caller can handle it. `complex_executor.py:81–83` catches fetch-batch errors individually and returns an empty list so one bad batch doesn't abort the full table scan.

**GAP 1 (Confidence: 100):** `sqlite_connector.py:27` has a naked `raise` with no active exception:

```python
if not self.session:
    log.error("Database session is not established.")
    raise               # <-- raises RuntimeError: No active exception
```

In Python, `raise` with no argument re-raises the current exception. If called outside an except block (which this path is), it raises `RuntimeError: No active exception` — which is technically correct behavior but produces an incomprehensible traceback. The intent is clearly `raise RuntimeError("Database session not established")`.

**MIGRATION:** `raise RuntimeError("Database session not established. Call connect() first.")`

**GAP 2 (Confidence: 95):** `embedding.py:100` and `embedding.py:142` have bare `raise` with no exception in a non-except context:

```python
if self.model is None:
    log.error("Embedding model is not initialized")
    raise       # line 100 — outside an except block
```

Same problem as above — produces a `RuntimeError: No active exception` message that obscures the real issue during a demo.

**MIGRATION:** `raise RuntimeError("Embedding model not initialized — check model download logs.")`

**GAP 3 (Confidence: 90):** There is no retry logic or graceful degradation for Groq rate limits or 5xx errors anywhere in the reviewed files. The CLAUDE.md (line 63) mentions `src/agents/middleware/` contains retry decorators with exponential backoff — but `report_generator.py` and `rule_structuring.py` (the non-node stage files) do not use those decorators, so LLM calls made directly from stages bypass the retry layer entirely.

**GAP 4 (Confidence: 85):** `data_scanning.py:86–88` connects both `target_conn` and `violations_conn` but does not guard against the case where `target_conn.connect()` raises (e.g., SQLite locked). The `finally` block at line 183 calls `target_conn.close()` but if `connect()` failed, `target_conn.engine` is `None` and `close()` silently does nothing. This is safe today but fragile — if `close()` is ever changed to assert the connection exists, it will mask the original error.

**WHY IT MATTERS:** Unhandled Groq 429s and `raise` with no active exception are the two failure modes most likely to surface during the demo's live LLM call.

**REFERENCE:** https://docs.python.org/3/reference/simple_stmts.html#the-raise-statement

---

## 5. LOGGING & OBSERVABILITY

**POSITIVE CLAIM:** `src/utils/logger.py` is imported consistently across all reviewed database and stage files using `log = setup_logger(__name__)`. Rich tracebacks and rotating file handlers are supported. Noisy third-party loggers (httpx, langchain, etc.) are suppressed at WARNING level (lines 86–92).

**GAP 1 (Confidence: 95):** `logger.py:125` and `logger.py:128` use `print()` inside the utility module itself:

```python
print(f"Failed to delete {log_file}: {e}")   # line 125
print(f"Cleaned up {deleted_count} old log file(s)")  # line 128
```

These bypass the structured handler entirely. The cleanup function runs at process end and its output won't appear in log files.

**MIGRATION:** Replace both with `log = setup_logger(__name__)` at module level and use `log.warning(...)` / `log.info(...)`.

**GAP 2 (Confidence: 85):** No metrics are emitted at the right hooks. A senior engineer would expect:
- `rule_extraction_latency_ms` — logged in the rule extraction node after each Groq call.
- `scan_duration_per_table_ms` — at the end of each table in `scan_table_batched` (`data_scanning.py:281`).
- `violations_per_rule` — already in `scan_summary["violations_by_rule"]` but never emitted as a structured log field.
- `llm_token_count` — Groq returns token usage in its response metadata; it is not captured anywhere.

The right hooks are: after `execute_scan_query` returns in `scan_table_batched`, and in `scan_complex_rule` after the while loop.

**GAP 3 (Confidence: 80):** `setup_logger` creates a new `FileHandler` per module per process start, because `use_timestamp=True` is the default. A project with 20 modules produces 20 log files per run in `/logs/`. File handle proliferation can hit OS limits on restricted environments (e.g. student lab machines).

**MIGRATION:** Use a single shared handler keyed to the run timestamp, or change the default to `use_timestamp=False` with rotation enabled.

**WHY IT MATTERS:** Without structured timing metrics, the faculty demo cannot show "the scan took 3.2 s across 5 tables" — the student can only say "it ran."

**REFERENCE:** https://docs.python.org/3/howto/logging-cookbook.html#logging-to-multiple-destinations

---

## 6. CONFIGURATION SPRAWL

**POSITIVE CLAIM:** Path constants in `run_hi_small.py` are collected at the top of the file (lines 43–46) rather than scattered across functions. `batch_size` and `violations_db_path` are passed through LangGraph state, so callers can override them.

**GAP (Confidence: 90):** Config is defined in at least five places with conflicting defaults:
- `data_scanning.py:44`: `violations_db_path = state.get("violations_db_path", "violations.db")` — relative path.
- `run_scan.py:48`: `--violations-db default="violations.db"` — relative.
- `run_hi_small.py:45`: `VIOLATIONS_DB = str(ROOT / "data" / "hi_small_violations.db")` — absolute.
- `audit_logger.py:25` (per prior audit): `"data/interceptor_audit.db"` — relative.
- `baseconnector.py:33`: model name `'all-MiniLM-L6-v2'` hardcoded.
- `embedding.py:37`: model name `'BAAI/bge-small-en-v1.5'` hardcoded.

**MIGRATION — Pydantic BaseSettings (10-line example):**

```python
# src/config.py
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    groq_api_key: str
    violations_db_path: Path = Path("data/violations.db")
    interceptor_audit_db: Path = Path("data/interceptor_audit.db")
    batch_size: int = 1000
    pii_model: str = "all-MiniLM-L6-v2"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
```

Every module then does `from src.config import settings` and reads `settings.violations_db_path`. One `.env` file controls all behavior.

**WHY IT MATTERS:** Five conflicting defaults mean the violations database written during `run_hi_small.py` is not the same file read by `run_scan.py` — faculty clicking between modes see different violation counts.

**REFERENCE:** https://docs.pydantic.dev/latest/concepts/pydantic_settings/

---

## 7. TYPING

**POSITIVE CLAIM:** `query_executor.py` has a fully annotated public function signature including the return type `tuple[List[Dict[str, Any]], Optional[str], Optional[str]]` (line 24). `violations_store.py` annotates all public functions. `query_builder.py` annotates `build_keyset_query` with a `Tuple[Optional[str], Dict[str, Any]]` return.

**GAP 1 (Confidence: 90):** `data_scanning.py:226–235` — `scan_table_batched` has `session` and `violations_session` typed as bare `session` (lowercase) with no annotation — they are actually `sqlmodel.Session` objects. The function signature is:

```python
def scan_table_batched(
    session,            # no type
    violations_session, # no type
    rule: StructuredRule, ...
) -> int:
```

Any static analysis tool will treat these as `Any` and not catch callers passing the wrong type.

**GAP 2 (Confidence: 85):** `embedding.py:66` — `generate_embedding` is annotated correctly but `batch_generate_embeddings` at line 183 takes `chunks: List[List[DocumentChunk]]` (a list of lists) yet the name and docstring suggest it's a flat list. The return type `List[List[EmbeddedChunk]]` is correct but the parameter shape is unobvious and will confuse any caller.

**GAP 3 (Confidence: 85):** `cache.py:21–26` — `SchemaCache.get()` and `SchemaCache.set()` have no type annotations whatsoever despite being core infrastructure called from three connectors. The return of `set()` is `None` but undeclared.

**GAP 4 (Confidence: 80):** `docs_processor.py:252–263` — `batch_process` returns `Dict[str, List[DocumentChunk]]` (unannotated). The `_detect_section` and `_chunk_text` helpers have no return type declarations.

**MIGRATION — minimal mypy config:**

```ini
# mypy.ini
[mypy]
python_version = 3.13
strict = false
disallow_untyped_defs = true
warn_return_any = true
ignore_missing_imports = true
exclude = tests/
```

Add `mypy src/` to CI. Fix the four worst offenders above first.

**WHY IT MATTERS:** Untyped `session` parameters have already caused one real bug: `complex_executor.py:336` passes `db_type="sqlite"` as a hardcoded string even when scanning Postgres — a type-checked parameter of `Literal["sqlite", "postgresql"]` would have caught this at definition time.

**REFERENCE:** https://mypy.readthedocs.io/en/stable/getting_started.html

---

## 8. DEPENDENCY HYGIENE

**POSITIVE CLAIM:** `pyproject.toml` pins minimum versions (`>=`) for all dependencies. `requires-python = ">=3.13"` is explicit. `uv` provides a lock file (`uv.lock`) that guarantees reproducible installs.

**GAP 1 (Confidence: 100):** `dotenv>=0.9.9` (line 8) is the wrong package name. The correct package is `python-dotenv`. The `dotenv` package on PyPI is a stub/placeholder. This will cause `from dotenv import load_dotenv` to fail on a clean install.

**GAP 2 (Confidence: 95):** `pytest>=9.0.2` (line 22) is in `[project.dependencies]` — a runtime dependency — instead of a development dependency. Every deployment of this package (including in production, or when someone installs it as a library) pulls in pytest. There is no `[dependency-groups]` or `[project.optional-dependencies]` section.

**MIGRATION:**

```toml
[project.optional-dependencies]
dev = [
    "pytest>=9.0.2",
    "pytest-asyncio>=0.25",
    "mypy>=1.10",
    "ruff>=0.5",
]

[project.dependencies]
# remove pytest from here
```

**GAP 3 (Confidence: 90):** `mem0ai>=1.0.4` (prior audit, confirmed unused in all reviewed files). Dead dependency adds install time, surface area for supply-chain attacks, and confusion for faculty reading the dependency list.

**GAP 4 (Confidence: 80):** No formatter or linter is listed (`ruff`, `black`). The codebase mixes 4-space and 2-space indentation in some files (e.g., `baseconnector.py:87–91` — the noisy-logger suppression block is indented under the file handler `if` block, not at function level). A `ruff` config in `pyproject.toml` fixes this class of issue.

**WHY IT MATTERS:** The wrong `dotenv` package name is a hard import failure on any clean environment — including whatever machine the faculty use to verify the demo.

**REFERENCE:** https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#dependencies-and-requirements

---

## 9. TESTING DISCIPLINE

**POSITIVE CLAIM:** `test_data_scanning.py` is an honest integration test: it creates a real SQLite file, inserts known-violating rows, runs the full stage, and asserts on `scan_summary.status`. `test_query_builder.py` tests both the first-page and cursor cases and uses the actual `StructuredRule` model rather than mocks.

**Current shape:** 5 test files, all in `tests/unit/`. Judging by the content, `test_data_scanning.py` is integration (real DB), `test_document_cache.py`, `test_sqlite_connector.py`, `test_postgres_connector.py`, and `test_query_builder.py` are unit. Zero e2e tests. The pyramid is inverted — integration at the base, nothing at the top.

**Target shape:** ~15 fast unit tests, ~5 integration tests (real SQLite), 1–2 e2e smoke tests using `run_scan.py` with a known fixture DB.

**The 3 files a senior engineer demands tests for first:**

1. **`src/agents/tools/database/violations_store.py`** — `update_violation_status` has the SQL injection vulnerability (Gap 1 in Section 1) and `get_rule_explanations` has a bare `except Exception` swallowing parse errors (line 286, known from prior audit). A unit test with a mock session would have caught the f-string IN clause. Priority: IMMEDIATE.

2. **`src/agents/tools/database/query_builder.py` — `_build_rule_condition`** — The LIKE, IN, and regex branches all use manual string escaping. A parametric test covering a value containing a single quote (`O'Brien`) would fail today for the IN clause (the escaping at line 98 uses `chr(39)+chr(39)` but the join logic can produce double-escaped values). Priority: HIGH.

3. **`src/stages/report_generator.py`** — The `_ensure_list` helper (lines 29–58) has complex branching logic for list-of-single-characters detection. It is entirely untested. A failure here means the PDF is generated with garbled remediation steps — visible to faculty. Priority: HIGH for demo reliability.

**WHY IT MATTERS:** A test for `update_violation_status` with IDs `[1, "2; DROP TABLE violations_log; --"]` would have caught the injection gap before any audit.

**REFERENCE:** https://martinfowler.com/bliki/TestPyramid.html

---

## 10. DEMO SAFETY

**POSITIVE CLAIM:** `run_intercept.py:62–64` warns when `GROQ_API_KEY` is absent without crashing. `run_scan.py:52–54` validates the DB path before connecting. `run_hi_small.py` uses absolute paths resolved from `Path(__file__)` (line 43), so it is working-directory independent.

**GAP 1 (Confidence: 100) — Groq down / rate-limited:** If Groq returns a 429 or 5xx, the LLM extraction stage raises an unhandled exception that dumps a full traceback to the faculty's screen. There is no user-friendly fallback message. The `run_hi_small.py` main loop does not catch `groq.RateLimitError` specifically.

**MIGRATION — pre-flight check function (add to `run_hi_small.py`):**

```python
def preflight():
    import httpx, os
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        err("GROQ_API_KEY not set — set it in .env"); sys.exit(1)
    r = httpx.get("https://api.groq.com/openai/v1/models",
                  headers={"Authorization": f"Bearer {key}"}, timeout=5)
    if r.status_code != 200:
        err(f"Groq API unreachable (HTTP {r.status_code}) — check connectivity")
        sys.exit(1)
    ok("Groq API reachable")
```

**GAP 2 (Confidence: 95) — Large PDF hang:** As noted in Section 2, there is no page limit. If `AML_Compliance_Policy.pdf` is accidentally replaced with a large file, `run_hi_small.py` Step 1's `process_pdf` call hangs with no timeout and no output for minutes.

**GAP 3 (Confidence: 90) — SQLite DB locked:** The `target_conn` and `violations_conn` are separate connections to potentially the same file (if misconfigured). SQLite's writer lock will cause one of them to block for 30 seconds (the `timeout=30` in `sqlite_connector.py:17`) and then raise `OperationalError: database is locked`. This exception propagates up through `data_scanning_stage`, surfaces as an unhandled error in `run_hi_small.py`, and terminates the demo. A pre-flight check should verify that no other process holds the violations DB open.

**GAP 4 (Confidence: 85) — Missing data files:** `run_hi_small.py:42–44` defines `DB_PATH`, `POLICY_PDF`, and `VIOLATIONS_DB` but only checks `DB_PATH` implicitly (PyMuPDF raises `FileNotFoundError` when the PDF is missing). The student should add an explicit preflight:

```python
for label, path in [("Target DB", DB_PATH), ("Policy PDF", POLICY_PDF)]:
    if not Path(path).exists():
        err(f"{label} not found: {path}"); sys.exit(1)
```

**GAP 5 (Confidence: 80) — No scan progress for large tables:** `scan_table_batched` in `data_scanning.py` logs at `DEBUG` level per batch and at `INFO` only on completion. For a table with 500,000 rows and `batch_size=1000`, the demo shows 500 seconds of silence at `INFO` level before printing results. Add a progress log every 10 batches:

```python
if batch_num % 10 == 0:
    log.info(f"  Table '{table}': {batch_num} batches, {total_violations} violations so far")
```

**WHY IT MATTERS:** The single most likely demo failure mode is Groq being rate-limited on a shared student API key during the live presentation. A pre-flight check and a graceful error message is the difference between a recoverable pause and a faculty-visible Python traceback.

**REFERENCE:** https://docs.python.org/3/library/sqlite3.html#sqlite3.OperationalError

---

## Critical Issues Summary (fix before demo day)

| Priority | File | Line | Issue |
|---|---|---|---|
| CRITICAL | `src/agents/tools/database/violations_store.py` | 179–184 | SQL injection via f-string IN clause |
| CRITICAL | `pyproject.toml` | 8 | `dotenv` wrong package — breaks clean install |
| HIGH | `src/agents/tools/database/baseconnector.py` | 53 | DB password logged in plaintext |
| HIGH | `src/agents/tools/database/sqlite_connector.py` | 27 | Bare `raise` outside except block |
| HIGH | `src/embedding/embedding.py` | 100, 142 | Bare `raise` outside except block |
| HIGH | `run_hi_small.py` | (no preflight) | No Groq connectivity check before demo |
| HIGH | `src/docs_processing/docs_processor.py` | 148 | No page/size limit on PDF ingestion |
| MEDIUM | `pyproject.toml` | 22 | pytest in runtime deps, not dev deps |
| MEDIUM | `src/utils/logger.py` | 125, 128 | `print()` in logging utility |
| MEDIUM | `src/stages/data_scanning.py` | 226 | Untyped `session` parameters |
