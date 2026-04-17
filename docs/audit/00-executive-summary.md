# Executive Summary — Data Compliance Agent Audit

**Date:** 2026-04-11
**Auditors:** 5 senior AI engineers (parallel review across LLM engineering, LangGraph architecture, Python craft, code quality, and security/ops)
**Purpose:** Pre-presentation audit ahead of college faculty demo (1 week out)

---

## What the project is

A LangGraph-based AI agent that:
1. Reads regulatory policy PDFs and extracts compliance rules with Groq Llama (`llama-3.3-70b-versatile` for extraction, `llama-3.1-8b-instant` for fast classification)
2. Discovers SQLite/Postgres schemas, identifies PII columns via semantic similarity
3. Scans target databases for violations using keyset pagination, with a Python-side complex-rule executor for BETWEEN/REGEX/cross-field/date-math rules
4. Runs LLM-based false-positive validation, generates explanations, and produces PDF + HTML audit reports
5. Includes a real-time SQL query interceptor mode (APPROVE/BLOCK verdicts) backed by a separate LangGraph

---

## Top-line findings

**Architecture is sound but ~30% of documented features are defined-but-not-wired:**
- Qdrant vector DB indexes policy chunks but is **never queried during rule extraction** — RAG is inert
- `ProgressCallback` is defined in `streaming/callbacks.py` but **never passed to `workflow.compile()`** — no streaming reaches users
- `get_rate_limiter()` is applied to **only 1 of 5** LLM-calling nodes (`rule_extraction.py`)
- Middleware decorators (retry/guardrails/logging) likewise applied to only 1 of 5 LLM nodes

**6 latent runtime bugs found that the test suite doesn't catch:**
1. `pyproject.toml:8` lists `dotenv>=0.9.9` — wrong PyPI package name. Correct: `python-dotenv>=1.0.1`. **Breaks `from dotenv import load_dotenv` on any clean install.**
2. `violations_store.py:179-184` — SQL injection via f-string `WHERE id IN ({ids_csv})` clause
3. `baseconnector.py:53` — logs full Postgres connection string including plaintext password
4. `sqlite_connector.py:27` and `embedding.py:100,142` — bare `raise` outside `except` block produces cryptic `RuntimeError: No active exception`
5. `middleware/retry.py:80` — backoff multiplier is `(1 + backoff_factor)` = **3× per retry** instead of the documented 2×
6. `complex_executor.py:337` — hardcodes `db_type="sqlite"` ignoring the parameter, breaks Postgres complex-rule scans
7. `sqlite_connector.py:29` — `with self.session as session:` *closes* `self.session`; subsequent scans use a dead session

**README does not match the code:**
- Scanner has 9 nodes (README claims 11)
- Interceptor has 10 nodes (README claims 9)
- README references `agent-chat-ui/` and `langgraph.json` — neither exists in the repo (frontend was deleted; LangGraph config never written)

---

## The 3 biggest strengths (use these on slides)

1. **Clean separation of concerns** — `state → memory → tools → middleware → prompts → streaming → runtime → nodes → graph` is the layering taught in your own `AGENT_BUILDING_GUIDE.md`. The HITL `interrupt()` flow works correctly (`graph.py:306,344`), the keyset paginator avoids OFFSET (`query_builder.py:14-58`), and the violations log lives in an external SQLite file so the LangGraph state stays small.
2. **Multi-graph design** — three composable graphs (scanner, interceptor, unified router), with conditional routing, retry policies on policy-mapping (`interceptor_graph.py:69-77`), and external violation/audit databases.
3. **Dual-layer memory architecture** — checkpointer factory supports memory/sqlite/postgres backends with correct context-manager wrapping (`memory/checkpointer.py:46-113`); long-term store exists for cross-thread learning (currently underused but architected correctly).

## The 3 biggest gaps (must close before the demo)

1. **`pyproject.toml:8` wrong package name** — one-character fix; demo-blocker.
2. **SQL injection in `violations_store.py:179-184`** — exploitable the moment an HTTP layer is added.
3. **3 features documented but never wired** — Qdrant retrieval, streaming callbacks, rate limiter on most LLM nodes. The graph runs without them; they're a story you can't honestly tell.

## The single biggest demo-day risk

`run_hi_small.py` has no preflight check for Groq connectivity. A 429 or 5xx during the live presentation will dump a Python traceback to the projector. The 10-line preflight in `docs/audit/05-action-plan.md` Phase 0.8 is the difference between a recoverable pause and a public failure.

---

## Where to read more

- **Full LLM engineering review** → `01-llm-engineering-review.md` (prompts, model selection, RAG, guardrails, eval, prompt injection, cost controls)
- **Full LangGraph architecture review** → `02-langgraph-architecture-review.md` (state design, graph composition, node contract, checkpointer, HITL, streaming, error boundaries, runtime config)
- **Full code quality + security + ops review** → `03-code-quality-security-ops-review.md` (SQL injection, secrets, error handling, logging, configuration, typing, deps, testing, demo safety)
- **Full Python craft review** → `04-python-code-review.md` (Pythonic idioms, modern Python 3.13 features, type hints, dataclass vs Pydantic, context managers, generators, asyncio, stdlib hygiene, signatures, performance)
- **Action plan with Phase 0–6 sequence** → `05-action-plan.md`

---

## Sequencing summary (1 week)

```
Day 1 AM    Phase 0 — Critical pre-flight fixes (dotenv, SQL injection, bare-raises, password leak, retry formula)
Day 1 PM    Phase 1 — Cleanup
Day 2-3     Phase 2 — Restructure (wire middleware, callbacks, langgraph.json, README fixes, extract rule_structuring)
Day 4       Phase 3 — Quality (bare excepts, type hints, modernize Optional → |None)
Day 5       Phase 4 — Correctness/eval (DeepEval + 5 critical test files)
Day 6       Phase 5 — Demo readiness (preflight, pinned dataset, screenshots, dry-run)
Day 7       Phase 6 — UI regen OR buffer
```
