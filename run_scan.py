"""
Run compliance data scanning on a database.

Usage:
    uv run python run_scan.py [--db PATH] [--rules RULES_JSON]

Example:
    uv run python run_scan.py --db data/HI-Small_Trans.db
"""
import argparse
import json
from pathlib import Path

from src.agents.tools.database.sqlite_connector import SQLiteConnector
from src.stages.data_scanning import data_scanning_stage


DEFAULT_RULES = [
    {
        "rule_id": "retention_90d",
        "rule_text": "Personal data must be deleted within 90 days of account closure",
        "source": "GDPR Art 17",
        "rule_type": "retention",
        "target_column": "deleted_at",
        "operator": "<",
        "value": "datetime('now', '-90 days')",
        "data_type": "datetime",
        "confidence": 0.9,
    },
    {
        "rule_id": "email_format",
        "rule_text": "Email addresses must be in valid format",
        "source": "Data Quality Policy",
        "rule_type": "quality",
        "target_column": "email",
        "operator": "NOT LIKE",
        "value": "%@%.%",
        "data_type": "string",
        "confidence": 0.85,
    },
]


def main():
    parser = argparse.ArgumentParser(description="Run compliance data scan")
    parser.add_argument("--db", default="data/HI-Small_Trans.db", help="Path to SQLite database")
    parser.add_argument("--rules", help="Path to JSON file with structured rules")
    parser.add_argument("--violations-db", default="violations.db", help="Path for violations log DB")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per batch")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    if args.rules:
        with open(args.rules) as f:
            rules = json.load(f)
    else:
        rules = DEFAULT_RULES

    conn = SQLiteConnector(str(db_path))
    conn.connect()
    schema = conn.discover_schema()
    conn.close()

    state = {
        "db_type": "sqlite",
        "db_config": {"db_path": str(db_path)},
        "schema_metadata": schema,
        "structured_rules": rules,
        "violations_db_path": args.violations_db,
        "batch_size": args.batch_size,
    }

    print(f"Scanning {db_path} with {len(rules)} rules across {len(schema)} tables...")
    result = data_scanning_stage(state)

    summary = result["scan_summary"]
    print(f"\nScan complete: {result['scan_id']}")
    print(f"  Status: {summary['status']}")
    print(f"  Total violations: {summary['total_violations']}")
    print(f"  Tables scanned: {summary['tables_scanned']}")
    print(f"  Rules processed: {summary['rules_processed']}")
    if summary.get("violations_by_table"):
        print("  Violations by table:", summary["violations_by_table"])
    if summary.get("violations_by_rule"):
        print("  Violations by rule:", summary["violations_by_rule"])

    return 0


if __name__ == "__main__":
    exit(main())
