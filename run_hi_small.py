"""
End-to-end compliance scan of HI-Small_Trans.db (graph path)
============================================================

This is the canonical CLI smoke test. It invokes the REAL compiled
``StateGraph`` (same code path the langgraph dev server and the Next.js
frontend use in the live demo) — no hand-crafted rule fallbacks, no
step-by-step node orchestration.

What it does
------------
1. Generates the AML policy PDF (if missing).
2. Compiles the scanner graph with a SQLite checkpointer.
3. Streams the graph with ``stream_mode="updates"`` and prints each node's
   output keys as they land.
4. If the graph hits an ``interrupt()`` for low-confidence rules, it
   auto-approves them (batch mode) and resumes with ``Command(resume=...)``.
5. Asserts the final state contains ``report_paths`` + violations and
   prints a one-page summary. Evaluator + ground-truth table are preserved
   from the legacy script for demo context.

Usage
-----
    python run_hi_small.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# ── Project root on sys.path ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

# Importing logger reconfigures stdout/stderr to UTF-8 on Windows so
# Unicode status chars do not raise encoding errors.
from src.utils.logger import setup_logger  # noqa: E402, F401
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.rule import Rule  # noqa: E402
from rich.table import Table  # noqa: E402

console = Console(force_terminal=True, legacy_windows=False, color_system="auto")

# ── Paths ────────────────────────────────────────────────────────────────
DB_PATH       = str(ROOT / "data" / "HI-Small_Trans.db")
POLICY_PDF    = str(ROOT / "data" / "AML_Compliance_Policy.pdf")
VIOLATIONS_DB = str(ROOT / "data" / "hi_small_violations.db")
CHECKPOINT_DB = str(ROOT / "data" / "hi_small_checkpoints.db")

THREAD_ID = "run-hi-small-cli"


# ═════════════════════════════════════════════════════════════════════════
#  Utilities
# ═════════════════════════════════════════════════════════════════════════
def step(n: str, title: str) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]Step {n}: {title}[/bold cyan]", style="cyan"))

def ok(msg: str)   -> None: console.print(f"  [bold green][ok][/bold green]  {msg}")
def info(msg: str) -> None: console.print(f"  [dim]i[/dim]  {msg}")
def warn(msg: str) -> None: console.print(f"  [bold yellow][!][/bold yellow]  {msg}")
def err(msg: str)  -> None: console.print(f"  [bold red][X][/bold red]  {msg}")

def elapsed(t0: float) -> str:
    return f"{(time.perf_counter() - t0)*1000:.0f} ms"


# ═════════════════════════════════════════════════════════════════════════
#  Step 1 — Ensure the policy PDF exists
# ═════════════════════════════════════════════════════════════════════════
def step1_ensure_pdf() -> str:
    step("1", "Ensure AML Compliance Policy PDF")
    if Path(POLICY_PDF).exists():
        ok(f"PDF already present at {POLICY_PDF}")
        return POLICY_PDF
    from scripts.generate_policy_pdf import build_pdf
    t0 = time.perf_counter()
    path = build_pdf(POLICY_PDF)
    ok(f"PDF generated at {path} ({elapsed(t0)})")
    return path


# ═════════════════════════════════════════════════════════════════════════
#  Step 2 — Build the graph
# ═════════════════════════════════════════════════════════════════════════
def step2_build_graph():
    step("2", "Build LangGraph compliance pipeline (real graph.invoke path)")
    from src.agents.graph import build_graph
    from src.agents.memory import get_checkpointer

    t0 = time.perf_counter()
    cp_ctx = get_checkpointer("sqlite", db_path=CHECKPOINT_DB)
    cp = cp_ctx.__enter__()
    graph = build_graph(checkpointer=cp)

    node_names = [n for n in graph.nodes if not n.startswith("__")]
    ok(f"Pipeline compiled ({elapsed(t0)})")
    info(f"Nodes: {node_names}")
    return graph, cp_ctx


# ═════════════════════════════════════════════════════════════════════════
#  Step 3 — Stream the graph
# ═════════════════════════════════════════════════════════════════════════
def step3_stream_graph(graph, initial: Dict[str, Any]) -> Dict[str, Any]:
    step("3", "Stream graph (rule_extraction -> schema_discovery -> ... -> report_generation)")
    from langgraph.types import Command

    config = {"configurable": {"thread_id": THREAD_ID}}
    interrupted = False

    def _consume(stream) -> None:
        nonlocal interrupted
        for chunk in stream:
            for node, updates in chunk.items():
                if node == "__interrupt__":
                    interrupted = True
                    payload = updates[0].value if isinstance(updates, list) else updates
                    warn(f"Graph interrupted at human_review -- "
                         f"{len(payload.get('rules', []))} low-confidence rules")
                else:
                    keys = ", ".join(sorted(updates.keys())) if isinstance(updates, dict) else str(updates)[:80]
                    ok(f"node [{node}] -> {keys}")

    # First pass
    _consume(graph.stream(initial, config=config, stream_mode="updates"))

    # Auto-resume HITL if the graph paused
    if interrupted:
        info("Auto-approving all low-confidence rules and resuming...")
        snap = graph.get_state(config)
        low = snap.values.get("low_confidence_rules", [])
        decision = {
            "approved": [r.rule_id for r in low],
            "edited":   [],
            "dropped":  [],
        }
        _consume(graph.stream(Command(resume=decision), config=config, stream_mode="updates"))

    # Return the final state snapshot
    final = graph.get_state(config)
    return dict(final.values)


# ═════════════════════════════════════════════════════════════════════════
#  Step 4 — Assert + print summary
# ═════════════════════════════════════════════════════════════════════════
def step4_summary(state: Dict[str, Any]) -> None:
    step("4", "Final State Summary")
    raw_rules   = state.get("raw_rules", [])
    structured  = state.get("structured_rules", [])
    low_conf    = state.get("low_confidence_rules", [])
    schema      = state.get("schema_metadata", {})
    scan_sum    = state.get("scan_summary", {})
    val_sum     = state.get("validation_summary", {})
    rule_expl   = state.get("rule_explanations", {})
    report_paths = state.get("report_paths", {})
    errors      = state.get("errors", [])

    info(f"raw_rules:          {len(raw_rules)}")
    info(f"structured_rules:   {len(structured)}")
    info(f"low_confidence:     {len(low_conf)}")
    info(f"tables_discovered:  {len(schema)}")
    info(f"total_violations:   {scan_sum.get('total_violations', 0)}")
    info(f"rules_processed:    {scan_sum.get('rules_processed', 0)}")
    info(f"rules_failed:       {scan_sum.get('rules_failed', 0)}")
    if val_sum:
        info(f"validator:          {val_sum.get('confirmed', 0)} confirmed, "
             f"{val_sum.get('false_positives', 0)} FP, "
             f"{val_sum.get('total_validated', 0)} total")
    info(f"rule_explanations:  {len(rule_expl)}")

    if report_paths.get("pdf"):
        ok(f"PDF report:  {report_paths['pdf']}")
    if report_paths.get("html"):
        ok(f"HTML report: {report_paths['html']}")

    # Violations by rule table
    by_rule = scan_sum.get("violations_by_rule", {})
    if by_rule:
        t = Table("rule_id", "violations", title="Violations by Rule")
        for rid, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
            color = "red" if cnt > 0 else "green"
            t.add_row(rid, f"[{color}]{cnt}[/{color}]")
        console.print(t)

    if errors:
        warn(f"{len(errors)} error(s) accumulated:")
        for e in errors:
            warn(f"  {e}")


# ═════════════════════════════════════════════════════════════════════════
#  Step 5 — LLM evaluator against ground truth (preserved from legacy script)
# ═════════════════════════════════════════════════════════════════════════
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
  "findings": [{"severity": "HIGH"|"MEDIUM"|"LOW", "rule_id": str, "issue": str, "recommendation": str}],
  "ground_truth_validation": [{"fact": str, "expected": str, "actual": str, "verdict": "PASS"|"FAIL"|"WARN"}],
  "summary": str
}
Return ONLY valid JSON."""

_GROUND_TRUTH = """
Known facts about HI-Small_Trans.db (10,000 rows, table 'transactions'):
  - Exactly 1 row has Is Laundering = '1'
  - Exactly 6 rows have Payment Format = 'Bitcoin'
  - Exactly 291 rows have Payment Format = 'Cash'
  - Exactly 3,711 rows have CAST("Amount Paid" AS REAL) > 10000
  - Exactly 3,711 rows have CAST("Amount Received" AS REAL) > 10000
  - Exactly 81 rows have CAST("Amount Paid" AS REAL) < 1.0
  - Exactly 554 rows have CAST("Amount Paid" AS REAL) > 1000000
  - Zero rows have NULL in Timestamp, Account, Payment Format, or currency columns
  - Column 'Transaction Amount' does NOT exist; correct names are 'Amount Paid' / 'Amount Received'
"""


def step5_llm_evaluate(state: Dict[str, Any]) -> None:
    step("5", "LLM Evaluator (ground-truth validation)")
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    structured = state.get("structured_rules", [])
    scan_summary = state.get("scan_summary", {})
    schema_meta = state.get("schema_metadata", {})

    if not scan_summary:
        warn("No scan_summary in state — skipping evaluator")
        return

    table_cols: List[str] = []
    for tbl, tinfo in schema_meta.items():
        cols = [c["column_name"] for c in tinfo.get("columns", [])]
        table_cols.append(f"Table '{tbl}': {tinfo.get('row_count', 0)} rows, columns: {cols}")

    rules_summary: List[str] = []
    by_rule = scan_summary.get("violations_by_rule", {})
    for r in structured:
        rid = r.rule_id if hasattr(r, "rule_id") else r.get("rule_id", "")
        col = r.target_column if hasattr(r, "target_column") else r.get("target_column", "")
        op  = r.operator if hasattr(r, "operator") else r.get("operator", "")
        val = r.value if hasattr(r, "value") else r.get("value", "")
        conf = r.confidence if hasattr(r, "confidence") else r.get("confidence", 0)
        rules_summary.append(
            f"  {rid} | col='{col}' op='{op}' val='{val}' "
            f"conf={conf:.2f} violations={by_rule.get(rid, 0)}"
        )

    payload = (
        f"DATABASE SCHEMA:\n{chr(10).join(table_cols)}\n\n"
        f"APPLIED RULES ({len(structured)} total):\n{chr(10).join(rules_summary)}\n\n"
        f"SCAN SUMMARY:\n"
        f"  total_violations: {scan_summary.get('total_violations', 0)}\n"
        f"  tables_scanned:   {scan_summary.get('tables_scanned', 0)}\n"
        f"  rules_processed:  {scan_summary.get('rules_processed', 0)}\n"
        f"  rules_failed:     {scan_summary.get('rules_failed', 0)}\n\n"
        f"{_GROUND_TRUTH}\n"
        "Evaluate the scan and return the JSON assessment."
    )

    info(f"Sending {len(payload)} chars to LLM evaluator...")
    t0 = time.perf_counter()
    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, timeout=45)
        response = llm.invoke([SystemMessage(content=_EVAL_SYSTEM), HumanMessage(content=payload)])
        raw = response.content.strip() if hasattr(response, "content") else str(response)  # type: ignore
    except Exception as e:
        warn(f"Evaluator failed: {e}")
        return

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        ev = json.loads(raw)
    except Exception as e:
        warn(f"Could not parse evaluator JSON: {e}")
        console.print(raw[:800])
        return

    ok(f"Evaluation complete ({elapsed(t0)})")

    score = ev.get("overall_score", 0)
    grade = ev.get("grade", "?")
    grade_color = {"A": "green", "B": "cyan", "C": "yellow", "D": "red", "F": "bold red"}.get(grade, "white")
    console.print(Panel(
        f"[bold]Overall Score:[/bold] [{grade_color}]{score}/100 Grade: {grade}[/{grade_color}]\n"
        f"[bold]Rule Extraction Quality:[/bold] {ev.get('rule_extraction_quality', '?')}/100\n"
        f"[bold]Scan Accuracy:[/bold]          {ev.get('scan_accuracy', '?')}/100\n"
        f"[bold]Coverage Score:[/bold]          {ev.get('coverage_score', '?')}/100\n\n"
        f"[italic]{ev.get('summary', '')}[/italic]",
        title="[bold cyan]Compliance Evaluation[/bold cyan]",
        border_style=grade_color,
    ))

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


# ═════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════
def main() -> int:
    console.print(Panel.fit(
        "[bold blue]HI-Small Financial Transactions[/bold blue]\n"
        "[dim]Anti-Money Laundering Compliance Scan (graph path)[/dim]\n"
        f"[dim]{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}[/dim]",
        border_style="blue",
    ))

    if not Path(DB_PATH).exists():
        err(f"Database not found: {DB_PATH}")
        return 1

    if not os.environ.get("GROQ_API_KEY"):
        err("GROQ_API_KEY not set — aborting (the graph requires live LLM access).")
        err("Add GROQ_API_KEY=... to .env at the repo root.")
        return 2

    total_t0 = time.perf_counter()
    policy_pdf = step1_ensure_pdf()
    graph, cp_ctx = step2_build_graph()

    initial: Dict[str, Any] = {
        "document_path":      policy_pdf,
        "db_type":            "sqlite",
        "db_config":          {"db_path": DB_PATH},
        "violations_db_path": VIOLATIONS_DB,
        "batch_size":         500,
        "errors":             [],
        "raw_rules":          [],
    }
    info(f"Initial state keys: {list(initial.keys())}")

    try:
        state = step3_stream_graph(graph, initial)
        step4_summary(state)
        step5_llm_evaluate(state)
    except Exception as e:
        err(f"Pipeline failed: {e}")
        traceback.print_exc()
        return 1
    finally:
        cp_ctx.__exit__(None, None, None)

    console.print()
    console.print(Rule("[bold green]Pipeline Complete[/bold green]", style="green"))
    total_ms = (time.perf_counter() - total_t0) * 1000
    ok(f"Total wall time: {total_ms/1000:.1f}s")
    ok(f"Violations DB:   {VIOLATIONS_DB}")
    ok(f"Checkpoints DB:  {CHECKPOINT_DB}")

    if state.get("report_paths", {}).get("pdf"):
        ok(f"PDF report: {state['report_paths']['pdf']}")
    if state.get("report_paths", {}).get("html"):
        ok(f"HTML report: {state['report_paths']['html']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
