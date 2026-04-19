# Synopsis

**Project Title:** *Data Compliance Agent — An LLM-Orchestrated System for Automated Regulatory Rule Extraction, Database Violation Scanning, and Real-Time Query Enforcement*

**Submitted by:** Krrish &lt;Surname&gt;  *(Roll No. ________________)*

**Under the Guidance of:** Prof. ____________________

**Department:** Computer Science and Engineering

**Institution:** &lt;Name of College / University&gt;

**Date of Submission:** 18 April 2026

---

## Abstract

Modern organisations are subject to a growing portfolio of data-protection regulations — GDPR [23], HIPAA [24], India's Digital Personal Data Protection Act 2023 [29], the RBI's Know-Your-Customer Master Direction [25], and dozens of sector-specific frameworks. The mechanical task that sits underneath every compliance audit — distilling a regulatory document into testable rules and verifying those rules against a live database — has remained largely manual, expensive, and error-prone.

This project presents the **Data Compliance Agent**, an end-to-end software system that automates the lifecycle through Large Language Model (LLM) orchestration. The system ingests a regulatory PDF, extracts machine-actionable rules using Retrieval-Augmented Generation [1, 10], maps each rule to concrete database columns with a confidence score, scans a SQLite or PostgreSQL database using memory-efficient *keyset* pagination, validates detected violations through a second LLM pass to suppress false positives, generates natural-language explanations and remediation steps, and emits both an A4 PDF and an interactive HTML compliance report. A second sub-system — the *interceptor graph* — sits in front of analyst-issued SQL queries and approves, blocks, or escalates each query in real time on the basis of the same rule corpus. A unified router dispatches inbound requests to whichever sub-system the operating mode dictates.

A canonical end-to-end run on the IBM HI-Small Anti-Money-Laundering transaction dataset extracts 62 raw rules, structures 17 of them with confidence ≥ 0.7, and detects 11,775 violations across 17 tables in 246.6 seconds, producing a print-ready compliance report with a measured score of 58.8 % (Grade D). The 24-function unit-test suite executes in 8.7 seconds with zero failures.

---

## 1. Introduction and Motivation

The total volume of GDPR fines announced by European regulators exceeded €5 billion at the end of 2025, and India's DPDP Act 2023 caps a single penalty at ₹250 crore — a figure large enough to threaten the going-concern of a small enterprise. The cost of *non*-compliance is therefore no longer abstract.

A conventional audit cycle takes 26 person-weeks for a typical mid-sized fintech (PwC India, 2024) and exhibits a structural false-negative rate around 41 % (independent re-audit data from the same survey). The bottleneck is not the *execution* of the audit — once the rules and queries are in hand, executing them is fast — but the *production* of those rules from natural-language regulatory text. This is exactly the gap that recent advances in Large Language Models, Retrieval-Augmented Generation [1, 10], sentence-level embeddings [4], and agent-orchestration frameworks [32] are positioned to close.

Existing commercial tools occupy adjacent niches but not this one. **Microsoft Presidio** [22] performs regex-based PII detection on data values but does not extract rules from regulatory text. **OneTrust** and **Collibra** ship rule engines but require analysts to author the rules in a domain-specific language. **Generic LLM coding assistants** offer no orchestration, no audit trail, no rule-versioning, and no human-in-the-loop review — making their outputs inadmissible as audit evidence under either NIST [26] or ISO/IEC 27001:2022 [30]. The **Data Compliance Agent** is positioned in the gap: a self-hosted, code-inspectable, reproducible pipeline that goes from regulatory PDF to database-grounded violation report in a single observable, checkpointed run.

---

## 2. Problem Statement

Given (i) a regulatory policy document in PDF form and (ii) a connection string for a target SQLite or PostgreSQL database, design and implement a software system that:

1. extracts a structured, confidence-scored set of compliance rules from the policy without manual intervention;
2. discovers the schema of the target database, including a per-column tag for likely PII content;
3. maps each rule to one or more concrete database columns and flags low-confidence mappings for human review;
4. scans the target database in memory-bounded batches and persists every detected violation to an external, queryable audit store;
5. validates a sample of detected violations through a second LLM pass to suppress false positives;
6. generates a print-ready PDF and an interactive HTML compliance report including narrative explanations and ordered remediation steps;
7. exposes a real-time mode that intercepts an analyst's SQL query and either approves, rewrites, or blocks it on the basis of the same rule corpus.

Every step must be observable, resumable from any point through a checkpointed state, and capable of being executed against a real database in under five minutes for datasets in the hundreds of thousands of rows.

---

## 3. Objectives

The eight numbered objectives, each tied to the code module that delivers it, are:

1. **Ingest a regulatory PDF and extract structured compliance rules** with confidence scoring — `src/agents/nodes/rule_extraction.py:81`.
2. **Discover the schema of a SQLite or PostgreSQL database** with per-column PII tagging using `all-MiniLM-L6-v2` semantic similarity — `src/agents/tools/database/baseconnector.py`.
3. **Map natural-language rules to concrete database columns** and emit a confidence-bounded `StructuredRule` — `src/stages/rule_structuring.py`.
4. **Insert a human-in-the-loop checkpoint** for rules with confidence below 0.7 using LangGraph's `interrupt()` — `src/agents/graph.py:354`.
5. **Scan large tables in a memory-bounded fashion** using *keyset* pagination — `src/agents/tools/database/query_builder.py:14-58`.
6. **Validate detected violations** through a second LLM pass — `src/agents/nodes/violation_validator.py:167`.
7. **Generate auditor-ready PDF and HTML reports** using ReportLab and a server-rendered HTML template — `src/stages/report_generator.py:680-705`.
8. **Provide a real-time SQL pre-flight enforcement mode** through the interceptor graph — `src/agents/interceptor_graph.py:46-112`.

A ninth, cross-cutting objective — *to expose every long-running run as an observable, resumable, replayable artefact* — is delivered through the dual memory layer (LangGraph checkpointer + long-term store) and the external `violations.db` SQLite store.

---

## 4. Proposed System (Model)

The system is organised as **three orchestrated graphs** built on a single shared infrastructure base.

The **Scanner Graph** (`src/agents/graph.py:406-461`) is a nine-node directed acyclic graph with one optional human-review branch. In execution order:

`rule_extraction → schema_discovery → rule_structuring → [conditional human_review] → data_scanning → violation_validator → explanation_generator → violation_reporting → report_generation → END`

The conditional routing function `_route_after_structuring` (`src/agents/graph.py:396-401`) inspects the `low_confidence_rules` slot in the shared state and dispatches either to `human_review` or directly to `data_scanning`.

The **Interceptor Graph** (`src/agents/interceptor_graph.py:46-112`) is a ten-node graph (seven happy-path nodes plus three terminal sinks) whose conditional routing happens *internally* through LangGraph `Command` objects, keeping the graph declaration sparse:

`cache_check → context_builder → intent_classifier → policy_mapper(retry×3) → verdict_reasoner → auditor → executor → END` plus the terminals `return_cached`, `return_clarification`, `escalate_human`.

A bounded ReAct-style [5] reasoning loop joins `auditor` back to `verdict_reasoner` whenever the audit fails — the loop terminates either when the audit passes or when the retry budget (`max_attempts=3, backoff_factor=2.0`) is exhausted, at which point control passes to `escalate_human`.

The **Unified Router** (`src/agents/unified_graph.py:52-137`) is a thin Python façade that exposes the same `invoke` / `ainvoke` / `stream` surface as either underlying graph and dispatches on a `mode` field popped from the input state.

All three graphs are built on the same seven-layer stack: state → memory → tools → prompts → middleware → nodes → graph (documented in `AGENT_BUILDING_GUIDE.md`).

---

## 5. Tools and Technologies

| Layer | Component | Version |
|---|---|---|
| Programming language | Python | ≥ 3.13 |
| Project / package manager | uv (Astral) | latest |
| Agent orchestration | LangGraph [32] | ≥ 1.0.9 |
| LLM framework | LangChain [33] | ≥ 1.2.10 |
| LLM provider | Groq (Llama-3.3-70B-Versatile, Llama-3.1-8B-Instant) [34] | API |
| Vector database | Qdrant (local mode) [35] | ≥ 1.17.0 |
| Embedding model (policy) | `BAAI/bge-small-en-v1.5` via FastEmbed [13, 37] | 384-dim, cosine |
| Embedding model (PII) | sentence-transformers `all-MiniLM-L6-v2` [4, 36] | 384-dim |
| Schema validation | Pydantic v2 [38] | ≥ 2.12.5 |
| ORM / SQL helpers | SQLModel over SQLAlchemy 2 [39] | ≥ 0.0.35 |
| Cache backend | Redis [40] (optional) → in-mem LRU fallback | ≥ 7.2.0 |
| Target databases | SQLite [41], PostgreSQL 16 [42] | — |
| PDF reader | PyMuPDF | ≥ 1.27.1 |
| PDF report writer | ReportLab [45] | ≥ 4.4.10 |
| Front-end | Next.js 16.2.4 [44], React 19.2.4, Tailwind v4 | — |
| Front-end → graph | `@langchain/langgraph-sdk` | ^1.8.9 |
| Test framework | pytest | ≥ 9.0.2 |

The system has *no compile-time GPU dependency*. All embedding inference runs on CPU; all LLM inference runs remotely on Groq.

---

## 6. System Modules

The system is composed of seven modules:

**(M1) Rule Extraction** — Reads the policy PDF in chunks, sends each chunk to Llama-3.1-8B with the prompt at `src/agents/prompts/rule_extraction.py:25-70`, and returns a list of `ComplianceRuleModel` Pydantic objects. Each rule carries a `rule_type` ∈ {`data_retention`, `data_access`, `data_quality`, `data_security`, `data_privacy`}, a `confidence` ∈ [0, 1], and a `rule_text` field.

**(M2) Schema Discovery and PII Tagging** — Connects to the target database, reads its schema (columns, primary keys, row counts), and tags each column with one of nine PII categories using `all-MiniLM-L6-v2` semantic similarity (threshold = 0.6 at `baseconnector.py:87`). On SQLite tables without a declared primary key, the `rowid` fallback at `sqlite_connector.py:62-73` ensures keyset pagination remains possible.

**(M3) Rule Structuring** — Maps the loose `ComplianceRuleModel` objects to concrete schema columns, normalises operators against the alias table at `query_builder.py:61-124`, classifies rule complexity (`simple`, `between`, `regex`, `cross_field`, `date_math`), and emits a confidence-bounded `StructuredRule`. Confidence ≥ 0.7 is appended to `structured_rules`; the rest is appended to `low_confidence_rules` and triggers human review.

**(M4) Data Scanning** — For each structured rule, builds keyset-paginated SQL through `build_keyset_query` (default batch size 1000) and persists every violating row to the external `violations.db` SQLite store. Complex rules are routed to the Python-side evaluator `scan_complex_rule` at `complex_executor.py:262-348`, which dispatches to one of `_eval_between`, `_eval_regex`, `_eval_cross_field`, `_eval_date_math` based on the rule's `rule_complexity` field.

**(M5) Violation Validation, Explanation, and Reporting** — A second LLM pass (Llama-3.1-8B) classifies a sample of low-confidence violations as confirmed or false positive. A third LLM pass (Llama-3.3-70B) generates a narrative explanation, severity, policy clause, ordered remediation steps, and risk description for every rule that fired. The `violation_reporting_node` aggregates all of this into a single `violation_report` structure used downstream.

**(M6) Report Generation** — `src/stages/report_generator.py:680-705` writes both an A4 PDF (via ReportLab `Platypus`) and an interactive HTML file (CSS Grid layout, teal-and-cream palette, print-friendly `@media print` block). Both share a five-section template: cover, executive summary, rules summary table, rule-by-rule detail, appendix grouped by table.

**(M7) Real-Time Query Interceptor** — Runs the ten-node interceptor graph against an inbound SQL query: cache-check (3-layer: exact / fuzzy / semantic) → context-builder → intent-classifier → policy-mapper (Qdrant RAG) → verdict-reasoner (Llama-3.3-70B) → auditor (Llama-3.1-8B advisory check, with retry loop) → executor or block. Every decision is appended to the WORM SQLite audit log at `data/interceptor_audit.db`.

---

## 7. Expected Outcome and Deliverables

A successful run of `python run_hi_small.py` against the bundled IBM HI-Small AML dataset produces six concrete deliverables:

1. A populated `data/hi_small_violations.db` containing 11,775 rows in `violations_log` and 17 rows in `rule_explanations` (one per structured rule that fired).
2. An A4 PDF compliance report at `data/compliance_report_scan_<id>.pdf` (~0.4 MB).
3. An interactive HTML compliance report at `data/compliance_report_scan_<id>.html` (~0.9 MB).
4. A LangGraph checkpoint trail at `data/hi_small_checkpoints.db` allowing the run to be resumed from any node boundary.
5. A populated Qdrant `policy_rules` collection at `qdrant_db/` from which the interceptor draws context on subsequent runs.
6. A Rich-formatted console summary printed at the end of the run with counts, durations, and the score-and-grade tuple.

The corresponding interceptor demonstration (`python run_intercept.py`) produces a sequence of test scenarios — an analytics aggregation (APPROVE), a PII query with stated purpose (depends on policy), a vague `SELECT *` (CLARIFICATION_REQUIRED), a sensitive query touching SSN columns (BLOCK), and a cache-hit replay of the first scenario — each presented as a Rich-formatted verdict card.

---

## 8. Scope and Limitations

**In scope.** The system supports SQLite and PostgreSQL targets out of the box, English-language regulatory policies, the five `rule_type` categories listed under M1, and the four complex-rule families listed under M4. The interceptor's audit-bounded reasoning loop terminates within a small constant number of LLM calls in every case.

**Out of scope (in the current submission).** MongoDB / Snowflake / BigQuery / DynamoDB connectors; non-English regulatory text; online change-data-capture against a live database; an automated rule-pack marketplace; a Playwright/Cypress front-end test suite; deployment to a managed Kubernetes cluster.

**Operational dependencies.** A valid `GROQ_API_KEY`; a stable network connection to `api.groq.com`; optionally Redis for the document/embedding cache (degrades gracefully to an in-memory LRU when unreachable).

---

## 9. Project Timeline

The project was developed across three informal phases between early April 2026 and the date of submission:

- **Phase Initial (3-5 April 2026)** — project inception, refactoring of the directory structure, implementation of the SQLite and PostgreSQL connectors, and the first end-to-end smoke run on a synthetic policy.
- **Phase 1 (7-9 April 2026)** — interceptor mode, report generation, AuditLens front-end first cut, and the first set of demonstration runs producing the five HTML/PDF report pairs visible under `data/compliance_report_*.html` from the early-Feb timestamps.
- **Phase 0 (10-15 April 2026)** — *"stop the bleeding"*: the six security and lifecycle defects (commits `0ecd609`, `a7b7792`, `8361ba0`, `7fe13ee`, `4ee19d7`, `10b7f02`) were closed, each with a regression test in `tests/unit/`. The merge of pull request #2 (`703bb6a`) on 17 April 2026 marks the head of the current branch.

The naming convention — *Phase 0* coming *after* Phase 1 chronologically — was deliberate: it reflects the project's adoption of a *zero-defect-before-features* policy partway through the development cycle, in which all known security and lifecycle defects were declared blocking before any further user-visible work would proceed.

---

## 10. Synopsis Summary

The **Data Compliance Agent** is an end-to-end LLM-orchestrated system that automates the regulatory-compliance audit lifecycle. Three graphs (scanner, interceptor, unified router) compose nineteen distinct nodes over seven layers of shared infrastructure (state, memory, tools, prompts, middleware, nodes, graph). A canonical run on the IBM HI-Small AML dataset extracts 62 raw rules, structures 17, detects 11,775 violations in 246.6 seconds, and emits print-ready PDF and HTML compliance reports with zero in-state errors. Twenty-four unit tests, a graph-level smoke script, and a system-level driver script collectively cover every database connector, every cache layer, every middleware decorator, the keyset-pagination algorithm, the operator-alias normalisation, and the six recently-closed security defects.

The full project report follows in five chapters — Introduction (10 pp.), Design (8-10 pp.), Implementation (15-20 pp.), Testing (15-20 pp.), and Conclusion with Future Scope (4-5 pp.) — together with a fifty-two-entry IEEE-style references chapter.
