from __future__ import annotations

from runacross import ConfigError, RunAcrossError


def test_config_error_is_runacross_error_not_value_error() -> None:
    error = ConfigError("discovery failed")

    assert isinstance(error, RunAcrossError)
    assert isinstance(error, Exception)
    assert not isinstance(error, ValueError)
    assert not isinstance(error, TypeError)
