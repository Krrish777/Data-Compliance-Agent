"""
Prewarm the demo cache.

Runs rule_extraction once against the demo policy PDF so that the first
live demo click hits the cache instead of the LLM. This shaves ~30-60s
off the first scan the judges see.

Usage
-----
    python scripts/prewarm_demo.py

Idempotent — safe to run multiple times. No-op if GROQ_API_KEY is unset.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from rich.console import Console  # noqa: E402

console = Console()


def main() -> int:
    policy_pdf = ROOT / "data" / "AML_Compliance_Policy.pdf"

    if not os.getenv("GROQ_API_KEY"):
        console.print("[yellow]GROQ_API_KEY not set — cannot prewarm. Exiting.[/yellow]")
        return 0

    # Ensure the PDF exists (generate if missing)
    if not policy_pdf.exists():
        console.print("[cyan]Policy PDF missing — generating...[/cyan]")
        from scripts.generate_policy_pdf import build_pdf
        build_pdf(str(policy_pdf))
        console.print(f"[green]✔ PDF written → {policy_pdf}[/green]")

    console.print("[cyan]Running rule_extraction_node once to warm the cache...[/cyan]")
    from src.agents.nodes.rule_extraction import rule_extraction_node

    state = {"document_path": str(policy_pdf)}
    result = rule_extraction_node(state)

    rules = result.get("raw_rules", [])
    stage = result.get("current_stage", "?")
    console.print(
        f"[green]✔ Prewarm complete — {len(rules)} rules extracted "
        f"(stage={stage})[/green]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
