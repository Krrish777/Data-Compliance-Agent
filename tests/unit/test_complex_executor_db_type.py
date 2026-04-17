from unittest.mock import patch, MagicMock
from src.agents.tools.database.complex_executor import scan_complex_rule


def test_scan_complex_rule_passes_db_type_to_log_violation():
    captured_db_types: list[str] = []

    def fake_log_violation(**kwargs):
        captured_db_types.append(kwargs.get("db_type"))
        return 1

    rule = MagicMock()
    rule.rule_id = "r1"
    rule.rule_type = "data_quality"
    rule.rule_text = "t"
    rule.applies_to_tables = ["x"]
    rule.rule_complexity = "between"

    # fake_evaluator returns True so log_violation is called for every row
    def fake_evaluator(rule, row):
        return True

    with patch(
        "src.agents.tools.database.complex_executor.log_violation",
        side_effect=fake_log_violation,
    ), patch(
        "src.agents.tools.database.complex_executor._fetch_batch",
        return_value=([{"id": 1, "col": "bad"}], None),
    ), patch.dict(
        "src.agents.tools.database.complex_executor._EVALUATORS",
        {"between": fake_evaluator},
    ):
        scan_complex_rule(
            session=MagicMock(),
            violations_session=MagicMock(),
            rule=rule,
            table="x",
            pk_column="id",
            scan_id="s1",
            db_type="postgresql",
        )

    assert (
        "postgresql" in captured_db_types
    ), f"db_type not propagated; saw: {captured_db_types}"
