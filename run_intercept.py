"""
run_intercept.py — Test harness for the Interceptor (real-time) mode.

Demonstrates the full interceptor pipeline with several query scenarios:
  1. Analytics query (aggregation, no PII)        → likely APPROVE
  2. PII query with purpose                        → depends on policy
  3. Vague query (SELECT *, no purpose)            → CLARIFICATION_REQUIRED
  4. Sensitive query (SSN/credit card)             → likely BLOCK
  5. Cache hit test (repeat query #1)              → exact cache hit

Prerequisites:
  - Run the scanner first to populate the policy rule vector DB:
      uv run python run_hi_small.py
  - Or manually ingest rules:
      from src.vector_database.policy_store import PolicyRuleStore
      store = PolicyRuleStore()
      store.ingest_structured_rules(your_rules)

Usage:
  uv run python run_intercept.py --db data/HI-Small_Trans.db
"""
from __future__ import annotations

import argparse
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # Load .env (GROQ_API_KEY, etc.)

from rich.console import Console  # noqa: E402
from rich.panel import Panel # noqa: E402
from rich.table import Table # noqa: E402
from rich import box # noqa: E402

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Test the interceptor compliance pipeline")
    parser.add_argument(
        "--db",
        default="data/HI-Small_Trans.db",
        help="Path to the SQLite database to intercept queries against",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip policy ingestion (assumes rules already in Qdrant)",
    )
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        console.print("Run the scanner first:  uv run python run_hi_small.py")
        return

    if not os.environ.get("GROQ_API_KEY"):
        console.print("[yellow]WARNING: GROQ_API_KEY not set — LLM stages will fail.[/yellow]")
        console.print("Add it to .env or set it in your shell.")

    console.print(Panel.fit(
        "[bold cyan]Data Compliance Agent — Interceptor Mode[/bold cyan]\n"
        "Real-time query compliance enforcement",
        border_style="cyan",
    ))

    # ── Step 1: Ensure policy rules are in the vector DB ─────────────────
    if not args.skip_ingest:
        _ensure_policy_rules(db_path)

    # ── Step 2: Build the interceptor graph ──────────────────────────────
    console.print("\n[bold]Building interceptor graph…[/bold]")
    from src.agents.interceptor_graph import build_interceptor_graph
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    graph = build_interceptor_graph(checkpointer=checkpointer)
    console.print("[green]✓ Interceptor graph compiled[/green]")

    # ── Step 3: Run test scenarios ───────────────────────────────────────
    scenarios = [
        {
            "name": "Analytics Query (aggregation, no PII)",
            "query": 'SELECT COUNT(*) FROM transactions GROUP BY "Is Laundering"',
            "user_id": "analyst_01",
            "user_role": "analyst",
            "stated_purpose": "Q4 fraud pattern analysis",
            "expected": "BLOCK (restricted column)",
        },
        {
            "name": "PII Query (accounts + amounts)",
            "query": 'SELECT Account, "Amount Received" FROM transactions WHERE "Amount Received" > 10000',
            "user_id": "compliance_01",
            "user_role": "compliance_officer",
            "stated_purpose": "AML threshold monitoring",
            "expected": "APPROVE or BLOCK",
        },
        {
            "name": "Vague Query (SELECT *, no purpose)",
            "query": "SELECT * FROM transactions",
            "user_id": "intern_01",
            "user_role": "intern",
            "stated_purpose": None,
            "expected": "CLARIFICATION_REQUIRED",
        },
        {
            "name": "Suspicious Query (laundering flag)",
            "query": 'SELECT Account, "To Bank", "Amount Paid" FROM transactions WHERE "Is Laundering" = 1',
            "user_id": "external_01",
            "user_role": "viewer",
            "stated_purpose": "Customer analysis",
            "expected": "BLOCK",
        },
        {
            "name": "Cache Hit Test (repeat scenario 1)",
            "query": 'SELECT COUNT(*) FROM transactions GROUP BY "Is Laundering"',
            "user_id": "analyst_01",
            "user_role": "analyst",
            "stated_purpose": "Q4 fraud pattern analysis",
            "expected": "BLOCK (cached)",
        },
    ]

    results_table = Table(
        title="Interceptor Test Results",
        box=box.ROUNDED,
        show_lines=True,
    )
    results_table.add_column("Scenario", style="cyan", width=35)
    results_table.add_column("Decision", style="bold", width=25)
    results_table.add_column("Expected", width=25)
    results_table.add_column("Cached", width=8)
    results_table.add_column("Cost", width=10)
    results_table.add_column("Time", width=10)

    for i, scenario in enumerate(scenarios, 1):
        console.print(f"\n{'─' * 70}")
        console.print(f"[bold yellow]Scenario {i}: {scenario['name']}[/bold yellow]")
        console.print(f"  Query: [dim]{scenario['query'][:80]}[/dim]")
        console.print(f"  User:  {scenario['user_id']} ({scenario['user_role']})")
        console.print(f"  Purpose: {scenario['stated_purpose'] or '(none)'}")

        session_id = f"test-{uuid.uuid4().hex[:8]}"
        input_state = {
            "query": scenario["query"],
            "user_id": scenario["user_id"],
            "user_role": scenario["user_role"],
            "stated_purpose": scenario["stated_purpose"],
            "session_id": session_id,
            "db_type": "sqlite",
            "db_config": {"db_path": db_path},
            "retry_counts": {},
            "errors": [],
            "total_cost_usd": 0.0,
        }

        config = {"configurable": {"thread_id": session_id}}

        t0 = time.time()
        try:
            result = graph.invoke(input_state, config=config)

            elapsed_ms = (time.time() - t0) * 1000
            decision = result.get("final_decision", "UNKNOWN")
            cached = "Yes" if result.get("cache_hit") else "No"
            cost = f"${result.get('total_cost_usd', 0):.4f}"

            # Color-code decision
            if decision == "APPROVE":
                dec_style = "[green]APPROVE[/green]"
            elif decision == "BLOCK":
                dec_style = "[red]BLOCK[/red]"
            elif decision == "CLARIFICATION_REQUIRED":
                dec_style = "[yellow]CLARIFY[/yellow]"
            else:
                dec_style = f"[dim]{decision}[/dim]"

            console.print(f"  [bold]Result: {dec_style}[/bold]")
            if result.get("block_reason"):
                console.print(f"  Reason: [dim]{result['block_reason'][:120]}[/dim]")
            if result.get("guidance"):
                console.print(f"  Guidance: [dim]{result['guidance'][:120]}[/dim]")
            if result.get("query_results") and isinstance(result["query_results"], dict):
                qr = result["query_results"]
                console.print(f"  Returned: {qr.get('row_count', 0)} rows")

            results_table.add_row(
                scenario["name"][:35],
                decision,
                scenario["expected"],
                cached,
                cost,
                f"{elapsed_ms:.0f}ms",
            )
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000
            console.print(f"  [red]ERROR: {e}[/red]")
            results_table.add_row(
                scenario["name"][:35],
                f"ERROR: {str(e)[:30]}",
                scenario["expected"],
                "No",
                "$0",
                f"{elapsed_ms:.0f}ms",
            )

    # ── Summary ──────────────────────────────────────────────────────────
    console.print(f"\n{'═' * 70}")
    console.print(results_table)

    # Print cache stats
    from src.agents.interceptor_nodes.cache import get_decision_cache
    cache = get_decision_cache()
    stats = cache.stats
    console.print("\n[bold]Cache Stats:[/bold]")
    console.print(f"  Total lookups: {stats['total_lookups']}")
    console.print(f"  Hits: exact={stats['hits']['exact']}, fuzzy={stats['hits']['fuzzy']}, semantic={stats['hits']['semantic']}")
    console.print(f"  Misses: {stats['misses']}")
    console.print(f"  Hit rate: {stats['hit_rate']:.1%}")

    # Print audit log stats
    try:
        from src.agents.interceptor_nodes.audit_logger import get_audit_logger
        logger = get_audit_logger()
        audit_stats = logger.get_stats()
        console.print("\n[bold]Audit Log Stats:[/bold]")
        console.print(f"  Total decisions: {audit_stats['total_decisions']}")
        console.print(f"  Approved: {audit_stats['approved']}")
        console.print(f"  Blocked: {audit_stats['blocked']}")
    except Exception:
        pass

    console.print("\n[green bold]✓ Interceptor test complete[/green bold]")


def _ensure_policy_rules(db_path: str):
    """Check if policy rules exist in Qdrant; if not, create some defaults."""
    from src.vector_database.policy_store import PolicyRuleStore

    console.print("\n[bold]Checking policy rule store…[/bold]")
    store = PolicyRuleStore()
    count = store.count()

    if count > 0:
        console.print(f"[green]✓ Found {count} policy rules in vector DB[/green]")
        store.close()
        return

    console.print("[yellow]No policy rules found — ingesting default AML rules…[/yellow]")

    from src.models.structured_rule import StructuredRule

    default_rules = [
        StructuredRule(
            rule_id="aml_high_value",
            rule_text="Transactions exceeding 10,000 in value must be flagged for AML review. High-value transactions require enhanced due diligence.",
            source="aml_policy",
            rule_type="data_security",
            target_column="Amount_Received",
            operator=">",
            value="10000",
            data_type="number",
            confidence=0.9,
        ),
        StructuredRule(
            rule_id="aml_laundering_flag",
            rule_text="Access to laundering flag data is restricted to compliance officers and above. Unauthorized access to Is_Laundering column must be blocked.",
            source="aml_policy",
            rule_type="data_access",
            target_column="Is_Laundering",
            operator="=",
            value="1",
            data_type="number",
            confidence=0.95,
        ),
        StructuredRule(
            rule_id="data_retention_90d",
            rule_text="Transaction records older than 90 days must be archived. Active retention period is 90 days from transaction timestamp.",
            source="aml_policy",
            rule_type="data_retention",
            target_column="Timestamp",
            operator=">",
            value="NOW() - 90 DAYS",
            data_type="datetime",
            confidence=0.85,
            rule_complexity="date_math",
        ),
        StructuredRule(
            rule_id="pii_account_access",
            rule_text="Account identifiers (Sender_account, Receiver_account) are PII and require stated business purpose for access. Access must be logged.",
            source="aml_policy",
            rule_type="data_privacy",
            target_column="Sender_account",
            operator="IS NOT NULL",
            value=None,
            data_type="string",
            confidence=0.9,
        ),
        StructuredRule(
            rule_id="select_star_prohibition",
            rule_text="SELECT * queries against transaction tables are prohibited without explicit column justification. All data access must follow principle of least privilege.",
            source="aml_policy",
            rule_type="data_access",
            target_column="*",
            operator="!=",
            value="SELECT *",
            data_type="string",
            confidence=0.85,
        ),
        StructuredRule(
            rule_id="currency_format",
            rule_text="All currency amounts must be in standardized format. Payment_currency field must contain valid ISO 4217 currency codes.",
            source="aml_policy",
            rule_type="data_quality",
            target_column="Payment_currency",
            operator="IS NOT NULL",
            value=None,
            data_type="string",
            confidence=0.8,
        ),
        StructuredRule(
            rule_id="cross_border_monitoring",
            rule_text="Cross-border transactions (where Sender and Receiver are in different countries) require enhanced monitoring and compliance review.",
            source="aml_policy",
            rule_type="data_security",
            target_column="Sender_bank_location",
            operator="!=",
            value="Receiver_bank_location",
            data_type="string",
            confidence=0.85,
            rule_complexity="cross_field",
            second_column="Receiver_bank_location",
        ),
        StructuredRule(
            rule_id="bitcoin_transaction_flag",
            rule_text="Cryptocurrency transactions (Payment_currency = 'Bitcoin') require additional AML scrutiny and must be flagged for compliance review.",
            source="aml_policy",
            rule_type="data_security",
            target_column="Payment_currency",
            operator="=",
            value="Bitcoin",
            data_type="string",
            confidence=0.9,
        ),
    ]

    n = store.ingest_structured_rules(default_rules, framework="AML")
    console.print(f"[green]✓ Ingested {n} default AML policy rules[/green]")
    store.close()


if __name__ == "__main__":
    main()
