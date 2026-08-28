"""Process-boundary shutdown presentation regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

import pytest

import main as main_module

type _MainCoroutine = Coroutine[object, object, None]


def test_run_treats_keyboard_interrupt_as_intentional_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return normally when asyncio reports the operator's Ctrl+C."""

    def raise_keyboard_interrupt(coroutine: _MainCoroutine) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module.asyncio, "run", raise_keyboard_interrupt)

    main_module.run()


def test_run_does_not_swallow_ordinary_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep genuine startup and runtime tracebacks visible at the process edge."""
    failure = RuntimeError("configured process failure")

    def raise_failure(coroutine: _MainCoroutine) -> None:
        coroutine.close()
        raise failure

    monkeypatch.setattr(main_module.asyncio, "run", raise_failure)

    with pytest.raises(RuntimeError) as captured:
        main_module.run()

    assert captured.value is failure


def test_run_does_not_swallow_async_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve cancellation propagation below the KeyboardInterrupt boundary."""
    cancellation = asyncio.CancelledError()

    def raise_cancellation(coroutine: _MainCoroutine) -> None:
        coroutine.close()
        raise cancellation

    monkeypatch.setattr(main_module.asyncio, "run", raise_cancellation)

    with pytest.raises(asyncio.CancelledError) as captured:
        main_module.run()

    assert captured.value is cancellation
