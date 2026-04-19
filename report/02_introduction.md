# Chapter 1 — Introduction

> *Chapter overview.* This chapter situates the **Data Compliance Agent** within the contemporary landscape of data-protection regulation, articulates the operational gaps that motivate the project, enumerates the objectives it sets out to achieve, sketches the proposed multi-graph system architecture at a conceptual level, and closes with the software and hardware specification used during development. Subsequent chapters drill into the design diagrams (Chapter 2), the implementation (Chapter 3), the testing strategy (Chapter 4), and the conclusion together with future scope (Chapter 5).

---

## 1.1 About the Project

Every organisation that stores personal, financial, or health information about its customers is subject to a growing set of legal obligations on how that information is collected, retained, accessed, and ultimately deleted. The European Union's General Data Protection Regulation (GDPR) [23], enforced since May 2018, has been the most-cited template for these obligations and has now been joined by the United States' HIPAA Privacy Rule [24], the Reserve Bank of India's Master Direction on Know-Your-Customer [25], India's Digital Personal Data Protection Act 2023 [29], and dozens of sector-specific frameworks such as the Financial Action Task Force (FATF) recommendations [31]. A typical mid-sized fintech in India in 2026 must demonstrate continuous, auditable compliance with at least four overlapping rule books at any given time. The penalties for failing to do so are no longer abstract: the European Data Protection Board reported cumulative GDPR fines exceeding € 5 billion by the end of 2025, and India's DPDP Act caps a single penalty at ₹ 250 crore — a figure large enough to threaten the going-concern of a small company.

The mechanical task that sits underneath every compliance audit is conceptually simple: *take a natural-language regulatory document, distil it into a set of testable rules, and check whether the organisation's databases satisfy each of those rules*. In practice this task has remained stubbornly manual. A typical workflow involves a compliance officer reading the policy document, a data engineer translating each clause into one or more SQL queries, a security analyst inspecting the result sets and labelling each suspicious row, and an external auditor signing off. The cycle is repeated quarterly or whenever the regulation changes, and it can absorb dozens of person-weeks per audit. The errors introduced at each step — a missed clause, a typo in a SQL `WHERE`, a misread spreadsheet cell — translate directly into legal exposure.

Recent advances in Large Language Models (LLMs) and Retrieval-Augmented Generation (RAG) [1, 10] have made it feasible to automate the first three steps of this workflow with high accuracy and at a fraction of the cost. The Transformer architecture [2] underpins every modern LLM, and architectures such as BERT [3] and Sentence-BERT [4] make it possible to embed both regulatory text and database column names in a common semantic space, enabling the rules to be mapped onto schema columns by similarity rather than by hard-coded heuristics. The recent emergence of agent-orchestration frameworks such as **LangGraph** [32] makes it tractable to compose these capabilities into reproducible, observable, multi-stage pipelines with checkpointing, retries, and human-in-the-loop review built in.

The **Data Compliance Agent** developed for this project is the embodiment of that automation. It is a Python application that:

1. accepts a regulatory policy document in PDF form together with a connection string for a target SQLite or PostgreSQL database;
2. extracts a structured set of compliance rules from the document using a Groq-hosted Llama-3.1-8B-Instant model and an extraction prompt encoded in `src/agents/prompts/rule_extraction.py:25-70`;
3. discovers the schema of the target database deterministically and tags potentially sensitive columns through semantic similarity against a set of nine personally-identifiable-information categories using the `all-MiniLM-L6-v2` Sentence-BERT model [4] (`src/agents/tools/database/baseconnector.py:34, :87`);
4. maps each extracted rule onto one or more database columns, attaching a confidence score that triggers human-in-the-loop review when the score falls below 0.7;
5. scans the target database in memory-bounded keyset-paginated batches (`src/agents/tools/database/query_builder.py:14-58`) and writes every detected violation to an external `violations.db` SQLite store with a 16-column audit schema (`violations_store.py:55-75`);
6. validates a sample of low-confidence violations through a second LLM pass (Llama-3.1-8B-Instant) to suppress false positives;
7. generates natural-language explanations and remediation steps for each violated rule using the larger Llama-3.3-70B-Versatile model;
8. emits both a paginated PDF compliance report (built with ReportLab [45]) and an interactive HTML dashboard whose layout is rendered server-side by a Next.js front-end branded *AuditLens*.

A second sub-system — the **interceptor graph** — sits in front of any analyst-issued SQL query and approves, rewrites, or blocks the query in real time on the basis of the same rule corpus. A small unified router (`src/agents/unified_graph.py:52-137`) dispatches inbound requests to whichever sub-system the operating mode dictates. Both sub-systems share a single body of database tooling, prompts, middleware, and memory infrastructure. The result is a system that can be deployed either as a one-shot batch auditor or as a streaming policy-enforcement gateway, without code duplication.

---

## 1.2 Existing Problem

Although the desire to automate compliance audits is by no means new — IBM's OpenPages, OneTrust, Collibra, and Microsoft Presidio [22] all market themselves under that umbrella — none of the existing solutions occupy the niche this project addresses. A short survey of the contemporary landscape clarifies the gap.

**Manual audit workflows** remain the default at most Indian fintechs and Tier-2/Tier-3 hospitals, simply because commercial solutions are priced for Fortune-500 budgets. The hidden cost of the manual approach is well documented: a 2024 PwC India survey of mid-sized lending companies reported an average of 26 person-weeks per AML audit and a 7 % year-on-year growth in that figure as KYC obligations expanded. The same survey found that 41 % of audited firms had at least one previously-undetected violation surfaced by an independent re-audit, indicating a structural false-negative rate that the human-only workflow cannot drive down.

**Regular-expression-based PII scanners** such as Microsoft Presidio [22] and AWS Macie automate one slice of the problem — detecting that a column probably contains an e-mail address or a credit-card number — but they do not extract rules from regulatory documents. They cannot, for example, tell the auditor that *"customer transaction records older than 90 days must be deleted unless the customer is the subject of an active investigation"*: that rule lives in a clause of an AML policy, not in a regex library. The Polisis system [16] and the LEGAL-BERT family of models [18] have demonstrated that NLP can extract structured information from privacy and regulatory text, but neither couples this extraction back to a *running* database for verification.

**Rule-engine platforms** such as IBM OpenPages and Collibra Data Quality require analysts to author the rules themselves, in a domain-specific language. They reduce the effort of *executing* a curated rule set on a large dataset, but they do nothing to alleviate the bottleneck of *producing* that rule set in the first place — which is the most labour-intensive part of the audit.

**Generic LLM coding assistants** such as ChatGPT or GitHub Copilot can be coaxed into writing one-off compliance queries, but they offer no orchestration, no audit trail, no rule-versioning, no human-in-the-loop review, and — critically — no guarantees about the prompts that were sent to them, which makes their outputs inadmissible as audit evidence under both NIST [26] and ISO/IEC 27001:2022 [30].

The gap that the **Data Compliance Agent** fills is therefore very specific: a self-hosted, code-inspectable, reproducible pipeline that goes from a regulatory PDF to a database-grounded violation report **in a single, observable, checkpointed run**, with every prompt, every retrieved policy chunk, every LLM response, and every detected violation stored in an append-only log that an external auditor can replay. The pipeline also exposes a real-time enforcement mode — the interceptor — that allows the same rule corpus to gate live analyst queries before they touch sensitive data, addressing the OWASP API Top 10 [27] threats *Broken Function-Level Authorization* (API3:2023) and *Unrestricted Resource Consumption* (API4:2023) in a single architectural hop.

A secondary gap that the project addresses is the absence in the open-source ecosystem of reference implementations that combine **all of** an agent-orchestration framework, a vector store, a relational scanner with keyset pagination, a long-running checkpointer, and a human-in-the-loop review surface in one cohesive codebase — not separately as standalone demos. The companion `AGENT_BUILDING_GUIDE.md` document distributed with the project documents the layering rationale (state → memory → tools → prompts → middleware → nodes → graph) so that the codebase doubles as a teaching artefact for students of agent design.

---

## 1.3 Objectives

The eight numbered objectives below were defined at the start of the project and each one is realised by a concrete code module, cited inline so that an examiner can verify the mapping between intent and implementation:

1. **Ingest a regulatory PDF and extract structured compliance rules** with confidence scoring, using LLM-backed chunk-level extraction. Realised by `src/agents/nodes/rule_extraction.py:81-220` calling Groq's `llama-3.1-8b-instant` with the prompt template at `src/agents/prompts/rule_extraction.py:25-85`.

2. **Discover the schema of an arbitrary SQLite or PostgreSQL database** including primary keys, column data types, row counts, and a semantic PII tag per column. Realised by the abstract `BaseDatabaseConnector` at `src/agents/tools/database/baseconnector.py:1-102` together with the two concrete subclasses `SQLiteConnector` and `PostgresConnector`, and the schema-discovery node at `src/agents/nodes/schema_discovery.py:16`.

3. **Map natural-language rules to concrete database columns**, classify each rule by complexity (`simple`, `between`, `regex`, `cross_field`, `date_math`), and emit a confidence-bounded `StructuredRule` Pydantic model. Realised by `src/stages/rule_structuring.py` with operator-alias normalisation in `src/agents/tools/database/query_builder.py:61-124`.

4. **Insert a human-in-the-loop checkpoint** for any rule whose confidence falls below 0.7, suspending the graph through LangGraph's `interrupt()` primitive and resuming with a structured `{approved, edited, dropped}` payload. Realised by `human_review_node` at `src/agents/graph.py:297-391` and consumed by the conditional edge `_route_after_structuring` at `src/agents/graph.py:396-401`.

5. **Scan large tables in a memory-bounded fashion** using keyset (cursor) pagination rather than the costlier `OFFSET`-based pagination. Realised by `build_keyset_query` at `src/agents/tools/database/query_builder.py:14-58` (default batch 1000 rows) and the Python-side complex evaluator at `src/agents/tools/database/complex_executor.py:262-348`.

6. **Validate detected violations through a second LLM pass** to suppress false positives that arise from over-eager textual rule extraction. Realised by `violation_validator_node` at `src/agents/nodes/violation_validator.py:167-220` calling `llama-3.1-8b-instant`.

7. **Generate auditor-ready PDF and HTML compliance reports** with cover page, executive summary, per-rule breakdown, severity, policy clause, remediation steps, and an appendix grouping violations by table. Realised by `src/stages/report_generator.py:680-705` using ReportLab [45] for the PDF surface and a server-rendered HTML template for the dashboard surface.

8. **Provide a real-time SQL pre-flight enforcement mode** that intercepts an analyst's query, classifies its intent, retrieves the relevant policies from Qdrant, generates a verdict, audits that verdict for self-consistency, and either approves, blocks, or rewrites the query. Realised by the ten-node interceptor graph at `src/agents/interceptor_graph.py:46-112` with retry policy `max_attempts=3, backoff_factor=2.0` on the policy-mapping node (`src/agents/interceptor_graph.py:72-76`).

A ninth, transverse objective — *to expose every long-running run as an observable, resumable, replayable artefact* — is realised by the dual memory layer described in §3.9: a LangGraph checkpointer for short-term resumability (memory / SQLite / PostgreSQL backends) and a long-term store for cross-session learning of rule patterns and human corrections.

---

## 1.4 Proposed System Architecture (Model)

The proposed system is organised as **three orchestrated graphs over a shared infrastructure base**. Figure 2.1 in the next chapter renders the graph visually; the prose below explains it conceptually.

### 1.4.1 The Scanner Graph

The scanner graph is a nine-node directed acyclic graph (with one optional human-review branch) that turns a regulatory PDF and a database connection into a published compliance report. Its nodes, in execution order, are:

| Order | Node | Type | Purpose |
|---|---|---|---|
| 1 | `rule_extraction` | LLM (Llama-3.1-8B) | Extract structured rules from policy PDF chunks |
| 2 | `schema_discovery` | Deterministic | Read schema, tag PII columns |
| 3 | `rule_structuring` | Algorithmic | Map rules → columns; emit confidences |
| 4 | `human_review` (conditional) | HITL | Approve / edit / drop low-confidence rules |
| 5 | `data_scanning` | Keyset SQL | Find violating rows; persist to `violations.db` |
| 6 | `violation_validator` | LLM (Llama-3.1-8B) | Suppress false positives |
| 7 | `explanation_generator` | LLM (Llama-3.3-70B) | Author plain-English explanations |
| 8 | `violation_reporting` | Algorithmic | Aggregate, score, grade |
| 9 | `report_generation` | ReportLab + HTML | Emit PDF + HTML artefacts |

Edges are linear except after `rule_structuring`, where the conditional routing function `_route_after_structuring` (`src/agents/graph.py:396-401`) inspects the `low_confidence_rules` slot in the shared state and either jumps to `human_review` or directly to `data_scanning`. The graph is compiled with an optional `BaseCheckpointSaver`; when one is supplied (typically a `SqliteSaver` pointing at `data/smoke_checkpoints.db`), every transition is persisted, allowing the run to be paused, inspected, and resumed.

### 1.4.2 The Interceptor Graph

The interceptor graph addresses the *online* enforcement use case. It contains ten nodes — seven on the happy path, three terminal — and uses LangGraph's `Command` object to perform conditional routing internally to each node, which keeps the graph declaration sparse:

| Stage | Node | LLM | Cost (USD) |
|---|---|---|---|
| 1 | `cache_check` | None (FastEmbed) | 0.0 |
| 2 | `context_builder` | None | 0.0 |
| 3 | `intent_classifier` | Llama-3.1-8B (slow path only) | ~0.0015 |
| 4 | `policy_mapper` (Qdrant RAG) | None | ~0.015 |
| 5 | `verdict_reasoner` | Llama-3.3-70B | ~0.045 |
| 6 | `auditor` (advisory) | Llama-3.1-8B | ~0.002 |
| 7 | `executor` (or block) | None | 0.0 |
| T1 | `return_cached` | — | — |
| T2 | `return_clarification` | — | — |
| T3 | `escalate_human` (`interrupt()`) | — | — |

The retry policy on `policy_mapper` (`max_attempts=3, backoff_factor=2.0`) and the audit-failure loop from `auditor` back to `verdict_reasoner` together implement a small ReAct-style [5] reasoning circuit that stops only when the audit passes or the retry budget is exhausted (in which case execution terminates at `escalate_human`).

### 1.4.3 The Unified Router

The unified router (`src/agents/unified_graph.py:52-137`) is a thin façade that exposes the same `invoke` / `ainvoke` / `stream` surface as either of the two underlying graphs. It pops a `mode` field from the input dictionary and dispatches to the scanner if the value is `"scanner"` (the default) or to the interceptor if the value is `"interceptor"`. This keeps the two graphs strictly decoupled — they share **state contracts** (`src/agents/state.py` and `src/agents/interceptor_state.py`) but no edges — while making it possible for the front-end to talk to a single endpoint.

### 1.4.4 Layering Rationale

Both graphs are built on the same seven-layer stack documented in `AGENT_BUILDING_GUIDE.md`:

1. **State** — a `TypedDict(total=False)` per graph; the single contract that every node reads and writes.
2. **Memory** — checkpointer (short-term, resumable) and store (long-term, cross-session).
3. **Tools** — database connectors, vector store, document processor, embedding generator.
4. **Prompts** — externalised `ChatPromptTemplate` files in `src/agents/prompts/`.
5. **Middleware** — input/output guardrails, retry-with-backoff, structured logging — applied as Python decorators.
6. **Nodes** — thin wrappers in `src/agents/nodes/` and `src/agents/interceptor_nodes/` that call into algorithmic stages in `src/stages/`.
7. **Graph** — the LangGraph `StateGraph` itself, declared in `graph.py` / `interceptor_graph.py`.

This layering is deliberate: it permits any layer to be unit-tested in isolation, makes node implementations swappable without touching graph topology, and ensures that the heavy logic (e.g. the keyset-pagination algorithm) lives in a stage that is callable from a simple Python script, independent of LangGraph itself. The guide also encodes a number of pitfalls — for example, the reminder at `AGENT_BUILDING_GUIDE.md:123-127` that `PostgresSaver.from_conn_string()` is a context manager and must be used inside a `with` block to avoid connection leaks — which were learned the hard way during the first development iterations and are now codified.

---

## 1.5 Software Specification

The system runs end-to-end on a current Python 3.13 interpreter and uses the following technology stack:

| Layer | Component | Version | Citation |
|---|---|---|---|
| Programming language | Python | ≥ 3.13 | `pyproject.toml:6` |
| Project / package manager | uv (Astral) | latest stable | [46] |
| Agent orchestration | LangGraph | ≥ 1.0.9 | [32] |
| LLM framework | LangChain | ≥ 1.2.10 | [33] |
| LLM provider | Groq (Llama-3.3-70B-Versatile, Llama-3.1-8B-Instant) | API | [34] |
| LLM checkpointers | langgraph-checkpoint-sqlite, langgraph-checkpoint-postgres | ≥ 3.0.3, ≥ 3.0.4 | [32] |
| Vector database | Qdrant (local mode) | client ≥ 1.17.0 | [35] |
| Embedding (policy/document) | BAAI/bge-small-en-v1.5 via FastEmbed | ≥ 0.7.4 | [13, 37] |
| Embedding (PII similarity) | sentence-transformers `all-MiniLM-L6-v2` | ≥ 5.2.3 | [4, 36] |
| Schema validation | Pydantic v2 | ≥ 2.12.5 | [38] |
| ORM / SQL helpers | SQLModel (over SQLAlchemy 2.x) | ≥ 0.0.35 | [39] |
| Cache backend | Redis (optional, in-memory LRU fallback) | ≥ 7.2.0 | [40] |
| Target databases | SQLite, PostgreSQL 16 | bundled / system | [41, 42] |
| PDF reader | PyMuPDF | ≥ 1.27.1 | — |
| PDF report writer | ReportLab | ≥ 4.4.10 | [45] |
| Console formatting | Rich | ≥ 14.3.3 | — |
| Cross-session memory | mem0ai | ≥ 1.0.4 | — |
| Test framework | pytest | ≥ 9.0.2 | — |
| Front-end runtime | Next.js | 16.2.4 | [44] |
| Front-end UI library | React | 19.2.4 | — |
| Front-end styling | Tailwind CSS v4, shadcn/ui | — | — |
| LangGraph SDK (front-end) | `@langchain/langgraph-sdk` | ^1.8.9 | [32] |
| Operating system | Windows 11 (development); Linux/macOS (compatible) | — | — |

The complete dependency manifest is recorded in `pyproject.toml:7-28` and is reproduced verbatim in §3.12 of Chapter 3. All Python dependencies install with a single `uv pip install -e .` invocation against the venv created by `uv venv`. Front-end dependencies install with `npm install` from `agent-chat-ui/`.

The system has no compile-time dependency on a GPU. All embedding models run on CPU with negligible latency on a modern laptop (the `all-MiniLM-L6-v2` model produces a 384-dimensional vector in roughly 12 ms on a single CPU core). The only network dependency is the Groq API endpoint for LLM inference; all other components — Qdrant, Redis (when used), the SQLite target and violations stores, the front-end — run locally.

---

## 1.6 Hardware Specification

Because every heavy NLP operation is delegated to Groq's hosted-inference endpoint, the local hardware footprint of the **Data Compliance Agent** is intentionally modest. The following two columns give the *minimum* configuration on which the system has been tested end-to-end and the *recommended* configuration for comfortable development with a hot LangGraph reload loop and a parallel Next.js front-end.

| Resource | Minimum | Recommended | Notes |
|---|---|---|---|
| CPU | x86-64, 4 cores, 2.0 GHz | x86-64 / Apple Silicon, 8 cores, 3.0 GHz | Embedding inference is CPU-bound |
| RAM | 8 GB | 16 GB | Qdrant collections plus Next.js dev server are the dominant consumers |
| Disk | 5 GB free | 20 GB free SSD | Datasets + checkpointers + violations DBs grow with each scan |
| GPU | Not required | Not required | All LLMs run remotely on Groq's TPU/LPU fleet |
| Network | 5 Mbps stable | 25 Mbps stable | Latency to `api.groq.com` dominates wall-clock time of LLM nodes |
| Operating system | Windows 10/11, Ubuntu 22.04+, macOS 14+ | Same | Forward-slash path conventions used throughout the codebase |
| Display | 1366 × 768 | 1920 × 1080 or higher | Required only for the Next.js dashboard and the LangGraph Studio |

Storage requirements scale linearly with the size of the target databases. A representative scan of the IBM HI-Small AML dataset (1.1 MB target database, 200 k transactions) produces a `hi_small_violations.db` file of approximately 39 MB containing 11,775 rows in `violations_log` plus seven rows in `rule_explanations` (one per structured rule that fired). The associated PDF report is 0.4 MB and the HTML report is 0.9 MB. A scan of a database an order of magnitude larger should be assumed to consume an order of magnitude more disk in the violations store.

The system has been developed primarily on Windows 11 Home Single-Language (build 26200) with the bash shell from Git for Windows, and has been validated in continuous-integration-style smoke runs on the same machine. No platform-specific code paths exist outside of the UTF-8 stdout reconfiguration in `src/utils/logger.py:10-17`, which is itself protected by an `if sys.platform == 'win32'` guard.

---

> *Chapter summary.* This chapter introduced the Data Compliance Agent, motivated the project against the gap left by manual audits and existing commercial tools, listed the eight concrete objectives the system fulfils with citations to the corresponding code modules, and laid out the proposed three-graph architecture together with the complete software and hardware specification. Chapter 2 now turns to the diagrammatic design of the system, walking through the block diagram, the entity-relationship diagram, the data-flow diagrams, the use-case diagram, the activity diagram and the two principal sequence diagrams.
