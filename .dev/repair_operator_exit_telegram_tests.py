from __future__ import annotations

import sys
from pathlib import Path


def replace_exact(text: str, old: str, new: str, *, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise SystemExit(
            f"Expected {count} test replacement(s), found {actual}: {old.splitlines()[0]!r}"
        )
    return text.replace(old, new, count)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: repair_operator_exit_telegram_tests.py <target-root>"
        )

    path = (
        Path(sys.argv[1]).resolve()
        / "tests/test_telegram_operator_exit_ui.py"
    )
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        "    ExecutionPolicy,\n",
        "    ExecutionPolicy,\n    MarketType,\n",
    )
    text = text.replace("def _challenge(\n", "def challenge(\n")
    text = text.replace("self._challenge(\n", "self.challenge(\n")
    text = text.replace("_OperatorService(typed=True)._challenge(\n", "_OperatorService(typed=True).challenge(\n")

    text = replace_exact(
        text,
        "    async def prepare(self, *, market_type: object) -> bool:\n"
        "        del market_type\n"
        "        return False\n\n"
        "    def commit(self, *, market_type: object) -> None:\n"
        "        del market_type\n",
        "    async def prepare(self, *, market_type: MarketType) -> bool:\n"
        "        del market_type\n"
        "        return False\n\n"
        "    def commit(self, *, market_type: MarketType) -> None:\n"
        "        del market_type\n",
    )

    text = replace_exact(
        text,
        "                query_provider=cast(object, _QueryProvider()),\n"
        "                runtime_control=TradingRuntimeControl(),\n"
        "                market_type_switcher=(\n"
        "                    cast(object, switcher)\n"
        "                    if switcher is not None\n"
        "                    else None\n"
        "                ),\n",
        "                positions=(_position(),),\n"
        "                runtime_control=TradingRuntimeControl(),\n"
        "                market_type_switcher=switcher,\n",
    )

    callback_set = (
        "        callbacks = {\n"
        "            button.callback_data\n"
        "            for row in markup.inline_keyboard\n"
        "            for button in row\n"
        "        }\n"
    )
    callback_set_typed = (
        "        callbacks = {\n"
        "            button.callback_data\n"
        "            for row in markup.inline_keyboard\n"
        "            for button in row\n"
        "            if isinstance(button.callback_data, str)\n"
        "        }\n"
    )
    text = replace_exact(text, callback_set, callback_set_typed, count=3)

    confirmation_set = (
        "        confirmation_callbacks = {\n"
        "            button.callback_data\n"
        "            for row in confirmation_markup.inline_keyboard\n"
        "            for button in row\n"
        "        }\n"
    )
    confirmation_set_typed = (
        "        confirmation_callbacks = {\n"
        "            button.callback_data\n"
        "            for row in confirmation_markup.inline_keyboard\n"
        "            for button in row\n"
        "            if isinstance(button.callback_data, str)\n"
        "        }\n"
    )
    text = replace_exact(text, confirmation_set, confirmation_set_typed)

    path.write_text(text, encoding="utf-8", newline="\n")
    print("Telegram operator-exit UI tests made strictly typed")


if __name__ == "__main__":
    main()
