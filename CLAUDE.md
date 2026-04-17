# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Data Compliance Agent — a LangGraph pipeline that reads a regulatory PDF, extracts rules, scans SQLite/Postgres for violations, and emits PDF/HTML audit reports. Python ≥3.13, `uv`-managed. LLM calls go through Groq (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`). There is a second graph (`interceptor_graph`) that reviews individual SQL queries pre-execution (APPROVE/BLOCK) and a `unified_graph` router that dispatches to either mode.

Note: `README.md` references an `agent-chat-ui/` Next.js frontend and a `langgraph.json` — neither is present in this repo snapshot. Treat the backend as the source of truth. When asked about the frontend or `langgraph dev`, verify the files exist before acting.

## Commands

```bash
# Install (editable) into the uv venv
uv venv
uv pip install -e .

# Quick sanity demo — indexes data/raft.pdf, probes HI-Small_Trans.db for PII
python main.py

# End-to-end pipeline (PDF → rules → scan → validate → explain → report)
python run_hi_small.py

# Scan-only stage against a SQLite DB (bypasses LLM rule extraction)
uv run python run_scan.py --db data/HI-Small_Trans.db

# Real-time SQL query interceptor
python run_intercept.py

# Tests
pytest tests/unit/ -v
pytest tests/unit/test_data_scanning.py -v     # single module
pytest tests/unit/ -m "not slow" -v
```

Environment: `.env` must define `GROQ_API_KEY`. Redis is optional — the cache layer falls back to in-memory LRU if it's unreachable.

## Architecture

### State is the contract
`src/agents/state.py` defines `ComplianceScannerState` — a single `TypedDict(total=False)` that every scanner node reads from and writes back to. Lists accumulated across nodes (`raw_rules`, `errors`) are `Annotated[List[...], operator.add]` so streamed nodes can append safely. Before changing any node signature, update the state schema first; it is the interface, not an implementation detail. The interceptor pipeline has its own parallel schema at `src/agents/interceptor_state.py`.

### Three graphs, shared tooling
- `src/agents/graph.py` — the scanner `StateGraph`. Pipeline: `rule_extraction → schema_discovery → rule_structuring → [conditional: human_review if any rule.confidence < 0.7] → data_scanning → violation_validator → explanation_generator → violation_reporting → report_generation → END`. The `rule_structuring_node` in `graph.py` is currently a pass-through stub — real column mapping happens inside `rule_extraction` output or downstream.
- `src/agents/interceptor_graph.py` — cache-check → context → intent classify → policy map → verdict → auditor (loops on FAIL with retry budget) → executor. Low-confidence or exhausted retries route to `escalate_human`.
- `src/agents/unified_graph.py` — a router that inspects the input and dispatches to scanner or interceptor.

### Node vs. stage split
`src/agents/nodes/*.py` are thin LangGraph node wrappers — they read state, call into a `stage`, write state. Heavy logic lives in `src/stages/*.py` (`data_scanning.py`, `report_generator.py`, `rule_structuring.py`) so it can be unit-tested without a running graph. When adding a new scanning capability, put the algorithm in `stages/` and keep the node as a plumbing layer.

### Human-in-the-loop
Low-confidence structured rules trigger LangGraph's `interrupt()` with a structured resume payload of shape `{approved, edited, dropped}`. Never silently auto-approve — the HITL gate is intentional and the `review_decision` key on state is how downstream nodes know the rules are trusted.

### Database tooling
`src/agents/tools/database/` is the only place that talks to target DBs:
- `baseconnector.py` — ABC that also carries PII-column detection (uses sentence-transformers semantic similarity against category prompts).
- `sqlite_connector.py`, `postgres_connector.py` — concrete connectors, both returning the same schema dict shape.
- `query_builder.py` — **keyset pagination**, not `OFFSET`. Large tables (millions of rows) must stay on this path; don't introduce offset-based pagination "for simplicity."
- `complex_executor.py` — Python-side evaluator for rules that can't be a single SQL `WHERE`: `BETWEEN`, regex, cross-field, date-math. If a new rule operator can't round-trip through SQL, add it here rather than forcing it into `query_executor.py`.
- `violations_store.py` — violations are written to an **external SQLite file** (`violations.db` at repo root by default), not into LangGraph state. This keeps checkpoints small and makes the audit trail independently queryable. Preserve this split.

### Middleware
`src/agents/middleware/` provides composable decorators applied at node definition: retry w/ exponential backoff for LLM calls, input/output guardrails, node-timing logger. Wrap new LLM-touching nodes in these rather than reinventing retry logic.

### Memory
`src/agents/memory/` holds both the LangGraph **checkpointer** (short-term thread state, supports `memory` / `sqlite` / `postgres` backends) and a long-term **store** for cross-thread learning (rule patterns, prior user corrections). These are deliberately separate — don't conflate them.

### Caching
`src/utils/document_cache.py` does Redis-then-memory-LRU caching for parsed PDFs and embeddings; `src/utils/cache.py` does TTL caching for schema discovery. Qdrant (local mode) stores policy-doc embeddings via `src/vector_database/qdrant_vectordb.py`. Embedding model is `BAAI/bge-small-en-v1.5` via FastEmbed; PII semantic matching uses `all-MiniLM-L6-v2` via sentence-transformers.

### LLM model pinning
Different nodes use different Groq models on purpose — 70b for rule extraction and explanation (quality), 8b for violation validation (fast/cheap binary classification). Check `src/agents/prompts/` and per-node model selection before "unifying" these.

## Conventions specific to this repo

- Rule-operator aliasing is non-obvious: ~40 SQL operator aliases are normalized in the query builder. When adding rules, check the normalization table before inventing a new operator string.
- `run_scan.py` ships a `DEFAULT_RULES` list so you can exercise the scanner without running the LLM extraction stages — useful when debugging just the DB path.
- `AGENT_BUILDING_GUIDE.md` is a long-form companion doc that explains *why* the `state → memory → tools → prompts → middleware → nodes → graph` layering exists. Read it before restructuring the agent layout.
- Windows is a supported dev platform (the project was developed on it). Use forward slashes in paths and Unix shell syntax in scripts; don't add Windows-only commands without a cross-platform fallback.
