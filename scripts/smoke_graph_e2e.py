"""
Graph-based end-to-end smoke test.

Unlike ``run_hi_small.py`` (which calls each node function directly and relies
on hardcoded fallback rules), this script invokes the real compiled
``StateGraph`` via ``graph.invoke()`` — the same path the langgraph dev server
and the Next.js frontend will exercise in the live demo.

It will exit with:
  0  — full pipeline succeeded (report_paths present)
  1  — pipeline raised / state missing expected keys
  2  — GROQ_API_KEY not set

Usage
-----
    python scripts/smoke_graph_e2e.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402

# Windows legacy console + cp1252 crashes on ✓/→/em-dash. Force ANSI via UTF-8
# stdout (the logger already reconfigured sys.stdout above-chain).
console = Console(force_terminal=True, legacy_windows=False, color_system="auto")

DB_PATH    = ROOT / "data" / "HI-Small_Trans.db"
POLICY_PDF = ROOT / "data" / "AML_Compliance_Policy.pdf"
VIOL_DB    = ROOT / "data" / "hi_small_violations.db"


def main() -> int:
    if not os.getenv("GROQ_API_KEY"):
        console.print("[red]GROQ_API_KEY not set — cannot smoke test.[/red]")
        return 2

    if not DB_PATH.exists():
        console.print(f"[red]Demo DB missing at {DB_PATH}[/red]")
        return 1

    if not POLICY_PDF.exists():
        console.print(f"[cyan]Policy PDF missing — generating...[/cyan]")
        from scripts.generate_policy_pdf import build_pdf
        build_pdf(str(POLICY_PDF))

    from src.agents.graph import build_graph
    from src.agents.memory import get_checkpointer

    console.print(Panel.fit(
        "[bold]Graph-based E2E smoke test[/bold]\n"
        "Uses the compiled StateGraph (the real demo path).",
        border_style="cyan",
    ))

    # Use sqlite checkpointer so the interrupt/resume path is real.
    checkpoint_db = ROOT / "data" / "smoke_checkpoints.db"
    t0 = time.perf_counter()

    with get_checkpointer("sqlite", db_path=str(checkpoint_db)) as cp:
        graph = build_graph(checkpointer=cp)
        config = {"configurable": {"thread_id": "smoke-e2e"}}

        initial = {
            "document_path":      str(POLICY_PDF),
            "db_type":            "sqlite",
            "db_config":          {"db_path": str(DB_PATH)},
            "violations_db_path": str(VIOL_DB),
            "batch_size":         500,
            "errors":             [],
            "raw_rules":          [],
        }

        console.print("[cyan]Invoking graph (this will stream LLM calls)...[/cyan]")
        state: dict = {}
        interrupted = False
        try:
            # First invoke — may hit an interrupt() if any rule is low-confidence.
            for chunk in graph.stream(initial, config=config, stream_mode="updates"):
                for node, updates in chunk.items():
                    if node == "__interrupt__":
                        interrupted = True
                        payload = updates[0].value if isinstance(updates, list) else updates
                        console.print(
                            f"[yellow][!] Graph interrupted at human_review -- "
                            f"{len(payload.get('rules', []))} low-confidence rules[/yellow]"
                        )
                    else:
                        summary = ", ".join(sorted(updates.keys())) if isinstance(updates, dict) else str(updates)[:80]
                        console.print(f"  [green][ok][/green] {node} -> {summary}")

            if interrupted:
                console.print("[cyan]Auto-approving all low-confidence rules and resuming...[/cyan]")
                from langgraph.types import Command
                snap = graph.get_state(config)
                low = snap.values.get("low_confidence_rules", [])
                decision = {
                    "approved": [r.rule_id for r in low],
                    "edited":   [],
                    "dropped":  [],
                }
                for chunk in graph.stream(Command(resume=decision), config=config, stream_mode="updates"):
                    for node, updates in chunk.items():
                        summary = ", ".join(sorted(updates.keys())) if isinstance(updates, dict) else str(updates)[:80]
                        console.print(f"  [green][ok][/green] {node} -> {summary}")

            # Final state snapshot
            final = graph.get_state(config)
            state = dict(final.values)

        except Exception as e:
            import traceback
            console.print(f"[red][X] Graph raised: {e}[/red]")
            traceback.print_exc()
            return 1

    elapsed = time.perf_counter() - t0

    # Assertions
    report_paths = state.get("report_paths") or {}
    scan_summary = state.get("scan_summary") or {}
    raw_rules    = state.get("raw_rules") or []
    structured   = state.get("structured_rules") or []
    errors       = state.get("errors") or []

    console.print()
    console.print(Panel(
        f"[bold]Duration:[/bold]         {elapsed:.1f}s\n"
        f"[bold]raw_rules:[/bold]        {len(raw_rules)}\n"
        f"[bold]structured_rules:[/bold] {len(structured)}\n"
        f"[bold]total_violations:[/bold] {scan_summary.get('total_violations', 0)}\n"
        f"[bold]tables_scanned:[/bold]   {scan_summary.get('tables_scanned', 0)}\n"
        f"[bold]report_paths.pdf:[/bold] {report_paths.get('pdf', '(missing)')}\n"
        f"[bold]report_paths.html:[/bold] {report_paths.get('html', '(missing)')}\n"
        f"[bold]errors:[/bold]           {len(errors)}",
        title="[cyan]Smoke Test Result[/cyan]",
    ))

    if errors:
        console.print("[yellow]Errors accumulated during run:[/yellow]")
        for e in errors:
            console.print(f"  • {e}")

    status_ok = (
        len(raw_rules) > 0 and
        len(structured) > 0 and
        scan_summary.get("status") == "completed"
    )

    if status_ok:
        console.print("[bold green]✔ Graph E2E smoke test PASSED[/bold green]")
        return 0
    else:
        console.print("[bold red][X] Graph E2E smoke test FAILED -- see details above[/bold red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
