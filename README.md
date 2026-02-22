<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.13-3776AB?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-0.7.50-1C3C3C?logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-15-000000?logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/LLM-Groq%20Llama3-F55036?logo=meta&logoColor=white" />
  <img src="https://img.shields.io/badge/license-MIT-green" />
</p>

# 🛡️ Data Compliance Agent

An **AI-powered compliance scanning and enforcement platform** built on [LangGraph](https://github.com/langchain-ai/langgraph). It reads regulatory policy documents, extracts enforceable rules, scans databases for violations, and generates audit-ready reports — all orchestrated through a multi-node agent pipeline with human-in-the-loop review.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Scanner Pipeline](#scanner-pipeline)
- [Interceptor Pipeline](#interceptor-pipeline)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Frontend](#frontend)
- [Configuration](#configuration)
- [Testing](#testing)
- [Design Principles](#design-principles)
- [License](#license)

---

## Features

| Capability | Description |
|---|---|
| **PDF Policy Extraction** | LLM reads compliance policy PDFs and extracts structured rules with confidence scoring |
| **Automated Schema Discovery** | Connects to SQLite or PostgreSQL, discovers tables, columns, PKs, and identifies PII columns via semantic similarity |
| **Intelligent Rule Mapping** | Maps extracted rules to database columns with operator normalization (40+ SQL operator aliases) |
| **Human-in-the-Loop** | Low-confidence rules are routed to human review via LangGraph `interrupt()` before scanning |
| **Keyset-Paginated Scanning** | Efficient cursor-based database scanning — no OFFSET bottlenecks on large tables |
| **Complex Rule Execution** | Handles BETWEEN, REGEX, cross-field, and date-math rules via Python-side evaluation |
| **False-Positive Reduction** | LLM-powered violation validator classifies violations as confirmed or false positive |
| **Explanation Generation** | LLM generates natural-language explanations, remediation steps, and severity ratings per rule |
| **Dual Report Formats** | Professional PDF (ReportLab) and HTML audit reports with compliance scoring and grading |
| **Real-Time Interceptor** | Intercepts SQL queries pre-execution with APPROVE/BLOCK decisions, caching, and escalation |
| **Custom Dashboard** | Purpose-built Next.js frontend with scanner controls, live progress, charts, and report export |
| **Multi-Layer Caching** | Redis + in-memory LRU caching for documents, embeddings, and vector DB lookups |
| **Checkpoint & Recovery** | LangGraph checkpointer (memory / SQLite / PostgreSQL) for crash recovery and session persistence |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                        │
│  Landing Page → Scanner → Dashboard → Report Export (PDF/HTML)   │
│                    Interceptor Mode (SQL Query)                  │
└──────────────────────┬───────────────────────────────────────────┘
                       │  REST / SSE
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                   LangGraph Dev Server (:2024)                   │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────────────────┐ │
│  │ Scanner Graph │  │ Interceptor   │  │ Unified Router Graph  │ │
│  │  (11 nodes)   │  │  Graph        │  │  (mode → scanner |   │ │
│  │               │  │  (9 nodes)    │  │   interceptor)       │ │
│  └──────┬───────┘  └──────┬────────┘  └───────────────────────┘ │
│         │                  │                                     │
│  ┌──────┴──────────────────┴─────────────────────────────┐      │
│  │  Middleware: Guardrails │ Retry │ Logging │ Rate-Limit │      │
│  └──────┬──────────────────┬─────────────────────────────┘      │
│         │                  │                                     │
│  ┌──────┴──────┐    ┌──────┴──────┐                             │
│  │  Memory     │    │   Tools     │                             │
│  │ Checkpointer│    │ PDF Reader  │                             │
│  │ Store       │    │ DB Connectors│                            │
│  └─────────────┘    │ Query Builder│                            │
│                     │ Violations DB│                            │
│                     └──────────────┘                            │
└──────────────────────────────────────────────────────────────────┘
         │                    │                     │
    ┌────┴────┐         ┌────┴────┐           ┌────┴────┐
    │  Groq   │         │ SQLite/ │           │ Qdrant  │
    │  LLM    │         │PostgreSQL│          │VectorDB │
    │ Llama3  │         │(Target) │           │ (Local) │
    └─────────┘         └─────────┘           └─────────┘
```

---

## Scanner Pipeline

The primary compliance scanning workflow is a **9-stage LangGraph state graph** with conditional routing:

![Scanner Pipeline](data/Screenshot%202026-02-22%20105730.png)

### Pipeline State

The scanner pipeline operates on a single `ComplianceScannerState` TypedDict contract shared by all nodes:

| Stage | State Keys |
|---|---|
| Entry | `document_path`, `db_config`, `db_type` |
| Rule Extraction | `raw_rules: List[ComplianceRuleModel]` |
| Schema Discovery | `schema_metadata: Dict[str, Dict]` |
| Rule Structuring | `structured_rules`, `low_confidence_rules` |
| Human Review | `review_decision: {approved, edited, dropped}` |
| Data Scanning | `scan_id`, `violations_db_path`, `scan_summary` |
| Validation | `validation_summary` |
| Explanation | `rule_explanations` |
| Reporting | `violation_report`, `report_paths: {pdf, html}` |
| Cross-cutting | `current_stage`, `errors: List[str]` |

---

## Interceptor Pipeline

A **real-time SQL query enforcement** mode that intercepts queries before execution:

```
START → cache_check
          ├── HIT  → return_cached → END
          └── MISS → context_builder → intent_classifier
                       ├── VAGUE  → return_clarification → END
                       └── CLEAR  → policy_mapper
                                     ├── UNCERTAIN → escalate_human → END
                                     └── CONFIDENT → verdict_reasoner → auditor
                                                       ├── PASS → executor → END
                                                       ├── FAIL (retry) → verdict_reasoner
                                                       └── FAIL (exhausted) → escalate_human → END
```

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Agent Framework | [LangGraph](https://github.com/langchain-ai/langgraph) v0.7.50 |
| LLM Provider | [Groq](https://groq.com/) — `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` |
| LLM SDK | [LangChain](https://python.langchain.com/) + `langchain-groq` |
| Data Models | [Pydantic](https://pydantic-docs.helpmanual.io/) v2 |
| Database ORM | [SQLModel](https://sqlmodel.tiangolo.com/) |
| PDF Processing | [PyMuPDF](https://pymupdf.readthedocs.io/) |
| Embeddings | [FastEmbed](https://github.com/qdrant/fastembed) (`BAAI/bge-small-en-v1.5`) + [Sentence Transformers](https://www.sbert.net/) (`all-MiniLM-L6-v2`) |
| Vector Database | [Qdrant](https://qdrant.tech/) (local mode) |
| Report Generation | [ReportLab](https://www.reportlab.com/) (PDF) + custom HTML |
| Caching | [Redis](https://redis.io/) + in-memory LRU fallback |
| Logging | [Rich](https://rich.readthedocs.io/) console + rotating file handler |

### Frontend

| Component | Technology |
|---|---|
| Framework | [Next.js](https://nextjs.org/) 15 (App Router) |
| UI Library | [React](https://react.dev/) 19 |
| Language | TypeScript |
| Styling | [Tailwind CSS](https://tailwindcss.com/) v4 + [shadcn/ui](https://ui.shadcn.com/) |
| Charts | [Recharts](https://recharts.org/) |
| Animations | [Framer Motion](https://www.framer.com/motion/) |
| LangGraph Client | `@langchain/langgraph-sdk` |
| Math Rendering | [KaTeX](https://katex.org/) |

---

## Project Structure

```
data-compliance-agent/
│
├── src/
│   ├── agents/
│   │   ├── graph.py                  # Scanner pipeline graph builder (11 nodes)
│   │   ├── state.py                  # ComplianceScannerState TypedDict
│   │   ├── interceptor_graph.py      # Interceptor pipeline graph
│   │   ├── interceptor_state.py      # Interceptor state schema
│   │   ├── unified_graph.py          # Unified router (scanner | interceptor)
│   │   │
│   │   ├── nodes/                    # Scanner pipeline nodes
│   │   │   ├── rule_extraction.py    # LLM — PDF → ComplianceRuleModel
│   │   │   ├── schema_discovery.py   # Deterministic — DB schema discovery
│   │   │   ├── data_scanning.py      # Deterministic — violation scanning
│   │   │   ├── violation_validator.py# LLM — false-positive reduction
│   │   │   ├── explanation_generator.py # LLM — explanations & remediation
│   │   │   ├── violation_reporting.py# Deterministic — report aggregation
│   │   │   └── report_generation.py  # Deterministic — PDF + HTML output
│   │   │
│   │   ├── interceptor_nodes/        # Interceptor pipeline nodes
│   │   ├── prompts/                  # LLM prompt templates
│   │   ├── middleware/               # Guardrails, retry, logging decorators
│   │   ├── memory/                   # Checkpointer + long-term store
│   │   ├── runtime/                  # Config, rate limiter
│   │   ├── streaming/               # Callbacks, progress tracking
│   │   └── tools/
│   │       ├── pdf_reader.py         # LangChain @tool for PDF processing
│   │       └── database/
│   │           ├── baseconnector.py  # ABC with PII detection
│   │           ├── sqlite_connector.py
│   │           ├── postgres_connector.py
│   │           ├── query_builder.py  # Keyset pagination
│   │           ├── query_executor.py
│   │           ├── complex_executor.py # BETWEEN, REGEX, date-math rules
│   │           └── violations_store.py # Violations log read/write
│   │
│   ├── docs_processing/
│   │   └── docs_processor.py         # PDF → DocumentChunk pipeline
│   │
│   ├── embedding/
│   │   └── embedding.py              # FastEmbed embeddings
│   │
│   ├── vector_database/
│   │   └── qdrant_vectordb.py        # Local Qdrant store
│   │
│   ├── models/
│   │   ├── compilance_rules.py       # ComplianceRuleModel (Pydantic)
│   │   ├── structured_rule.py        # StructuredRule (dataclass)
│   │   └── interceptor_models.py     # Interceptor data models
│   │
│   ├── stages/                       # Business logic (called by nodes)
│   │   ├── data_scanning.py          # Keyset-paginated scan engine
│   │   ├── report_generator.py       # PDF + HTML report builder
│   │   └── rule_structuring.py       # Rule conversion utilities
│   │
│   └── utils/
│       ├── logger.py                 # Rich logging + rotating files
│       ├── cache.py                  # Schema cache (TTL-based)
│       └── document_cache.py         # Redis + memory cache manager
│
├── agent-chat-ui/                    # Next.js frontend
│   └── src/
│       ├── app/                      # Next.js App Router
│       │   └── api/                  # Proxy routes + report serving
│       ├── components/
│       │   ├── landing/              # Landing page
│       │   ├── scanner/              # Scanner controls + progress panel
│       │   ├── dashboard/            # Metrics cards, charts, violations table
│       │   ├── interceptor/          # Query interceptor UI + verdict cards
│       │   ├── chat/                 # Chat thread components
│       │   └── ui/                   # shadcn/ui primitives
│       ├── hooks/                    # File upload, media queries
│       ├── providers/                # LangGraph SDK client, streaming
│       └── stores/                   # Zustand compliance store
│
├── data/                             # Sample databases, generated reports
├── scripts/                          # Utility scripts (PDF generation)
├── notebooks/                        # Jupyter prototyping notebooks
├── tests/
│   ├── unit/                         # pytest unit tests
│   ├── integration/
│   └── system/
│
├── langgraph.json                    # LangGraph server configuration
├── pyproject.toml                    # Python project metadata
├── main.py                           # Quick demo entry point
├── run_scan.py                       # CLI scanner
└── run_hi_small.py                   # Full pipeline runner
```

---

## Getting Started

### Prerequisites

- **Python** ≥ 3.13
- **Node.js** ≥ 18 + **pnpm**
- **Redis** (optional — falls back to in-memory cache)
- **Groq API key** ([get one free](https://console.groq.com/keys))

### 1. Clone & Install Backend

```bash
git clone <repo-url> data-compliance-agent
cd data-compliance-agent

# Create virtual environment (using uv or venv)
uv venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\Activate.ps1       # Windows PowerShell

# Install dependencies
uv pip install -e .
```

### 2. Environment Variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=gsk_your_groq_api_key_here
```

### 3. Install Frontend

```bash
cd agent-chat-ui
pnpm install
```

Create `agent-chat-ui/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:2024
```

### 4. Start Services

**Terminal 1 — LangGraph Server:**

```bash
langgraph dev
```

**Terminal 2 — Frontend:**

```bash
cd agent-chat-ui
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Usage

### Full Pipeline (CLI)

Run an end-to-end compliance scan against a database:

```bash
python run_hi_small.py
```

This executes all 9 stages: PDF extraction → schema discovery → rule structuring → human review → scanning → validation → explanation → reporting → PDF/HTML generation.

### Scan Only (CLI)

Run just the scanning stage against a target database:

```bash
uv run python run_scan.py --db data/HI-Small_Trans.db
```

### Web UI

1. Navigate to [http://localhost:3000](http://localhost:3000)
2. Select **Scanner Mode** from the landing page
3. Choose or upload a compliance policy PDF
4. Select the target database
5. Monitor real-time scan progress
6. View the compliance dashboard with charts and violation details
7. Export reports as **PDF** or **HTML**

### LangGraph Studio

The graph is registered in `langgraph.json` and is compatible with [LangGraph Studio](https://github.com/langchain-ai/langgraph-studio) for visual debugging and step-through execution.

---

## Frontend

The frontend is a purpose-built compliance interface built on top of the [agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) template:

| View | Description |
|---|---|
| **Landing Page** | Mode selection — Scanner or Interceptor |
| **Scanner View** | Policy PDF selection/upload, database picker, scan trigger |
| **Progress Panel** | Real-time stage progress with animated transitions |
| **Dashboard** | Compliance score gauge, rule-type breakdown chart, violations-by-table chart, violations data table |
| **Report Export** | One-click PDF or HTML report download |
| **Interceptor View** | SQL query input with real-time APPROVE/BLOCK verdict cards |

---

## Configuration

### LangGraph Server

```json
// langgraph.json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./src/agents/graph.py:agent"
  },
  "env": ".env"
}
```

### Scan Parameters

Configurable via state input or defaults:

| Parameter | Default | Description |
|---|---|---|
| `batch_size` | 1000 | Rows per keyset pagination page |
| `max_batches_per_table` | None | Safety cap on pages per table |
| `db_type` | `"sqlite"` | Target database type (`sqlite` or `postgresql`) |

### LLM Models

| Node | Model | Rationale |
|---|---|---|
| Rule Extraction | `llama-3.3-70b-versatile` | High accuracy for document comprehension |
| Violation Validator | `llama-3.1-8b-instant` | Fast + cheap for binary classification |
| Explanation Generator | `llama-3.3-70b-versatile` | Quality synthesis for remediation text |

### Checkpointer Backends

| Backend | Use Case |
|---|---|
| `memory` | Tests and notebooks |
| `sqlite` | Local development |
| `postgres` | Production deployment |

---

## Testing

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test module
pytest tests/unit/test_data_scanning.py -v

# Run with markers
pytest tests/unit/ -m "not slow" -v
```

### Test Coverage

| Module | Tests |
|---|---|
| Data Scanning | `test_data_scanning.py` |
| Document Cache | `test_document_cache.py` |
| SQLite Connector | `test_sqlite_connector.py` |
| PostgreSQL Connector | `test_postgres_connector.py` |
| Query Builder | `test_query_builder.py` |

---

## Design Principles

1. **State as Contract** — A single `TypedDict` defines the interface between all nodes; designed upfront, flat, with `Annotated[list, operator.add]` for safe accumulation across nodes.

2. **Separation of Concerns** — State, memory, tools, middleware, prompts, streaming, runtime, and nodes each get their own module with clear boundaries.

3. **Dual-Layer Memory** — *Checkpointer* for short-term per-thread state (crash recovery, `interrupt()`) + *Store* for long-term cross-thread learning (rule patterns, user corrections).

4. **Middleware as Decorators** — Retry with exponential backoff, input/output guardrails, and execution logging are applied as composable decorators on node functions.

5. **Human-in-the-Loop** — Low-confidence rules trigger `interrupt()` with structured resume payloads (`{approved, edited, dropped}`) — no blind automation.

6. **External Violation Storage** — Violations are persisted to a dedicated SQLite database, not the LangGraph state, keeping the state small and the audit trail queryable.

7. **Keyset Pagination** — Cursor-based scanning instead of `OFFSET` for consistent performance on tables with millions of rows.

8. **Complex Rule Execution** — Rules that can't be expressed as SQL `WHERE` clauses (BETWEEN, REGEX, cross-field comparisons, date math) are evaluated via a dedicated Python-side executor.

9. **Graceful Degradation** — Multi-layer caching (Redis → in-memory), multiple checkpointer backends, and robust fallback chains ensure the system works in constrained environments.

---

## License

MIT
