# Building a LangGraph Agent — A Practitioner's Guide

> Distilled from building the **Data Compliance Agent**.  
> Every pattern below has a working implementation in `src/agents/`.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Step 1 — Define State](#2-step-1--define-state)
3. [Step 2 — Memory (Short-term + Long-term)](#3-step-2--memory)
4. [Step 3 — Build Tools](#4-step-3--build-tools)
5. [Step 4 — Write Prompts](#5-step-4--write-prompts)
6. [Step 5 — Add Middleware](#6-step-5--add-middleware)
7. [Step 6 — Create Nodes](#7-step-6--create-nodes)
8. [Step 7 — Streaming & Callbacks](#8-step-7--streaming--callbacks)
9. [Step 8 — Runtime Configuration](#9-step-8--runtime-configuration)
10. [Step 9 — Wire the Graph](#10-step-9--wire-the-graph)
11. [Step 10 — Run It](#11-step-10--run-it)
12. [Common Pitfalls](#12-common-pitfalls)
13. [File Layout Template](#13-file-layout-template)

---

## 1. Architecture Overview

```
src/agents/
├── state.py              # TypedDict — the contract
├── graph.py              # StateGraph assembly
├── memory/
│   ├── checkpointer.py   # Short-term (thread-level persistence)
│   └── store.py          # Long-term (cross-thread knowledge)
├── tools/
│   └── pdf_reader.py     # @tool-decorated functions
├── middleware/
│   ├── retry.py          # Exponential backoff for LLM calls
│   ├── guardrails.py     # Input/output validation
│   └── logging_mw.py     # Node-level timing & logging
├── prompts/
│   └── rule_extraction.py  # ChatPromptTemplate + system prompt
├── streaming/
│   └── callbacks.py      # UsageTracker, ProgressCallback
├── runtime/
│   └── config.py         # RunnableConfig factory, rate limiter
└── nodes/
    ├── rule_extraction.py      # LLM node
    ├── schema_discovery.py     # Deterministic node
    ├── data_scanning.py        # Deterministic node
    └── violation_reporting.py  # Deterministic node
```

**Principle:** Every concern gets its own module. Nodes import from
middleware, prompts, memory, etc. — they never own that logic themselves.

---

## 2. Step 1 — Define State

Your state is a `TypedDict` that every node reads from and writes to.
It is **the contract** — design it before writing any node.

```python
# src/agents/state.py
import operator
from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict

class MyAgentState(TypedDict, total=False):
    # Input
    input_path: str
    
    # Accumulated results (use Annotated + operator.add for lists)
    results: Annotated[List[dict], operator.add]
    
    # Cross-cutting
    current_stage: str
    errors: Annotated[List[str], operator.add]
```

**Key rules:**
- `Annotated[List[...], operator.add]` — nodes **append** to the list instead of overwriting.
- `total=False` — every key is optional (nodes only write what they own).
- Keep state **flat** — avoid deep nesting.

---

## 3. Step 2 — Memory

### Short-term: Checkpointer

Saves state at every graph step. Required for `interrupt()` (human-in-the-loop)
and crash recovery.

```python
# src/agents/memory/checkpointer.py
from contextlib import contextmanager
from langgraph.checkpoint.memory import InMemorySaver

@contextmanager
def get_checkpointer(backend="memory", *, db_path=None, conn_string=None):
    if backend == "memory":
        yield InMemorySaver()
        return
    
    if backend == "sqlite":
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver  # pip install langgraph-checkpoint-sqlite
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            yield SqliteSaver(conn)
        finally:
            conn.close()
        return
    
    if backend == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver  # pip install langgraph-checkpoint-postgres
        with PostgresSaver.from_conn_string(conn_string) as saver:
            saver.setup()
            yield saver
        return
```

> **Critical:** `PostgresSaver.from_conn_string()` is a **context manager**.
> Always use `with`. The old pattern of `return PostgresSaver.from_conn_string(...)` leaks connections.

### Long-term: Store

Cross-thread knowledge that survives across sessions.

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

# Save
store.put(("extractions",), "doc_hash", {"rules": [...], "extracted_at": "..."})

# Load
item = store.get(("extractions",), "doc_hash")
```

---

## 4. Step 3 — Build Tools

Use `@tool` from `langchain_core.tools`. This gives you schema auto-documentation
and makes the function callable via `tool.invoke({"arg": value})`.

```python
from langchain_core.tools import tool

@tool
def read_pdf_chunks(pdf_path: str) -> list[dict]:
    """Read a PDF and return text chunks."""
    processor = DocumentProcessor()
    chunks = processor.process_pdf(pdf_path)
    return [{"content": c.content, "chunk_id": c.chunk_id} for c in chunks]
```

---

## 5. Step 4 — Write Prompts

Keep prompts in a dedicated module. Use `ChatPromptTemplate`.

```python
from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """You are an expert analyst..."""

my_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Analyze this: {text}"),
])
```

**Tips:**
- If your Pydantic model uses `Literal["a", "b"]`, the prompt MUST list the exact same values.
- Include `{chunk_index}` / `{total_chunks}` so the LLM knows it's seeing a fragment.

---

## 6. Step 5 — Add Middleware

### Retry with backoff

```python
@retry_with_backoff(max_retries=3, initial_delay=2.0)
def call_llm(chain, inputs):
    return chain.invoke(inputs)
```

### Input guardrails

```python
class InputGuardrail:
    max_chars: int = 8000
    min_chars: int = 50
    strip_pii: bool = True

    def __call__(self, text: str) -> str | None:
        # Returns cleaned text or None to skip
```

### Output guardrails

```python
class OutputGuardrail:
    def validate_rule(self, rule) -> rule | None:
        # Check rule_type, confidence range, non-empty text
```

### Node logging

```python
@log_node_execution
def my_node(state):
    ...
# Logs: [NODE START] my_node | input_keys=[...]
# Logs: [NODE END]   my_node | duration=1234.5ms | output_keys=[...]
```

---

## 7. Step 6 — Create Nodes

A node is just a function: `state → dict`.

```python
@log_node_execution
def my_llm_node(state: dict) -> dict:
    # 1. Get inputs from state
    text = state["input_text"]
    
    # 2. Input guardrail
    clean = validate_input(text)
    if not clean:
        return {"results": [], "errors": ["empty input"]}
    
    # 3. Build LLM chain
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, rate_limiter=get_rate_limiter())
    structured_llm = llm.with_structured_output(MyOutputModel)
    chain = my_prompt | structured_llm
    
    # 4. Call with retry
    @retry_with_backoff(max_retries=3)
    def _call(inputs):
        return chain.invoke(inputs)
    
    result = _call({"text": clean})
    
    # 5. Output guardrail
    result = validate_output(result)
    
    # 6. Save to memory
    memory.save(result)
    
    return {"results": [result], "current_stage": "done"}
```

**Pattern:** Every LLM node follows these 6 steps.

---

## 8. Step 7 — Streaming & Callbacks

```python
from src.agents.streaming import UsageTracker, stream_graph_updates

tracker = UsageTracker()
config = make_config(thread_id="run-001", callbacks=[tracker])

final_state = stream_graph_updates(graph, initial_state, config, stream_mode="updates")

print(tracker.summary())
# {'prompt_tokens': 12345, 'completion_tokens': 678, 'total_tokens': 13023, 'llm_calls': 15}
```

---

## 9. Step 8 — Runtime Configuration

```python
from src.agents.runtime import make_config, get_rate_limiter

config = make_config(
    thread_id="scan-001",
    callbacks=[tracker],
    tags=["production"],
    metadata={"user": "admin"},
)

# Rate limiter for Groq free tier
rate_limiter = get_rate_limiter(requests_per_second=0.1)
llm = ChatGroq(model="...", rate_limiter=rate_limiter)
```

---

## 10. Step 9 — Wire the Graph

```python
from langgraph.graph import StateGraph, START, END

def build_graph(checkpointer=None):
    workflow = StateGraph(MyAgentState)
    
    # Add nodes
    workflow.add_node("extract", extract_node)
    workflow.add_node("transform", transform_node)
    workflow.add_node("review", human_review_node)
    workflow.add_node("report", report_node)
    
    # Linear edges
    workflow.add_edge(START, "extract")
    workflow.add_edge("extract", "transform")
    
    # Conditional edge
    workflow.add_conditional_edges(
        "transform",
        lambda state: "review" if state.get("needs_review") else "report",
        {"review": "review", "report": "report"},
    )
    
    workflow.add_edge("review", "report")
    workflow.add_edge("report", END)
    
    return workflow.compile(checkpointer=checkpointer)
```

---

## 11. Step 10 — Run It

```python
from src.agents.graph import build_graph
from src.agents.memory import get_checkpointer
from src.agents.runtime import make_config
from src.agents.streaming import UsageTracker, stream_graph_updates

tracker = UsageTracker()
config = make_config(thread_id="run-001", callbacks=[tracker])

with get_checkpointer("memory") as cp:
    graph = build_graph(checkpointer=cp)
    
    # Option A: invoke (blocking, returns final state)
    result = graph.invoke(initial_state, config=config)
    
    # Option B: stream (prints node-by-node updates)
    result = stream_graph_updates(graph, initial_state, config)

print(tracker.summary())
```

---

## 12. Common Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| `PostgresSaver` not as context manager | Connection pool leak, hangs | Use `with PostgresSaver.from_conn_string(...) as saver:` |
| Missing `pip install langgraph-checkpoint-sqlite` | `ModuleNotFoundError` | These are separate packages, not included with `langgraph` |
| `logprobs=True` + `with_structured_output()` | Groq 400 error | Create a fresh `ChatGroq` without `.bind(logprobs=True)` for structured output |
| Prompt says `retention` but Pydantic requires `data_retention` | Validation error | Prompt literal values must exactly match `Literal[...]` in the model |
| `Optional[int]` field gets `""` from LLM | Groq 400 (server-side schema validation) | Remove the field or change to `Optional[str]` — Pydantic validators can't help because Groq validates before returning |
| State list overwritten instead of appended | Data loss between nodes | Use `Annotated[List[...], operator.add]` |
| No `thread_id` in config with checkpointer | Runtime error | Always pass `config={"configurable": {"thread_id": "..."}}` |

---

## 13. File Layout Template

Copy this for any new LangGraph agent project:

```
src/agents/
├── __init__.py
├── state.py               # Step 1: TypedDict state contract
├── graph.py               # Step 9: StateGraph assembly
├── memory/
│   ├── __init__.py
│   ├── checkpointer.py    # Step 2a: get_checkpointer() context manager
│   └── store.py           # Step 2b: InMemoryStore + domain helper
├── tools/
│   ├── __init__.py
│   └── my_tool.py         # Step 3: @tool decorated functions
├── middleware/
│   ├── __init__.py
│   ├── retry.py           # Step 5: retry_with_backoff decorator
│   ├── guardrails.py      # Step 5: Input/OutputGuardrail classes
│   └── logging_mw.py      # Step 5: @log_node_execution decorator
├── prompts/
│   ├── __init__.py
│   └── my_prompt.py       # Step 4: ChatPromptTemplate + system prompt
├── streaming/
│   ├── __init__.py
│   └── callbacks.py       # Step 7: UsageTracker, ProgressCallback
├── runtime/
│   ├── __init__.py
│   └── config.py          # Step 8: make_config(), get_rate_limiter()
└── nodes/
    ├── __init__.py
    ├── my_llm_node.py     # Step 6: LLM nodes
    └── my_deterministic.py # Step 6: pure-logic nodes
```

---

## Quick-Start Checklist

1. [ ] `uv add langgraph langchain-groq langgraph-checkpoint-sqlite langgraph-checkpoint-postgres`
2. [ ] Define `state.py` with `TypedDict`
3. [ ] Create `memory/checkpointer.py` with `@contextmanager get_checkpointer()`
4. [ ] Write your `@tool` functions in `tools/`
5. [ ] Write `ChatPromptTemplate` in `prompts/`
6. [ ] Add `retry.py`, `guardrails.py`, `logging_mw.py` in `middleware/`
7. [ ] Build each node in `nodes/` following the 6-step pattern
8. [ ] Add `UsageTracker` and `ProgressCallback` in `streaming/`
9. [ ] Create `make_config()` in `runtime/`
10. [ ] Wire it all in `graph.py` with `StateGraph`
11. [ ] Run with `with get_checkpointer() as cp: graph = build_graph(cp)`
