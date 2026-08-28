from __future__ import annotations

import sys
from pathlib import Path


def replace_once(*, root: Path, path: str, old: str, new: str) -> None:
    target = root / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def patch_cache(root: Path) -> None:
    path = "botragram/services/live_futures_user_data_cache.py"
    replace_once(
        root=root,
        path=path,
        old='''    async def apply(self, *, event: FuturesUserDataEvent) -> None:\n        """Apply one normalized private-stream event to the local cache."""\n        async with self._lock:\n            match event:\n                case FuturesUserDataStreamConnected():\n                    return\n                case FuturesUserDataAlgoUpdate():\n                    self._recent_algo_updates.append(event)\n                case FuturesUserDataAccountUpdate():\n                    for balance in event.balances:\n                        self._balances[balance.asset.upper()] = balance.free\n                        self._wallet_balances[balance.asset.upper()] = (\n                            balance.free + balance.locked\n                        )\n                    for position in event.positions:\n                        self._apply_position_update(\n                            position=position, observed_at=event.observed_at\n                        )\n                case FuturesUserDataOrderUpdate():\n                    self._recent_orders.append(event.order)\n            self._last_event_at = event.observed_at\n            self._status = LiveFuturesUserDataStatus.READY\n''',
        new='''    async def apply(\n        self,\n        *,\n        event: FuturesUserDataEvent,\n    ) -> frozenset[str]:\n        """Apply one private event and report positions needing REST reseed."""\n        unseeded_position_symbols: set[str] = set()\n        async with self._lock:\n            match event:\n                case FuturesUserDataStreamConnected():\n                    return frozenset()\n                case FuturesUserDataAlgoUpdate():\n                    self._recent_algo_updates.append(event)\n                case FuturesUserDataAccountUpdate():\n                    for balance in event.balances:\n                        self._balances[balance.asset.upper()] = balance.free\n                        self._wallet_balances[balance.asset.upper()] = (\n                            balance.free + balance.locked\n                        )\n                    for position in event.positions:\n                        if self._apply_position_update(\n                            position=position, observed_at=event.observed_at\n                        ):\n                            unseeded_position_symbols.add(position.symbol.upper())\n                case FuturesUserDataOrderUpdate():\n                    self._recent_orders.append(event.order)\n            self._last_event_at = event.observed_at\n            self._status = (\n                LiveFuturesUserDataStatus.RESYNCING\n                if unseeded_position_symbols\n                else LiveFuturesUserDataStatus.READY\n            )\n        return frozenset(unseeded_position_symbols)\n''',
    )
    replace_once(
        root=root,
        path=path,
        old='''            return collateral + sum(\n                (position.unrealized_pnl for position in self._positions.values()),\n                start=_DECIMAL_ZERO,\n            )\n''',
        new='''            return collateral + sum(\n                (\n                    position_update.unrealized_pnl\n                    for position_update in self._position_updates.values()\n                ),\n                start=_DECIMAL_ZERO,\n            )\n''',
    )
    replace_once(
        root=root,
        path=path,
        old='''    def _apply_position_update(\n        self,\n        *,\n        position: FuturesUserDataPositionUpdate,\n        observed_at: datetime,\n    ) -> None:\n        """Keep both position views synchronized with one account update."""\n        normalized_symbol = position.symbol.upper()\n        if position.quantity == _DECIMAL_ZERO:\n            self._position_updates.pop(normalized_symbol, None)\n            self._positions.pop(normalized_symbol, None)\n            return\n\n        self._position_updates[normalized_symbol] = position\n        existing_position = self._positions.get(normalized_symbol)\n        quantity = abs(position.quantity)\n        side = (\n            PositionSide.LONG\n            if position.quantity > _DECIMAL_ZERO\n            else PositionSide.SHORT\n        )\n        if existing_position is None:\n            self._positions[normalized_symbol] = Position(\n                symbol=position.symbol,\n                side=side,\n                quantity=quantity,\n                entry_price=position.entry_price,\n                current_price=position.entry_price,\n                unrealized_pnl=position.unrealized_pnl,\n                leverage=1,\n                opened_at=observed_at,\n                updated_at=observed_at,\n            )\n            return\n\n        self._positions[normalized_symbol] = replace(\n            existing_position,\n            side=side,\n            quantity=quantity,\n            entry_price=position.entry_price,\n            unrealized_pnl=position.unrealized_pnl,\n            updated_at=observed_at,\n        )\n''',
        new='''    def _apply_position_update(\n        self,\n        *,\n        position: FuturesUserDataPositionUpdate,\n        observed_at: datetime,\n    ) -> bool:\n        """Overlay a streamed position only when REST seeded its leverage."""\n        normalized_symbol = position.symbol.upper()\n        if position.quantity == _DECIMAL_ZERO:\n            self._position_updates.pop(normalized_symbol, None)\n            self._positions.pop(normalized_symbol, None)\n            return False\n\n        self._position_updates[normalized_symbol] = position\n        existing_position = self._positions.get(normalized_symbol)\n        if existing_position is None:\n            return True\n\n        quantity = abs(position.quantity)\n        side = (\n            PositionSide.LONG\n            if position.quantity > _DECIMAL_ZERO\n            else PositionSide.SHORT\n        )\n        self._positions[normalized_symbol] = replace(\n            existing_position,\n            side=side,\n            quantity=quantity,\n            entry_price=position.entry_price,\n            unrealized_pnl=position.unrealized_pnl,\n            updated_at=observed_at,\n        )\n        return False\n''',
    )


def patch_service(root: Path) -> None:
    path = "botragram/app/live_futures_user_data_service.py"
    replace_once(
        root=root,
        path=path,
        old='''                    await self.cache.apply(event=event)\n                    if isinstance(event, FuturesUserDataAccountUpdate):\n                        await self._observe_current_equity()\n''',
        new='''                    unseeded_symbols = await self.cache.apply(event=event)\n                    if unseeded_symbols:\n                        await self._reseed_unseeded_positions(\n                            symbols=unseeded_symbols\n                        )\n                    if isinstance(event, FuturesUserDataAccountUpdate):\n                        await self._observe_current_equity()\n''',
    )
    replace_once(
        root=root,
        path=path,
        old='''    async def _refresh_snapshot(self, *, clear_recent_orders: bool) -> None:\n        """Refresh only after startup or loss of private-stream continuity."""\n        account = await self.snapshot_provider.get_account()\n        positions = await self.snapshot_provider.get_positions()\n        await self.cache.initialize(\n            account=account,\n            positions=positions,\n            clear_recent_orders=clear_recent_orders,\n        )\n\n    def _get_reconnect_delay(self, *, attempt: int) -> float:\n''',
        new='''    async def _refresh_snapshot(self, *, clear_recent_orders: bool) -> None:\n        """Refresh only after startup or loss of private-stream continuity."""\n        account = await self.snapshot_provider.get_account()\n        positions = await self.snapshot_provider.get_positions()\n        await self.cache.initialize(\n            account=account,\n            positions=positions,\n            clear_recent_orders=clear_recent_orders,\n        )\n\n    async def _reseed_unseeded_positions(self, *, symbols: frozenset[str]) -> None:\n        """Resolve streamed new exposure only through an authoritative REST read."""\n        self._status = LiveFuturesUserDataStatus.RESYNCING\n        await self._refresh_snapshot(clear_recent_orders=False)\n        snapshot = await self.cache.get_snapshot()\n        authoritative_symbols = {\n            position.symbol.upper() for position in snapshot.positions\n        }\n        missing_symbols = tuple(sorted(symbols - authoritative_symbols))\n        if missing_symbols:\n            await self.cache.mark_resyncing()\n            raise RuntimeError(\n                "Binance Futures REST snapshot did not confirm streamed position(s): "\n                + ", ".join(missing_symbols)\n            )\n        self._status = LiveFuturesUserDataStatus.READY\n\n    def _get_reconnect_delay(self, *, attempt: int) -> float:\n''',
    )


def patch_tests(root: Path) -> None:
    path = "tests/test_live_futures_user_data_service.py"
    replace_once(
        root=root,
        path=path,
        old='''        leverage=1,\n''',
        new='''        leverage=7,\n''',
    )
    replace_once(
        root=root,
        path=path,
        old='''    assert snapshot.positions[0].quantity == Decimal("2")\n    assert snapshot.position_updates[0].quantity == Decimal("2")\n''',
        new='''    assert snapshot.positions[0].quantity == Decimal("2")\n    assert snapshot.positions[0].leverage == 7\n    assert snapshot.position_updates[0].quantity == Decimal("2")\n''',
    )
    marker = '''\n\n@pytest.mark.asyncio\nasync def test_user_data_cache_exposes_resync_and_stale_freshness() -> None:\n'''
    block = '''\n\n@dataclass(slots=True)\nclass EmergingPositionSnapshotProvider:\n    """Expose a new REST position only after the stream observes exposure."""\n\n    account_calls: int = 0\n    position_calls: int = 0\n\n    async def get_account(self) -> Account:\n        self.account_calls += 1\n        return Account(\n            balances=(\n                Balance(asset="USDT", free=Decimal("100"), locked=Decimal("0")),\n            )\n        )\n\n    async def get_positions(self, *, symbol: str | None = None) -> Sequence[Position]:\n        assert symbol is None\n        self.position_calls += 1\n        if self.position_calls == 1:\n            return ()\n        return (\n            Position(\n                symbol="BTCUSDT",\n                side=PositionSide.LONG,\n                quantity=Decimal("2"),\n                entry_price=Decimal("100"),\n                current_price=Decimal("101"),\n                unrealized_pnl=Decimal("4"),\n                leverage=7,\n                opened_at=_NOW,\n                updated_at=_NOW,\n                interval=Interval.M1,\n            ),\n        )\n\n\n@pytest.mark.asyncio\nasync def test_new_streamed_position_reseeds_authoritative_rest_leverage() -> None:\n    account_update = FuturesUserDataAccountUpdate(\n        observed_at=_NOW,\n        balances=(Balance(asset="USDT", free=Decimal("125"), locked=Decimal("0")),),\n        positions=(\n            FuturesUserDataPositionUpdate(\n                symbol="BTCUSDT",\n                quantity=Decimal("2"),\n                entry_price=Decimal("100"),\n                unrealized_pnl=Decimal("4"),\n            ),\n        ),\n    )\n    stream = FakeEventStream(\n        events=(\n            FuturesUserDataStreamConnected(observed_at=_NOW),\n            account_update,\n        )\n    )\n    snapshots = EmergingPositionSnapshotProvider()\n    service = LiveFuturesUserDataService(\n        snapshot_provider=snapshots,\n        event_stream=stream,\n    )\n\n    await service.start()\n    await stream.delivered.wait()\n\n    snapshot = await service.get_snapshot()\n    assert snapshots.account_calls == 2\n    assert snapshots.position_calls == 2\n    assert service.status is LiveFuturesUserDataStatus.READY\n    assert snapshot.status is LiveFuturesUserDataStatus.READY\n    assert snapshot.positions[0].quantity == Decimal("2")\n    assert snapshot.positions[0].leverage == 7\n\n    await service.close()\n\n\n@pytest.mark.asyncio\nasync def test_unseeded_stream_position_never_fabricates_leverage() -> None:\n    cache = LiveFuturesUserDataCache()\n    await cache.initialize(\n        account=Account(\n            balances=(\n                Balance(asset="USDT", free=Decimal("100"), locked=Decimal("0")),\n            )\n        ),\n        positions=(),\n        clear_recent_orders=True,\n    )\n\n    unseeded_symbols = await cache.apply(\n        event=FuturesUserDataAccountUpdate(\n            observed_at=_NOW,\n            balances=(),\n            positions=(\n                FuturesUserDataPositionUpdate(\n                    symbol="BTCUSDT",\n                    quantity=Decimal("1"),\n                    entry_price=Decimal("100"),\n                    unrealized_pnl=Decimal("1"),\n                ),\n            ),\n        )\n    )\n\n    snapshot = await cache.get_snapshot()\n    assert unseeded_symbols == frozenset({"BTCUSDT"})\n    assert snapshot.status is LiveFuturesUserDataStatus.RESYNCING\n    assert snapshot.positions == ()\n    assert snapshot.position_updates[0].symbol == "BTCUSDT"\n    with pytest.raises(RuntimeError, match="cache is not ready"):\n        await cache.get_equity(asset="USDT")\n'''
    replace_once(root=root, path=path, old=marker, new=block + marker)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_authoritative_live_leverage_cache.py <target-root>")
    root = Path(sys.argv[1]).resolve()
    patch_cache(root)
    patch_service(root)
    patch_tests(root)
    print("Authoritative LIVE leverage cache patch applied")


if __name__ == "__main__":
    main()
