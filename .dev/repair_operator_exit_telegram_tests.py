from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_exact(text: str, old: str, new: str, *, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise SystemExit(
            f"Expected {count} test replacement(s), found {actual}: {old.splitlines()[0]!r}"
        )
    return text.replace(old, new, count)


def sub_exact(
    text: str,
    pattern: re.Pattern[str],
    replacement: str,
    *,
    count: int = 1,
) -> str:
    updated, actual = pattern.subn(replacement, text, count=count)
    if actual != count:
        raise SystemExit(
            f"Expected {count} regex replacement(s), found {actual}: {pattern.pattern!r}"
        )
    return updated


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: repair_operator_exit_telegram_tests.py <target-root>"
        )

    path = Path(sys.argv[1]).resolve() / "tests/test_telegram_operator_exit_ui.py"
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        "    ExecutionPolicy,\n",
        "    ExecutionPolicy,\n    MarketType,\n",
    )
    text = text.replace("def _challenge(\n", "def challenge(\n")
    text = text.replace("self._challenge(\n", "self.challenge(\n")
    text = text.replace(
        "_OperatorService(typed=True)._challenge(\n",
        "_OperatorService(typed=True).challenge(\n",
    )

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

    query_provider_pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)query_provider=cast\(object, _QueryProvider\(\)\),\n"
    )
    match = query_provider_pattern.search(text)
    if match is None:
        raise SystemExit("Generated query_provider fixture line was not found")
    query_indent = match.group("indent")
    text = sub_exact(
        text,
        query_provider_pattern,
        f"{query_indent}positions=(_position(),),\n",
    )

    switcher_pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)market_type_switcher=\(\n"
        r"[ \t]+cast\(object, switcher\)\n"
        r"[ \t]+if switcher is not None\n"
        r"[ \t]+else None\n"
        r"(?P=indent)\),\n"
    )
    match = switcher_pattern.search(text)
    if match is None:
        raise SystemExit("Generated market_type_switcher fixture block was not found")
    switcher_indent = match.group("indent")
    text = sub_exact(
        text,
        switcher_pattern,
        f"{switcher_indent}market_type_switcher=switcher,\n",
    )

    callbacks_pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)callbacks = \{\n"
        r"(?P=indent)    button\.callback_data\n"
        r"(?P=indent)    for row in markup\.inline_keyboard\n"
        r"(?P=indent)    for button in row\n"
        r"(?P=indent)\}\n"
    )

    def add_callback_narrowing(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}callbacks = {{\n"
            f"{indent}    button.callback_data\n"
            f"{indent}    for row in markup.inline_keyboard\n"
            f"{indent}    for button in row\n"
            f"{indent}    if isinstance(button.callback_data, str)\n"
            f"{indent}}}\n"
        )

    text, callback_count = callbacks_pattern.subn(add_callback_narrowing, text)
    if callback_count != 3:
        raise SystemExit(
            f"Expected 3 callback set narrowings, found {callback_count}"
        )

    confirmation_pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)confirmation_callbacks = \{\n"
        r"(?P=indent)    button\.callback_data\n"
        r"(?P=indent)    for row in confirmation_markup\.inline_keyboard\n"
        r"(?P=indent)    for button in row\n"
        r"(?P=indent)\}\n"
    )

    def add_confirmation_narrowing(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}confirmation_callbacks = {{\n"
            f"{indent}    button.callback_data\n"
            f"{indent}    for row in confirmation_markup.inline_keyboard\n"
            f"{indent}    for button in row\n"
            f"{indent}    if isinstance(button.callback_data, str)\n"
            f"{indent}}}\n"
        )

    text, confirmation_count = confirmation_pattern.subn(
        add_confirmation_narrowing,
        text,
    )
    if confirmation_count != 1:
        raise SystemExit(
            "Expected 1 confirmation callback set narrowing, "
            f"found {confirmation_count}"
        )

    path.write_text(text, encoding="utf-8", newline="\n")
    print("Telegram operator-exit UI tests made strictly typed")


if __name__ == "__main__":
    main()
