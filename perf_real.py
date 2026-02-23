#!/usr/bin/env python3
"""
Perf_Test real-data bootstrap for KiwoomServer.

Usage:
  python perf_real.py

Optional env:
  PERF_BASE_URL=http://localhost:8082
  PERF_CODES=005930;000660;035420
  PERF_SCREEN=1000
  PERF_TICK=1
  PERF_NOGUI=1
"""

from __future__ import annotations

import asyncio
import atexit
from collections import deque
import json
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore

try:
    import websockets  # type: ignore
except Exception:
    websockets = None

try:
    import pymysql  # type: ignore
except Exception:
    pymysql = None


def _to_num(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return 0.0
    sign = -1 if s.startswith("-") else 1
    s = s.replace("+", "").replace("-", "")
    try:
        return float(s) * sign
    except Exception:
        return 0.0


def _coalesce(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _normalize_code(code: Any) -> str:
    s = str(code or "").strip()
    if s.startswith(("A", "a")) and len(s) >= 7:
        s = s[1:]
    return s


# Stable unicode-escaped broker keys to avoid source encoding issues.
K_TIME = "\uccb4\uacb0\uc2dc\uac04"   # 泥닿껐?쒓컙
K_DATE = "\uc77c\uc790"               # ?쇱옄
K_OPEN = "\uc2dc\uac00"               # ?쒓?
K_HIGH = "\uace0\uac00"               # 怨좉?
K_LOW = "\uc800\uac00"                # ?媛
K_CLOSE = "\ud604\uc7ac\uac00"        # ?꾩옱媛
K_CLOSE_ALT = "\uc885\uac00"          # 醫낃?
K_VOL = "\uac70\ub798\ub7c9"          # 嫄곕옒??
K_STOCK_CODE = "\uc885\ubaa9\ucf54\ub4dc"
K_STOCK_NAME = "\uc885\ubaa9\uba85"
K_HOLD_QTY = "\ubcf4\uc720\uc218\ub7c9"
K_BUY_PRICE = "\ub9e4\uc785\uac00"
K_BUY_AMOUNT = "\ub9e4\uc785\uae08\uc561"
K_EVAL_AMOUNT = "\ud3c9\uac00\uae08\uc561"
K_EVAL_PNL = "\ud3c9\uac00\uc190\uc775"
K_PNL_RATE = "\uc218\uc775\ub960(%)"
K_CUR_PRICE = "\ud604\uc7ac\uac00"
K_ORDER_NO = "\uc8fc\ubb38\ubc88\ud638"
K_ORDER_TYPE = "\uc8fc\ubb38\uad6c\ubd84"
K_ORDER_PRICE = "\uc8fc\ubb38\uac00\uaca9"
K_ORDER_QTY = "\uc8fc\ubb38\uc218\ub7c9"
K_REMAIN_QTY = "\ubbf8\uccb4\uacb0\uc218\ub7c9"
K_ORDER_STATUS = "\uc8fc\ubb38\uc0c1\ud0dc"

class RealDataSimulator:
    """Drop-in replacement for Perf_Test.DummyDataSimulator using kiwoomserver."""

    DEFAULT_CODES = [
        "005930", "000660", "035420", "035720", "051910",
        "005380", "068270", "207940", "012330", "066570",
    ]

    def __init__(self, n: int = 50):
        self.n = n
        self.base_url = os.getenv("PERF_BASE_URL", "http://localhost:8082").rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.screen = os.getenv("PERF_SCREEN", "1000")
        self.tick_unit = int(os.getenv("PERF_TICK", "1"))

        self._lock = threading.RLock()
        self._last_dashboard: Dict[str, Any] = {}
        self._last_dashboard_poll = 0.0
        self._last_quote_poll = 0.0
        self._last_heartbeat = 0.0
        self._last_login_retry = 0.0
        self._last_subscribe_retry = 0.0
        self._api_calls = 0
        self._mode = "bootstrap"

        self.stocks: List[Dict[str, Any]] = []
        self._stock_by_code: Dict[str, Dict[str, Any]] = {}
        self._candles: Dict[str, List[Dict[str, Any]]] = {}
        self._candle_idx: Dict[str, int] = {}
        self._candle_req_queue: deque[str] = deque()
        self._candle_req_set: set[str] = set()

        self._rt_thread: Optional[threading.Thread] = None
        self._rt_stop = threading.Event()
        self._exec_thread: Optional[threading.Thread] = None
        self._exec_stop = threading.Event()
        self._bg_thread: Optional[threading.Thread] = None
        self._bg_stop = threading.Event()
        self._rt_connected = False
        self._rt_subscribed = False
        self._rt_recv_count = 0
        self._rt_last_recv_ts = 0.0
        self._exec_connected = False
        self._exec_recv_count = 0
        self._dashboard_dirty = False
        self._account_no = ""
        self._mysql_enabled = False
        self._did_contract_check = False

        self._wait_for_server_ready()
        self._ensure_login(max_wait_sec=12.0)
        self._bootstrap_universe()
        for s in self.stocks:
            code = str(s.get("code", "")).strip()
            if code:
                self._enqueue_candle_fetch(code)
        print(f"[perf_real] boot: base={self.base_url} account={self._account_no or '-'} symbols={len(self.stocks)}")
        self._start_realtime_listener()
        self._start_execution_listener()
        self._subscribe_realtime(force=True)
        self._refresh_dashboard(force=True)
        self._setup_mysql()
        self._start_background_worker()
        atexit.register(self.close)

    # ----------------------- HTTP helpers -----------------------
    def _request_json(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Any = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            q = urllib.parse.urlencode(params)
            url = f"{url}?{q}"
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
        self._api_calls += 1
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}

    def _api_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            return self._request_json("GET", path, params=params)
        except urllib.error.URLError:
            return {"Success": False, "Message": "Server unreachable", "Data": None}
        except Exception as ex:
            return {"Success": False, "Message": str(ex), "Data": None}

    @staticmethod
    def _ok(resp: Dict[str, Any]) -> bool:
        return bool(resp and resp.get("Success"))

    @staticmethod
    def _data(resp: Dict[str, Any], default: Any) -> Any:
        if isinstance(resp, dict) and "Data" in resp:
            return resp.get("Data") if resp.get("Data") is not None else default
        return default

    # ----------------------- bootstrap -----------------------
    def _wait_for_server_ready(self, timeout_sec: float = 15.0) -> None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            st = self._api_get("/api/status")
            if self._ok(st):
                return
            time.sleep(0.4)
        print("[perf_real] WARN: server status not ready yet; continuing with retries")

    @staticmethod
    def _now_kst() -> datetime:
        if ZoneInfo is not None:
            return datetime.now(ZoneInfo("Asia/Seoul"))
        return datetime.now()

    def _is_market_open(self) -> bool:
        now = self._now_kst()
        # Korea cash market window: Mon-Fri 09:00-15:30 KST.
        if now.weekday() >= 5:
            return False
        hhmm = now.hour * 100 + now.minute
        return 900 <= hhmm <= 1530

    def _market_stop_time_kst(self) -> str:
        now = self._now_kst()
        if self._is_market_open():
            return now.strftime("%Y%m%d%H%M%S")
        # Off-market: use session close time to avoid empty intraday windows.
        return now.strftime("%Y%m%d") + "153000"

    def _history_stop_time(self) -> str:
        # Wide historical window for chart bootstrapping/replay.
        return os.getenv("PERF_CANDLE_STOP", "20180101090000").strip() or "20180101090000"

    def _is_logged_in(self) -> bool:
        st = self._api_get("/api/status")
        data = self._data(st, {})
        if isinstance(data, dict) and data.get("IsLoggedIn"):
            self._account_no = str(data.get("AccountNo") or "")
            return True
        self._account_no = ""
        return False

    def _ensure_login(self, max_wait_sec: float = 8.0) -> bool:
        if self._is_logged_in():
            return True
        self._api_get("/api/auth/login")
        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            time.sleep(0.4)
            if self._is_logged_in():
                print(f"[perf_real] login ok: account={self._account_no}")
                return True
        print("[perf_real] WARN: login not ready yet (will retry)")
        return False

    def _bootstrap_universe(self) -> None:
        codes_env = os.getenv("PERF_CODES", "").strip()
        codes = [c.strip() for c in codes_env.split(";") if c.strip()] if codes_env else []
        names: Dict[str, str] = {}

        if not codes:
            cond = self._api_get("/api/conditions")
            cond_list = self._data(cond, [])
            if isinstance(cond_list, list) and cond_list:
                first = cond_list[0]
                idx = _coalesce(first, ["Index", "index"], 0)
                nm = _coalesce(first, ["Name", "name"], "")
                rs = self._api_get("/api/conditions/search", {"index": idx, "name": nm})
                payload = self._data(rs, {})
                if isinstance(payload, dict):
                    codes = [c for c in (_coalesce(payload, ["Codes"], []) or []) if c]
                    stocks = _coalesce(payload, ["Stocks"], []) or []
                    for row in stocks:
                        if not isinstance(row, dict):
                            continue
                        code = str(_coalesce(row, ["code"], "")).strip()
                        name = str(_coalesce(row, ["name"], "")).strip()
                        if code:
                            names[code] = name

        if not codes:
            codes = self.DEFAULT_CODES[:]
        codes = list(dict.fromkeys(codes))[: max(1, min(self.n, len(codes)))]

        stocks: List[Dict[str, Any]] = []
        for code in codes:
            sym = self._api_get("/api/market/symbol", {"code": code})
            sym_data = self._data(sym, {})
            name = names.get(code) or str(_coalesce(sym_data, ["name"], code))
            last = _to_num(_coalesce(sym_data, ["last_price"], 0))
            base = last if last > 0 else 10000.0
            stocks.append({
                "code": code,
                "name": name,
                "sector": "UNKNOWN",
                "base_price": base,
                "open_price": base,
                "price": base,
                "volume_acc": 0.0,
                "tick_count": 0,
                "avg5d": 1000.0,
                "prev_d": 1000.0,
                "tes": 1.0,
                "ucs": 0.5,
                "frs": 1.0,
                "hms": 0.5,
                "bms": 0.5,
                "sls": 0.5,
                "axes": 1,
                "candle_idx": 0,
            })

        with self._lock:
            self.stocks = stocks
            self._stock_by_code = {s["code"]: s for s in stocks}

    def _subscribe_realtime(self, force: bool = False) -> bool:
        if not self._account_no:
            self._rt_subscribed = False
            return False
        with self._lock:
            codes = [s["code"] for s in self.stocks]
        if not codes:
            self._rt_subscribed = False
            return False
        if self._rt_subscribed and not force:
            return True
        code_str = ";".join(codes)
        resp = self._api_get("/api/realtime/subscribe", {"codes": code_str, "screen": self.screen})
        ok = self._ok(resp)
        self._rt_subscribed = ok
        if ok:
            print(f"[perf_real] realtime subscribed: {len(codes)} codes screen={self.screen}")
        else:
            msg = str(resp.get("Message", "unknown error"))
            print(f"[perf_real] WARN: subscribe failed: {msg}")
        return ok

    def _enqueue_candle_fetch(self, code: str) -> None:
        code = str(code).strip()
        if not code:
            return
        with self._lock:
            if code in self._candle_req_set:
                return
            self._candle_req_set.add(code)
            self._candle_req_queue.append(code)

    def _process_candle_fetch_once(self) -> None:
        code = ""
        with self._lock:
            if self._candle_req_queue:
                code = self._candle_req_queue.popleft()
                self._candle_req_set.discard(code)
        if not code:
            return
        rows = self._fetch_candles(code)
        if not rows:
            return
        with self._lock:
            self._candles[code] = rows
            # Resume near the tail for immediate chart movement.
            self._candle_idx[code] = max(0, len(rows) - min(120, len(rows)))

    def _start_background_worker(self) -> None:
        self._bg_thread = threading.Thread(target=self._background_loop, daemon=True)
        self._bg_thread.start()

    def _background_loop(self) -> None:
        while not self._bg_stop.is_set():
            try:
                now = time.time()
                market_open = self._is_market_open()
                self._mode = "realtime" if market_open else "closed_fallback"
                if not self._account_no and now - self._last_login_retry > 3.0:
                    self._ensure_login(max_wait_sec=2.0)
                    self._last_login_retry = now
                if self._account_no and now - self._last_subscribe_retry > (4.0 if market_open else 30.0):
                    stale_rt = self._rt_last_recv_ts <= 0 or (now - self._rt_last_recv_ts > 15.0)
                    if self._rt_connected and (not self._rt_subscribed or (market_open and stale_rt)):
                        self._subscribe_realtime(force=True)
                    self._last_subscribe_retry = now
                if self._dashboard_dirty or (now - self._last_dashboard_poll > 5.0):
                    self._refresh_dashboard(force=self._dashboard_dirty)
                    self._dashboard_dirty = False
                    self._last_dashboard_poll = now
                quote_interval = 2.0 if market_open else 10.0
                if now - self._last_quote_poll > quote_interval:
                    self._refresh_quotes()
                    self._last_quote_poll = now
                self._process_candle_fetch_once()
                if now - self._last_heartbeat > 5.0:
                    self._print_heartbeat(now)
                    self._last_heartbeat = now
                if not self._did_contract_check and now - self._last_dashboard_poll > 2.0:
                    self._run_contract_checks()
                    self._did_contract_check = True
            except Exception as ex:
                print(f"[perf_real] WARN: background loop error: {ex}")
            time.sleep(0.05)

    # ----------------------- websocket -----------------------
    def _start_realtime_listener(self) -> None:
        if websockets is None:
            print("[perf_real] realtime websocket disabled: `websockets` package not installed")
            return
        self._rt_thread = threading.Thread(target=self._rt_loop_runner, daemon=True)
        self._rt_thread.start()

    def _start_execution_listener(self) -> None:
        if websockets is None:
            return
        self._exec_thread = threading.Thread(target=self._exec_loop_runner, daemon=True)
        self._exec_thread.start()

    def _rt_loop_runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._realtime_loop())
        finally:
            loop.close()

    def _exec_loop_runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._execution_loop())
        finally:
            loop.close()

    async def _realtime_loop(self) -> None:
        uri = f"{self.ws_url}/ws/realtime"
        while not self._rt_stop.is_set():
            try:
                async with websockets.connect(uri) as ws:  # type: ignore[arg-type]
                    self._rt_connected = True
                    print(f"[perf_real] realtime connected: {uri}")
                    self._subscribe_realtime(force=True)
                    while not self._rt_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=20)
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            raise
                        evt = json.loads(raw)
                        self._on_realtime(evt)
            except Exception:
                if self._rt_connected:
                    print("[perf_real] realtime disconnected; retrying...")
                self._rt_connected = False
                self._rt_subscribed = False
                await asyncio.sleep(1.5)

    async def _execution_loop(self) -> None:
        uri = f"{self.ws_url}/ws/execution"
        while not self._exec_stop.is_set():
            try:
                async with websockets.connect(uri) as ws:  # type: ignore[arg-type]
                    self._exec_connected = True
                    print(f"[perf_real] execution connected: {uri}")
                    while not self._exec_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=20)
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            raise
                        evt = json.loads(raw)
                        self._on_execution(evt)
            except Exception:
                if self._exec_connected:
                    print("[perf_real] execution disconnected; retrying...")
                self._exec_connected = False
                await asyncio.sleep(1.5)

    def _on_realtime(self, evt: Dict[str, Any]) -> None:
        code = str(evt.get("code", "")).strip()
        data = evt.get("data", {}) or {}
        if not code:
            return
        with self._lock:
            s = self._stock_by_code.get(code)
            if s is None:
                return

            price = _to_num(_coalesce(data, ["current_price", "price", K_CLOSE], 0))
            op = _to_num(_coalesce(data, ["open", K_OPEN], s["open_price"]))
            vol = _to_num(_coalesce(data, ["cum_volume", "volume", K_VOL], s["volume_acc"]))
            rate = _to_num(_coalesce(data, ["rate", "change_rate"], 0))
            diff = _to_num(_coalesce(data, ["diff", "change"], 0))
            intensity = _to_num(_coalesce(data, ["intensity"], 0))

            if price > 0:
                s["price"] = price
            if op > 0:
                s["open_price"] = op
            if vol > 0:
                s["volume_acc"] = vol

            if s["open_price"] > 0 and rate == 0 and s["price"] > 0:
                rate = (s["price"] - s["open_price"]) / s["open_price"] * 100.0
            if s["open_price"] > 0 and diff == 0 and s["price"] > 0:
                diff = s["price"] - s["open_price"]

            # Derived factors for existing UI scores.
            abs_rate = abs(rate)
            s["tes"] = max(0.0, min(3.0, (abs_rate / 2.5) + (intensity / 200.0)))
            s["ucs"] = max(0.0, min(1.0, min(1.0, abs_rate / 10.0) * 0.5 + min(1.0, intensity / 150.0) * 0.5))
            s["frs"] = max(0.0, min(2.5, 1.0 + diff / max(1.0, s["open_price"]) * 5.0 + s["ucs"] * 0.3))
            s["hms"] = max(0.0, min(1.0, s["ucs"]))
            s["bms"] = max(0.0, min(1.0, abs_rate / 5.0))
            s["sls"] = max(0.0, min(1.0, min(1.0, s["volume_acc"] / 5_000_000.0)))
            s["axes"] = (1 if s["hms"] >= 0.4 else 0) + (1 if s["bms"] >= 0.4 else 0) + (1 if s["sls"] >= 0.4 else 0)
            s["tick_count"] += 1
            self._rt_recv_count += 1
            self._rt_last_recv_ts = time.time()

    def _on_execution(self, evt: Dict[str, Any]) -> None:
        typ = str(evt.get("type", "")).strip().lower()
        data = evt.get("data")
        self._exec_recv_count += 1
        if typ == "dashboard" and isinstance(data, dict):
            with self._lock:
                self._last_dashboard = data
            return
        if typ in ("order", "balance"):
            # Chejan/order events imply holdings/outstanding changed.
            self._dashboard_dirty = True

    # ----------------------- periodic refresh -----------------------
    def tick(self) -> None:
        # UI thread safe: networking is handled by the background worker.
        return

    def _refresh_quotes(self) -> None:
        with self._lock:
            codes = [s.get("code", "") for s in self.stocks if s.get("code")]
        for code in codes[: min(20, len(codes))]:
            sym = self._api_get("/api/market/symbol", {"code": code})
            if not self._ok(sym):
                continue
            data = self._data(sym, {})
            if not isinstance(data, dict):
                continue
            price = _to_num(_coalesce(data, ["last_price", "current_price", "price", K_CLOSE], 0))
            op = _to_num(_coalesce(data, ["open", K_OPEN], 0))
            vol = _to_num(_coalesce(data, ["cum_volume", "volume", K_VOL], 0))
            with self._lock:
                s = self._stock_by_code.get(code)
                if s is None:
                    continue
                prev_price = _to_num(s.get("price", 0))
                if price > 0:
                    s["price"] = price
                if op > 0:
                    s["open_price"] = op
                if vol > 0:
                    s["volume_acc"] = vol
                if price > 0 and price != prev_price:
                    s["tick_count"] = int(_to_num(s.get("tick_count", 0))) + 1

    def _print_heartbeat(self, now_ts: float) -> None:
        with self._lock:
            s = self.stocks[0] if self.stocks else None
            if s is None:
                sample = "-"
            else:
                sample = f"{s.get('code','-')}:{_to_num(s.get('price')):,.0f} t={int(_to_num(s.get('tick_count')))}"
        last_sec = int(now_ts - self._rt_last_recv_ts) if self._rt_last_recv_ts > 0 else -1
        print(
            f"[perf_real] hb rt={'on' if self._rt_connected else 'off'} "
            f"exec={'on' if self._exec_connected else 'off'} "
            f"sub={'on' if self._rt_subscribed else 'off'} acct={self._account_no or '-'} "
            f"mode={self._mode} recv={self._rt_recv_count} last={last_sec}s api={self._api_calls} sample={sample}"
        )

    def _refresh_dashboard(self, force: bool) -> None:
        use_refresh = force
        if not use_refresh:
            with self._lock:
                use_refresh = not bool(self._last_dashboard)
        path = "/api/dashboard/refresh" if use_refresh else "/api/dashboard"
        resp = self._api_get(path)
        if self._ok(resp):
            data = self._data(resp, {})
            if isinstance(data, dict):
                with self._lock:
                    self._last_dashboard = data
            if force and self._mysql_enabled:
                self._flush_daily_to_mysql("000660")
        else:
            msg = str(resp.get("Message", "")).lower()
            if "not logged in" in msg:
                self._account_no = ""

    # ----------------------- data views for existing UI -----------------------
    def get_universe_grid(self) -> List[list]:
        with self._lock:
            sorted_stocks = sorted(self.stocks, key=lambda x: x.get("frs", 0.0), reverse=True)
            rows: List[list] = []
            for rank, s in enumerate(sorted_stocks, 1):
                open_p = max(1.0, _to_num(s.get("open_price")))
                price = _to_num(s.get("price"))
                change_pct = (price - open_p) / open_p * 100.0
                trade_value = _to_num(s.get("volume_acc")) * price / 1e8
                avg5d = max(1.0, _to_num(s.get("avg5d", 1000)))
                prev_d = max(1.0, _to_num(s.get("prev_d", 1000)))
                tc = max(1.0, _to_num(s.get("tick_count", 1)))
                r1 = tc / (avg5d * 0.0385)
                r2 = tc / (prev_d * 0.0385)
                r3 = prev_d / avg5d
                rows.append([
                    rank, s.get("code", ""), s.get("name", ""), price, change_pct, trade_value,
                    _to_num(s.get("tes")), _to_num(s.get("ucs")), _to_num(s.get("frs")),
                    r1, r2, r3, int(_to_num(s.get("axes", 1))),
                    "ENTRY" if rank <= 5 else "WATCH" if rank <= 15 else "IDLE",
                    s.get("sector", "UNKNOWN"),
                ])
            return rows

    def get_universe_tree(self) -> List[dict]:
        with self._lock:
            sorted_stocks = sorted(self.stocks, key=lambda x: x.get("frs", 0.0), reverse=True)
            out: List[dict] = []
            for rank, s in enumerate(sorted_stocks, 1):
                open_p = max(1.0, _to_num(s.get("open_price")))
                price = _to_num(s.get("price"))
                change_pct = (price - open_p) / open_p * 100.0
                out.append({
                    "code": s.get("code", ""),
                    "name": s.get("name", ""),
                    "change": change_pct,
                    "tes": _to_num(s.get("tes")),
                    "ucs": _to_num(s.get("ucs")),
                    "frs": _to_num(s.get("frs")),
                    "axes": int(_to_num(s.get("axes", 1))),
                    "is_target": rank <= 5,
                    "sector": s.get("sector", "UNKNOWN"),
                })
            return out

    def get_stock_detail(self, code: str) -> dict:
        with self._lock:
            s = self._stock_by_code.get(code)
            if s is None:
                return {}
            price = _to_num(s.get("price"))
            open_p = max(1.0, _to_num(s.get("open_price")))
            change_pct = (price - open_p) / open_p * 100.0
            return {
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "price": price,
                "change": change_pct,
                "market_cap": "-",
                "trade_value": f"{_to_num(s.get('volume_acc')) * price / 1e8:,.1f}",
                "tes": _to_num(s.get("tes")),
                "ucs": _to_num(s.get("ucs")),
                "frs": _to_num(s.get("frs")),
                "AVG5D": f"{int(_to_num(s.get('avg5d'))):,}",
                "PREV_D": f"{int(_to_num(s.get('prev_d'))):,}",
                "TODAY_15M": f"{int(_to_num(s.get('tick_count'))):,}",
                "R1": f"{_to_num(s.get('hms')) * 2:.2f}",
                "R2": f"{_to_num(s.get('bms')) * 2:.2f}",
                "R3": f"{_to_num(s.get('sls')) * 2:.2f}",
                "change_rate": f"{change_pct:+.2f}%",
                "TES Z": f"{_to_num(s.get('tes')):.3f}",
                "ATR?곴?": f"{abs(price - open_p):.0f}",
                "HMS": _to_num(s.get("hms")),
                "BMS": _to_num(s.get("bms")),
                "SLS": _to_num(s.get("sls")),
            }

    def get_positions(self) -> List[list]:
        with self._lock:
            holdings = self._last_dashboard.get("Holdings") or []
            rows: List[list] = []
            for h in holdings:
                if not isinstance(h, dict):
                    continue
                code = _normalize_code(_coalesce(h, ["code", K_STOCK_CODE], ""))
                if not code:
                    continue
                sref = self._stock_by_code.get(code, {})
                name = str(_coalesce(h, ["name", K_STOCK_NAME], sref.get("name", code))).strip()
                qty = int(_to_num(_coalesce(h, ["qty", K_HOLD_QTY], 0)))
                avg = _to_num(_coalesce(h, ["avg_price", K_BUY_PRICE], 0))
                cur = _to_num(_coalesce(h, ["price", K_CUR_PRICE], 0))
                if cur <= 0:
                    cur = _to_num(sref.get("price", 0))
                pnl = _to_num(_coalesce(h, ["pnl", K_EVAL_PNL], 0))
                pnl_pct = _to_num(_coalesce(h, ["pnl_rate", K_PNL_RATE], 0))
                if avg > 0 and cur > 0 and qty > 0:
                    calc_pnl = (cur - avg) * qty
                    if pnl == 0:
                        pnl = calc_pnl
                    if pnl_pct == 0:
                        pnl_pct = (cur - avg) / avg * 100.0
                stop = avg * 0.97 if avg > 0 else 0.0
                tes = _to_num(sref.get("tes", 0))
                rows.append([code, name, qty, avg, cur, pnl_pct, pnl, stop, "1李?50%)", tes])
            return rows

    def get_pending(self) -> List[list]:
        with self._lock:
            outs = self._last_dashboard.get("Outstanding") or []
            rows: List[list] = []
            for o in outs:
                if not isinstance(o, dict):
                    continue
                code = _normalize_code(_coalesce(o, ["code", K_STOCK_CODE], ""))
                name = str(_coalesce(o, ["name", K_STOCK_NAME], self._stock_by_code.get(code, {}).get("name", "")))
                rows.append([
                    str(_coalesce(o, ["order_no", K_ORDER_NO], "")),
                    code,
                    name,
                    str(_coalesce(o, ["type", K_ORDER_TYPE], "")),
                    _to_num(_coalesce(o, ["price", K_ORDER_PRICE], 0)),
                    int(_to_num(_coalesce(o, ["qty", K_ORDER_QTY], 0))),
                    int(_to_num(_coalesce(o, ["remain", K_REMAIN_QTY], 0))),
                    str(_coalesce(o, ["status", K_ORDER_STATUS], "")),
                ])
            return rows

    def _fetch_candles(self, code: str) -> List[Dict[str, Any]]:
        # Fast path first: recent intraday rows with low server load.
        recent_stop = self._market_stop_time_kst()
        resp = self._api_get("/api/market/candles/minute", {"code": code, "tick": self.tick_unit, "stopTime": recent_stop})
        rows = self._data(resp, [])
        # Deep history fallback only when recent payload is too small.
        if not isinstance(rows, list) or len(rows) < 50:
            deep_stop = self._history_stop_time()
            deep = self._api_get("/api/market/candles/minute", {"code": code, "tick": self.tick_unit, "stopTime": deep_stop})
            deep_rows = self._data(deep, [])
            if isinstance(deep_rows, list) and len(deep_rows) > len(rows if isinstance(rows, list) else []):
                rows = deep_rows
        out: List[Dict[str, Any]] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            t = str(_coalesce(row, [K_TIME, K_DATE, "time", "timestamp", "date"], ""))
            o = abs(_to_num(_coalesce(row, [K_OPEN, "open"], 0)))
            h = abs(_to_num(_coalesce(row, [K_HIGH, "high"], 0)))
            l = abs(_to_num(_coalesce(row, [K_LOW, "low"], 0)))
            c = abs(_to_num(_coalesce(row, [K_CLOSE, K_CLOSE_ALT, "close"], 0)))
            v = abs(_to_num(_coalesce(row, [K_VOL, "volume"], 0)))
            if c <= 0:
                continue
            if h <= 0:
                h = max(o, c)
            if l <= 0:
                l = min(o, c)
            out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v})

        # chart wants oldest -> newest sequence for progressive draw
        out.sort(key=lambda x: x["t"])
        return out

    # ----------------------- checks & mysql -----------------------
    def _run_contract_checks(self) -> None:
        # From server_info full manual: 000660 should be requestable and typically >= 900 rows with long stop range.
        code = "000660"
        now_kst = self._now_kst()
        day = now_kst.strftime("%Y%m%d")
        stop_now = self._market_stop_time_kst()
        daily = self._api_get("/api/market/candles/daily", {"code": code, "date": day, "stopDate": "20180101"})
        minute = self._api_get("/api/market/candles/minute", {"code": code, "tick": 1, "stopTime": stop_now})
        tick = self._api_get("/api/market/candles/tick", {"code": code, "tick": 1, "stopTime": stop_now})
        d_cnt = len(self._data(daily, []) or [])
        m_cnt = len(self._data(minute, []) or [])
        t_cnt = len(self._data(tick, []) or [])
        print(f"[perf_real] Candle contract check {code}: daily={d_cnt}, minute={m_cnt}, tick={t_cnt}")
        if not (self._ok(daily) and self._ok(minute) and self._ok(tick)):
            print("[perf_real] WARN: one or more candle endpoints returned Success=false")
        if d_cnt < 900:
            print("[perf_real] INFO: daily rows < 900 (market/history range may be limited)")

    def _setup_mysql(self) -> None:
        # Optional MySQL integration from server_info schema.
        # Enable only if env vars are provided and pymysql is installed.
        host = os.getenv("MYSQL_HOST", "").strip()
        user = os.getenv("MYSQL_USER", "").strip()
        password = os.getenv("MYSQL_PASSWORD", "").strip()
        db = os.getenv("MYSQL_DB", "stock_info").strip()
        if not (host and user and password):
            return
        if pymysql is None:
            print("[perf_real] MYSQL_* provided but pymysql is missing. Install: pip install pymysql")
            return
        self._mysql_cfg = {"host": host, "user": user, "password": password, "database": db, "charset": "utf8mb4", "autocommit": True}
        self._mysql_enabled = True
        print(f"[perf_real] MySQL enabled: {user}@{host}/{db}")
        self._sync_base_info_to_mysql()

    def _mysql_conn(self):
        if not self._mysql_enabled:
            return None
        return pymysql.connect(**self._mysql_cfg)

    def _sync_base_info_to_mysql(self) -> None:
        if not self._mysql_enabled:
            return
        sql = (
            "INSERT INTO stock_base_info(code,name,market,instrument_type,is_common_stock,is_excluded,sector_role) "
            "VALUES(%s,%s,%s,'STOCK',1,0,'NONE') "
            "ON DUPLICATE KEY UPDATE name=VALUES(name), market=VALUES(market), instrument_type=VALUES(instrument_type)"
        )
        try:
            conn = self._mysql_conn()
            if conn is None:
                return
            with conn:
                with conn.cursor() as cur:
                    with self._lock:
                        rows = [(s.get("code", ""), s.get("name", ""), "KOSPI") for s in self.stocks if s.get("code")]
                    if rows:
                        cur.executemany(sql, rows)
            print(f"[perf_real] stock_base_info upsert: {len(rows)} rows")
        except Exception as ex:
            print(f"[perf_real] MySQL stock_base_info upsert failed: {ex}")

    def _flush_daily_to_mysql(self, code: str) -> None:
        if not self._mysql_enabled:
            return
        day = datetime.now().strftime("%Y%m%d")
        resp = self._api_get("/api/market/candles/daily", {"code": code, "date": day, "stopDate": "20180101"})
        rows = self._data(resp, [])
        if not isinstance(rows, list) or not rows:
            return
        sql = (
            "INSERT INTO daily_candles(code,`date`,open,high,low,`close`,volume,tramount,change_pct) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low), "
            "`close`=VALUES(`close`), volume=VALUES(volume), tramount=VALUES(tramount), change_pct=VALUES(change_pct)"
        )
        params: List[Tuple[Any, ...]] = []
        prev_close = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            dt_raw = str(_coalesce(r, ["date", K_DATE], "")).strip()
            if len(dt_raw) < 8:
                continue
            dt = f"{dt_raw[0:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}"
            o = int(abs(_to_num(_coalesce(r, ["open", K_OPEN], 0))))
            h = int(abs(_to_num(_coalesce(r, ["high", K_HIGH], 0))))
            l = int(abs(_to_num(_coalesce(r, ["low", K_LOW], 0))))
            c = int(abs(_to_num(_coalesce(r, ["close", K_CLOSE, K_CLOSE_ALT], 0))))
            v = int(abs(_to_num(_coalesce(r, ["volume", K_VOL], 0))))
            tramount = int(c * v)
            change_pct = None if prev_close in (None, 0) else round((c - prev_close) / float(prev_close) * 100.0, 2)
            prev_close = c
            params.append((code, dt, o, h, l, c, v, tramount, change_pct))
        if not params:
            return
        try:
            conn = self._mysql_conn()
            if conn is None:
                return
            with conn:
                with conn.cursor() as cur:
                    cur.executemany(sql, params)
            print(f"[perf_real] daily_candles upsert {code}: {len(params)} rows")
        except Exception as ex:
            print(f"[perf_real] MySQL daily_candles upsert failed: {ex}")

    def close(self) -> None:
        self._bg_stop.set()
        self._rt_stop.set()
        self._exec_stop.set()
        try:
            self._api_get("/api/realtime/unsubscribe", {"screen": self.screen, "code": "ALL"})
        except Exception:
            pass
        if self._bg_thread is not None and self._bg_thread.is_alive():
            self._bg_thread.join(timeout=1.5)
        if self._rt_thread is not None and self._rt_thread.is_alive():
            self._rt_thread.join(timeout=1.5)
        if self._exec_thread is not None and self._exec_thread.is_alive():
            self._exec_thread.join(timeout=1.5)

    def generate_candle(self, stock_idx: int) -> Tuple[float, float, float, float, float, int]:
        with self._lock:
            if not self.stocks:
                return 0, 0, 0, 0, 0, 0
            s = self.stocks[max(0, min(stock_idx, len(self.stocks) - 1))]
            code = s["code"]
            if code not in self._candles:
                self._enqueue_candle_fetch(code)
                self._candles[code] = []
                self._candle_idx[code] = 0
            series = self._candles.get(code, [])
            i = self._candle_idx.get(code, 0)

            if not series:
                p = _to_num(s.get("price", 0))
                s["candle_idx"] = int(_to_num(s.get("candle_idx", 0))) + 1
                return p, p, p, p, max(0.0, _to_num(s.get("volume_acc", 0))), s["candle_idx"]

            if i >= len(series):
                # Off-market: replay recent candles so chart doesn't appear frozen.
                if not self._is_market_open() and len(series) > 1:
                    i = max(0, len(series) - min(120, len(series)))
                    self._candle_idx[code] = i + 1
                else:
                    i = len(series) - 1
            row = series[i]
            if i < len(series) - 1:
                self._candle_idx[code] = i + 1
            s["price"] = row["c"]
            s["candle_idx"] = int(_to_num(s.get("candle_idx", 0))) + 1
            return row["o"], row["h"], row["l"], row["c"], row["v"], s["candle_idx"]


def main() -> None:
    nogui = os.getenv("PERF_NOGUI", "").strip() == "1" or "--nogui" in sys.argv
    prefer_tk = os.getenv("PERF_UI", "").strip().lower() == "tk" or "--tk" in sys.argv

    if nogui:
        sim = RealDataSimulator(50)
        print("[perf_real] running in --nogui mode")
        print(f"[perf_real] base={sim.base_url} account={sim._account_no or '-'} symbols={len(sim.stocks)}")
        time.sleep(1.0)
        sim.close()
        return

    if prefer_tk:
        try:
            import tkinter as tk
            from tester_ui import ServerTesterUI
            print("[perf_real] starting tkinter realtime UI")
            root = tk.Tk()
            ServerTesterUI(root)
            root.mainloop()
            return
        except Exception as ex:
            print(f"[perf_real] tkinter UI startup failed: {ex}")
            traceback.print_exc()

    # Prefer Qt OpenGL backend for smoother rendering on this UI.
    os.environ.setdefault("QT_OPENGL", "desktop")
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
    os.environ.setdefault("QT_QUICK_BACKEND", "opengl")
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QStyleFactory
        import pyqtgraph as pg
        import Perf_Test as pt
        import chart_patch
    except Exception as ex:
        print(f"[perf_real] python={sys.executable}")
        print("GUI init failed. Install/check: pip install PySide6 pyqtgraph")
        print("Tip: if message includes 'paging file too small', increase Windows virtual memory and reboot.")
        print("Tip: run `python perf_real.py --nogui` for headless mode.")
        print("Tip: run `python perf_real.py --tk` only if you explicitly want tkinter mode.")
        print(f"Details: {ex}")
        traceback.print_exc()
        return

    # Swap dummy simulator with real adapter, then keep original UI.
    pt.DummyDataSimulator = RealDataSimulator
    chart_patch.apply()

    # Fix chart update key mismatch: dict key can be "code_type", not raw code.
    def _patched_update_charts(self) -> None:
        for key, cw in list(self.chart_windows.items()):
            code = str(getattr(cw, "stock_code", "") or key).strip()
            if "_" in code:
                code = code.split("_", 1)[0]
            idx = next((i for i, s in enumerate(self.sim.stocks) if str(s.get("code", "")).strip() == code), None)
            if idx is None:
                continue
            o, h, l, c, v, ci = self.sim.generate_candle(idx)
            cw.add_candle(o, h, l, c, v, ci)
    pt.TESMainWindow._update_charts = _patched_update_charts

    # Use GPU rendering by default; set PERF_REAL_OPENGL=0 to disable.
    use_opengl = os.environ.get("PERF_REAL_OPENGL", "1").strip().lower() not in ("0", "false", "off", "no")
    pg.setConfigOptions(antialias=False, useOpenGL=use_opengl, enableExperimental=True)

    app = QApplication([])
    app.setStyle(QStyleFactory.create("Fusion"))
    pt.Theme.apply_dark_palette(app)
    app.setStyleSheet(pt.Theme.STYLESHEET)
    app.setFont(QFont(pt.Theme.FONT_FAMILY, pt.Theme.FONT_SIZE_M))

    win = pt.TESMainWindow()
    win.setWindowTitle("TES-Universe Trading Platform (REAL DATA) | KiwoomServer")
    win.show()
    app.exec()


if __name__ == "__main__":
    main()


