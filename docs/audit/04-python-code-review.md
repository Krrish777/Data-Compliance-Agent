# Python Craft Review — Data Compliance Agent

**Date:** 2026-04-11
**Reviewer persona:** Senior Python engineer
**Scope:** All Python source files. Domain: pure Python craft (idioms, modern features, type hints, performance).

---

## 1. Pythonic Idioms

**POSITIVE CLAIM:** `context_builder.py:48` uses `list(dict.fromkeys(tables))` for order-preserving deduplication — the correct Pythonic idiom over a manual seen-set loop.

**GAP 1 — Explicit index loop instead of `enumerate`**

`docs_processor.py:155–158` iterates `range(total_pages)` to get `page_num` and then immediately indexes back into `doc`:

```python
# BEFORE  (docs_processor.py:155)
for page_num in range(total_pages):
    page = doc.load_page(page_num)
```

```python
# AFTER
for page_num, page in enumerate(doc):   # PyMuPDF Document is iterable
    page_num += 1                        # or keep 0-based and adjust metadata key
```

WHY IT MATTERS: Removes the `doc.load_page(page_num)` index call entirely; `enumerate` is the canonical Python pattern for index+value iteration.
REFERENCE: https://docs.python.org/3/library/functions.html#enumerate

---

**GAP 2 — Manual `list.append` in tight loop instead of comprehension**

`postgres_connector.py:47–52` and `sqlite_connector.py:44–52` build `columns` lists with repeated `.append()` inside a for-loop:

```python
# BEFORE  (postgres_connector.py:47)
columns = []
for col in columns_result:
    columns.append({'column_name': col[0], 'data_type': col[1], 'nullable': ...})
```

```python
# AFTER
columns = [
    {'column_name': col[0], 'data_type': col[1], 'nullable': (col[2] == 'YES')}
    for col in columns_result
]
```

WHY IT MATTERS: List comprehensions are ~20–30% faster than equivalent `.append` loops in CPython due to bytecode specialisation, and they communicate intent more clearly.
REFERENCE: https://docs.python.org/3/tutorial/datastructures.html#list-comprehensions

---

## 2. Modern Python 3.13 Features Not Used

**POSITIVE CLAIM:** `compilance_rules.py` and `interceptor_models.py` already use lowercase built-in generics (`list[str]`, `dict[str, Any]`) in Pydantic `Field` defaults — correct 3.10+ style.

**GAP 1 — `Optional[X]` everywhere instead of `X | None`**

Both state files and every node use `Optional[str]`, `Optional[int]`, `Optional[Dict]` imported from `typing`. In Python 3.10+ the union syntax `X | None` is idiomatic and removes the `Optional` import entirely.

Files affected: `src/agents/state.py:8`, `src/agents/interceptor_state.py:9`, `src/models/structured_rule.py:8`, `src/docs_processing/docs_processor.py:8`, `src/embedding/embedding.py:3`, `src/utils/document_cache.py:16`, `src/agents/tools/database/baseconnector.py:4`, and all interceptor nodes.

```python
# BEFORE  (state.py:8,61)
from typing import Annotated, Any, Dict, List, Literal, Optional
max_batches_per_table: Optional[int]
```

```python
# AFTER
from typing import Annotated, Any, Literal  # Optional removed
max_batches_per_table: int | None
```

WHY IT MATTERS: The project targets Python ≥3.13; `Optional[X]` is a typing museum piece on this runtime. Faculty reviewers will notice immediately.
REFERENCE: https://peps.python.org/pep-0604/

---

**GAP 2 — `Dict[str, X]` / `List[X]` instead of lowercase built-ins**

`src/agents/state.py:29,42` uses `Dict[str, Any]` and `List[ComplianceRuleModel]` imported from `typing`. Both are aliases for `dict` and `list` since Python 3.9 (PEP 585).

```python
# BEFORE  (state.py:29)
db_config: Dict[str, Any]
raw_rules: Annotated[List[ComplianceRuleModel], operator.add]
```

```python
# AFTER
db_config: dict[str, Any]
raw_rules: Annotated[list[ComplianceRuleModel], operator.add]
```

Affected across the entire codebase: `state.py`, `interceptor_state.py`, `baseconnector.py`, `query_executor.py`, `violations_store.py`, `docs_processor.py`, `embedding.py`, `qdrant_vectordb.py`, `policy_store.py`.

WHY IT MATTERS: PEP 585 deprecated `typing.List`/`typing.Dict` — static analysers (pyright, mypy) emit deprecation warnings on Python 3.13.
REFERENCE: https://peps.python.org/pep-0585/

---

**GAP 3 — No `type` alias statement (PEP 695)**

`violations_store.py`, `query_builder.py`, and `complex_executor.py` all repeatedly write `Dict[str, Any]` for "a database row". A `type` alias would centralise this:

```python
# BEFORE  (query_executor.py:24)
) -> tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
```

```python
# AFTER  (new, at module top)
type Row = dict[str, Any]
type ScanResult = tuple[list[Row], str | None, str | None]

def execute_scan_query(...) -> ScanResult:
```

WHY IT MATTERS: PEP 695 `type` aliases are lazy, generic-capable, and self-documenting — exactly what a database-row type alias needs.
REFERENCE: https://peps.python.org/pep-0695/

---

**GAP 4 — `match/case` not used where operator dispatch is done**

`complex_executor.py:254–259` uses a plain dict `_EVALUATORS` to dispatch on `rule.rule_complexity`. This is fine, but `_build_rule_condition` in `query_builder.py:68–123` is a long `if/elif` chain on `operator` — a textbook `match/case` target:

```python
# BEFORE  (query_builder.py:68)
if operator == "IS NULL":
    return f'"{column}" IS NULL'
if operator == "IS NOT NULL":
    ...
if operator in ("LIKE", "NOT LIKE"):
    ...
```

```python
# AFTER
match operator:
    case "IS NULL":
        return f'"{column}" IS NULL'
    case "IS NOT NULL":
        return f'"{column}" IS NOT NULL'
    case "LIKE" | "NOT LIKE":
        if value is None:
            return None
        return f'"{column}" {operator} \'{str(value).replace(chr(39), chr(39)*2)}\''
    case _:
        log.warning(...)
        return None
```

WHY IT MATTERS: `match/case` makes the exhaustiveness of a dispatch more obvious to a reviewer and allows the interpreter to optimise the dispatch table.
REFERENCE: https://peps.python.org/pep-0634/

---

## 3. Type Hint Correctness

**POSITIVE CLAIM:** `query_executor.py:24` uses the lowercase `tuple[...]` return type (no `Tuple` import) — correct Python 3.9+ style for built-in generics in annotations.

**GAP 1 — Untyped `*args` in `_hash_content`**

`document_cache.py:272`:

```python
# BEFORE
def _hash_content(self, *args) -> str:
```

```python
# AFTER
def _hash_content(self, *args: object) -> str:
```

`object` is the correct type for "any value that can be converted via `str()`". Using bare `*args` means mypy treats each element as `Any`, defeating type checking for all callers.
REFERENCE: https://mypy.readthedocs.io/en/stable/kinds_of_types.html#the-type-of-none-and-optional-types

---

**GAP 2 — `Dict[str, Any]` return type where a `TypedDict` would be tighter**

`baseconnector.py:64` returns `List[Dict[str, Any]]` for `identify_sensitive_columns`. The shape is always `{'table': str, 'column': str, 'data_type': str, 'category': str}`. A `TypedDict` makes this contract explicit:

```python
# BEFORE  (baseconnector.py:64)
def identify_sensitive_columns(self, schema: Dict) -> List[Dict[str, Any]]:
```

```python
# AFTER
from typing import TypedDict

class SensitiveColumn(TypedDict):
    table: str
    column: str
    data_type: str
    category: str

def identify_sensitive_columns(self, schema: dict) -> list[SensitiveColumn]:
```

`get_scan_summary` in `violations_store.py:374` has the same pattern — six fixed keys, all typed, returning `Dict[str, Any]`.
WHY IT MATTERS: `TypedDict` enables key-level type checking at every call site; `Dict[str, Any]` silences the type checker entirely.
REFERENCE: https://peps.python.org/pep-0589/

---

**GAP 3 — Missing `-> None` on several void methods**

`baseconnector.py:44` (`connect`), `baseconnector.py:95` (`close`), `violations_store.py:18` (`create_violations_table`), `violations_store.py:196` (`create_explanations_table`), `docs_processor.py:148` (`_process_pdf`). Specifically `baseconnector.connect()` returns `self.session` on line 57 but is not annotated with `-> Session`.

```python
# BEFORE  (baseconnector.py:44)
def connect(self):
```

```python
# AFTER
def connect(self) -> Session:
```

WHY IT MATTERS: Without a return annotation, mypy infers `-> None`, masking the real return type and causing spurious errors at call sites.
REFERENCE: https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html

---

## 4. Dataclass / Pydantic / TypedDict Choice

**POSITIVE CLAIM:** `interceptor_models.py` correctly uses Pydantic `BaseModel` with `field_validator` for all stage outputs that cross LLM boundaries — the right choice for external-data validation.

**GAP 1 — `StructuredRule` is a plain dataclass but mutates post-construction and has no validation**

`src/models/structured_rule.py` is a `@dataclass`. It has optional mutable fields (`applies_to_tables: Optional[List[str]]`), no field validation, and is passed across node boundaries where incorrect `operator` or `confidence` values cause silent downstream failures in `_build_rule_condition`. The project already uses Pydantic v2 everywhere else.

The fix has two sub-options:

Option A — if immutability is desired (fields never mutate after construction):
```python
# BEFORE  (structured_rule.py:11)
@dataclass
class StructuredRule:
    applies_to_tables: Optional[List[str]] = None
```

```python
# AFTER
@dataclass(slots=True, frozen=True)
class StructuredRule:
    applies_to_tables: tuple[str, ...] | None = None
```

`frozen=True` prevents accidental mutation; `slots=True` saves ~48 bytes per instance — meaningful at 50M-row scale where thousands of rule objects exist simultaneously.

Option B — migrate to Pydantic `BaseModel` with validators (preferred, aligns with the rest of `src/models/`):
```python
from pydantic import BaseModel, Field, field_validator

class StructuredRule(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    operator: str = Field(min_length=1)
    ...
```

WHY IT MATTERS: `@dataclass` provides zero validation; a bad `confidence=1.5` or empty `operator=""` passes silently and only fails deep inside `_build_rule_condition` with an uninformative `None` return.
REFERENCE: https://docs.pydantic.dev/latest/concepts/dataclasses/

---

**GAP 2 — `CacheStats` dataclass should use `slots=True`**

`document_cache.py:27–35`: `CacheStats` is a pure-data accumulator incremented in hot paths (every cache hit/miss). A `slots=True` dataclass halves attribute-access overhead:

```python
# BEFORE  (document_cache.py:27)
@dataclass
class CacheStats:
    hits: int = 0
```

```python
# AFTER
@dataclass(slots=True)
class CacheStats:
    hits: int = 0
```

WHY IT MATTERS: `__slots__` eliminates the per-instance `__dict__`, reducing memory and improving attribute lookup speed — relevant when this object is updated on every cache operation.
REFERENCE: https://docs.python.org/3/reference/datamodel.html#slots

---

## 5. Context Manager Usage

**POSITIVE CLAIM:** `violation_validator_node` at `violation_validator.py:221` wraps the violations `Session` in `with Session(engine) as session:` — correct context-manager usage.

**GAP 1 — `SQLiteConnector.discover_schema` uses `with self.session` but `self.session` is a `Session` object, not a context manager that closes the connection**

`sqlite_connector.py:29`: `with self.session as session:` — SQLModel/SQLAlchemy `Session` used as a context manager will `close()` the session on exit (not just commit). This means after `discover_schema()` runs, `self.session` is closed, yet `data_scanning_stage` later calls `target_conn.session` to pass it directly to `execute_scan_query`. The session is already dead.

```python
# BEFORE  (sqlite_connector.py:29)
with self.session as session:
    table_query = text("SELECT name FROM sqlite_master WHERE type='table';")
    ...
```

```python
# AFTER — create a fresh session for discovery, leave self.session open
with Session(self.engine) as session:
    table_query = text("SELECT name FROM sqlite_master WHERE type='table';")
    ...
# self.session is untouched and still valid for scanning
```

The same bug exists in `data_scanning_stage` (`data_scanning.py:88–90`) where `target_conn.session` is directly accessed without any null-check or context manager after `connect()` runs.

WHY IT MATTERS: This is a latent correctness bug — using a closed session for scanning will raise `sqlalchemy.exc.InvalidRequestError` in the same process run if `discover_schema` is called before scanning, which is the normal pipeline flow.
REFERENCE: https://docs.sqlalchemy.org/en/20/orm/session_basics.html#closing

---

**GAP 2 — `docs_processor.py:151` opens a PyMuPDF document without a `with` block**

```python
# BEFORE  (docs_processor.py:151)
doc = pymupdf.open(file_path)
...
doc.close()   # only called at line 183
```

```python
# AFTER
with pymupdf.open(file_path) as doc:
    total_pages = len(doc)
    for page_num, page in enumerate(doc, start=1):
        ...
```

PyMuPDF's `Document` supports the context-manager protocol since version 1.18.
WHY IT MATTERS: Explicit `close()` calls are brittle — a future edit adding a `return` inside the loop would leak the file handle. `with` guarantees cleanup.
REFERENCE: https://pymupdf.readthedocs.io/en/latest/document.html#Document.__enter__

---

## 6. Generators and Lazy Evaluation

**POSITIVE CLAIM:** The keyset pagination design in `query_builder.py` / `scan_table_batched` correctly avoids materialising all rows at once — the architecture is generator-friendly.

**GAP 1 — `_process_pdf` materialises all chunks from all pages before returning**

`docs_processor.py:149–191`: `_process_pdf` collects every `DocumentChunk` into a `chunks: list` across all pages before returning. For a 200-page regulatory PDF this materialises hundreds of objects simultaneously.

```python
# BEFORE
def _process_pdf(self, file_path: Path) -> List[DocumentChunk]:
    chunks = []
    for page_num in range(total_pages):
        ...
        chunks.extend(page_chunks)
    return chunks
```

```python
# AFTER — generator version
from collections.abc import Generator

def _process_pdf(self, file_path: Path) -> Generator[DocumentChunk, None, None]:
    with pymupdf.open(file_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            yield from self._chunk_text(page.get_text(), file_path.name, page_num)
```

WHY IT MATTERS: A 500-page PDF at 1 000 chars/chunk = ~500 `DocumentChunk` objects allocated at once. For a batch of 10 PDFs, 5 000 objects sit in memory simultaneously — unnecessary when the embedding model processes them sequentially anyway.
REFERENCE: https://docs.python.org/3/reference/expressions.html#yield-expressions

---

## 7. Asyncio

**POSITIVE CLAIM:** The project wisely defers async complexity by keeping the pipeline synchronous and using LangGraph's built-in concurrency model at the graph level, which is a defensible architectural choice.

**GAP — `rule_extraction_node` processes PDF chunks sequentially; LLM calls are the bottleneck**

`rule_extraction_node` in `nodes/rule_extraction.py:168` loops over chunks and calls the Groq API once per chunk, entirely sequentially. Each call has ~1–2s latency. A 30-chunk PDF takes 30–60 seconds.

Migration sketch using `asyncio.TaskGroup` (Python 3.11+, available in 3.13):

```python
import asyncio
from langchain_groq import ChatGroq

async def _extract_from_chunk_async(chain, chunk_text, chunk_index, total_chunks):
    response = await chain.ainvoke({
        "chunk_text": chunk_text,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
    })
    ...  # same JSON parsing as _extract_from_chunk

async def _extract_all_chunks(chain, chunks):
    results = []
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(_extract_from_chunk_async(chain, c, i+1, len(chunks)))
            for i, c in enumerate(chunks)
        ]
    return [t.result() for t in tasks]
```

`asyncio.TaskGroup` (PEP 654) provides structured concurrency and correct cancellation when any task fails — superior to `asyncio.gather(..., return_exceptions=True)` for this pattern.

WHY IT MATTERS: Concurrent LLM calls would reduce a 30-chunk extraction from ~45s to ~5s (bounded by Groq's rate limit, which the existing `rate_limiter` already handles). This alone would impress faculty far more than any style change.
REFERENCE: https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup

---

## 8. Standard Library Hygiene

**POSITIVE CLAIM:** `pathlib.Path` is used correctly throughout `data_scanning.py`, `logger.py`, `violation_validator.py`, and `run_scan.py` — no raw `os.path` string manipulation.

**GAP 1 — `itertools.batched` not used for chunk batching**

`embedding.py:195–199` manually slices `chunk_batch[j:j+batch_size]` inside a loop:

```python
# BEFORE  (embedding.py:195)
for j in range(0, len(chunk_batch), batch_size):
    sub_batch = chunk_batch[j:j+batch_size]
```

```python
# AFTER (Python 3.12+, available in 3.13)
from itertools import batched

for sub_batch in batched(chunk_batch, batch_size):
    embedded_sub_batch = self.generate_embedding(list(sub_batch))
```

The same pattern appears in `violation_validator_node` at `violation_validator.py:247`: `violations_batch[i : i + _BATCH_SIZE]`.

WHY IT MATTERS: `itertools.batched` is the stdlib-blessed solution, eliminating off-by-one risk and communicating intent unambiguously.
REFERENCE: https://docs.python.org/3/library/itertools.html#itertools.batched

---

**GAP 2 — `datetime.now()` without timezone in `cache.py` and `docs_processor.py`**

`cache.py:16–24` calls `datetime.now()` (naive, local time) for TTL comparison. `docs_processor.py:173` does the same for `extracted_at` metadata. The rest of the codebase (`violations_store.py`, `interceptor_models.py`) correctly uses `datetime.now(timezone.utc)`.

```python
# BEFORE  (cache.py:16)
if datetime.now() < entry['expires_at']:
```

```python
# AFTER
from datetime import datetime, timezone
if datetime.now(timezone.utc) < entry['expires_at']:
```

WHY IT MATTERS: Mixing naive and aware datetimes raises `TypeError` at comparison time in Python 3.x. This is a latent bug that surfaces on any machine where the local timezone offset causes the naïve/aware comparison to be attempted.
REFERENCE: https://docs.python.org/3/library/datetime.html#aware-and-naive-objects

---

## 9. Function Signatures

**POSITIVE CLAIM:** `build_keyset_query` in `query_builder.py:14` uses keyword-only arguments naturally and all parameters have explicit types and defaults — well-formed signature.

**GAP 1 — Untyped session parameters in `scan_table_batched`**

`data_scanning.py:226`:

```python
# BEFORE
def scan_table_batched(
    session,
    violations_session,
    ...
```

```python
# AFTER
from sqlmodel import Session

def scan_table_batched(
    session: Session,
    violations_session: Session,
    rule: StructuredRule,
    ...
) -> int:
```

WHY IT MATTERS: Untyped `session` means any object satisfying the duck-type passes silently — a debugger's nightmare when the wrong connection type is passed.
REFERENCE: https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html

---

**GAP 2 — `scan_complex_rule` hardcodes `db_type="sqlite"` in the call to `log_violation`**

`complex_executor.py:337`:

```python
# BEFORE
log_violation(
    ...
    db_type="sqlite",  # ← hardcoded, ignores the `db_type` parameter on line 268
)
```

The function signature at line 262 accepts `db_type: str`, and this parameter is correctly used for `_fetch_batch`, but is silently overridden to `"sqlite"` when logging violations. This is a functional bug (not just a signature issue) — Postgres scans will write violations with the wrong `db_type`, causing `log_violation` to execute the `last_insert_rowid()` SQLite query against a Postgres session.

```python
# AFTER
log_violation(
    ...
    db_type=db_type,   # pass the received parameter through
)
```

WHY IT MATTERS: This is a concrete bug — on a Postgres target DB, the violation ID retrieval will silently fail (`SELECT last_insert_rowid()` is not valid Postgres SQL) and the function will return 0 for all violation IDs logged during complex-rule scans.

---

## 10. Python-Specific Performance

**POSITIVE CLAIM:** The cosine similarity in `baseconnector.py:78–80` uses `np.dot` / `np.linalg.norm` directly on numpy arrays — correctly vectorised, no Python loops over float values.

**GAP 1 — Repeated attribute lookup in `identify_sensitive_columns` hot path**

`baseconnector.py:69–92` has a nested loop: for every `(table, column)` pair it re-accesses `self._category_embeddings` on every inner iteration. In a schema with 50 tables × 20 columns × 9 categories = 9 000 attribute lookups per `identify_sensitive_columns` call.

```python
# AFTER — extract to local variable, vectorise inner loop
category_embeddings = self._category_embeddings  # one lookup
for table, info in schema.items():
    for col in info['columns']:
        col_embedding = model.encode(col['column_name'].lower().replace('_', ' '))
        # All 9 category similarities in one vectorised call:
        cat_matrix = np.stack(list(category_embeddings.values()))
        sims = cat_matrix @ col_embedding / (
            np.linalg.norm(cat_matrix, axis=1) * np.linalg.norm(col_embedding)
        )
        best_idx = int(np.argmax(sims))
        ...
```

The fully vectorised form computes all 9 similarities in one matrix multiply — O(9) BLAS operations vs. 9 separate Python-dispatched dot-products.

WHY IT MATTERS: At 1 000 columns (realistic for a data warehouse), the vectorised form is ~5–10x faster for the inner loop.

---

## Summary of Findings by Priority

**Critical (will cause runtime failures):**
- `complex_executor.py:337` — `db_type="sqlite"` hardcoded; breaks Postgres violation logging
- `sqlite_connector.py:29` — `with self.session as session:` closes `self.session`; subsequent scan calls use a dead session

**Important (correctness or significant performance):**
- `violations_store.py:178` — raw string IN-list in SQL; breaks above ~32K IDs
- `docs_processor.py:151` — PyMuPDF document not opened with `with` block
- `cache.py:16` — naive `datetime.now()` mixed with aware datetimes elsewhere
- `state.py`, all nodes — `Optional[X]`, `Dict[str, X]`, `List[X]` instead of modern union syntax and built-in generics
- `structured_rule.py` — plain `@dataclass` with no validation for a type that crosses LLM boundaries

**Presentation-quality (faculty will notice):**
- No `match/case` in `query_builder.py:68` operator dispatch
- No `itertools.batched` in embedding and validation batch loops
- `scan_table_batched` missing `Session` type annotations on `session` parameters
