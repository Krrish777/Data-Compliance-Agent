# Action Plan — Data Compliance Agent

> This is a copy of the master plan for in-repo reference. The authoritative version lives at `C:\Users\777kr\.claude\plans\happy-coalescing-codd.md`.
> All findings here come from the four senior reviews in this directory (`01-04-*.md`) and the executive summary (`00-executive-summary.md`).

---

## Sequence at a glance (1 week, ~6 productive workdays)

```
Day 1 AM    Phase 0 — Critical pre-flight fixes
Day 1 PM    Phase 1 — Cleanup
Day 2-3     Phase 2 — Restructure
Day 4       Phase 3 — Quality
Day 5       Phase 4 — Correctness & evaluation
Day 6       Phase 5 — Demo readiness
Day 7       Phase 6 — UI regen (stretch) OR buffer
```

---

## Phase 0 — Critical pre-flight fixes (~3-4 hours)

These items block everything else. They are correctness bugs that already broke the demo on a clean checkout, latent SQL injection vectors, or 1-line fixes with disproportionate value.

| # | File:Line | Fix |
|---|---|---|
| 0.1 | `pyproject.toml:8` | `dotenv>=0.9.9` → `python-dotenv>=1.0.1`. Run `uv lock --upgrade-package python-dotenv`. |
| 0.2 | `violations_store.py:179-184` | Replace f-string `WHERE id IN ({ids_csv})` with bound parameters (see `03-code-quality-security-ops-review.md` § 1). |
| 0.3 | `baseconnector.py:53` | `re.sub(r":[^:@]+@", ":***@", self.connection_string)` before logging. |
| 0.4 | `sqlite_connector.py:27`, `embedding.py:100,142` | Replace bare `raise` with explicit `RuntimeError("...")`. |
| 0.5 | `middleware/retry.py:80` | `delay *= backoff_factor` (was `delay *= (1 + backoff_factor)` — wrong by 50%). |
| 0.6 | `complex_executor.py:337` | `db_type=db_type` instead of hardcoded `"sqlite"`. |
| 0.7 | `sqlite_connector.py:29` | Use `with Session(self.engine) as session:` for discovery so `self.session` stays alive. |
| 0.8 | `run_hi_small.py` | Add `preflight()` that checks `GROQ_API_KEY` + does a HEAD to `https://api.groq.com/openai/v1/models`. |
| 0.9 | `docs_processor.py:148` | Add `MAX_PAGES = 200` and `MAX_FILE_MB = 50` size guards. |

After Phase 0: `pytest tests/unit/ -v` (must stay green) and `python run_hi_small.py` end-to-end smoke check.

---

## Phase 1 — Cleanup (~3 hours)

1. Delete `src/docs_processing/enriched_chunk.py` (broken import; never used).
2. Remove `mem0ai>=1.0.4` from `pyproject.toml`. KEEP `pytest`, `ipython`, `ipykernel`.
3. Replace 10+ `print()` calls in `src/agents/nodes/violation_reporting.py:238-250+` with `log.info()`.
4. Replace 2 `print()` calls inside `src/utils/logger.py:125,128`.
5. Remove redundant `import json as _json` blocks in `src/stages/report_generator.py:37,49`.
6. `git mv src/models/compilance_rules.py src/models/compliance_rules.py` and update imports in `state.py:11`, `nodes/rule_extraction.py:34`.
7. Audit `src/agents/nodes/__init__.py` `__all__` — keep only the symbols re-imported elsewhere.

---

## Phase 2 — Restructure (~12 hours)

1. **Wire middleware to all 5 LLM-calling nodes** (today only `rule_extraction.py` uses `@retry_with_backoff` and `@log_node_execution`). Apply to: `violation_validator.py`, `explanation_generator.py`, `intent_classifier.py`, `policy_mapper.py`, `verdict_reasoner.py`, `auditor.py`. Pass `rate_limiter=get_rate_limiter()` to every `ChatGroq(...)` constructor.
2. **Extract `rule_structuring_node` from `graph.py:74-284`** into `src/stages/rule_structuring.py::rule_structuring_stage(state)`. The node becomes a 3-line wrapper. This is the single biggest architecture violation in the codebase.
3. **Add `operator.add` reducer** to `structured_rules` in `state.py` (currently written by 2 nodes with no reducer — silent overwrite bug).
4. **Wire streaming via `astream_events(version="v2")`** instead of the never-wired `ProgressCallback`. See `02-langgraph-architecture-review.md` § 6 for the snippet.
5. **Convert `unified_graph.py` to a real `StateGraph`** with a router node (currently a plain Python class invisible to LangGraph Studio).
6. **Give the module-level `agent` a `SqliteSaver` checkpointer** at `graph.py:455` so HITL can be demoed in LangGraph Studio.
7. **Recreate `langgraph.json`** at the repo root with three graph entries (scanner, interceptor, unified).
8. **Centralize LLM model selection** in `src/agents/runtime/config.py::LLM_MODELS`. Promote `violation_validator` to 70b for `data_security` and `data_privacy` rule types.
9. **Add `max_tokens` caps** to `ChatGroq` calls in `explanation_generator.py:205` (800) and `violation_validator.py:211` (600).
10. **Add a few-shot example** to `src/agents/prompts/rule_extraction.py` between the schema description and the "RETURN ONLY" instruction. Single highest-ROI prompt change.
11. **Externalize interceptor prompts** into `src/agents/prompts/interceptor_prompts.py`.
12. **Add prompt-injection defense** to `validate_chunk_input` and wrap user query in `verdict_reasoner.py:115` in `<user_query>...</user_query>` XML tags.
13. **Decide what to do about Qdrant** — recommend Option A (move `LocalVectorDB` indexing to `examples/`, drop the "Qdrant retrieval" claim from README and slides). Option B (actually wire RAG into `rule_extraction_node`) is ~1 day and a strong story for the presentation.
14. **Fix the README's wrong node counts** (scanner has 9, interceptor has 10). Remove `agent-chat-ui/` references until a frontend exists.
15. **Extract `print_report()` from `nodes/violation_reporting.py:226`** into `src/cli/report_print.py`. Move scoring logic into `src/stages/violation_reporting.py`.

---

## Phase 3 — Quality (~6 hours)

1. **Fix all 8 bare-except handlers**: see `03-code-quality-security-ops-review.md` § 4 for the table.
2. **Wrap `explanation_generator.py:206` engine creation** in try/except with `errors` accumulation.
3. **Validate the `interrupt()` resume payload** in `human_review_node` with a Pydantic `ReviewPayload` model.
4. **Convert `StructuredRule` to Pydantic `BaseModel`** with `field_validator`s for `confidence` (0..1), `operator` (non-empty), `rule_type` (literal). Removes the `hasattr(rule, "rule_id")` ducktyping in 2 nodes.
5. **Modernize type hints across the codebase**: `Optional[X]` → `X | None`, `Dict[str, X]` → `dict[str, X]`, `List[X]` → `list[X]`, `Tuple[X, Y]` → `tuple[X, Y]`. Affects ~15 files.
6. **Add return type hints** to every node entry point (today most are `def x(state: Dict[str, Any])` with no `-> Dict[str, Any]`).
7. **Add a `TypedDict`** for `identify_sensitive_columns` return.
8. **Replace inflated cost accounting** in `verdict_reasoner.py:59`, `auditor.py:133`, `intent_classifier.py:184` with token-based math from `response.usage_metadata`. Today's hardcoded `$0.045/call` is 15× the real Groq cost.
9. **Centralize config with Pydantic Settings** in `src/config.py`. See `03-code-quality-security-ops-review.md` § 6 for the 10-line example.

---

## Phase 4 — Correctness & evaluation (~6 hours)

| New test file | What it covers |
|---|---|
| `tests/unit/test_complex_executor.py` | Table-driven test: ~30 cases for BETWEEN, REGEX, cross-field, date-math rules. |
| `tests/unit/test_violation_validator.py` | Mock `ChatGroq`, feed canned LLM responses, assert verdict mapping. |
| `tests/unit/test_report_generator.py` | HTML snapshot test + PDF non-empty assertion. |
| `tests/unit/test_interceptor_pipeline.py` | One APPROVE case + one BLOCK case end-to-end. |
| `tests/unit/test_human_review.py` | Pre-populated `review_decision` short-circuit; malformed payload triggers `ValidationError`. |
| `tests/eval/test_golden_runs.py` | DeepEval golden cases — 3-5 fixtures with known expected violation counts. |

Add `pytest-asyncio`, `deepeval`, `mypy`, `ruff` to `[project.optional-dependencies] dev`. Add a minimal `mypy.ini`.

---

## Phase 5 — Demo readiness (~6 hours)

1. **Pin the demo dataset** — small subset of `data/HI-Small_Trans.db` (or 5-table synthetic with 1k rows). Demo runs in <90 seconds.
2. **Pin the demo policy PDF** — verify it produces ≥10 rules and ≥5 violations.
3. **Capture screenshots** of: rule extraction output, structured rules table, violations list, the final PDF report, the interceptor APPROVE/BLOCK cards.
4. **Write the 60-second pitch** for slide 1. Use the framing from your vault's `Agent-Architecture-MOC.md`: *why* LangGraph (vs raw LangChain, vs BeeAI, vs Claude SDK).
5. **Dry-run** `run_hi_small.py` and `run_intercept.py` on a clean checkout.

---

## Phase 6 — Frontend regen (stretch only)

Only if Phases 0-5 finish with ≥1 day to spare. Don't restore the deleted `agent-chat-ui/` from git history (it'll be stale against the cleaned-up backend). Scaffold a fresh Next.js 15 + shadcn/ui app: Scanner view (PDF + DB picker → progress → results) and Interceptor view (SQL input → verdict card). Use `@langchain/langgraph-sdk` to talk to `langgraph dev`.

---

## Verification (run after each phase)

1. `pytest tests/unit/ -v` — all green.
2. `python run_scan.py --db data/HI-Small_Trans.db` — non-zero violation count, no exceptions.
3. `python run_hi_small.py` — full pipeline end-to-end. PDF + HTML reports written.
4. `python run_intercept.py` — both APPROVE and BLOCK verdicts land.
5. `langgraph dev` — starts cleanly using the new `langgraph.json`. All three graphs listed at `http://127.0.0.1:2024`.
6. Follow the README "Getting Started" verbatim on a clean checkout. Fix the README, not the user.
7. `mypy src/` — 0 errors after Phase 4.4.
8. Slides dry-run out loud, with screenshots, in front of a friend.
