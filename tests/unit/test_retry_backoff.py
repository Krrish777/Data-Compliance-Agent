from unittest.mock import patch
import pytest
from src.agents.middleware.retry import retry_with_backoff


def test_backoff_factor_is_exactly_two_x():
    sleeps: list[float] = []

    @retry_with_backoff(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
    def always_fail():
        raise ValueError("boom")

    with patch("src.agents.middleware.retry.time.sleep", side_effect=sleeps.append):
        with pytest.raises(ValueError):
            always_fail()

    assert sleeps == [2.0, 4.0, 8.0], f"expected [2, 4, 8], got {sleeps}"
