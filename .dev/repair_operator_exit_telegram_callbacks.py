from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: repair_operator_exit_telegram_callbacks.py <target-root>"
        )

    root = Path(sys.argv[1]).resolve()
    path = root / "botragram/telegram/callbacks.py"
    text = path.read_text(encoding="utf-8")

    anchor = """        try:
            changed = await switcher.prepare_execution_policy(
                execution_policy=target,
            )
"""
    anchor_index = text.find(anchor)
    if anchor_index < 0:
        raise SystemExit("Execution-policy prepare block was not found")

    search_start = anchor_index + len(anchor)
    match = re.search(
        r"(?m)^ +except Exception as error:\r?\n",
        text[search_start:],
    )
    if match is None:
        raise SystemExit("Execution-policy exception block was not found")
    start = search_start + match.start()

    end_marker = "        if not changed:\n"
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit("Execution-policy post-validation block was not found")

    replacement = '''        except Exception as error:
            _LOGGER.exception(
                "Telegram execution-policy switch validation failed"
            )
            operator_service = bot_context.operator_exit_service
            positions = ()
            if operator_service is not None:
                try:
                    positions = tuple(await operator_service.get_positions())
                except Exception:
                    _LOGGER.exception(
                        "Telegram operator-exit position lookup failed"
                    )
            if positions:
                await query.edit_message_text(
                    f"⚠️ <b>{escape(str(error))}</b>\\n\\n"
                    f"{len(positions)} active position(s) block this switch. "
                    "Botragram can flatten them through the guarded "
                    "operator-exit workflow and switch only after zero "
                    "exposure is verified.",
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_operator_flatten_switch_keyboard(
                        execution_policy=target,
                    ),
                )
                return
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_execution_policy_keyboard(
                    current_policy=bot_context.execution_policy,
                    available_policies=switcher.available_execution_policies(),
                ),
            )
            return
'''
    path.write_text(
        text[:start] + replacement + text[end:],
        encoding="utf-8",
        newline="\n",
    )
    print("Telegram execution-policy callback block repaired")


if __name__ == "__main__":
    main()
