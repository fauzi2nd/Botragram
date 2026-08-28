from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_operator_exit_recovery_hardening.py TARGET")
    root = Path(sys.argv[1])

    path = root / "botragram/exchanges/base/client.py"
    text = path.read_text(encoding="utf-8")
    old = '''    @abstractmethod\n    async def close_position(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str | None = None,\n    ) -> Order:\n        \"\"\"Close the active position with an optional durable client identity.\"\"\"\n\n    @abstractmethod\n    async def close_all_positions(self) -> Sequence[Order]:\n'''
    new = '''    @abstractmethod\n    async def close_position(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str | None = None,\n    ) -> Order:\n        \"\"\"Close the active position with an optional durable client identity.\"\"\"\n\n    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        \"\"\"Close from one already-authoritative durable position snapshot.\n\n        Connectors that cannot guarantee the exact single-mutation boundary fail\n        closed. Product-specific clients may override this for durable operator\n        workflows that must not perform a second position lookup before POST.\n        \"\"\"\n        del position, client_order_id\n        raise NotImplementedError(\n            \"Exact position-snapshot closing is not supported\"\n        )\n\n    @abstractmethod\n    async def close_all_positions(self) -> Sequence[Order]:\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/exchanges/binance/futures_client.py"
    text = path.read_text(encoding="utf-8")
    old = '''    async def close_all_positions(self) -> Sequence[Order]:\n        \"\"\"Close all active one-way Futures positions.\"\"\"\n        positions = await self.get_positions()\n        closed: list[Order] = []\n\n        for position in positions:\n            closed.append(await self._close_position(position))\n\n        return tuple(closed)\n\n    def _build_order_params(\n'''
    new = '''    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        \"\"\"Submit one reduce-only close from an authoritative snapshot.\"\"\"\n        return await self._close_position(\n            position,\n            client_order_id=self._normalize_client_order_id(client_order_id),\n        )\n\n    async def close_all_positions(self) -> Sequence[Order]:\n        \"\"\"Close all active one-way Futures positions.\"\"\"\n        positions = await self.get_positions()\n        closed: list[Order] = []\n\n        for position in positions:\n            closed.append(await self._close_position(position))\n\n        return tuple(closed)\n\n    def _build_order_params(\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/services/operator_exit_service.py"
    text = path.read_text(encoding="utf-8")
    old = '''    async def close_position(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str | None = None,\n    ) -> Order:\n        \"\"\"Submit one reduce-only close with a durable client identity.\"\"\"\n        ...\n'''
    new = '''    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        \"\"\"Submit one reduce-only close from the durable position snapshot.\"\"\"\n        ...\n'''
    text = replace_once(text, old, new, label=f"{path}: protocol")
    old = '''        except Exception as error:\n            await self._mark_recovery_required(\n                operation=operation,\n                reason=str(error),\n            )\n            self._start_background_recovery()\n'''
    new = '''        except Exception as error:\n            try:\n                await self._mark_recovery_required(\n                    operation=operation,\n                    reason=str(error),\n                )\n            finally:\n                self._start_background_recovery()\n'''
    text = replace_once(text, old, new, label=f"{path}: background recovery")
    old = '''                order = await exchange.close_position(\n                    symbol=attempt.symbol,\n                    client_order_id=attempt.client_order_id,\n                )\n'''
    new = '''                order = await exchange.close_position_exact(\n                    position=authoritative,\n                    client_order_id=attempt.client_order_id,\n                )\n'''
    text = replace_once(text, old, new, label=f"{path}: exact close")
    path.write_text(text, encoding="utf-8")

    path = root / "tests/test_binance_futures.py"
    text = path.read_text(encoding="utf-8")
    old = "from botragram.models import MarketUniverseEntry, Order\n"
    new = "from botragram.models import MarketUniverseEntry, Order, Position\n"
    text = replace_once(text, old, new, label=f"{path}: imports")
    anchor = '''@pytest.mark.asyncio\nasync def test_futures_client_reads_and_closes_short_position() -> None:\n'''
    if anchor not in text:
        raise RuntimeError(f"{path}: close-position test anchor missing")
    insert_at = text.index(anchor)
    new_test = '''@pytest.mark.asyncio\nasync def test_futures_exact_close_uses_snapshot_without_position_lookup() -> None:\n    \"\"\"Do not insert a second position GET between durable intent and POST.\"\"\"\n    rest = RecordingBinanceRestClient()\n    rest.response = {\n        \"orderId\": 43,\n        \"clientOrderId\": \"bop-0123456789abcdef0123456789abcdef\",\n        \"symbol\": \"BTCUSDT\",\n        \"side\": \"BUY\",\n        \"type\": \"MARKET\",\n        \"status\": \"FILLED\",\n        \"origQty\": \"0.02\",\n        \"executedQty\": \"0.02\",\n        \"price\": \"0\",\n        \"stopPrice\": \"0\",\n        \"updateTime\": 1_700_000_000_000,\n        \"time\": 1_700_000_000_000,\n    }\n    client = _create_client(rest)\n    position = Position(\n        symbol=\"BTCUSDT\",\n        side=PositionSide.SHORT,\n        quantity=Decimal(\"0.02\"),\n        entry_price=Decimal(\"50000\"),\n        current_price=Decimal(\"49000\"),\n        unrealized_pnl=Decimal(\"20\"),\n        leverage=2,\n        opened_at=_NOW,\n        updated_at=_NOW,\n    )\n\n    order = await client.close_position_exact(\n        position=position,\n        client_order_id=\"bop-0123456789abcdef0123456789abcdef\",\n    )\n\n    assert order.client_order_id == \"bop-0123456789abcdef0123456789abcdef\"\n    assert len(rest.requests) == 1\n    method, request_path, params, authenticated = rest.requests[0]\n    assert method == \"POST\"\n    assert request_path == \"/fapi/v1/order\"\n    assert authenticated\n    assert params is not None\n    assert params[\"symbol\"] == \"BTCUSDT\"\n    assert params[\"side\"] == \"BUY\"\n    assert params[\"quantity\"] == \"0.02\"\n    assert params[\"reduceOnly\"] == \"true\"\n    assert (\n        params[\"newClientOrderId\"]\n        == \"bop-0123456789abcdef0123456789abcdef\"\n    )\n\n\n'''
    text = text[:insert_at] + new_test + text[insert_at:]
    path.write_text(text, encoding="utf-8")

    print("operator-exit recovery hardening applied")


if __name__ == "__main__":
    main()
