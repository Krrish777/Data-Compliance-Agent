# DATA COMPLIANCE AGENT

### An LLM-Orchestrated System for Automated Regulatory Rule Extraction, Database Violation Scanning, and Real-Time Query Enforcement

---

**A Project Report**

submitted in partial fulfilment of the requirements
for the award of the degree of

**Bachelor of Technology / Master of Computer Applications**

*(strike through whichever does not apply)*

in

**Computer Science and Engineering**

---

**Submitted by**

**Krrish &lt;Surname&gt;**
Roll No. _________________

**Under the Guidance of**

**Prof. ______________**
Department of Computer Science and Engineering

---

**&lt;Name of Department&gt;**
**&lt;Name of College / University&gt;**
**&lt;City, State – PIN&gt;**

**April 2026**

---

\pagebreak

## Certificate

This is to certify that the project report entitled **"Data Compliance Agent: An LLM-Orchestrated System for Automated Regulatory Rule Extraction, Database Violation Scanning, and Real-Time Query Enforcement"** submitted by **Krrish &lt;Surname&gt;** (Roll No. ________) in partial fulfilment of the requirements for the award of the degree of **Bachelor of Technology / Master of Computer Applications** in **Computer Science and Engineering** is a bonafide record of work carried out by the candidate under my supervision and guidance.

The contents of this report, in full or in part, have not been submitted to any other institution or university for the award of any degree or diploma.

Place: ____________________
Date: 18 April 2026

\
\
\

| Project Guide | Head of Department |
|---|---|
| Prof. ____________________ | Prof. ____________________ |
| Department of CSE | Department of CSE |

External Examiner

____________________________________

\pagebreak

## Candidate's Declaration

I hereby declare that the project report entitled **"Data Compliance Agent: An LLM-Orchestrated System for Automated Regulatory Rule Extraction, Database Violation Scanning, and Real-Time Query Enforcement"** is the result of my own work carried out at &lt;Name of College&gt;, under the supervision of Prof. ____________________.

I further declare that to the best of my knowledge, this report does not contain any part of any work that has been submitted for the award of any degree at any other university or institution. All sources used and consulted have been duly acknowledged in the references section.

Place: ____________________
Date: 18 April 2026

\
\

____________________________________

(Krrish &lt;Surname&gt;)

Roll No. ________________

\pagebreak

## Acknowledgement

I take this opportunity to express my profound gratitude and deep regard to my project guide **Prof. ____________________**, Department of Computer Science and Engineering, for their exemplary guidance, monitoring, and constant encouragement throughout the course of this project. Their valuable suggestions, critical feedback, and willingness to engage with the technical depth of an experimental Large Language Model–driven system shaped the direction of this work.

I would also like to thank the **Head of the Department**, **Prof. ____________________**, for providing the laboratory infrastructure and computational resources necessary to develop and test the system end-to-end, and for fostering an academic environment in which independent project work is taken seriously.

I extend my thanks to the faculty and the technical staff of the department for their assistance during the various stages of design, implementation, and evaluation. I am grateful to my classmates for spirited discussions on agent orchestration, vector databases, and LangGraph that contributed many small refinements to the final architecture.

Finally, I would like to thank my family for their unconditional support and encouragement, without which this work would not have been possible.

Krrish &lt;Surname&gt;

\pagebreak

## Abstract

Modern enterprises operate under an ever-expanding burden of data-protection regulations — the European Union's General Data Protection Regulation (GDPR), the United States' Health Insurance Portability and Accountability Act (HIPAA), India's Digital Personal Data Protection Act 2023, the Reserve Bank of India's Anti-Money-Laundering (AML) directives, and many sector-specific frameworks. Manual auditing of databases against the natural-language rules embedded in these documents is slow, error-prone, and does not scale to the volumes of structured data that modern organisations hold.

This project presents the **Data Compliance Agent**, an end-to-end software system that automates the regulatory-compliance audit lifecycle through Large Language Model (LLM) orchestration. The system ingests a regulatory PDF, extracts machine-actionable rules using Retrieval-Augmented Generation (RAG), maps each rule to concrete database columns, scans target SQLite or PostgreSQL databases using memory-efficient *keyset* pagination, validates detected violations through a second LLM pass to suppress false positives, generates natural-language explanations and remediation steps, and emits a print-ready PDF and an interactive HTML compliance report. A second sub-system — the **interceptor graph** — operates in real time: it sits in front of any analyst-issued SQL query and either approves, rewrites, or blocks it on the basis of the same extracted rule corpus, pre-empting violations before they happen. A unified router dispatches inbound requests to whichever sub-system matches the operating mode.

The implementation is built on the LangGraph orchestration framework with Groq-hosted Llama-3.3-70B and Llama-3.1-8B models, the Qdrant vector database, the BAAI/bge-small-en-v1.5 embedding model, and a layered Python codebase comprising 66 source modules. A representative end-to-end run on the IBM HI-Small Anti-Money-Laundering transaction dataset extracted 62 raw rules, structured 17 of them with confidence ≥ 0.7, and detected 11,775 violations across 17 tables in 246.6 seconds, producing a paginated compliance report with a measured score of 58.8 % (Grade D) — values that an external auditor can reproduce by running the supplied `run_hi_small.py` driver script.

The report documents the complete lifecycle of the project: motivation, system architecture, design diagrams, implementation walkthrough, layered testing strategy, observed results, and avenues for future extension including support for MongoDB and Snowflake, fine-tuned Legal-domain language models, and integration with security-information-and-event-management (SIEM) pipelines.

\pagebreak

## Table of Contents

| Chapter | Title | Page |
|---|---|---|
|  | Certificate | i |
|  | Candidate's Declaration | ii |
|  | Acknowledgement | iii |
|  | Abstract | iv |
|  | Table of Contents | v |
|  | List of Figures | vii |
|  | List of Tables | viii |
|  | List of Abbreviations | ix |
|  | **Synopsis** | 1 |
| 1 | **Introduction** | 9 |
| 1.1 | About the Project | 9 |
| 1.2 | Existing Problem | 11 |
| 1.3 | Objectives | 13 |
| 1.4 | Proposed System Architecture | 14 |
| 1.5 | Software Specification | 17 |
| 1.6 | Hardware Specification | 18 |
| 2 | **Design** | 19 |
| 2.1 | Block Diagram | 19 |
| 2.2 | Entity-Relationship Diagram | 21 |
| 2.3 | Data Flow Diagram | 23 |
| 2.4 | Use Case Diagram | 25 |
| 2.5 | Activity Diagram | 26 |
| 2.6 | Sequence Diagrams | 27 |
| 3 | **Implementation** | 29 |
| 3.1 | Project Layout | 29 |
| 3.2 | The State Contract | 30 |
| 3.3 | The Three Graphs | 33 |
| 3.4 | Node Implementations | 36 |
| 3.5 | Stages — The Algorithmic Core | 40 |
| 3.6 | Database Tooling | 42 |
| 3.7 | Vector Store and Retrieval-Augmented Generation | 44 |
| 3.8 | Caching and Resilience | 45 |
| 3.9 | Memory Layer | 46 |
| 3.10 | LLM Model Pinning | 47 |
| 3.11 | Human-in-the-Loop Checkpoint | 47 |
| 3.12 | Configuration, Front-end and Deployment | 48 |
| 4 | **Testing** | 49 |
| 4.1 | Testing Strategy | 49 |
| 4.2 | Unit Testing | 50 |
| 4.3 | Integration Testing | 56 |
| 4.4 | System Testing | 58 |
| 4.5 | Performance Testing | 62 |
| 4.6 | Security and Compliance Testing | 64 |
| 4.7 | Test Results Summary | 66 |
| 5 | **Conclusion and Future Scope** | 68 |
| 5.1 | Summary of Work Done | 68 |
| 5.2 | Key Contributions | 69 |
| 5.3 | Limitations | 70 |
| 5.4 | Future Scope | 70 |
| 5.5 | Closing Remarks | 72 |
| 6 | **References** | 73 |

\pagebreak

## List of Figures

| Fig. No. | Title | Page |
|---|---|---|
| 2.1 | High-level block diagram of the Data Compliance Agent | 19 |
| 2.2 | Entity-Relationship diagram for the violations and explanations stores | 21 |
| 2.3 | Level-0 Data Flow Diagram (context) | 23 |
| 2.4 | Level-1 Data Flow Diagram (scanner pipeline) | 24 |
| 2.5 | Level-1 Data Flow Diagram (interceptor pipeline) | 24 |
| 2.6 | Use case diagram | 25 |
| 2.7 | Activity diagram of the scanner pipeline | 26 |
| 2.8 | Sequence diagram — scanner end-to-end | 27 |
| 2.9 | Sequence diagram — interceptor with retry loop | 28 |
| 4.1 | Test pyramid adopted in the project | 49 |
| 4.2 | Sample compliance-report HTML rendered in a browser | 60 |
| 4.3 | Keyset vs. OFFSET pagination latency curve | 62 |

## List of Tables

| Tab. No. | Title | Page |
|---|---|---|
| 1.1 | Software stack | 17 |
| 1.2 | Hardware specification | 18 |
| 3.1 | `ComplianceScannerState` field reference | 31 |
| 3.2 | `InterceptorState` field reference | 32 |
| 3.3 | Scanner graph nodes and edges | 34 |
| 3.4 | Interceptor graph nodes and routing conditions | 35 |
| 3.5 | LLM model assignment per node | 47 |
| 3.6 | Key cache TTLs and constants | 45 |
| 4.1 | Unit-test inventory | 51 |
| 4.2 | End-to-end run metrics on the HI-Small AML dataset | 59 |
| 4.3 | Operator alias coverage in the query builder | 53 |
| 6.1 | References by category | 73 |

## List of Abbreviations

| Acronym | Expansion |
|---|---|
| AML | Anti-Money Laundering |
| API | Application Programming Interface |
| CDC | Change Data Capture |
| CRUD | Create, Read, Update, Delete |
| CSV | Comma-Separated Values |
| DAG | Directed Acyclic Graph |
| DDL | Data Definition Language |
| DFD | Data Flow Diagram |
| DPDP | Digital Personal Data Protection (Act, 2023) |
| ERD | Entity-Relationship Diagram |
| GDPR | General Data Protection Regulation |
| HIPAA | Health Insurance Portability and Accountability Act |
| HITL | Human-in-the-Loop |
| HTML | HyperText Markup Language |
| JSON | JavaScript Object Notation |
| KYC | Know Your Customer |
| LLM | Large Language Model |
| LRU | Least Recently Used |
| NLP | Natural Language Processing |
| ORM | Object-Relational Mapper |
| OWASP | Open Web Application Security Project |
| PDF | Portable Document Format |
| PII | Personally Identifiable Information |
| RAG | Retrieval-Augmented Generation |
| RBI | Reserve Bank of India |
| ReAct | Reasoning + Acting (prompting paradigm) |
| RFC | Request for Comments |
| SBERT | Sentence-BERT |
| SDK | Software Development Kit |
| SIEM | Security Information and Event Management |
| SQL | Structured Query Language |
| TTL | Time To Live |
| UI | User Interface |
| UTC | Coordinated Universal Time |
| WORM | Write Once Read Many |

\pagebreak
