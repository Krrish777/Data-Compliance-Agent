# Chapter 3 — Implementation

> *Chapter overview.* This is the longest chapter of the report. It walks through the implementation in a top-down manner: project layout, the state contracts that bind every node to every other node, the three graphs and their wiring, the implementation of every node, the algorithmic stages, the database tooling (PII detection, keyset pagination, complex-rule evaluation, the violations store), the vector store and the RAG path, the cache and resilience layer, the dual memory model, the rationale for pinning specific Llama variants to specific nodes, the human-in-the-loop checkpoint, and finally the configuration / front-end / deployment story. Source-file paths are given throughout in the form `file:line` so that the chapter doubles as a guided code-walk.

---

## 3.1 Project Layout

The project root contains four primary directories — `src/`, `tests/`, `scripts/`, `data/` — and one front-end sub-project, `agent-chat-ui/`. The Python package layout is shown below in annotated form (depth limited for readability):

```
Data-Compliance-Agent/
├── pyproject.toml                # uv-managed dependency manifest
├── README.md                     # operator-facing overview
├── CLAUDE.md                     # short architecture brief
├── AGENT_BUILDING_GUIDE.md       # long-form layering rationale
├── main.py                       # Quick PII demo (no LLM)
├── run_scan.py                   # Scan-only driver (bypasses extraction)
├── run_hi_small.py               # Full E2E driver against HI-Small AML DB
├── run_intercept.py              # Interactive interceptor demo
│
├── src/
│   ├── agents/
│   │   ├── state.py              # ComplianceScannerState (TypedDict)
│   │   ├── interceptor_state.py  # InterceptorState   (TypedDict)
│   │   ├── graph.py              # Scanner StateGraph builder
│   │   ├── interceptor_graph.py  # Interceptor StateGraph builder
│   │   ├── unified_graph.py      # Mode-routed façade
│   │   ├── nodes/                # 7 scanner nodes (one .py per node)
│   │   ├── interceptor_nodes/    # 10 interceptor nodes
│   │   ├── memory/               # checkpointer.py, store.py
│   │   ├── tools/database/       # connectors, query builder, executor, store
│   │   ├── prompts/              # ChatPromptTemplate files
│   │   ├── middleware/           # guardrails, logging, retry decorators
│   │   └── runtime/              # rate-limit + config helpers
│   ├── stages/                   # data_scanning, rule_structuring, report_generator
│   ├── vector_database/          # policy_store, qdrant_vectordb (LocalVectorDB)
│   ├── docs_processing/          # PDF chunker, processor
│   ├── embedding/                # FastEmbed wrapper
│   ├── models/                   # Pydantic data classes (ComplianceRuleModel etc.)
│   └── utils/                    # logger, cache, document_cache
│
├── tests/unit/                   # 18 test files / 24 test functions
├── scripts/                      # prewarm_demo.py, smoke_graph_e2e.py, generate_policy_pdf.py
├── data/                         # sample DBs, policy PDFs, generated reports, logs
└── agent-chat-ui/                # Next.js 16 front-end (separate npm project)
```

The split between `src/agents/nodes/` and `src/stages/` is the most consequential layout choice. A *node* file is a thin LangGraph wrapper that reads the shared state, applies a thin guardrail or middleware, calls into a *stage* function for the heavy work, and writes back to state. The same algorithmic logic, exposed as a pure Python function in `src/stages/`, can be exercised from a unit test or a one-off script (such as `run_scan.py`) without spinning up the LangGraph runtime. This separation pays for itself in the tests chapter (Chapter 4): the test suite reaches deep into stages without ever needing to instantiate a graph.

The 66 Python source files in `src/` total 10,187 lines of code, with `src/agents/graph.py` (465 lines) and `src/stages/data_scanning.py` (285 lines) being the two largest individual modules.

---

## 3.2 The State Contract

LangGraph's central abstraction is the **state** — a single typed dictionary that every node receives, mutates, and returns. The Data Compliance Agent has two state types: `ComplianceScannerState` (`src/agents/state.py:15-78`) for the scanner graph and `InterceptorState` (`src/agents/interceptor_state.py:14-68`) for the interceptor graph. Both are declared as `TypedDict(total=False)`, which means every field is optional at any given moment — a node need only populate the fields that are downstream-relevant.

### 3.2.1 `ComplianceScannerState`

The scanner state has nineteen fields. They fall into three groups: *inputs* supplied by the operator, *intermediates* that pass between nodes, and *outputs* that the report generator consumes.

| Field | Type | Group | Purpose |
|---|---|---|---|
| `document_path` | `str` | input | Absolute path to the policy PDF |
| `db_config` | `Dict[str, Any]` | input | `{db_path}` for SQLite, `{host, port, database, user, password}` for PostgreSQL |
| `db_type` | `Literal["sqlite", "postgresql"]` | input | Chosen connector |
| `batch_size` | `int` | input | Rows per keyset page (default 1000) |
| `max_batches_per_table` | `Optional[int]` | input | Safety cap; `None` means unbounded |
| `violations_db_path` | `str` | input | Output SQLite store for violations |
| `raw_rules` | `Annotated[List[ComplianceRuleModel], operator.add]` | intermediate | Output of `rule_extraction`, accumulated chunk-by-chunk |
| `schema_metadata` | `Dict[str, Dict[str, Any]]` | intermediate | Table → columns/PK/row-count mapping |
| `structured_rules` | `List[StructuredRule]` | intermediate | Confidence ≥ 0.7 |
| `low_confidence_rules` | `List[StructuredRule]` | intermediate | Confidence < 0.7 |
| `review_decision` | `Dict[str, Any]` | intermediate | `{approved, edited, dropped}` from HITL |
| `scan_id` | `str` | intermediate | Unique identifier for the run |
| `scan_summary` | `Dict[str, Any]` | intermediate | Counts only; full rows live in the violations DB |
| `validation_summary` | `Dict[str, Any]` | intermediate | `{confirmed, false_positives, skipped, by_rule}` |
| `rule_explanations` | `Dict[str, Any]` | intermediate | `{rule_id: {explanation, clause, remediation, severity}}` |
| `violation_report` | `Dict[str, Any]` | intermediate | Aggregated artefact passed to the report generator |
| `report_paths` | `Dict[str, str]` | output | `{"pdf": ..., "html": ...}` |
| `current_stage` | `str` | intermediate | Pipeline stage tracker (used by middleware logger) |
| `errors` | `Annotated[List[str], operator.add]` | output | Non-fatal warnings accumulated across nodes |

Two fields — `raw_rules` and `errors` — are wrapped in `Annotated[List[...], operator.add]`. This is LangGraph's *reducer* mechanism: when two nodes write to the same field (which happens during streaming or when the rule-extraction node is parallelised over chunks), LangGraph composes the two writes by *adding the lists* rather than overwriting them. This is the only way to implement chunk-parallel extraction safely without race conditions and is one of the reasons the project has stayed on LangGraph rather than rolling its own scheduler.

### 3.2.2 `InterceptorState`

The interceptor state has 22 fields, also typed and `total=False`. Its design pursues a different goal: every intermediate result is serialisable to JSON so that an end-to-end audit log can be constructed by simply concatenating successive checkpoints. The fields are summarised in Table 3.2:

| Field | Type | Purpose |
|---|---|---|
| `query` / `user_id` / `user_role` / `stated_purpose` / `session_id` | `str` / `Optional[str]` | Inbound request envelope |
| `db_config` / `db_type` | dict / literal | Connection target |
| `cache_hit` / `cache_layer` / `cached_decision` | `bool` / `Optional[str]` / `Optional[dict]` | Cache outcome |
| `context_bundle` / `intent_result` / `policy_mapping` / `verdict` / `audit_result` | `Optional[dict]` (each) | Per-stage serialised payloads |
| `final_decision` | `Optional[Literal["APPROVE","BLOCK","CLARIFICATION_REQUIRED","ESCALATED"]]` | Terminal state |
| `block_reason` / `guidance` / `query_results` | `Optional[str]` / `Optional[Any]` | Detailed outcome |
| `current_stage` / `retry_counts` / `errors` / `total_cost_usd` / `processing_start_time` | misc | Telemetry and audit |

The `total_cost_usd` field is incremented by every node that calls the LLM, so that at the end of every run the operator has a precise dollar figure for the request. The `retry_counts` field is keyed by node name and is what the auditor and policy-mapper consult before deciding whether to loop or to escalate.

### 3.2.3 The contract as documentation

Because both state types are `TypedDict`, `mypy` and the Pydantic-rooted IDE tooling can flag any node that writes a non-existent key or reads a key with the wrong type. In practice this means that `state.py` is the most reliable piece of documentation in the project — when adding a new node, the rule of thumb is *"update the state schema first, then wire the node"*. This rule is repeated in `CLAUDE.md` and is enforced informally during code review.

---

## 3.3 The Three Graphs

### 3.3.1 Scanner Graph (`src/agents/graph.py:406-461`)

The scanner is built by `build_graph(checkpointer)`, which constructs a `StateGraph(ComplianceScannerState)`, registers the nine nodes by name, declares the linear edges, declares the single conditional edge after rule structuring, and finally compiles the graph with the supplied checkpointer. The factory is reproduced in compressed form below; the line numbers refer to the actual source.

```python
# src/agents/graph.py (lines 406-461)
def build_graph(checkpointer: Optional[BaseCheckpointSaver] = None):
    workflow = StateGraph(ComplianceScannerState)
    workflow.add_node("rule_extraction",        rule_extraction_node)        # 425
    workflow.add_node("schema_discovery",       schema_discovery_node)       # 426
    workflow.add_node("rule_structuring",       rule_structuring_node)       # 427
    workflow.add_node("human_review",           human_review_node)           # 428
    workflow.add_node("data_scanning",          data_scanning_node)          # 429
    workflow.add_node("violation_validator",    violation_validator_node)    # 430
    workflow.add_node("explanation_generator",  explanation_generator_node)  # 431
    workflow.add_node("violation_reporting",    violation_reporting_node)    # 432
    workflow.add_node("report_generation",      report_generation_node)      # 433

    workflow.add_edge(START,                    "rule_extraction")           # 436
    workflow.add_edge("rule_extraction",        "schema_discovery")          # 437
    workflow.add_edge("schema_discovery",       "rule_structuring")          # 438
    workflow.add_conditional_edges(
        "rule_structuring",
        _route_after_structuring,                                            # 396-401
        {"human_review": "human_review", "data_scanning": "data_scanning"},
    )                                                                        # 441-448
    workflow.add_edge("human_review",           "data_scanning")             # 450
    workflow.add_edge("data_scanning",          "violation_validator")       # 451
    workflow.add_edge("violation_validator",    "explanation_generator")     # 452
    workflow.add_edge("explanation_generator",  "violation_reporting")       # 453
    workflow.add_edge("violation_reporting",    "report_generation")         # 454
    workflow.add_edge("report_generation",      END)                         # 455

    return workflow.compile(checkpointer=checkpointer)                       # 458
```

The conditional routing function is short and total:

```python
# src/agents/graph.py:396-401
def _route_after_structuring(state: Dict[str, Any]) -> str:
    """Decide whether human review is needed."""
    low_confidence = state.get("low_confidence_rules", [])
    if low_confidence:
        return "human_review"
    return "data_scanning"
```

This is the single source of truth for the human-in-the-loop branch: the threshold is implicit, embedded in the upstream `rule_structuring_node`, which uses 0.7 as the cut-off (`src/agents/graph.py:280`). Lifting the threshold to a configurable field on the state is one of the future-scope items mentioned in §5.4 of Chapter 5.

### 3.3.2 Interceptor Graph (`src/agents/interceptor_graph.py:46-112`)

The interceptor graph differs from the scanner in two deliberate ways. First, retry policies are attached to specific nodes — most importantly, `policy_mapper` is wrapped with `RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0)` (lines 72-76) so that a transient Qdrant or embedding failure is silently retried up to three times. Second, the conditional routing is *internal* to each node: nodes return LangGraph `Command` objects that name the next node directly, rather than relying on `add_conditional_edges` declarations. This makes the graph declaration short (only ten edges are explicit) but moves routing logic into the node bodies, which is documented as a deliberate architectural choice at `interceptor_graph.py:17-18`:

> *"Routing is done via `Command` objects inside nodes, so only minimal edges are declared here."*

The compiled graph exposes four terminal exits — `executor → END`, `return_cached → END`, `return_clarification → END`, `escalate_human → END` — so that every input request terminates in exactly one of four well-defined states. This is what allows the AuditLens UI to render a deterministic outcome card for every run.

### 3.3.3 Unified Router (`src/agents/unified_graph.py:52-137`)

The unified graph is, strictly speaking, not a `StateGraph` at all. It is a small Python class, `UnifiedComplianceAgent`, that holds two compiled sub-graphs and forwards `invoke / ainvoke / stream` calls to whichever one the input requests:

```python
# src/agents/unified_graph.py (excerpt)
class UnifiedComplianceAgent:
    def __init__(self, scanner, interceptor):
        self.scanner = scanner
        self.interceptor = interceptor

    def invoke(self, input_state, config=None):
        mode = input_state.pop("mode", "scanner")
        if mode == "interceptor":
            return self.interceptor.invoke(input_state, config)
        return self.scanner.invoke(input_state, config)
```

This pattern is borrowed from LangGraph's own *router agent* template. Its single advantage is operational: the front-end and the LangGraph dev server both speak to one URL, and the routing happens server-side. Its single disadvantage is that the `mode` field must be popped from the state before forwarding (line 94), which is easy to forget. A future refactor to express the router as an *actual* `StateGraph` with two conditional edges from `START` would unify the two paths inside the LangGraph runtime, which would in turn make checkpointing across mode boundaries possible — at the cost of having to define a unified state. The design currently favours simplicity.

---

## 3.4 Node Implementations

This section catalogues every node, scanner and interceptor, with its file location, what it reads from state, what it writes back, and which LLM (if any) it invokes. The descriptions are intentionally compressed — for the full algorithmic detail behind each node see §3.5 (stages) and the code itself.

### 3.4.1 Scanner nodes (`src/agents/nodes/`)

| Node file | Function | Reads | Writes | LLM | Prompt |
|---|---|---|---|---|---|
| `rule_extraction.py:81` | `rule_extraction_node` | `document_path` | `raw_rules`, `current_stage`, `errors` | `llama-3.1-8b-instant` (line 157) | `rule_extraction_prompt` (line 163) |
| `schema_discovery.py:16` | `schema_discovery_node` | `db_type`, `db_config` | `schema_metadata`, `current_stage`, `errors` | None | None |
| (in `graph.py:74-294`) | `rule_structuring_node` | `raw_rules`, `schema_metadata` | `structured_rules`, `low_confidence_rules`, `current_stage` | None | None |
| (in `graph.py:297-391`) | `human_review_node` | `low_confidence_rules` | `structured_rules` (merged), `review_decision` | None | None — `interrupt()` |
| `data_scanning.py:18` | `data_scanning_node` | `structured_rules`, `schema_metadata`, `db_config`, `db_type`, `violations_db_path`, `batch_size`, `max_batches_per_table` | `scan_id`, `scan_summary`, `current_stage`, `errors` | None | None |
| `violation_validator.py:167` | `violation_validator_node` | `scan_id`, `violations_db_path`, `structured_rules`, `scan_summary` | `validation_summary`, `current_stage` | `llama-3.1-8b-instant` (line 51) | `_SYSTEM_PROMPT` (line 53) |
| `explanation_generator.py:163` | `explanation_generator_node` | `scan_id`, `violations_db_path`, `structured_rules` | `rule_explanations`, `current_stage` | `llama-3.3-70b-versatile` (line 49) | `_SYSTEM_PROMPT` (line 57) |
| `violation_reporting.py:29` | `violation_reporting_node` | `scan_id`, `violations_db_path`, `scan_summary`, `structured_rules`, `rule_explanations` | `violation_report`, `current_stage`, `errors` | None | None |
| `report_generation.py:18` | `report_generation_node` | `violation_report`, `rule_explanations`, `scan_id` | `report_paths`, `current_stage`, `errors` | None | None |

### 3.4.2 Interceptor nodes (`src/agents/interceptor_nodes/`)

| Node file | Function | Purpose |
|---|---|---|
| `cache_check.py:21-72` | `cache_check_node` | Three-layer decision cache check (exact SHA-256 → fuzzy Levenshtein > 95% → semantic cosine > 0.92) |
| `context_builder.py:100-228` | `context_builder_node` | Deterministic assembly of `ContextBundle` (schema + user identity); zero LLM cost |
| `intent_classifier.py:111-220` | `intent_classifier_node` | Rule-based fast path (90 % of calls); falls back to Llama-3.1-8B for ambiguous cases |
| `policy_mapper.py:27-154` | `policy_mapper_node` | RAG retrieval from Qdrant `policy_rules` collection; routes `CONFIDENT → verdict_reasoner` or `UNCERTAIN → escalate_human` |
| `verdict_reasoner.py:22-71` | `verdict_reasoner_node` | Heavy reasoning with Llama-3.3-70B; emits `ComplianceVerdict(decision, cited_policies, sensitive_columns)` |
| `auditor.py:31-196` | `auditor_node` | Advisory check for verdict consistency (Llama-3.1-8B); loops back to verdict_reasoner on `FAIL` |
| `executor.py:23-147` | `executor_node` | Executes approved query with a 1000-row safety cap, or returns block message |
| `terminals.py:29-129` | `return_cached_node`, `return_clarification_node`, `escalate_human_node` | Three terminal sinks |
| `cache.py` | `DecisionCache` | Support module: TTL 1 h for exact/fuzzy, 6 h for semantic |
| `audit_logger.py` | `AuditLogger` | Append-only WORM SQLite audit log written by every node |

The two LLM-using interceptor nodes use *different* models on purpose: the `verdict_reasoner` calls Llama-3.3-70B because verdict generation needs rich reasoning, while the `auditor` and `intent_classifier` call Llama-3.1-8B because their tasks are essentially binary classification — small enough that an 8 B model is more than sufficient and an order of magnitude cheaper. This *model-tier pinning* is documented in §3.10 and is one of the project's most useful cost-control levers.

---

## 3.5 Stages — The Algorithmic Core

Three stages live in `src/stages/`: `data_scanning.py`, `rule_structuring.py`, and `report_generator.py`. All three are pure Python — they take a state-like dictionary in, return a state-like dictionary out, and never touch LangGraph directly.

### 3.5.1 `data_scanning_stage` (`src/stages/data_scanning.py`)

This is the heart of the scanner. The algorithm:

```text
for each rule in structured_rules:
    determine target tables (mapped or all tables that contain target_column)
    for each target table:
        determine pk_column from schema_metadata (rowid fallback for SQLite)
        if rule.rule_complexity == "simple":
            last_pk = None
            while True:
                sql, params = build_keyset_query(rule, table, pk_column, last_pk, batch_size, db_type)
                if sql is None: break       # operator unsupported → skip safely
                rows, last_pk, err = execute_scan_query(...)
                for row in rows:
                    log_violation(violations_session, scan_id, rule.rule_id,
                                  rule.rule_text, rule.source, table,
                                  str(row[pk_column]), row, rule.confidence,
                                  rule.rule_type, db_type)
                if not last_pk: break
                if max_batches and batches_done >= max_batches: break
        else:
            scan_complex_rule(...)          # Python-side evaluator
    update scan_summary counts
return state
```

Two design points are worth highlighting. First, the loop is *strictly bounded* by `max_batches_per_table`, which gives the operator a hard upper limit on the number of `SELECT` calls the scanner can make. This is what makes it safe to run against very large production databases — the worst case is bounded, not "however many rows are in the table". Second, every violation is *immediately* persisted to the external `violations.db` rather than accumulated in memory. This keeps the LangGraph state object tiny (only counts) and ensures that a crash midway through a scan loses no violations that were already detected.

### 3.5.2 `rule_structuring_stage` (`src/stages/rule_structuring.py`)

The structuring stage takes the loose `ComplianceRuleModel` objects produced by the rule-extraction LLM and turns them into `StructuredRule` Pydantic models that the scanner can act on. Its algorithm:

1. For each raw rule, attempt to map `rule.target_column` (a free-form string) to an actual column in `schema_metadata`. The matching is performed by exact-match first, then case-insensitive match, then a fuzzy-similarity match using the same `all-MiniLM-L6-v2` embedding that the PII detector uses.
2. Normalise the operator string against the alias table in `query_builder.py:61-124` (six groups: `IS NULL/IS NOT NULL`, `LIKE/NOT LIKE`, `~/!~`, `IN/NOT IN`, comparison, complex).
3. Classify the rule complexity (`simple`, `between`, `regex`, `cross_field`, `date_math`).
4. Emit a confidence score that combines the LLM's self-reported confidence with the column-mapping similarity.
5. If confidence ≥ 0.7, append to `structured_rules`; otherwise, append to `low_confidence_rules`.

### 3.5.3 `report_generator.generate_reports()` (`src/stages/report_generator.py:680-705`)

The report generator emits both a PDF and an HTML representation of the final compliance report. They share a single five-section template:

1. **Cover** — scan ID, timestamp, score-and-grade box, KPI summary table.
2. **Executive summary** — total violations, tables scanned, rules extracted, rules structured.
3. **Rules summary table** — one row per rule with violation count, severity, status.
4. **Rule-by-rule detail** — severity, violations, policy clause, narrative explanation, risk description, ordered remediation steps.
5. **Appendix** — violations grouped by table.

The PDF surface uses ReportLab's `Platypus` framework (`SimpleDocTemplate`, `Table`, `TableStyle`, `Paragraph`, `PageBreak`, `HRFlowable`, `Spacer`, A4 page size, 20 mm margins). The HTML surface uses an inline `<style>` block with CSS Grid for the metrics, Tailwind-like utility classes, a teal-and-cream palette (`#0f839a` / `#fef9f3`), and a `@media print` block that adds `break-inside: avoid` so that the HTML can be printed with zero further configuration. Helper functions handle grade-to-colour mapping (`_grade_color`), severity-to-colour mapping (`_sev_color`), score-to-grade conversion (`_score_to_grade`, lines 76-85), and robust parsing of the `remediation_steps` field which can arrive as either a list, a JSON-encoded string, or a newline-separated block (`_ensure_list`, lines 29-58).

---

## 3.6 Database Tooling

The directory `src/agents/tools/database/` contains seven modules totalling roughly 850 lines of code. They are the only place in the project that talks to a target database, and the only place that talks to the violations store.

### 3.6.1 `BaseDatabaseConnector` and PII Detection (`baseconnector.py:1-102`)

The abstract base class defines the connector lifecycle (`connect`, `discover_schema`, `close`) and *also* provides the project's PII-detection capability. Nine PII categories are declared as natural-language descriptors at lines 19-29:

```python
self.categories = {
    'email':       'email address contact mail electronic mail',
    'phone':       'phone number telephone mobile cell contact number',
    'ssn':         'social security number SSN tax identification',
    'credit_card': 'credit card number payment card debit card',
    'name':        'first name last name full name person name',
    'address':     'street address home address postal address location',
    'password':    'password credential secret key authentication',
    'health':      'medical record health data diagnosis patient',
    'financial':   'salary income revenue bank account balance'
}
```

On first use, `_get_pii_model()` lazily loads the `all-MiniLM-L6-v2` Sentence-BERT model and pre-computes embeddings for the nine descriptors. `identify_sensitive_columns(schema)` then encodes every column name (with underscores replaced by spaces) and computes cosine similarity against all nine category embeddings. A column whose best score exceeds **0.6** (line 87) is flagged as sensitive in the matching category. The choice of 0.6 is deliberately permissive — it favours recall over precision because a downstream operator can drop a false positive cheaply but cannot recover a missed PII column.

The two concrete subclasses `SQLiteConnector` (`sqlite_connector.py`) and `PostgresConnector` (`postgres_connector.py`) implement only `discover_schema` and `_get_connect_args` (the latter sets `{"timeout": 30}` for SQLite). The SQLite connector adds one critical fallback at lines 62-73: when a table has no declared primary key, the connector synthesises one by exposing SQLite's implicit `rowid`. This is what makes keyset pagination possible against arbitrary user-supplied SQLite tables — every non-`WITHOUT ROWID` table has a stable `rowid` even if the schema designer forgot to declare a primary key.

### 3.6.2 Keyset Pagination and Operator Normalisation (`query_builder.py:14-58, 61-124`)

Keyset pagination — sometimes called *cursor pagination* — is the technique of remembering the last primary-key value returned by a query and asking for the *next* batch of rows whose primary key is *strictly greater than* that value. Compared with `OFFSET` pagination, it is asymptotically faster on a B-tree-indexed primary key (O(log n + batch) vs O(n) per page) and uses bounded server-side memory regardless of how deep into the table the scan has progressed. The function `build_keyset_query` (`query_builder.py:14-58`) implements this pattern in four lines of effective SQL:

```sql
SELECT *                                  -- or "rowid, *" for SQLite implicit PK
FROM table_name
WHERE pagination_condition AND <rule_condition>
ORDER BY pk_column ASC
LIMIT :batch_size
```

`pagination_condition` is `'"<pk>" IS NOT NULL'` for the first page and `'"<pk>" IS NOT NULL AND "<pk>" > :last_pk'` for every subsequent page (lines 36-41).

The function also contains the operator alias normalisation table (lines 61-124). Six operator groups are recognised:

| Group | Operators handled | Note |
|---|---|---|
| Null tests | `IS NULL`, `IS NOT NULL` | Simple textual rendering |
| Pattern match | `LIKE`, `NOT LIKE` | Single quotes doubled to escape |
| Regex | `~`, `!~` | PostgreSQL only — returns `None` for SQLite |
| Set membership | `IN`, `NOT IN` | Comma-split, brackets stripped, quotes escaped via `chr(39)` |
| Comparison | `=`, `!=`, `>`, `<`, `>=`, `<=` | Datetime branch detects `NOW()` / `INTERVAL` / `datetime(`; numeric branch wraps in `CAST(... AS REAL)` for SQLite |
| Complex (Python-side) | `BETWEEN`, regex, `cross_field`, `date_math` | Routed to the `complex_executor` |

When the normalisation table cannot handle an operator, the function returns `(None, {})` (line 123-124) and the caller skips the rule cleanly without raising. This is the *defensive* path that allows the system to scan against schemas it has never seen before without ever hard-failing on an unrecognised SQL fragment.

### 3.6.3 The Complex Executor (`complex_executor.py:262-348`)

For rules that cannot be expressed as a single SQL `WHERE` (typically temporal or cross-field rules), `scan_complex_rule` performs the keyset loop at the Python level and dispatches each row to one of four evaluators:

```python
# complex_executor.py:254-259
_EVALUATORS = {
    "between":     _eval_between,
    "regex":       _eval_regex,
    "cross_field": _eval_cross_field,
    "date_math":   _eval_date_math,
}
```

`_eval_between` parses `rule.value` as `"lo,hi"` and returns `True` (i.e. the row is a violation) if the cell is outside the inclusive range. `_eval_regex` returns `True` when `re.search(pattern, str(value))` returns no match. `_eval_cross_field` evaluates `row[target_column] <op> row[second_column]` using the operator function map at lines 97-104 and returns the *negation* of the result (the rule states the *constraint*, so a violation is the negation). `_eval_date_math` parses the rule value through `_parse_date_threshold` (which handles `NOW()`, `CURRENT_TIMESTAMP`, `CURRENT_DATE`, `±N days` offsets, and three ISO date formats) and the cell value through `_parse_date_value` (which handles five common formats including `%d/%m/%Y` and `%m/%d/%Y`), then compares them through the same operator function map.

This Python-side evaluator is the project's escape hatch: any rule that does not fit a simple SQL `WHERE` ends up here, evaluated row-by-row in the keyset loop, paying the obvious latency cost in exchange for arbitrary expressiveness.

### 3.6.4 The Violations Store (`violations_store.py`)

The violations store has been described in §2.2 (its DDL) and is consumed throughout the pipeline through six query functions:

- `log_violation(...)` (lines 100-160) — single-row insert returning the new violation ID;
- `update_violation_status(...)` (lines 163-189) — bulk update for the validator's confirmed/false-positive labels;
- `store_rule_explanation(...)` (lines 214-256) — upsert into `rule_explanations` keyed on `(scan_id, rule_id)`;
- `get_violations_sample_for_validation(scan_id, rule_id, ceiling=0.85, limit=20)` (lines 289-317) — returns the lowest-confidence violations for the validator to sample;
- `get_violations_by_scan(...)` / `get_violations_by_table(...)` / `get_low_confidence_violations(...)` (lines 331-367) — straightforward retrieval helpers used by the reporting node;
- `get_scan_summary(scan_id)` (lines 370-402) — aggregates `total_violations`, `tables_with_violations`, `rules_violated`, `avg_confidence`, `scan_start`, `scan_end`.

The DDL is dialect-aware: the SQLite branch at lines 55-75 uses `INTEGER PRIMARY KEY AUTOINCREMENT` and `TEXT` timestamps, while the PostgreSQL branch at lines 26-46 uses `SERIAL PRIMARY KEY`, `TIMESTAMP`, and `JSONB` for the `violating_data` column (allowing range queries over the captured row payloads, useful in production analytics scenarios).

---

## 3.7 Vector Store and Retrieval-Augmented Generation

The project ships two Qdrant collections, both rooted in the local-mode store at `<repo>/qdrant_db/`:

- **`policy_rules`** — declared in `src/vector_database/policy_store.py:27` with the constant `POLICY_COLLECTION = "policy_rules"`. Vectors are 384-dimensional (line 28) and the distance metric is **cosine** (line 113). The embedding model is `BAAI/bge-small-en-v1.5` via FastEmbed (line 124). The `PolicyRuleStore` class manages the collection lifecycle and is exposed as a singleton through `get_policy_store()` (lines 53-70) — this is necessary because Qdrant local mode locks the storage directory, and without singleton wrapping a parallel test run will deadlock on a file lock.
- **`document_chunks`** — declared in `src/vector_database/qdrant_vectordb.py:25`. Vectors are also 384-dimensional but the distance metric is **Euclidean (L2)** (line 64). This collection holds raw document chunks (text, page number, character offsets) used by the `policy_mapper` interceptor node when it needs to retrieve more context than the structured `policy_rules` collection provides. Deduplication is performed at insertion time by checking existing chunk IDs (lines 91-106) so that re-running an ingestion pass does not bloat the collection.

Both collections share the `BAAI/bge-small-en-v1.5` model, which was chosen for its strong performance on the MTEB benchmark, its 384-dimensional output (small enough to keep the collection compact), and its CPU-friendly inference latency. The model itself is part of the BAAI BGE family documented by Xiao et al. [13].

The RAG path inside the interceptor's `policy_mapper_node` is straightforward: the user's SQL query plus the `stated_purpose` are encoded into a single vector by FastEmbed, the vector is used to search the `policy_rules` collection with `top_k=10` (typically) and an optional framework filter (e.g. `framework="GDPR"`), and the returned rules are reranked by their stored `confidence` scores. The reranked list is then passed to the `verdict_reasoner` as context.

---

## 3.8 Caching and Resilience

### 3.8.1 Document and Embedding Cache (`src/utils/document_cache.py:1-543`)

Three logical cache layers (lines 5-7) are unified behind a single `CacheManager`: parsed document chunks (Layer 1), generated embeddings (Layer 2), and vector-DB existence checks (Layer 3). Each layer has its own TTL (lines 235-237):

- `TTL_DOCUMENT = 7 * 24 * 3600`     # 7 days
- `TTL_EMBEDDING = 30 * 24 * 3600`   # 30 days
- `TTL_METADATA = 1 * 24 * 3600`     # 1 day

Each layer is keyed with a documented prefix (lines 229-232): `dca:doc`, `dca:emb`, `dca:meta`. The cache is two-tiered: Redis is the primary store (with connection pooling, max 50 connections at line 131-219) and `InMemoryCache` (LRU eviction, default 500 MB cap at line 56) is the deterministic fallback. If the Redis connection cannot be established at startup, the cache manager degrades gracefully to the in-memory store and logs a single warning — there is no further attempt to reconnect, so the cache behaves like a true LRU for the rest of the process lifetime.

A separate `SchemaCache` (`src/utils/cache.py`) caches the result of `discover_schema()` for a default TTL of 3600 s (1 hour). The cache key is `(db_type, db_name)` and the cache is stored in module-level state — appropriate because schema discovery is idempotent and the cost of a stale entry (one extra schema query) is negligible.

Cache statistics (hit count, miss count, hit rate) are kept in a `CacheStats` dataclass at `document_cache.py:27-50`, which lets the operator query the cache effectiveness at any time without instrumenting the rest of the codebase.

### 3.8.2 Middleware Decorators (`src/agents/middleware/`)

Three middleware modules wrap node bodies:

- **`guardrails.py`** — `InputGuardrail` and `OutputGuardrail` callable classes (lines 65-188). Inputs are sanitised (truncated above 8000 characters, PII patterns stripped). Outputs are validated against the schema for the rule-extraction tool: `rule_type ∈ {data_retention, data_access, data_quality, data_security, data_privacy}`, `confidence ∈ [0,1]`, `rule_text` non-empty.
- **`logging_mw.py`** — the `@log_node_execution` decorator (lines 33-97) logs the node start, end (with duration in milliseconds), and any exception, plus the names of the input and output state keys touched. It works transparently with both synchronous and asynchronous node bodies.
- **`retry.py`** — the `@retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)` decorator (lines 32-91) retries on any exception by default, with exponential back-off. The defaults are deliberately *unconfigurable in the type system* so that engineers cannot accidentally relax them; if a particular node needs different retry semantics it must override the decorator explicitly at the call site.

These three decorators compose: the canonical scanner LLM node is decorated with all three, in the order `@retry_with_backoff` (outermost) → `@log_node_execution` → `@guardrail` (innermost), so that retries are visible to the logger and the guardrail runs on every attempt.

---

## 3.9 Memory Layer (`src/agents/memory/`)

LangGraph distinguishes two kinds of persistent memory: *short-term* (a checkpointer that lets a graph resume mid-flight) and *long-term* (a store that persists across threads and across runs). The project keeps the two strictly separate.

### 3.9.1 Checkpointer (`checkpointer.py:46-116`)

The `get_checkpointer` factory is a context manager that returns one of three implementations based on a `backend` argument:

- `"memory"` — `InMemorySaver`, used by tests and notebooks.
- `"sqlite"` — `SqliteSaver` taking a `db_path`; this is the default in `run_hi_small.py` and `scripts/smoke_graph_e2e.py`, where the checkpoint file is `data/smoke_checkpoints.db`.
- `"postgres"` — `PostgresSaver` taking a `conn_string`; this is the production backend.

The factory wraps every implementation in a `with` block to guarantee resource cleanup, in line with the warning in `AGENT_BUILDING_GUIDE.md:123-127` that `PostgresSaver.from_conn_string()` is itself a context manager and must be entered before use.

### 3.9.2 Long-term Store (`store.py:39-127`)

The long-term store is a thin wrapper, `ExtractionMemory`, around LangGraph's `InMemoryStore`. It exposes three namespaces — `("extractions",)`, `("corrections",)`, `("patterns",)` — and six methods: `save_extraction`, `load_extraction`, `save_correction`, `get_corrections`, `save_pattern`, `get_pattern`. The key for an extraction is the SHA-256 hash of the document path, which means re-running an extraction over the same PDF is a constant-time lookup. In production, the `InMemoryStore` would be replaced with a database-backed store (e.g. the `PostgresStore` from `langgraph-store-postgres`) without any change to the wrapper's surface.

The two memory types serve different purposes that should not be conflated: a checkpoint is a *snapshot of one in-flight run*, while a long-term store is a *cross-run knowledge base*. Mixing the two — for example, by storing rule patterns in a checkpoint — would tie a learned correction to a single thread and lose its value the next time the policy is scanned.

---

## 3.10 LLM Model Pinning

The project pins specific Llama variants to specific nodes on a cost-vs-quality basis. The pinning is summarised in Table 3.5:

| Node | Model | Justification |
|---|---|---|
| `rule_extraction_node` | `llama-3.1-8b-instant` | High-volume, prompt-template-driven; model needs to follow a strict tool schema rather than reason |
| `violation_validator_node` | `llama-3.1-8b-instant` | Binary classification (`confirmed` vs `false_positive`); 8 B is over-spec |
| `explanation_generator_node` | `llama-3.3-70b-versatile` | Open-ended narrative generation; quality matters for the audit document |
| `intent_classifier_node` (slow path only) | `llama-3.1-8b-instant` | Multiclass classification; rule-based fast path handles 90 % of calls without LLM |
| `verdict_reasoner_node` | `llama-3.3-70b-versatile` | Joint reasoning over query + policy retrieval + sensitive-column inference |
| `auditor_node` | `llama-3.1-8b-instant` | Self-consistency check; needs only logical comparison of two strings |
| `schema_discovery_node` / `data_scanning_node` / `violation_reporting_node` / `report_generation_node` / `cache_check` / `context_builder` / `policy_mapper` / `executor` | None | Deterministic |

The cost differential between the two models is roughly an order of magnitude per token. By routing the high-volume, low-complexity tasks to the smaller model and reserving the larger model for the two genuinely reasoning-heavy nodes (explanation generation and verdict reasoning), the project keeps the per-scan cost firmly under one US dollar even on multi-thousand-row datasets — a number that has been measured directly through the `total_cost_usd` field on the interceptor state, accumulated by the per-node cost counters.

---

## 3.11 Human-in-the-Loop Checkpoint

The HITL surface is implemented through LangGraph's `interrupt()` primitive at `src/agents/graph.py:354`. When the conditional router decides to enter `human_review`, the node:

1. assembles a structured payload `{rules: [...], message: "...", interruptId: "..."}` containing every rule whose confidence fell below 0.7;
2. calls `interrupt(payload)` — LangGraph then suspends the graph, persists the checkpoint (with the SQLite checkpointer the suspension is durable across process restarts), and returns the payload to the streaming surface;
3. the AuditLens UI receives the payload through its WebSocket subscription and renders the HITL modal;
4. the operator chooses, per rule, one of `approve` / `edit` / `drop`;
5. the operator's choices are sent back to the LangGraph runtime as a `Command(resume={"approved": [...], "edited": [...], "dropped": [...]})`;
6. the resume payload is merged into `state["structured_rules"]` (approved + edited rules only) and the graph resumes at `data_scanning`.

The contract between the node and the UI — the exact key names of the payload and the resume — is the main thing to keep stable; this is why §3.2 of this chapter insists that updates to the state schema come *first*.

---

## 3.12 Configuration, Front-end and Deployment

### 3.12.1 `pyproject.toml`

The complete dependency manifest is a single `[project]` block at `pyproject.toml:1-29`:

```toml
[project]
name            = "data-compliance-agent"
version         = "0.1.0"
description     = "AI-powered compliance scanning and enforcement platform"
readme          = "README.md"
requires-python = ">=3.13"

dependencies = [
    "python-dotenv>=1.0.1",
    "fastembed>=0.7.4",
    "ipykernel>=7.2.0",
    "ipython>=9.10.0",
    "langchain>=1.2.10",
    "langchain-groq>=1.1.2",
    "langgraph>=1.0.9",
    "langgraph-checkpoint-postgres>=3.0.4",
    "langgraph-checkpoint-sqlite>=3.0.3",
    "langgraph-cli[inmem]>=0.4.8",
    "mem0ai>=1.0.4",
    "pydantic>=2.12.5",
    "pymupdf>=1.27.1",
    "pytest>=9.0.2",
    "qdrant-client>=1.17.0",
    "redis>=7.2.0",
    "reportlab>=4.4.10",
    "rich>=14.3.3",
    "sentence-transformers>=5.2.3",
    "sqlmodel>=0.0.35",
]
```

Twenty packages, all installed with one `uv pip install -e .` invocation against a `uv venv`-managed virtual environment. The project intentionally does not pin the upper bound of any dependency: the LangGraph and LangChain ecosystems iterate quickly, and being on the latest minor release has historically been the safer choice.

### 3.12.2 `.env`

A single environment variable is mandatory: `GROQ_API_KEY`. Optional variables include `REDIS_URL` (defaults to `localhost:6379/0`), `LANGSMITH_API_KEY` (for hosted tracing), and the four PostgreSQL variables (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`) consumed by `langgraph-checkpoint-postgres`. The `.env.example` shipped with the repository documents the full set.

### 3.12.3 Front-end (`agent-chat-ui/`)

The front-end is a separate Next.js 16.2.4 project with its own `package.json`. Notable dependencies:

- `next` 16.2.4 (App Router, server components)
- `react` 19.2.4
- `@langchain/langgraph-sdk` ^1.8.9 — the JavaScript LangGraph client
- `tailwindcss` ^4 with `shadcn/ui` for components
- `recharts` for the score gauge and rule breakdown chart
- `react-dropzone` for the policy-PDF upload widget
- `sonner` for toast notifications
- `zustand` for the central compliance-store state container
- `lucide-react` for icons
- `framer-motion` for the timeline animations

The five primary pages are `/` (landing), `/scan` (policy upload + DB target + Run button + live timeline + HITL modal), `/dashboard/[threadId]` (score gauge + rule breakdown + violations table + export buttons), `/api/reports/[...path]` (a Next.js API route that proxies the generated PDF/HTML files), and the root `layout.tsx`. The data flow is: `landing → scan → invoke graph → stream updates → HITL if needed → graph completes → dashboard → export`.

### 3.12.4 LangGraph Dev Server

In development the LangGraph runtime is started on `http://127.0.0.1:2024` either by `langgraph dev` (when a `langgraph.json` exists in the repository root) or by the embedded server in `run_hi_small.py`. The front-end's `lib/langgraph.ts` initialises a client against this URL, opens a stream with `mode="updates"`, and parses the per-node updates into the timeline component. *Note: the `langgraph.json` configuration file is not present in the current repository snapshot; the canonical operator path during development is therefore `python run_hi_small.py` for the full pipeline and `python run_intercept.py` for the interceptor demo. The `README.md` references `langgraph dev` and `agent-chat-ui` as the recommended demo path; both are operational once `langgraph.json` is added back.*

### 3.12.5 Build, Run, Test

| Action | Command |
|---|---|
| Create venv | `uv venv` |
| Install (editable) | `uv pip install -e .` |
| Quick PII demo | `python main.py` |
| Full E2E pipeline | `python run_hi_small.py` |
| Scan-only | `uv run python run_scan.py --db data/HI-Small_Trans.db` |
| Live interceptor demo | `python run_intercept.py` |
| Full unit-test suite | `pytest tests/unit/ -v` |
| Skip slow tests | `pytest tests/unit/ -m "not slow" -v` |
| End-to-end smoke | `python scripts/smoke_graph_e2e.py` |
| Cache prewarm | `python scripts/prewarm_demo.py` |
| Front-end dev | `cd agent-chat-ui && npm run dev` |

---

> *Chapter summary.* This chapter has walked through every layer of the implementation from the project layout, through the state contracts, the three graphs, the 17 nodes, the three algorithmic stages, the database tooling (PII detection, keyset pagination, complex-rule evaluation, the violations store), the vector store, the cache and middleware, the dual memory layer, the model pinning rationale, and the human-in-the-loop surface. Wherever a constant or a control-flow choice could be misread, the corresponding `file:line` location has been cited so that the reader can verify the description against the source. Chapter 4 now turns to the testing strategy, presenting the unit tests, the integration tests, the end-to-end system test, the performance characterisation, and the security posture of the codebase.
