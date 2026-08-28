from __future__ import annotations

from pathlib import Path

path = Path(__file__).with_name("apply_operator_exit_telegram_ux.py")
text = path.read_text(encoding="utf-8")
old = '''    # Flatten-and-switch remains the sole command path allowed to auto-pause.\n    needle = """        challenge = await service.request_close_all(\n            requested_by=requester,\n            target_execution_policy=target,\n            auto_pause=False,\n        )\n"""\n    if needle not in text:\n        raise RuntimeError("Expected flatten-and-switch request block after normalization")\n    text = text.replace(needle, needle.replace("auto_pause=False", "auto_pause=True"), 1)\n'''
new = '''    # Flatten-and-switch is the third request path and must retain auto-pause.\n    flatten_block = """        challenge = await service.request_close_all(\n            requested_by=requester,\n            target_execution_policy=target,\n            auto_pause=True,\n        )\n"""\n    if flatten_block not in text:\n        raise RuntimeError("Flatten-and-switch must remain the sole auto-pause exit path")\n'''
if old not in text:
    raise SystemExit("Telegram UX validator block was not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
print("Telegram UX patch validator corrected")
