# LangGraph Architecture Review — Data Compliance Agent

**Date:** 2026-04-11
**Reviewer persona:** Senior AI engineer (LangGraph specialist)
**Scope:** Full read of `graph.py`, `interceptor_graph.py`, `unified_graph.py`, `state.py`, `interceptor_state.py`, `memory/checkpointer.py`, `memory/store.py`, `streaming/callbacks.py`, `streaming/__init__.py`, `runtime/config.py`, and every node under `src/agents/nodes/` and `src/agents/interceptor_nodes/`.

---

## 1. State Design

**POSITIVE CLAIM:** `ComplianceScannerState` uses `Annotated[List[ComplianceRuleModel], operator.add]` for `raw_rules` and `Annotated[List[str], operator.add]` for `errors` (`state.py:36`, `state.py:77`). These are the two fields that legitimately accumulate across node invocations (multi-chunk PDF extraction and multi-node error collection). The annotation is placed correctly.

**GAP 1 — Missing key `violations_db_path`:** `data_scanning_node` writes `violations_db_path` into the scan_state sub-dict (line `src/agents/nodes/data_scanning.py:55`) but reads it from state at line `51`. However, `violations_db_path` IS declared in `state.py:58`. The real gap is that the field is never written *back* into the graph state by `data_scanning_node` — its return dict at line `67-71` returns `scan_id`, `scan_summary`, and `current_stage`, but not `violations_db_path`. Downstream nodes `violation_validator_node` (line `177`) and `explanation_generator_node` (line `173`) both read `state.get("violations_db_path", "violations.db")`, relying on the fallback default instead of a properly threaded state key. If a caller sets a non-default path in the initial input, it will work because LangGraph merges state — but the pattern is fragile and undocumented.

**GAP 2 — TypedDict vs Pydantic:** The schema is `TypedDict(total=False)`, meaning every key is optional. This gives zero runtime validation. A node that returns a malformed `scan_summary` (e.g., a `str` instead of `Dict`) silently corrupts state. LangGraph 0.3+ supports Pydantic v2 `BaseModel` as the state schema with full runtime field validation.

**MIGRATION:**
```python
from pydantic import BaseModel, Field
from typing import Annotated
import operator

class ComplianceScannerState(BaseModel):
    document_path: str = ""
    db_type: Literal["sqlite", "postgresql"] = "sqlite"
    db_config: Dict[str, Any] = Field(default_factory=dict)
    raw_rules: Annotated[List[ComplianceRuleModel], operator.add] = Field(default_factory=list)
    errors: Annotated[List[str], operator.add] = Field(default_factory=list)
    current_stage: str = ""
    # ... remaining fields with typed defaults
```

**WHY IT MATTERS:** With `total=False` TypedDict, a node returning `{"scan_summary": "oops"}` will be accepted silently; Pydantic raises `ValidationError` at the merge boundary and surfaces the bug immediately.

**REFERENCE:** LangGraph docs — "Using Pydantic Models as State" — https://langchain-ai.github.io/langgraph/how-tos/state-model/

---

**GAP 3 — `structured_rules` is `List[StructuredRule]` with no reducer:** `state.py:47` declares `structured_rules: List[StructuredRule]` without `Annotated[..., operator.add]`. The `human_review_node` (`graph.py:308-381`) reads the list, mutates it in-place by appending, and then returns the entire new list under the same key. This pattern works in a linear pipeline but silently overwrites state on any parallel branch. More critically, `rule_structuring_node` (`graph.py:280`) also returns `structured_rules` as a plain list. Without a reducer, if two nodes ever write this key in the same superstep, the last write wins and data is lost.

**WHY IT MATTERS:** No reducer on a list key that is written by two distinct nodes (`rule_structuring` and `human_review`) is a latent correctness bug.

---

## 2. Graph Composition

**POSITIVE CLAIM:** The three graphs are cleanly separated at the module level. `unified_graph.py` is a pure facade — it builds the two sub-graphs and delegates `invoke`/`ainvoke`/`stream` to them. It imports nothing from node modules directly, correctly referencing only `build_graph` and `build_interceptor_graph` (`unified_graph.py:45-46`). No logic is duplicated.

**POSITIVE CLAIM:** The interceptor graph uses `Command` objects for all internal routing (`auditor.py:33`, `cache_check.py:23`, `verdict_reasoner` return dict) and declares only terminal `add_edge` calls in the graph builder, which is the correct LangGraph 1.0 Command-based routing pattern.

**GAP 1 — `unified_graph.py` is not a real `StateGraph`:** `UnifiedComplianceAgent` (`unified_graph.py:79`) is a plain Python class, not a LangGraph `StateGraph`. This means it cannot be targeted by LangGraph Studio, cannot use a shared checkpointer across sub-graph boundaries (a thread started in scanner mode cannot be resumed in interceptor mode), and cannot produce LangGraph streaming events at the top level. `graph.stream()` on the facade (`unified_graph.py:117`) returns the sub-graph's stream, which is correct in output but strips any parent-level tracing.

**MIGRATION:** Wrap the dispatch logic in a real router node inside a parent `StateGraph`:
```python
from langgraph.graph import StateGraph, START, END
from typing import Literal
from langgraph.types import Command

def router_node(state: UnifiedState) -> Command[Literal["scanner", "interceptor"]]:
    mode = state.get("mode", "scanner")
    return Command(goto=mode, update={"mode": mode})

parent = StateGraph(UnifiedState)
parent.add_node("router", router_node)
parent.add_node("scanner", build_scanner_graph())   # subgraph as node
parent.add_node("interceptor", build_interceptor_graph())
parent.add_edge(START, "router")
parent.add_edge("scanner", END)
parent.add_edge("interceptor", END)
```

**WHY IT MATTERS:** A plain Python class is invisible to LangGraph Studio and breaks the shared-checkpointer contract — a critical gap if the faculty demo uses LangGraph Studio for visualization.

**REFERENCE:** LangGraph docs — "How to add and use subgraphs" — https://langchain-ai.github.io/langgraph/how-tos/subgraph/

**GAP 2 — `input_state.pop("mode", ...)` mutates the caller's dict:** `unified_graph.py:94`, `109`, `123` all call `input_state.pop("mode", ...)`. If the caller passes a live dict they intend to reuse, the `mode` key is silently removed. Use `input_state.get()` instead.

---

## 3. Node Contract

**POSITIVE CLAIM:** `data_scanning_node` (`src/agents/nodes/data_scanning.py:18`) is exactly a thin wrapper — it translates state keys into a sub-dict and calls `data_scanning_stage`, then maps the return back to state keys. This is the correct pattern.

**POSITIVE CLAIM:** `schema_discovery_node`, `report_generation_node` (wraps `generate_reports`), and all interceptor terminal nodes are similarly thin. The pattern is consistent.

**GAP 1 — `rule_structuring_node` contains 200+ lines of business logic in `graph.py:74-284`.** This is the single largest architecture violation in the codebase. Operator alias tables (`_OP_ALIASES`, line `107`), regex normalization (lines `185-193`), cross-field detection (lines `199-206`), date-math detection (lines `208-213`), constraint inversion (lines `225-234`), auto data-type inference (lines `238-241`), and LIKE-expansion (lines `244-252`) all live inside the graph builder file. None of it is testable without instantiating a full graph or calling the function directly with a mock state dict. The node is not a wrapper — it is the stage.

**MIGRATION:** Extract to `src/stages/rule_structuring.py`, expose `rule_structuring_stage(state: dict) -> dict`, and reduce `rule_structuring_node` to:
```python
from src.stages.rule_structuring import rule_structuring_stage

def rule_structuring_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return rule_structuring_stage(state)
```

**WHY IT MATTERS:** Unit tests for operator aliasing, date-math detection, and constraint inversion currently require running through the graph machinery; extraction into a stage makes them plain function calls.

**GAP 2 — `violation_reporting_node` is 282 lines including `print_report()` at line 226.** The compliance scoring logic (lines `139-175`) — priority fallback for `total_rules_checked`, grade band assignment — belongs in a `reporting_stage`. `print_report` is a CLI helper that has nothing to do with graph state and should live in a CLI module.

**GAP 3 — `explanation_generator_node` (`src/agents/nodes/explanation_generator.py:156`) directly creates a SQLAlchemy `engine` and `Session` at lines `206-207` inside the node.** Database connection lifecycle belongs in the stage layer, not in the node. If the engine creation fails, there is no `errors` key written — the exception is unhandled at that scope (there is no outer try/except wrapping lines `206-207`).

---

## 4. Checkpointer & Memory

**POSITIVE CLAIM:** `get_checkpointer()` (`src/agents/memory/checkpointer.py:46`) is a `@contextmanager` that wraps every backend correctly. The SQLite branch (`lines 94-99`) opens `sqlite3.connect()` and closes it in `finally`. The Postgres branch (`lines 109-113`) uses `PostgresSaver.from_conn_string()` as a context manager and calls `.setup()` once. No connection leaks are possible with correct usage. This is the right pattern.

**GAP 1 — SQLite `check_same_thread=False` is needed but risky in production.** `checkpointer.py:94` passes `check_same_thread=False` to `sqlite3.connect`. This is required because LangGraph checkpoints may be read from a different thread than the one that opened the connection. However, SQLite with `check_same_thread=False` and no external locking is unsafe under concurrent graph runs sharing the same DB file. For a single-user dev demo this is fine; it must not be used with `asyncio` graph execution on the same file.

**GAP 2 — Long-term store singleton is process-local and survives no restart.** `store.py:36-43` uses a module-level `_STORE: Optional[InMemoryStore]`. `rule_extraction_node` calls `get_store()` and `ExtractionMemory(store).load_extraction()` (`rule_extraction.py:113-115`), which is the correct use: caching previously extracted PDF rules within a process run to avoid redundant LLM calls. The store's `save_correction()` and `get_corrections()` methods exist but are never called anywhere in the graph. Human corrections made during `human_review_node` are not persisted to the store — the merge of approved/edited rules back into `structured_rules` (`graph.py:355-365`) writes to graph state only, not to the long-term store.

**MIGRATION:** In `human_review_node`, after processing the review decision, persist corrections:
```python
from src.agents.memory.store import ExtractionMemory, get_store

mem = ExtractionMemory(get_store())
for rule_id, changes in edited_map.items():
    original = {r.rule_id: r for r in low_confidence}.get(rule_id)
    if original:
        mem.save_correction(rule_id, original.model_dump(), changes)
```

**WHY IT MATTERS:** The correction store is the mechanism for the model to improve over time — without writing to it, the HITL loop produces audit logs but zero learning.

**REFERENCE:** LangGraph docs — "Memory Store" — https://langchain-ai.github.io/langgraph/concepts/memory/#long-term-memory

---

## 5. Interrupt() HITL

**POSITIVE CLAIM:** `interrupt()` is imported from `langgraph.types` (`graph.py:306`), which is correct for LangGraph 0.3+. The pre-populated `review_decision` short-circuit (`graph.py:320-322`) allows batch/test runs to skip the interrupt cleanly. `escalate_human_node` in the interceptor (`terminals.py:86`) also uses `interrupt()` correctly and documents the resume payload schema inline.

**GAP 1 — Resume payload schema is not validated at the consumption site.** `human_review_node` (`graph.py:347`) calls `review.get("approved", [])` with a bare default, `review.get("dropped", [])`, and a list comprehension over `review.get("edited", [])` with an `isinstance(e, dict)` guard. If the resume payload is `{"approved": "all"}` (a string instead of a list), `set("all")` evaluates to `{'a', 'l'}`, corrupting the approved_ids set. There is no `try/except` or schema validation around the payload consumption.

**MIGRATION:**
```python
from pydantic import BaseModel, ValidationError
from typing import List

class ReviewPayload(BaseModel):
    approved: List[str] = []
    edited: List[dict] = []
    dropped: List[str] = []

try:
    review = ReviewPayload.model_validate(interrupt(review_payload))
except ValidationError as e:
    log.error(f"human_review_node: malformed resume payload: {e}")
    return {"errors": [f"human_review: bad payload — {e}"],
            "current_stage": "review_failed"}
```

**GAP 2 — No timeout mechanism.** LangGraph's `interrupt()` suspends indefinitely. If a human reviewer never resumes the thread, the graph state sits in the checkpointer consuming storage forever with no expiry. There is no scheduled cleanup or timeout sentinel.

**GAP 3 — `escalate_human_node` is declared as a terminal node in `interceptor_graph.py:107` (`add_edge("escalate_human", END)`) but internally calls `interrupt()` and expects a resume (`terminals.py:114`).** After resumption, the node returns a `Dict[str, Any]` and execution continues — but the `add_edge("escalate_human", END)` means LangGraph routes to `END` after the node completes, which is correct only on the first pass. On resume, the node runs to completion and its return is the final state. This is technically correct (interrupt-then-resume-to-same-node is valid in LangGraph), but it is non-obvious: the graph visualization will show `escalate_human → END` without indicating the interrupt point, which will confuse the faculty reviewer.

**WHY IT MATTERS:** A malformed payload silently produces incorrect rule merges that persist into the scan — the silent data corruption is worse than an explicit failure.

**REFERENCE:** LangGraph docs — "Human-in-the-loop" — https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/

---

## 6. Streaming & Callbacks

**POSITIVE CLAIM:** `stream_graph_updates()` (`src/agents/streaming/callbacks.py:144`) is a correct consumer of `graph.stream(..., stream_mode="updates")` and correctly handles both `"updates"` and `"values"` modes. `UsageTracker` is a proper `BaseCallbackHandler` subclass.

**GAP — `ProgressCallback` (`callbacks.py:107`) and `UsageTracker` are never wired into any graph compile or invoke call.** The only wiring point is `make_config` (`runtime/config.py:67`), which accepts `callbacks` as an optional argument — but no caller in the codebase passes `callbacks` to `make_config`. The `module-level agent = build_graph()` at `graph.py:455` does not pass any callbacks. The `ProgressCallback` used in `rule_extraction_node` (`rule_extraction.py:166`) is a plain Python counter that calls `log.info` — it is not a LangGraph streaming event, it does not surface to a frontend, and it is not connected to `graph.astream()`.

In LangGraph 1.0 (2026), the correct idiom for surfacing node-level progress to a frontend is `graph.astream_events()` with `version="v2"`, which emits `on_chain_start`/`on_chain_end` events per node automatically. For custom progress within a node, the node should call `adispatch_custom_event()`.

**MIGRATION:**
```python
# In an async entrypoint (e.g., a FastAPI route):
from langchain_core.callbacks.manager import adispatch_custom_event

async def rule_extraction_node(state):
    for idx, chunk in enumerate(chunks):
        # ... process chunk ...
        await adispatch_custom_event(
            "chunk_processed",
            {"chunk": idx + 1, "total": total_chunks, "rules_found": len(output.extracted_rules)},
        )
    return {"raw_rules": all_rules, "current_stage": "extraction_complete"}

# Consumer:
async for event in graph.astream_events(inputs, config=config, version="v2"):
    if event["event"] == "on_custom_event" and event["name"] == "chunk_processed":
        data = event["data"]
        print(f"Chunk {data['chunk']}/{data['total']}: {data['rules_found']} rules")
```

**WHY IT MATTERS:** Without `astream_events`, the faculty demo can only show a final result with no live progress — a significant gap for a real-time compliance interceptor demo.

**REFERENCE:** LangGraph docs — "Streaming" and `adispatch_custom_event` — https://langchain-ai.github.io/langgraph/how-tos/streaming-content/

---

## 7. Error Boundaries

**POSITIVE CLAIM:** Every deterministic node (`schema_discovery_node`, `data_scanning_node`, `report_generation_node`) wraps its body in `try/except Exception` and returns `{"errors": [...], "current_stage": "..._failed"}` rather than re-raising. The graph does not crash on a single node failure. The `errors` field with `operator.add` reducer means errors from multiple nodes accumulate correctly.

**POSITIVE CLAIM:** The interceptor's `policy_mapper_node` is registered with `RetryPolicy(max_attempts=3, backoff_factor=2.0)` (`interceptor_graph.py:69-77`). This is LangGraph's native per-node retry and is exactly the right place for transient LLM call retries.

**GAP 1 — No fallback edge from `scanning_failed` state.** When `data_scanning_node` returns `current_stage = "scanning_failed"`, the graph continues to `violation_validator_node` (the hard edge at `graph.py:441` is unconditional). `violation_validator_node` reads `scan_id = state.get("scan_id", "")` — which is `""` on failure — and returns early with `validation_skipped`. The subsequent `explanation_generator_node` does the same. This graceful degradation works, but it silently produces an empty report rather than halting and alerting. There is no conditional edge that routes `scanning_failed → END` (or to a dedicated `notify_failure` node), so the pipeline wastes LLM calls on `violation_validator` and `explanation_generator` for an empty scan.

**MIGRATION:**
```python
def _route_after_scanning(state: Dict[str, Any]) -> str:
    if state.get("current_stage") == "scanning_failed":
        return "violation_reporting"   # skip validator + explainer, go straight to report
    return "violation_validator"

workflow.add_conditional_edges(
    "data_scanning",
    _route_after_scanning,
    {"violation_validator": "violation_validator", "violation_reporting": "violation_reporting"},
)
```

**GAP 2 — `explanation_generator_node` creates `engine = create_engine(...)` at line `206` outside any `try/except`.** If the DB engine creation raises (e.g., corrupted SQLite file), the exception propagates uncaught from the node and crashes the graph run entirely — contradicting the per-node error boundary pattern used everywhere else.

**WHY IT MATTERS:** An unhandled exception in any node bypasses the `errors` accumulation mechanism, produces no `current_stage` signal, and raises to the LangGraph runtime as an unrecoverable failure.

**REFERENCE:** LangGraph docs — "Error handling" — https://langchain-ai.github.io/langgraph/concepts/low_level/#error-handling

---

## 8. Runtime Configuration

**POSITIVE CLAIM:** `make_config()` (`runtime/config.py:67`) correctly builds a `RunnableConfig` dict with `configurable.thread_id`, `recursion_limit`, and optional `callbacks`, `tags`, and `metadata`. This is the correct LangGraph idiom. `get_rate_limiter()` as a singleton avoids multiple Groq rate limiter instances competing with each other.

**GAP 1 — Per-node configuration is passed via state, not via `RunnableConfig.configurable`.** `batch_size` (`state.py:59`) and `max_batches_per_table` (`state.py:60`) are scan tuning parameters that are passed as state keys. In LangGraph, parameters that do not change within a run and that the caller wants to configure without contaminating state should use the `configurable` dict in `RunnableConfig`. Nodes access this via `config: RunnableConfig` as a second argument.

**GAP 2 — LLM model name, temperature, and API key are hardcoded constants inside nodes.** `violation_validator_node` hardcodes `_MODEL = "llama-3.1-8b-instant"` (`violation_validator.py:50`). `explanation_generator_node` hardcodes `_MODEL = "llama-3.3-70b-versatile"` (`explanation_generator.py:48`). `verdict_reasoner_node` hardcodes `model="llama-3.3-70b-versatile"` (`verdict_reasoner.py:44`). None of these are overridable without editing source code.

**MIGRATION:**
```python
# In runtime/config.py — extend make_config:
def make_config(thread_id: str = "default", *, scan_model: str = "llama-3.1-8b-instant",
                reasoning_model: str = "llama-3.3-70b-versatile", batch_size: int = 1000,
                **kwargs) -> Dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id,
                               "scan_model": scan_model,
                               "reasoning_model": reasoning_model,
                               "batch_size": batch_size}, ...}
    return config

# In a node:
from langchain_core.runnables import RunnableConfig

def violation_validator_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    cfg = config.get("configurable", {})
    model = cfg.get("scan_model", "llama-3.1-8b-instant")
    llm = ChatGroq(model=model, ...)
```

**GAP 3 — `agent = build_graph()` at `graph.py:455` (module-level) calls `build_graph()` with no checkpointer.** This is the instance LangGraph Studio uses. Without a checkpointer, the Studio instance cannot demonstrate HITL resume — the interrupt will fire but the state will not be persisted between the suspend and resume calls. For a faculty demo of HITL, the Studio entrypoint must be compiled with at least a `SqliteSaver`.

**WHY IT MATTERS:** Model names and batch sizes are deployment decisions that vary between dev, staging, and prod. Hardcoding them into node files means changing environments requires source edits — the canonical anti-pattern for configurable agents.

**REFERENCE:** LangGraph docs — "Configuration" / `RunnableConfig` — https://langchain-ai.github.io/langgraph/concepts/low_level/#configuration

---

## Summary of Critical Gaps (Ranked by Faculty Impact)

| Priority | Area | File:Line | Impact |
|---|---|---|---|
| 1 | `rule_structuring_node` 200+ lines of business logic in graph.py | `graph.py:74-284` | Untestable, wrong layer |
| 2 | `UnifiedComplianceAgent` is a plain class, not a StateGraph | `unified_graph.py:79` | Invisible to Studio, no shared checkpointer |
| 3 | `ProgressCallback` never wired; no `astream_events` | `callbacks.py:107`, `graph.py:448` | Zero live progress in demo |
| 4 | `agent = build_graph()` with no checkpointer at module level | `graph.py:455` | HITL interrupt cannot be demonstrated in Studio |
| 5 | Resume payload not validated in `human_review_node` | `graph.py:347` | Silent data corruption on malformed resume |
| 6 | `explanation_generator` creates DB engine outside try/except | `explanation_generator.py:206` | Unhandled exception crashes graph |
| 7 | Hardcoded model names in 3 nodes | `violation_validator.py:50`, `explanation_generator.py:48`, `verdict_reasoner.py:44` | Not configurable without source edits |
| 8 | Human corrections never persisted to long-term store | `graph.py:355-365`, `store.py:103` | HITL loop produces no learning signal |
