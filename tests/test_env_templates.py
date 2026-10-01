"""Keep public dotenv templates aligned with the active PIER-only runtime."""

from pathlib import Path

from dotenv import dotenv_values

from botragram.app.settings.env_validator import validate_env_file
from botragram.enums import StrategyType

__all__ = []

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = (
    ".env.example",
    ".env.testnet.example",
    ".env.mainnet.example",
)
_REMOVED_STRATEGY_PREFIXES = (
    "CHOCH_",
    "CRBB_",
    "HCE_",
    "LSE_",
    "MORPH_",
    "NY_RANGE_",
    "ORIGIN_",
    "SCALPING_",
    "SWING_",
    "TREND_",
)


def test_public_env_templates_have_unique_keys() -> None:
    """Reject duplicate dotenv keys before an operator copies a template."""
    for name in _TEMPLATES:
        validate_env_file(str(_ROOT / name))


def test_base_env_template_selects_only_pier() -> None:
    """Keep deleted strategies out of the active configuration template."""
    values = dotenv_values(_ROOT / ".env.example")

    assert values["STRATEGY_TYPE"] == StrategyType.PINBAR_ENGULFING_EMA_RSI.value
    assert not any(key.startswith(_REMOVED_STRATEGY_PREFIXES) for key in values)
