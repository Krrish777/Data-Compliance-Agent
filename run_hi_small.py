"""
End-to-end compliance scan of HI-Small_Trans.db
================================================

Steps executed (all printed):
  1.  Generate AML policy PDF
  2.  Build the LangGraph pipeline
  3.  Run rule_extraction (LLM reads PDF chunks → ComplianceRuleModel list)
  4.  Run schema_discovery (connect to DB, emit schema)
  5.  Run rule_structuring (map raw rules → StructuredRule, split by confidence)
  6.  Run data_scanning   (keyset-paginated scan, log violations)
  7.  Run violation_reporting (aggregate report)
  8.  Print final report

Usage:
    python run_hi_small.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.rule import Rule # noqa: E402
from rich.table import Table  # noqa: E402
console = Console()

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH       = str(ROOT / "data" / "HI-Small_Trans.db")
POLICY_PDF    = str(ROOT / "data" / "AML_Compliance_Policy.pdf")
VIOLATIONS_DB = str(ROOT / "data" / "hi_small_violations.db")
CHECKPOINT_DB = str(ROOT / "data" / "hi_small_checkpoints.db")


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def step(n: int, title: str) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]Step {n}: {title}[/bold cyan]", style="cyan"))

def ok(msg: str) -> None:
    console.print(f"  [bold green]✔[/bold green]  {msg}")

def info(msg: str) -> None:
    console.print(f"  [dim]ℹ[/dim]  {msg}")

def warn(msg: str) -> None:
    console.print(f"  [bold yellow]⚠[/bold yellow]  {msg}")

def err(msg: str) -> None:
    console.print(f"  [bold red]✘[/bold red]  {msg}")

def elapsed(t0: float) -> str:
    return f"{(time.perf_counter() - t0)*1000:.0f} ms"


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Generate PDF
# ═══════════════════════════════════════════════════════════════════════════════

def step1_generate_pdf() -> str:
    step(1, "Generate AML Compliance Policy PDF")
    from scripts.generate_policy_pdf import build_pdf

    t0 = time.perf_counter()
    path = build_pdf(POLICY_PDF)
    size_kb = Path(path).stat().st_size // 1024
    ok(f"PDF written → {path}  ({size_kb} KB, {elapsed(t0)})")
    return path


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Build graph
# ═══════════════════════════════════════════════════════════════════════════════

def step2_build_graph():
    step(2, "Build LangGraph compliance pipeline")

    from src.agents.graph import build_graph
    from src.agents.memory import get_checkpointer

    t0 = time.perf_counter()
    # We'll use the context manager, but return both for later use
    graph_obj   = {"graph": None, "cp_ctx": None}  # noqa: E402, F841

    cp_ctx = get_checkpointer("sqlite", db_path=CHECKPOINT_DB)
    cp = cp_ctx.__enter__()
    graph = build_graph(checkpointer=cp)

    node_names = [n for n in graph.nodes if not n.startswith("__")]
    ok(f"Pipeline compiled ({elapsed(t0)})")
    info(f"Nodes: {node_names}")

    return graph, cp, cp_ctx


# ═══════════════════════════════════════════════════════════════════════════════
#  Individual node runner (verbose)
# ═══════════════════════════════════════════════════════════════════════════════

def run_node(node_fn, state: dict, node_name: str) -> dict:
    """Run a single node function, print inputs/outputs, merge results."""
    input_keys = [k for k, v in state.items() if v is not None and v != [] and v != {}]
    info(f"Input keys: {input_keys}")
    t0 = time.perf_counter()
    try:
        result = node_fn(state)
        ms = elapsed(t0)
        if isinstance(result, dict):
            for k, v in result.items():
                if isinstance(v, list):
                    info(f"  → {k}: {len(v)} items")
                elif isinstance(v, dict):
                    info(f"  → {k}: dict with {len(v)} keys")
                else:
                    info(f"  → {k}: {str(v)[:120]}")
        ok(f"{node_name} finished ({ms})")
        state = {**state, **result}
        return state
    except Exception as e:
        err(f"{node_name} raised: {e}")
        traceback.print_exc()
        raise


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — Rule extraction (LLM)
# ═══════════════════════════════════════════════════════════════════════════════

def step3_rule_extraction(state: dict) -> dict:
    step(3, "Rule Extraction (LLM reads PDF → ComplianceRuleModel objects)")
    from src.agents.nodes.rule_extraction import rule_extraction_node
    info(f"PDF: {state['document_path']}")
    state = run_node(rule_extraction_node, state, "rule_extraction_node")

    raw_rules = state.get("raw_rules", [])
    if raw_rules:
        console.print()
        t = Table("rule_id", "rule_type", "confidence", "rule_text", title="Extracted Rules")
        for r in raw_rules[:25]:
            rid   = r.rule_id   if hasattr(r, "rule_id")   else r.get("rule_id", "")
            rtype = r.rule_type if hasattr(r, "rule_type") else r.get("rule_type", "")
            conf  = r.confidence if hasattr(r, "confidence") else r.get("confidence", 0)
            text  = r.rule_text if hasattr(r, "rule_text") else r.get("rule_text", "")
            t.add_row(rid, rtype, f"{conf:.2f}", str(text)[:90])
        if len(raw_rules) > 25:
            t.add_row("...", "...", "...", f"... and {len(raw_rules)-25} more")
        console.print(t)
    else:
        warn("No rules extracted by LLM — falling back to hand-crafted rules")

    # ── Fallback / supplement with known-good rules for this dataset ──────────
    from src.models.compilance_rules import ComplianceRuleModel, RuleLogic

    KNOWN_RULES = [
        ComplianceRuleModel(
            rule_id="LAUN-001", rule_type="data_privacy",
            rule_text="All transactions where Is Laundering equals '1' must be flagged for SAR filing.",
            condition="Is Laundering field equals 1",
            action="Flag for SAR filing",
            scope="transactions table",
            confidence=1.0,
            source_reference="Section 6",
            logic=RuleLogic(field="Is Laundering", operator="=", value="1"),
        ),
        ComplianceRuleModel(
            rule_id="AMT-001", rule_type="data_quality",
            rule_text="Any transaction where Amount Paid exceeds 10000 must be flagged for CTR review.",
            condition="Amount Paid > 10000",
            action="Flag for CTR review",
            scope="transactions table",
            confidence=1.0,
            source_reference="Section 4",
            logic=RuleLogic(field="Amount Paid", operator=">", value="10000"),
        ),
        ComplianceRuleModel(
            rule_id="AMT-002", rule_type="data_quality",
            rule_text="Any transaction where Amount Received exceeds 10000 must be flagged.",
            confidence=1.0,
            source_reference="Section 4",
            logic=RuleLogic(field="Amount Received", operator=">", value="10000"),
        ),
        ComplianceRuleModel(
            rule_id="AMT-003", rule_type="data_quality",
            rule_text="Micro-transactions where Amount Paid is less than 1.00 must be flagged.",
            confidence=1.0,
            source_reference="Section 4",
            logic=RuleLogic(field="Amount Paid", operator="<", value="1.0"),
        ),
        ComplianceRuleModel(
            rule_id="AMT-004", rule_type="data_quality",
            rule_text="Transactions where Amount Paid exceeds 1,000,000 require enhanced due diligence.",
            confidence=1.0,
            source_reference="Section 4",
            logic=RuleLogic(field="Amount Paid", operator=">", value="1000000"),
        ),
        ComplianceRuleModel(
            rule_id="FMT-002", rule_type="data_security",
            rule_text="Transactions using Bitcoin as Payment Format shall be flagged for enhanced due diligence.",
            confidence=1.0,
            source_reference="Section 5",
            logic=RuleLogic(field="Payment Format", operator="=", value="Bitcoin"),
        ),
        ComplianceRuleModel(
            rule_id="FMT-001", rule_type="data_quality",
            rule_text="Payment Format field must not be NULL or empty.",
            confidence=1.0,
            source_reference="Section 5",
            logic=RuleLogic(field="Payment Format", operator="IS NOT NULL", value=""),
        ),
        ComplianceRuleModel(
            rule_id="RET-001", rule_type="data_retention",
            rule_text="Timestamp must not be NULL for any transaction record.",
            confidence=1.0,
            source_reference="Section 3",
            logic=RuleLogic(field="Timestamp", operator="IS NOT NULL", value=""),
        ),
    ]

    # Merge: keep LLM rules, add known rules that aren't duplicated
    existing_ids = {
        (r.rule_id if hasattr(r, "rule_id") else r.get("rule_id", ""))
        for r in raw_rules
    }
    added = 0
    for kr in KNOWN_RULES:
        if kr.rule_id not in existing_ids:
            raw_rules.append(kr)
            added += 1

    state["raw_rules"] = raw_rules
    if added:
        ok(f"Supplemented with {added} hand-crafted known-good rules")
    ok(f"Total rules for structuring: {len(raw_rules)}")
    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — Schema discovery
# ═══════════════════════════════════════════════════════════════════════════════

def step4_schema_discovery(state: dict) -> dict:
    step(4, "Schema Discovery (connect to DB, read table structures)")
    from src.agents.nodes.schema_discovery import schema_discovery_node
    state = run_node(schema_discovery_node, state, "schema_discovery_node")

    schema = state.get("schema_metadata", {})
    for tbl, info_d in schema.items():
        pk   = info_d.get("primary_key", "None")
        rows = info_d.get("row_count", 0)
        cols = [c["column_name"] for c in info_d.get("columns", [])]
        info(f"  Table '{tbl}': {rows} rows, PK='{pk}', columns={cols}")

    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 5 — Rule structuring
# ═══════════════════════════════════════════════════════════════════════════════

def step5_rule_structuring(state: dict) -> dict:
    step(5, "Rule Structuring (map raw rules → StructuredRule with DB columns)")
    from src.agents.graph import rule_structuring_node
    state = run_node(rule_structuring_node, state, "rule_structuring_node")

    structured = state.get("structured_rules", [])
    low_conf   = state.get("low_confidence_rules", [])

    console.print()
    t = Table("rule_id", "target_column", "operator", "value", "confidence", "tables",
              title=f"Structured Rules (high confidence: {len(structured)})")
    for r in structured:
        tbl_str = str(r.applies_to_tables or [])[:40]
        t.add_row(r.rule_id, r.target_column, r.operator, str(r.value or ""), f"{r.confidence:.2f}", tbl_str)
    console.print(t)

    if low_conf:
        info(f"Low-confidence rules (will be auto-approved by stub): {len(low_conf)}")
        for r in low_conf:
            info(f"  [{r.confidence:.2f}] {r.rule_id}: {r.target_column} {r.operator} {r.value}")

    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 5b — Human review (stub — auto-approve)
# ═══════════════════════════════════════════════════════════════════════════════

def step5b_human_review(state: dict) -> dict:
    low_conf = state.get("low_confidence_rules", [])
    if not low_conf:
        info("No low-confidence rules → human_review node skipped")
        return state

    step("5b", "Human Review (stub: auto-approving low-confidence rules)") # type: ignore
    from src.agents.graph import human_review_node
    state = run_node(human_review_node, state, "human_review_node")
    ok(f"Post-review structured_rules count: {len(state.get('structured_rules', []))}")
    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 6 — Data scanning
# ═══════════════════════════════════════════════════════════════════════════════

def step6_data_scanning(state: dict) -> dict:
    step(6, "Data Scanning (keyset-paginated scan for violations)")
    from src.agents.nodes.data_scanning import data_scanning_node

    n_rules = len(state.get("structured_rules", []))
    info(f"Scanning with {n_rules} rules against DB: {state['db_config']}")

    t0 = time.perf_counter()
    state = run_node(data_scanning_node, state, "data_scanning_node")

    summary = state.get("scan_summary", {})
    scan_id  = state.get("scan_id", "?")
    console.print()
    console.print(Panel(
        f"[bold]scan_id:[/bold] {scan_id}\n"
        f"[bold]total_violations:[/bold] [red]{summary.get('total_violations',0)}[/red]\n"
        f"[bold]tables_scanned:[/bold]   {summary.get('tables_scanned',0)}\n"
        f"[bold]tables_skipped:[/bold]   {summary.get('tables_skipped',0)}\n"
        f"[bold]rules_processed:[/bold]  {summary.get('rules_processed',0)}\n"
        f"[bold]rules_failed:[/bold]     {summary.get('rules_failed',0)}\n"
        f"[bold]duration:[/bold]         {elapsed(t0)}\n"
        f"[bold]status:[/bold]           {summary.get('status','?')}",
        title="[cyan]Scan Summary[/cyan]",
        border_style="cyan",
    ))

    by_rule = summary.get("violations_by_rule", {})
    if by_rule:
        t = Table("rule_id", "violations", title="Violations by Rule")
        for rid, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
            color = "red" if cnt > 0 else "green"
            t.add_row(rid, f"[{color}]{cnt}[/{color}]")
        console.print(t)

    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 7 — Violation reporting
# ═══════════════════════════════════════════════════════════════════════════════

def step7_violation_reporting(state: dict) -> dict:
    step(7, "Violation Reporting (aggregate results into structured report)")
    from src.agents.nodes.violation_reporting import violation_reporting_node
    state = run_node(violation_reporting_node, state, "violation_reporting_node")
    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 10 — Violation Validator (LLM false-positive reducer)
# ═══════════════════════════════════════════════════════════════════════════════

def step10_violation_validator(state: dict) -> dict:
    step(10, "Violation Validator (LLM classifies confirmed vs false-positive)")
    from src.agents.nodes.violation_validator import violation_validator_node
    state = run_node(violation_validator_node, state, "violation_validator_node")

    vsummary = state.get("validation_summary", {})
    if vsummary.get("skipped"):
        warn(f"Validator skipped: {vsummary.get('reason', '?')}")
        return state

    total_v  = vsummary.get("total_validated", 0)
    confirmed = vsummary.get("confirmed", 0)
    fp        = vsummary.get("false_positives", 0)

    if total_v == 0:
        info("No low-confidence violations found — nothing to validate")
        return state

    info(f"Validated {total_v} sampled violations:")
    t = Table("rule_id", "validated", "confirmed", "false_positives", "unresolved",
              title="Validation Results by Rule")
    by_rule = vsummary.get("by_rule", {})
    for rule_id, rdata in sorted(by_rule.items()):
        if isinstance(rdata, dict) and rdata.get("validated", 0) > 0:
            t.add_row(
                rule_id,
                str(rdata.get("validated", 0)),
                f"[green]{rdata.get('confirmed', 0)}[/green]",
                f"[red]{rdata.get('false_positives', 0)}[/red]",
                str(rdata.get("unresolved", 0)),
            )
    if t.row_count:
        console.print(t)
    else:
        info("All validated rules were skipped (not quality/security/privacy type)")

    ok(f"Validator done — {confirmed} confirmed, {fp} false positives out of {total_v} sampled")
    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 11 — Explanation Generator (LLM writes audit-ready explanations)
# ═══════════════════════════════════════════════════════════════════════════════

def step11_explanation_generator(state: dict) -> dict:
    step(11, "Explanation Generator (LLM writes per-rule audit explanations)")
    from src.agents.nodes.explanation_generator import explanation_generator_node
    state = run_node(explanation_generator_node, state, "explanation_generator_node")

    explanations = state.get("rule_explanations", {})
    if not explanations:
        warn("No explanations generated (no violations or LLM unavailable)")
        return state

    info(f"Generated explanations for {len(explanations)} rules")

    # Sort by severity priority
    sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_explanations = sorted(
        explanations.items(),
        key=lambda x: (sev_order.get(x[1].get("severity", "LOW"), 3), -x[1].get("violation_count", 0)),
    )

    for rule_id, expl in sorted_explanations:
        sev    = expl.get("severity", "?")
        count  = expl.get("violation_count", 0)
        sev_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}.get(sev, "white")

        console.print(Panel(
            f"[bold]Severity:[/bold] [{sev_color}]{sev}[/{sev_color}]   "
            f"[bold]Violations:[/bold] {count}\n\n"
            f"[bold]Explanation:[/bold]\n{expl.get('explanation','')}\n\n"
            f"[bold]Policy Clause:[/bold] {expl.get('policy_clause','')}\n\n"
            f"[bold]Risk:[/bold] {expl.get('risk_description','')}\n\n"
            f"[bold]Remediation Steps:[/bold]\n"
            + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(expl.get("remediation_steps", []))),
            title=f"[bold cyan]Rule {rule_id}[/bold cyan]",
            border_style=sev_color,
        ))

    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 8 — Print final report
# ═══════════════════════════════════════════════════════════════════════════════

def step8_print_report(state: dict) -> None:
    step(8, "Final Compliance Report")
    from src.agents.nodes.violation_reporting import print_report

    report = state.get("violation_report", {})
    if not report or report.get("error"):
        err(f"No valid report: {report.get('error','unknown error')}")
        return

    print_report(report)

    # Extra: show first 10 rows of violations DB
    console.print()
    console.print(Rule("[bold yellow]Violations Database Preview[/bold yellow]", style="yellow"))
    try:
        import sqlite3
        vc = sqlite3.connect(VIOLATIONS_DB)
        vc.row_factory = sqlite3.Row
        cur = vc.cursor()
        cur.execute("SELECT * FROM violations_log LIMIT 10")
        rows = cur.fetchall()
        vc.close()
        if rows:
            t = Table(*list(rows[0].keys())[:8], title="violations_log (first 10 rows, first 8 cols)")
            for row in rows:
                vals = [str(v)[:30] if v is not None else "NULL" for v in list(dict(row).values())[:8]]
                t.add_row(*vals)
            console.print(t)
        else:
            info("violations_log is empty")
    except Exception as e:
        warn(f"Could not read violations DB: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 9 — LLM Evaluator
# ═══════════════════════════════════════════════════════════════════════════════

_EVAL_SYSTEM = """\
You are a senior compliance systems auditor and AI quality evaluator.
You will be given:
  1. The database schema of the scanned dataset.
  2. The structured rules that were applied.
  3. The scan result summary (violation counts per rule).
  4. Known ground-truth facts about the dataset.

Your job is to evaluate the compliance scan and return a JSON object with this exact schema:
{
  "overall_score": <int 0-100>,
  "grade": <"A"|"B"|"C"|"D"|"F">,
  "rule_extraction_quality": <int 0-100>,
  "scan_accuracy": <int 0-100>,
  "coverage_score": <int 0-100>,
  "findings": [
    {"severity": "HIGH"|"MEDIUM"|"LOW", "rule_id": str, "issue": str, "recommendation": str}
  ],
  "false_positives": [
    {"rule_id": str, "reason": str}
  ],
  "missed_rules": [
    {"description": str, "suggested_rule_id": str, "suggested_logic": str}
  ],
  "duplicate_rules": [
    {"rule_ids": [str, str], "reason": str}
  ],
  "ground_truth_validation": [
    {"fact": str, "expected": str, "actual": str, "verdict": "PASS"|"FAIL"|"WARN"}
  ],
  "summary": str
}

Return ONLY valid JSON. No markdown. No explanation.
"""


def step9_llm_evaluate(state: dict) -> None:
    step(9, "LLM Evaluator (Groq judges rule quality, scan accuracy, coverage)")
    import json
    import re 
    from langchain_groq import ChatGroq
    from langchain_core.messages import SystemMessage, HumanMessage

    structured = state.get("structured_rules", [])
    scan_summary = state.get("scan_summary", {})
    schema_meta = state.get("schema_metadata", {})

    # ── Build the evaluation prompt payload ──────────────────────────────────────────
    table_cols = []
    for tbl, tinfo in schema_meta.items():
        cols = [c["column_name"] for c in tinfo.get("columns", [])]
        table_cols.append(f"Table '{tbl}': {tinfo.get('row_count',0)} rows, columns: {cols}")

    rules_summary = []
    for r in structured:
        vcount = scan_summary.get("violations_by_rule", {}).get(r.rule_id, 0)
        rules_summary.append(
            f"  {r.rule_id} | column='{r.target_column}' op='{r.operator}' "
            f"val='{r.value}' conf={r.confidence:.2f} violations={vcount}"
        )

    ground_truth = """
Known facts about HI-Small_Trans.db (10,000 rows):
  - Exactly 1 row has Is Laundering = '1'
  - Exactly 6 rows have Payment Format = 'Bitcoin'
  - Exactly 291 rows have Payment Format = 'Cash'
  - Exactly 3,711 rows have CAST("Amount Paid" AS REAL) > 10000
  - Exactly 3,711 rows have CAST("Amount Received" AS REAL) > 10000
  - Exactly 81 rows have CAST("Amount Paid" AS REAL) < 1.0
  - Exactly 554 rows have CAST("Amount Paid" AS REAL) > 1000000
  - Zero rows have NULL in Timestamp, Account, Account_2, From Bank, To Bank,
    Payment Format, Receiving Currency, Payment Currency
  - Column 'Transaction Amount' does NOT exist; correct names are 'Amount Paid' / 'Amount Received'
  - All 10,000 rows use one of: ACH, Bitcoin, Cash, Cheque, Credit Card, Reinvestment, Wire
"""

    payload = f"""DATABASE SCHEMA:
{chr(10).join(table_cols)}

APPLIED RULES ({len(structured)} total):
{chr(10).join(rules_summary)}

SCAN SUMMARY:
  total_violations : {scan_summary.get('total_violations', 0)}
  tables_scanned   : {scan_summary.get('tables_scanned', 0)}
  rules_processed  : {scan_summary.get('rules_processed', 0)}
  rules_failed     : {scan_summary.get('rules_failed', 0)}
  status           : {scan_summary.get('status', '?')}

{ground_truth}

Evaluate the scan and return the JSON assessment."""

    info(f"Sending {len(payload)} chars to LLM evaluator...")
    t0 = time.perf_counter()

    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
        response = llm.invoke([SystemMessage(content=_EVAL_SYSTEM), HumanMessage(content=payload)])
        raw = response.content.strip() # type: ignore
    except Exception as e:
        warn(f"LLM evaluator failed: {e}")
        return

    # Strip possible markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        ev = json.loads(raw)
    except Exception as e:
        warn(f"Could not parse evaluator JSON: {e}")
        console.print(raw[:2000])
        return

    ms = elapsed(t0)
    ok(f"Evaluation complete ({ms})")
    console.print()

    # ── Score banner ─────────────────────────────────────────────────────────────────────────
    score = ev.get("overall_score", 0)
    grade = ev.get("grade", "?")
    grade_color = {"A": "green", "B": "cyan", "C": "yellow", "D": "red", "F": "bold red"}.get(grade, "white")
    console.print(Panel(
        f"[bold]Overall Score:[/bold] [{grade_color}]{score}/100  Grade: {grade}[/{grade_color}]\n"
        f"[bold]Rule Extraction Quality:[/bold] {ev.get('rule_extraction_quality', '?')}/100\n"
        f"[bold]Scan Accuracy:[/bold]          {ev.get('scan_accuracy', '?')}/100\n"
        f"[bold]Coverage Score:[/bold]          {ev.get('coverage_score', '?')}/100\n\n"
        f"[italic]{ev.get('summary', '')}[/italic]",
        title="[bold cyan]LLM Evaluation Result[/bold cyan]",
        border_style=grade_color,
    ))

    # ── Ground truth validation ─────────────────────────────────────────────────────────────
    gtv = ev.get("ground_truth_validation", [])
    if gtv:
        t = Table("fact", "expected", "actual", "verdict", title="Ground Truth Validation")
        for row in gtv:
            v = row.get("verdict", "?")
            color = {"PASS": "green", "FAIL": "red", "WARN": "yellow"}.get(v, "white")
            t.add_row(
                str(row.get("fact", ""))[:55],
                str(row.get("expected", ""))[:20],
                str(row.get("actual", ""))[:20],
                f"[{color}]{v}[/{color}]",
            )
        console.print(t)

    # ── Findings ─────────────────────────────────────────────────────────────────═
    findings = ev.get("findings", [])
    if findings:
        t = Table("severity", "rule_id", "issue", "recommendation", title="Findings")
        for f in findings:
            sev = f.get("severity", "?")
            sev_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}.get(sev, "white")
            t.add_row(
                f"[{sev_color}]{sev}[/{sev_color}]",
                f.get("rule_id", ""),
                str(f.get("issue", ""))[:70],
                str(f.get("recommendation", ""))[:70],
            )
        console.print(t)

    # ── False positives ─────────────────────────────────────────────────────────────
    fps = ev.get("false_positives", [])
    if fps:
        t = Table("rule_id", "reason", title="Potential False Positives")
        for f in fps:
            t.add_row(f.get("rule_id", ""), str(f.get("reason", ""))[:100])
        console.print(t)

    # ── Duplicates ─────────────────────────────────────────────────────────────────═
    dupes = ev.get("duplicate_rules", [])
    if dupes:
        t = Table("duplicate rule_ids", "reason", title="Duplicate Rules")
        for d in dupes:
            t.add_row(str(d.get("rule_ids", "")), str(d.get("reason", ""))[:100])
        console.print(t)

    # ── Missed rules ─────────────────────────────────────────────────────────────────═
    missed = ev.get("missed_rules", [])
    if missed:
        t = Table("suggested_rule_id", "description", "suggested_logic", title="Missed / Suggested Rules")
        for m in missed:
            t.add_row(
                m.get("suggested_rule_id", ""),
                str(m.get("description", ""))[:60],
                str(m.get("suggested_logic", ""))[:60],
            )
        console.print(t)


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 12 — Generate audit reports (PDF + HTML)
# ═══════════════════════════════════════════════════════════════════════════════

def step12_generate_report(state: dict) -> None:
    step(12, "Generate Audit Reports (PDF + HTML)")
    from src.stages.report_generator import generate_reports

    report = state.get("violation_report", {})
    if not report or report.get("error"):
        warn(f"No valid violation report — skipping report generation. Error: {report.get('error','?')}")
        return

    t0 = time.perf_counter()
    try:
        paths = generate_reports(state, output_dir=ROOT / "data")
        ms = elapsed(t0)

        pdf_path  = paths.get("pdf", "")
        html_path = paths.get("html", "")

        pdf_size  = Path(pdf_path).stat().st_size  // 1024 if pdf_path and Path(pdf_path).exists()  else 0
        html_size = Path(html_path).stat().st_size // 1024 if html_path and Path(html_path).exists() else 0

        console.print()
        console.print(Panel(
            f"[bold]PDF  Report:[/bold]  [cyan]{pdf_path}[/cyan]  ({pdf_size} KB)\n"
            f"[bold]HTML Report:[/bold]  [cyan]{html_path}[/cyan]  ({html_size} KB)\n"
            f"[bold]Duration:[/bold]     {ms}",
            title="[bold green]Audit Reports Generated[/bold green]",
            border_style="green",
        ))

        if pdf_path:
            ok(f"PDF  → {pdf_path}  ({pdf_size} KB)")
        else:
            warn("PDF generation skipped (reportlab error — see log)")
        if html_path:
            ok(f"HTML → {html_path}  ({html_size} KB)")
        else:
            warn("HTML generation failed unexpectedly")

    except Exception as e:
        warn(f"Report generation failed: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    console.print(Panel.fit(
        "[bold blue]HI-Small Financial Transactions[/bold blue]\n"
        "[dim]Anti-Money Laundering Compliance Scan[/dim]\n"
        f"[dim]{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}[/dim]",
        border_style="blue",
    ))

    # ── Verify prerequisites ──────────────────────────────────────────────────
    if not Path(DB_PATH).exists():
        err(f"Database not found: {DB_PATH}")
        sys.exit(1)
    if not os.environ.get("GROQ_API_KEY"):
        warn("GROQ_API_KEY not set — LLM extraction will fail. Add it to .env")

    # ── Delete stale schema cache so rowid fallback takes effect ─────────────
    cache_file = ROOT / "data" / ".schema_cache.json"
    if cache_file.exists():
        cache_file.unlink()
        info("Cleared schema cache (rowid fix applied)")

    # ── Run pipeline step by step ─────────────────────────────────────────────
    total_t0 = time.perf_counter()

    policy_pdf = step1_generate_pdf()

    graph, cp, cp_ctx = step2_build_graph()

    initial_state = {
        "document_path": policy_pdf,
        "db_type":       "sqlite",
        "db_config":     {"db_path": DB_PATH},
        "violations_db_path": VIOLATIONS_DB,
        "batch_size":    500,
        "errors":        [],
        "raw_rules":     [],
    }
    info(f"Initial state keys: {list(initial_state.keys())}")

    state = dict(initial_state)

    try:
        state = step3_rule_extraction(state)
        state = step4_schema_discovery(state)
        state = step5_rule_structuring(state)
        state = step5b_human_review(state)
        state = step6_data_scanning(state)
        state = step10_violation_validator(state)
        state = step11_explanation_generator(state)
        state = step7_violation_reporting(state)
        step12_generate_report(state)
        step8_print_report(state)
        step9_llm_evaluate(state)

    except Exception as e:
        err(f"Pipeline failed: {e}")
        traceback.print_exc()
    finally:
        cp_ctx.__exit__(None, None, None)

    # ── Final summary ─────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold green]Pipeline Complete[/bold green]", style="green"))
    total_ms = (time.perf_counter() - total_t0) * 1000
    ok(f"Total wall time: {total_ms/1000:.1f}s")
    ok(f"Violations DB:   {VIOLATIONS_DB}")
    ok(f"Checkpoints DB:  {CHECKPOINT_DB}")
    # Show generated report files if present
    import glob as _glob
    scan_id = state.get("scan_id", "")
    if scan_id:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in scan_id)
        for ext in ("pdf", "html"):
            p = ROOT / "data" / f"compliance_report_{safe_id}.{ext}"
            if p.exists():
                ok(f"Report ({ext.upper()}): {p}")

    errors = state.get("errors", [])
    if errors:
        warn(f"{len(errors)} error(s) accumulated:")
        for e in errors:
            warn(f"  {e}")


if __name__ == "__main__":
    main()
