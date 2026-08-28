from __future__ import annotations

import sys
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one replacement in {path}: found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: apply_telegram_command_registry_cleanup.py <target-root>"
        )

    root = Path(sys.argv[1]).resolve()
    bot_path = root / "botragram/telegram/bot.py"
    test_path = root / "tests/test_telegram.py"

    replace_once(
        bot_path,
        '__all__ = ["TelegramBot"]\n\n_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)\n_TRADING_MODE_SWITCHED_MESSAGE: Final[str] = "Trading Mode Switched"\n',
        '__all__ = ["TelegramBot", "get_bot_commands"]\n\n_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)\n_TRADING_MODE_SWITCHED_MESSAGE: Final[str] = "Trading Mode Switched"\n\n\ndef get_bot_commands() -> tuple[BotCommand, ...]:\n    """Return the unique public Telegram command registry."""\n    commands = (\n        BotCommand("start", "Mulai bot dan tampilkan menu utama"),\n        BotCommand("status", "Lihat status bot dan pasar"),\n        BotCommand("positions", "Lihat posisi trading aktif"),\n        BotCommand("balance", "Lihat saldo paper tersedia"),\n        BotCommand("history", "Lihat riwayat paper trading"),\n        BotCommand("market", "Pilih pair crypto saat bot dijeda"),\n        BotCommand("strategy", "Pilih strategy saat bot dijeda"),\n        BotCommand("interval", "Pilih candle interval saat bot dijeda"),\n        BotCommand("stream", "Kelola market ticker stream"),\n        BotCommand("pause", "Jeda siklus trading baru"),\n        BotCommand("resume", "Lanjutkan siklus trading"),\n        BotCommand("risklimits", "Lihat limit entry runtime"),\n        BotCommand("setrisklimits", "Ubah limit runtime saat dijeda"),\n        BotCommand("exitstatus", "Lihat status operator exit"),\n        BotCommand("closeposition", "Tutup satu posisi saat PAUSED"),\n        BotCommand("closeall", "Tutup semua posisi saat PAUSED"),\n        BotCommand("closeandswitch", "Flatten lalu ganti trading mode"),\n        BotCommand("confirmexit", "Konfirmasi operator exit"),\n        BotCommand("cancelexit", "Batalkan konfirmasi operator exit"),\n        BotCommand("settings", "Lihat pengaturan bot"),\n        BotCommand("exchange", "Lihat exchange aktif"),\n        BotCommand("stop", "Lihat status penghentian bot"),\n    )\n    names = tuple(command.command for command in commands)\n    if len(names) != len(set(names)):\n        raise RuntimeError("Telegram command registry contains duplicate commands")\n    return commands\n',
    )

    old_registry = '''            await app.bot.set_my_commands(
                [
                    BotCommand("start", "Mulai bot dan tampilkan menu utama"),
                    BotCommand("status", "Lihat status bot dan pasar"),
                    BotCommand("positions", "Lihat posisi trading aktif"),
                    BotCommand("balance", "Lihat saldo paper tersedia"),
                    BotCommand("history", "Lihat riwayat paper trading"),
                    BotCommand("market", "Pilih pair crypto saat bot dijeda"),
                    BotCommand("strategy", "Pilih strategy saat bot dijeda"),
                    BotCommand("interval", "Pilih candle interval saat bot dijeda"),
                    BotCommand("stream", "Kelola market ticker stream"),
                    BotCommand("pause", "Jeda siklus trading baru"),
                    BotCommand("resume", "Lanjutkan siklus trading"),
                    BotCommand("risklimits", "Lihat limit entry runtime"),
                    BotCommand("exitstatus", "Lihat status operator exit"),
                    BotCommand("closeposition", "Tutup satu posisi saat PAUSED"),
                    BotCommand("closeall", "Tutup semua posisi saat PAUSED"),
                    BotCommand("closeandswitch", "Flatten lalu ganti trading mode"),
                    BotCommand("setrisklimits", "Ubah limit runtime saat dijeda"),
                    BotCommand("exitstatus", "Lihat status operator exit"),
                    BotCommand("closeposition", "Minta tutup satu posisi"),
                    BotCommand("closeall", "Minta tutup semua posisi"),
                    BotCommand("closeandswitch", "Flatten lalu ganti trading mode"),
                    BotCommand("confirmexit", "Konfirmasi operator exit"),
                    BotCommand("cancelexit", "Batalkan konfirmasi operator exit"),
                    BotCommand("settings", "Lihat pengaturan bot"),
                    BotCommand("exchange", "Lihat exchange aktif"),
                    BotCommand("stop", "Lihat status penghentian bot"),
                ]
            )
'''
    replace_once(
        bot_path,
        old_registry,
        "            await app.bot.set_my_commands(get_bot_commands())\n",
    )

    replace_once(
        test_path,
        "from botragram.telegram.context import BotContext\n",
        "from botragram.telegram.bot import get_bot_commands\n"
        "from botragram.telegram.context import BotContext\n",
    )

    test_anchor = '''# =============================================================================
# Mode-aware Menu Tests
# =============================================================================
'''
    test_block = '''# =============================================================================
# Command Registry Tests
# =============================================================================
def test_public_bot_command_registry_is_unique_and_complete() -> None:
    """Expose every operator command exactly once to Telegram clients."""
    commands = get_bot_commands()
    names = tuple(command.command for command in commands)

    assert len(names) == len(set(names))
    assert {
        "exitstatus",
        "closeposition",
        "closeall",
        "closeandswitch",
        "confirmexit",
        "cancelexit",
    } <= set(names)


'''
    replace_once(test_path, test_anchor, test_block + test_anchor)

    print("Telegram command registry cleanup applied")


if __name__ == "__main__":
    main()
