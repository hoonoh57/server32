import threading
import json
import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class SymbolState:
    code: str
    name: str = ""
    last_price: float = 0.0
    change: float = 0.0
    change_rate: float = 0.0
    volume: float = 0.0
    strength: float = 0.0
    prev_volume_ratio: float = 0.0
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandleCache:
    code: str
    series: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


class AppState:
    """Central state container for tester UI."""

    def __init__(self):
        self._lock = threading.RLock()
        self.symbols: Dict[str, SymbolState] = {}
        self.condition_hits: List[Dict[str, Any]] = []
        self.candles: Dict[Tuple[str, str], CandleCache] = {}
        self.dashboard: Dict[str, Any] = {}
        self.holdings: List[Dict[str, Any]] = []
        self.outstanding: List[Dict[str, Any]] = []
        self._dashboard_signature: str = ""

        self._condition_listeners: List[Callable[[List[Dict[str, Any]]], None]] = []
        self._symbol_listeners: List[Callable[[SymbolState], None]] = []
        self._candle_listeners: List[Callable[[CandleCache], None]] = []
        self._dashboard_listeners: List[Callable[[Dict[str, Any]], None]] = []

    # Listener registration -------------------------------------------------
    def register_condition_listener(self, callback: Callable[[List[Dict[str, Any]]], None]) -> None:
        self._condition_listeners.append(callback)

    def register_symbol_listener(self, callback: Callable[[SymbolState], None]) -> None:
        self._symbol_listeners.append(callback)

    def register_candle_listener(self, callback: Callable[[CandleCache], None]) -> None:
        self._candle_listeners.append(callback)

    def register_dashboard_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._dashboard_listeners.append(callback)

    # Condition hits --------------------------------------------------------
    def set_condition_hits(self, rows: Optional[List[Dict[str, Any]]]) -> None:
        cleaned = rows or []
        with self._lock:
            self.condition_hits = cleaned
            for row in cleaned:
                self._merge_symbol(row)
        self._emit(self._condition_listeners, cleaned)

    def apply_condition_event(self, code: str, state: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if not code:
            return
        payload = payload or {}
        changed = False
        with self._lock:
            idx = next((i for i, row in enumerate(self.condition_hits) if row.get("종목코드") == code), -1)
            if state == "enter":
                row = {
                    "종목코드": code,
                    "종목명": payload.get("종목명") or payload.get("condition_name") or "",
                    "상태": "편입"
                }
                if idx >= 0:
                    self.condition_hits[idx].update(row)
                else:
                    self.condition_hits.append(row)
                changed = True
            elif state == "exit":
                if idx >= 0:
                    self.condition_hits.pop(idx)
                    changed = True
        if changed:
            self._emit(self._condition_listeners, list(self.condition_hits))

    # Symbol updates --------------------------------------------------------
    def update_symbol(self, data: Dict[str, Any]) -> SymbolState:
        with self._lock:
            symbol = self._merge_symbol(data)
            self._update_condition_rows_with_symbol(symbol)
        self._emit(self._symbol_listeners, symbol)
        return symbol

    # Candle caches ---------------------------------------------------------
    def set_candles(self, code: str, series: str, rows: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> None:
        key = (code, series)
        cache = CandleCache(code=code, series=series, rows=rows or [], meta=meta or {})
        with self._lock:
            self.candles[key] = cache
        self._emit(self._candle_listeners, cache)

    def set_dashboard_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        if not snapshot:
            return False

        with self._lock:
            merged = dict(self.dashboard) if self.dashboard else {}

            for key, value in snapshot.items():
                if key in ("Holdings", "Outstanding", "RawBalance", "RawDeposit", "RawOutstanding"):
                    if value is not None:
                        merged[key] = copy.deepcopy(value)
                else:
                    merged[key] = value

            signature_target = {
                "AccountNo": merged.get("AccountNo"),
                "FetchedAt": merged.get("FetchedAt"),
                "Totals": {
                    "TotalPurchase": merged.get("TotalPurchase"),
                    "TotalEvaluation": merged.get("TotalEvaluation"),
                    "TotalPnL": merged.get("TotalPnL"),
                    "TotalPnLRate": merged.get("TotalPnLRate"),
                    "RealizedPnL": merged.get("RealizedPnL"),
                },
                "Holdings": merged.get("Holdings"),
                "Outstanding": merged.get("Outstanding"),
            }
            new_signature = json.dumps(signature_target, sort_keys=True, ensure_ascii=False)
            if new_signature == self._dashboard_signature:
                return False

            self.dashboard = merged
            self.holdings = copy.deepcopy(merged.get("Holdings") or [])
            self.outstanding = copy.deepcopy(merged.get("Outstanding") or [])
            self._dashboard_signature = new_signature

        self._emit(self._dashboard_listeners, dict(self.dashboard))
        return True

    def apply_execution_snapshot_refresh(self) -> None:
        """Notify listeners that holdings/outstanding should refresh."""
        self._emit(self._dashboard_listeners, dict(self.dashboard))

    # Helpers ---------------------------------------------------------------
    def _merge_symbol(self, data: Dict[str, Any]) -> SymbolState:
        code = self._coalesce(data, ["종목코드", "code"])
        if not code:
            return SymbolState(code="")
        code = code.strip()
        sym = self.symbols.get(code, SymbolState(code=code))

        name = self._coalesce(data, ["종목명", "name"])
        if name:
            sym.name = name.strip()

        sym.last_price = self._to_float(self._coalesce(data, ["현재가", "last_price"]))
        sym.change = self._to_float(self._coalesce(data, ["전일대비", "change"]))
        sym.change_rate = self._to_float(self._coalesce(data, ["등락율", "change_rate"]))
        sym.volume = self._to_float(self._coalesce(data, ["거래량", "volume"]))
        sym.strength = self._to_float(self._coalesce(data, ["체결강도", "strength"]))
        sym.prev_volume_ratio = self._to_float(self._coalesce(data, ["전일대비거래량비율", "전일비 거래량 대비(%)", "prev_vol_ratio"]))

        sym.extras.update({k: v for k, v in data.items() if k not in sym.extras})

        self.symbols[code] = sym
        return sym

    def _update_condition_rows_with_symbol(self, symbol: SymbolState) -> None:
        if not symbol or not symbol.code or not self.condition_hits:
            return
        for row in self.condition_hits:
            if not isinstance(row, dict):
                continue
            if row.get("종목코드") != symbol.code:
                continue
            if symbol.last_price:
                row["현재가"] = f"{symbol.last_price:.0f}"
            if symbol.change:
                row["전일대비"] = f"{symbol.change:+.0f}"
            if symbol.change_rate:
                row["등락율"] = f"{symbol.change_rate:+.2f}"
            if symbol.volume:
                row["거래량"] = f"{symbol.volume:.0f}"
            if symbol.strength:
                row["체결강도"] = f"{symbol.strength:.2f}"
            if symbol.prev_volume_ratio:
                row["전일대비거래량비율"] = f"{symbol.prev_volume_ratio:.2f}"

    @staticmethod
    def _coalesce(data: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return None

    @staticmethod
    def _to_float(val: Any) -> float:
        if val is None:
            return 0.0
        try:
            if isinstance(val, str):
                val = val.replace(",", "").strip()
            return float(val)
        except Exception:
            return 0.0

    @staticmethod
    def _emit(listeners: List[Callable], payload: Any) -> None:
        for callback in listeners:
            try:
                callback(payload)
            except Exception:
                # Listener errors should not crash state updates; log hook here later.
                pass
