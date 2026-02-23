#!/usr/bin/env python3
"""
perf_real.py — KiwoomServer Real-Data Integration + Stress Test
================================================================
장중: 순수 실시간 데이터 (부하테스트 자동 OFF)
장외: 서버 캐시 데이터 기반 가혹 부하테스트 (자동 ON)

Usage:
  python perf_real.py              # Qt GUI
  python perf_real.py --nogui      # headless
  python perf_real.py --tk         # tkinter

Env:
  PERF_BASE_URL=http://localhost:8082
  PERF_CODES=005930;000660;035420
  PERF_SCREEN=1000
  PERF_TICK=1
  PERF_NOGUI=1
  PERF_STRESS=1|0                  # force stress on/off
  PERF_STRESS_INTERVAL_MS=50
  PERF_STRESS_BATCH=20
  PERF_CANDLE_STOP=20180101090000
  PERF_REAL_OPENGL=1
  MYSQL_HOST / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
"""

from __future__ import annotations

import asyncio
import atexit
import json
import math
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
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


###############################################################################
# Utilities
###############################################################################

def _to_num(v: Any) -> float:
    """
    키움 브로커 데이터는 문자열로 올 수 있고,
    하락 시 음수 부호 또는 '+' 부호가 붙음. 안전하게 float 변환.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s:
        return 0.0
    sign = 1
    if s.startswith("--"):
        s = s[2:]
    elif s.startswith("-"):
        sign = -1
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    s = s.lstrip("0") or "0"
    try:
        return float(s) * sign
    except Exception:
        return 0.0


def _abs_num(v: Any) -> float:
    """키움 OHLC 데이터는 반드시 절대값으로 사용"""
    return abs(_to_num(v))


def _coalesce(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


# 한글 브로커 키 — unicode escape (인코딩 안전)
K_TIME       = "\uccb4\uacb0\uc2dc\uac04"          # 체결시간
K_DATE       = "\uc77c\uc790"                      # 일자
K_OPEN       = "\uc2dc\uac00"                      # 시가
K_HIGH       = "\uace0\uac00"                      # 고가
K_LOW        = "\uc800\uac00"                      # 저가
K_CLOSE      = "\ud604\uc7ac\uac00"                # 현재가
K_CLOSE_ALT  = "\uc885\uac00"                      # 종가
K_VOL        = "\uac70\ub798\ub7c9"                # 거래량
K_CODE       = "\uc885\ubaa9\ucf54\ub4dc"           # 종목코드
K_NAME       = "\uc885\ubaa9\uba85"                 # 종목명
K_HOLD_QTY   = "\ubcf4\uc720\uc218\ub7c9"          # 보유수량
K_ORDER_NO   = "\uc8fc\ubb38\ubc88\ud638"          # 주문번호
K_UNFILLED   = "\ubbf8\uccb4\uacb0\uc218\ub7c9"    # 미체결수량
K_AVAIL_AMT  = "\uc8fc\ubb38\uac00\ub2a5\uae08\uc561"  # 주문가능금액
K_TRAM       = "\uac70\ub798\ub300\uae08"           # 거래대금


###############################################################################
# RealDataSimulator
###############################################################################

class RealDataSimulator:
    """
    KiwoomServer REST/WS 실데이터 어댑터.
    Perf_Test.DummyDataSimulator 인터페이스 100% 호환.
    """

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

        # 내부 상태
        self._lock = threading.RLock()
        self._last_dashboard: Dict[str, Any] = {}
        self._last_dashboard_poll = 0.0
        self._last_quote_poll = 0.0
        self._last_heartbeat = 0.0
        self._last_login_retry = 0.0
        self._last_subscribe_retry = 0.0
        self._api_calls = 0
        self._api_errors = 0
        self._mode = "bootstrap"

        # 종목 데이터
        self.stocks: List[Dict[str, Any]] = []
        self._stock_by_code: Dict[str, Dict[str, Any]] = {}

        # 캔들 캐시
        self._candles: Dict[str, List[Dict[str, Any]]] = {}
        self._candle_idx: Dict[str, int] = {}
        self._candle_req_queue: deque[str] = deque()
        self._candle_req_set: set[str] = set()
        self._candles_daily: Dict[str, List[Dict[str, Any]]] = {}

        # 실시간
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
        self._account_no = ""

        # 부하테스트
        self._stress_enabled: Optional[bool] = None
        self._stress_override = os.getenv("PERF_STRESS", "").strip()
        self._stress_interval_ms = int(os.getenv("PERF_STRESS_INTERVAL_MS", "50"))
        self._stress_batch = int(os.getenv("PERF_STRESS_BATCH", "20"))
        self._stress_cycle = 0
        self._stress_candle_replay_idx: Dict[str, int] = {}

        # MySQL
        self._mysql_enabled = False
        self._mysql_cfg: Dict[str, Any] = {}

        # === 부트 시퀀스 ===
        self._wait_for_server_ready()
        self._ensure_login(max_wait_sec=12.0)
        self._bootstrap_universe()

        for s in self.stocks:
            code = str(s.get("code", "")).strip()
            if code:
                self._enqueue_candle_fetch(code)

        print(f"[perf_real] boot: base={self.base_url} "
              f"account={self._account_no or '-'} symbols={len(self.stocks)}")

        self._start_realtime_listener()
        self._start_execution_listener()
        self._subscribe_realtime(force=True)
        self._refresh_dashboard(force=True)
        self._setup_mysql()
        self._run_contract_checks()
        self._start_background_worker()
        atexit.register(self.close)

    # ─── HTTP ─────────────────────────────────────────────────────

    def _request_json(self, method: str, path: str,
                      params: Optional[Dict[str, Any]] = None,
                      body: Any = None, timeout: float = 5.0) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url=url, method=method,
                                     data=data, headers=headers)
        self._api_calls += 1
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}

    def _api_get(self, path: str, params: Optional[Dict[str, Any]] = None,
                 timeout: float = 5.0) -> Dict[str, Any]:
        try:
            return self._request_json("GET", path, params=params, timeout=timeout)
        except Exception as ex:
            self._api_errors += 1
            return {"Success": False, "Message": str(ex), "Data": None}

    def _api_post(self, path: str, body: Any = None,
                  timeout: float = 5.0) -> Dict[str, Any]:
        try:
            return self._request_json("POST", path, body=body, timeout=timeout)
        except Exception as ex:
            self._api_errors += 1
            return {"Success": False, "Message": str(ex), "Data": None}

    @staticmethod
    def _ok(resp: Dict[str, Any]) -> bool:
        return bool(resp and resp.get("Success"))

    @staticmethod
    def _data(resp: Dict[str, Any], default: Any) -> Any:
        if isinstance(resp, dict) and "Data" in resp:
            v = resp.get("Data")
            return v if v is not None else default
        return default

    # ─── 시간 ─────────────────────────────────────────────────────

    @staticmethod
    def _now_kst() -> datetime:
        if ZoneInfo is not None:
            return datetime.now(ZoneInfo("Asia/Seoul"))
        return datetime.now()

    def _is_market_open(self) -> bool:
        now = self._now_kst()
        if now.weekday() >= 5:
            return False
        hhmm = now.hour * 100 + now.minute
        return 900 <= hhmm <= 1530

    def _history_stop_time(self) -> str:
        return (os.getenv("PERF_CANDLE_STOP", "20180101090000").strip()
                or "20180101090000")

    # ─── 부하테스트 제어 ───────────────────────────────────────────

    @property
    def stress_active(self) -> bool:
        if self._stress_override == "1":
            return True
        if self._stress_override == "0":
            return False
        if self._stress_enabled is not None:
            return self._stress_enabled
        return not self._is_market_open()

    def set_stress_enabled(self, enabled: Optional[bool]):
        self._stress_enabled = enabled
        s = "AUTO" if enabled is None else ("ON" if enabled else "OFF")
        print(f"[perf_real] stress -> {s}")

    def set_stress_interval(self, ms: int):
        self._stress_interval_ms = max(10, ms)

    def set_stress_batch(self, n: int):
        self._stress_batch = max(1, min(n, 100))

    # ─── 부트스트랩 ───────────────────────────────────────────────

    def _wait_for_server_ready(self, timeout_sec: float = 15.0) -> None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self._ok(self._api_get("/api/status")):
                return
            time.sleep(0.4)
        print("[perf_real] WARN: server not ready; continuing")

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
        print("[perf_real] WARN: login not ready")
        return False

    def _bootstrap_universe(self) -> None:
        codes_env = os.getenv("PERF_CODES", "").strip()
        codes = ([c.strip() for c in codes_env.split(";") if c.strip()]
                 if codes_env else [])
        names: Dict[str, str] = {}

        if not codes:
            cond = self._api_get("/api/conditions")
            cond_list = self._data(cond, [])
            if isinstance(cond_list, list) and cond_list:
                first = cond_list[0]
                idx = _coalesce(first, ["Index", "index"], 0)
                nm = _coalesce(first, ["Name", "name"], "")
                rs = self._api_get("/api/conditions/search",
                                   {"index": idx, "name": nm})
                payload = self._data(rs, {})
                if isinstance(payload, dict):
                    codes = [c for c in
                             (_coalesce(payload, ["Codes"], []) or []) if c]
                    for row in (_coalesce(payload, ["Stocks"], []) or []):
                        if not isinstance(row, dict):
                            continue
                        c2 = str(_coalesce(row, ["code", K_CODE], "")).strip()
                        n2 = str(_coalesce(row, ["name", K_NAME], "")).strip()
                        if c2:
                            names[c2] = n2

        if not codes:
            codes = self.DEFAULT_CODES[:]
        codes = list(dict.fromkeys(codes))[:max(1, min(self.n, len(codes)))]

        stocks: List[Dict[str, Any]] = []
        for code in codes:
            sym = self._api_get("/api/market/symbol", {"code": code})
            sym_data = self._data(sym, {})
            name = (names.get(code)
                    or str(_coalesce(sym_data, ["name", K_NAME], code)))
            last = _abs_num(_coalesce(sym_data, ["last_price", "current_price"], 0))
            base = last if last > 0 else 10000.0
            stocks.append({
                "code": code, "name": name, "sector": "UNKNOWN",
                "base_price": base, "open_price": base, "price": base,
                "prev_close": base, "high": base, "low": base,
                "volume_acc": 0.0, "tick_count": 0,
                "avg5d": 1000.0, "prev_d": 1000.0,
                "tes": 0.0, "ucs": 0.0, "frs": 0.0,
                "hms": 0.0, "bms": 0.0, "sls": 0.0,
                "axes": 0, "candle_idx": 0,
            })

        with self._lock:
            self.stocks = stocks
            self._stock_by_code = {s["code"]: s for s in stocks}

        self._compute_historical_metrics()

    def _compute_historical_metrics(self) -> None:
        with self._lock:
            codes = [s["code"] for s in self.stocks[:20]]

        day = self._now_kst().strftime("%Y%m%d")
        for code in codes:
            resp = self._api_get("/api/market/candles/daily",
                                 {"code": code, "date": day,
                                  "stopDate": "20240101"}, timeout=8)
            rows = self._data(resp, [])
            if not isinstance(rows, list) or len(rows) < 2:
                continue

            parsed: List[Dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                dt = str(_coalesce(r, ["date", K_DATE], "")).strip()
                v = _abs_num(_coalesce(r, [K_VOL, "volume"], 0))
                c = _abs_num(_coalesce(r, [K_CLOSE, K_CLOSE_ALT, "close"], 0))
                o = _abs_num(_coalesce(r, [K_OPEN, "open"], 0))
                h = _abs_num(_coalesce(r, [K_HIGH, "high"], 0))
                lo = _abs_num(_coalesce(r, [K_LOW, "low"], 0))
                if c > 0 and dt:
                    parsed.append({"date": dt, "volume": v, "close": c,
                                   "open": o, "high": h, "low": lo})

            parsed.sort(key=lambda x: x["date"], reverse=True)
            if len(parsed) < 2:
                continue

            prev_d_vol = (parsed[0]["volume"]
                          if parsed[0]["volume"] > 0 else parsed[1]["volume"])
            avg5d_vol = (sum(p["volume"] for p in parsed[:5])
                         / min(5, len(parsed[:5])))
            prev_close = (parsed[1]["close"]
                          if len(parsed) > 1 else parsed[0]["close"])

            with self._lock:
                s = self._stock_by_code.get(code)
                if s:
                    s["avg5d"] = max(1.0, avg5d_vol)
                    s["prev_d"] = max(1.0, prev_d_vol)
                    s["prev_close"] = prev_close
                self._candles_daily[code] = parsed

    # ─── 실시간 구독 ──────────────────────────────────────────────

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
        resp = self._api_get("/api/realtime/subscribe",
                             {"codes": ";".join(codes), "screen": self.screen})
        ok = self._ok(resp)
        self._rt_subscribed = ok
        if ok:
            print(f"[perf_real] RT subscribed: {len(codes)} codes")
        return ok

    # ─── 캔들 프리로드 ─────────────────────────────────────────────

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
        rows = self._fetch_candles_minute(code)
        if rows:
            with self._lock:
                self._candles[code] = rows
                self._candle_idx[code] = max(0, len(rows) - min(120, len(rows)))
            print(f"[perf_real] candle loaded: {code} -> {len(rows)} bars")

    def _fetch_candles_minute(self, code: str) -> List[Dict[str, Any]]:
        stop_time = self._history_stop_time()
        resp = self._api_get("/api/market/candles/minute",
                             {"code": code, "tick": self.tick_unit,
                              "stopTime": stop_time}, timeout=10)
        rows = self._data(resp, [])
        if not rows:
            retry_stop = self._now_kst().strftime("%Y%m%d%H%M%S")
            resp = self._api_get("/api/market/candles/minute",
                                 {"code": code, "tick": self.tick_unit,
                                  "stopTime": retry_stop}, timeout=10)
            rows = self._data(resp, [])
        return self._parse_candle_rows(rows)

    @staticmethod
    def _parse_candle_rows(rows: Any) -> List[Dict[str, Any]]:
        """
        키움 브로커 캔들 데이터 파싱.
        핵심: 모든 가격은 abs() 처리. 키움은 하락 시 음수를 반환함.
        """
        out: List[Dict[str, Any]] = []
        if not isinstance(rows, list):
            return out

        for row in rows:
            if not isinstance(row, dict):
                continue

            # 타임스탬프
            t = str(_coalesce(row,
                [K_TIME, "time", K_DATE, "timestamp", "date"], "")).strip()

            # OHLCV — 반드시 절대값
            o = _abs_num(_coalesce(row, [K_OPEN, "open"], 0))
            h = _abs_num(_coalesce(row, [K_HIGH, "high"], 0))
            lo = _abs_num(_coalesce(row, [K_LOW, "low"], 0))
            c = _abs_num(_coalesce(row, [K_CLOSE, K_CLOSE_ALT, "close"], 0))
            v = _abs_num(_coalesce(row, [K_VOL, "volume"], 0))

            if c <= 0:
                continue

            # 누락 보정
            if o <= 0:
                o = c
            if h <= 0:
                h = max(o, c)
            if lo <= 0:
                lo = min(o, c)

            # OHLC 정합성 보정
            h = max(h, o, c)
            lo = min(lo, o, c)
            if lo <= 0:
                lo = min(o, c)

            out.append({"t": t, "o": o, "h": h, "l": lo, "c": c, "v": v})

        out.sort(key=lambda x: x["t"])
        return out

    # ─── WebSocket: 실시간 시세 ────────────────────────────────────

    def _start_realtime_listener(self) -> None:
        if websockets is None:
            print("[perf_real] RT WS disabled (no websockets)")
            return
        self._rt_thread = threading.Thread(
            target=self._rt_loop_runner, daemon=True)
        self._rt_thread.start()

    def _rt_loop_runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._realtime_loop())
        finally:
            loop.close()

    async def _realtime_loop(self) -> None:
        uri = f"{self.ws_url}/ws/realtime"
        while not self._rt_stop.is_set():
            try:
                async with websockets.connect(uri) as ws:
                    self._rt_connected = True
                    print(f"[perf_real] RT WS connected: {uri}")
                    self._subscribe_realtime(force=True)
                    while not self._rt_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=20)
                        except asyncio.TimeoutError:
                            continue
                        self._on_realtime(json.loads(raw))
            except Exception as ex:
                if self._rt_connected:
                    print(f"[perf_real] RT WS lost: {ex}")
                self._rt_connected = False
                self._rt_subscribed = False
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

            price = _abs_num(_coalesce(data,
                ["current_price", "price", K_CLOSE], 0))
            op = _abs_num(_coalesce(data, ["open", K_OPEN], 0))
            hi = _abs_num(_coalesce(data, ["high", K_HIGH], 0))
            lo = _abs_num(_coalesce(data, ["low", K_LOW], 0))
            vol = _abs_num(_coalesce(data,
                ["cum_volume", "volume", K_VOL], 0))
            rate = _to_num(_coalesce(data, ["rate", "change_rate"], 0))
            diff = _to_num(_coalesce(data, ["diff", "change"], 0))
            intensity = _abs_num(_coalesce(data, ["intensity"], 0))

            if price > 0:
                s["price"] = price
            if op > 0:
                s["open_price"] = op
            if hi > 0:
                s["high"] = max(s.get("high", 0), hi)
            if lo > 0:
                cur_lo = s.get("low", 0)
                s["low"] = min(cur_lo, lo) if cur_lo > 0 else lo
            if vol > 0:
                s["volume_acc"] = vol

            self._recompute_scores(s, rate, diff, intensity)
            s["tick_count"] += 1
            self._rt_recv_count += 1
            self._rt_last_recv_ts = time.time()

    # ─── WebSocket: 체결/잔고 ──────────────────────────────────────

    def _start_execution_listener(self) -> None:
        if websockets is None:
            return
        self._exec_thread = threading.Thread(
            target=self._exec_loop_runner, daemon=True)
        self._exec_thread.start()

    def _exec_loop_runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._execution_loop())
        finally:
            loop.close()

    async def _execution_loop(self) -> None:
        uri = f"{self.ws_url}/ws/execution"
        while not self._exec_stop.is_set():
            try:
                async with websockets.connect(uri) as ws:
                    self._exec_connected = True
                    print(f"[perf_real] EXEC WS connected")
                    while not self._exec_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            continue
                        self._on_execution(json.loads(raw))
            except Exception:
                self._exec_connected = False
                await asyncio.sleep(2.0)

    def _on_execution(self, evt: Dict[str, Any]) -> None:
        evt_type = str(evt.get("type", "")).lower()
        data = evt.get("data", {}) or {}
        self._exec_recv_count += 1
        if evt_type == "dashboard" and isinstance(data, dict):
            with self._lock:
                self._last_dashboard = data
        elif evt_type in ("order", "balance"):
            self._refresh_dashboard(force=True)

    # ─── 스코어 계산 ──────────────────────────────────────────────

    def _recompute_scores(self, s: Dict[str, Any],
                          rate: float = 0.0, diff: float = 0.0,
                          intensity: float = 0.0) -> None:
        price = _to_num(s.get("price", 0))
        open_p = _to_num(s.get("open_price", 0))

        if rate == 0 and open_p > 0 and price > 0:
            rate = (price - open_p) / open_p * 100.0
        if diff == 0 and open_p > 0 and price > 0:
            diff = price - open_p

        abs_rate = abs(rate)
        vol_acc = _to_num(s.get("volume_acc", 0))
        avg5d = max(1.0, _to_num(s.get("avg5d", 1000)))
        prev_d = max(1.0, _to_num(s.get("prev_d", 1000)))
        tc = max(1.0, _to_num(s.get("tick_count", 1)))
        vol_ratio = vol_acc / avg5d if avg5d > 0 else 0

        s["tes"] = max(0.0, min(3.0,
            abs_rate / 2.5 + intensity / 200.0 + min(tc / (avg5d * 0.0385), 1.0) * 0.5))
        s["hms"] = max(0.0, min(1.0,
            (rate / 10.0 + 0.5) * 0.6 + min(vol_ratio, 1.0) * 0.4))
        s["bms"] = max(0.0, min(1.0,
            abs_rate / 5.0 * 0.5 + min(intensity / 120.0, 1.0) * 0.5))
        s["sls"] = max(0.0, min(1.0,
            min(1.0, vol_acc / 5_000_000) * 0.7 + min(vol_ratio, 1.0) * 0.3))
        s["ucs"] = max(0.0, min(1.0,
            s["hms"] * 0.4 + s["bms"] * 0.35 + s["sls"] * 0.25))
        s["frs"] = max(0.0, min(2.5,
            s["tes"] * 0.5 + s["ucs"] * 1.0
            + min(tc / (avg5d * 0.0385), 1.5) * 0.3))

        axes = 0
        if s["hms"] >= 0.4: axes += 1
        if s["bms"] >= 0.4: axes += 1
        if s["sls"] >= 0.4: axes += 1
        s["axes"] = axes

    # ─── 백그라운드 워커 ───────────────────────────────────────────

    def _start_background_worker(self) -> None:
        self._bg_thread = threading.Thread(
            target=self._background_loop, daemon=True)
        self._bg_thread.start()

    def _background_loop(self) -> None:
        stress_timer = 0.0
        while not self._bg_stop.is_set():
            try:
                now = time.time()
                market_open = self._is_market_open()
                is_stress = self.stress_active

                if market_open:
                    self._mode = "realtime"
                elif is_stress:
                    self._mode = "stress_test"
                else:
                    self._mode = "closed_idle"

                # 로그인 유지
                if not self._account_no and now - self._last_login_retry > 3.0:
                    self._ensure_login(max_wait_sec=2.0)
                    self._last_login_retry = now

                # 구독 유지
                if (self._account_no
                        and now - self._last_subscribe_retry
                        > (4.0 if market_open else 30.0)):
                    stale = (self._rt_last_recv_ts <= 0
                             or now - self._rt_last_recv_ts > 15.0)
                    if self._rt_connected and (
                            not self._rt_subscribed
                            or (market_open and stale)):
                        self._subscribe_realtime(force=True)
                    self._last_subscribe_retry = now

                # 대시보드
                if now - self._last_dashboard_poll > 5.0:
                    self._refresh_dashboard(force=False)
                    self._last_dashboard_poll = now

                # 호가 폴링
                qi = 2.0 if market_open else 30.0
                if now - self._last_quote_poll > qi:
                    self._refresh_quotes()
                    self._last_quote_poll = now

                # 캔들 프리로드
                self._process_candle_fetch_once()

                # 부하테스트
                if is_stress and not market_open:
                    iv = self._stress_interval_ms / 1000.0
                    if now - stress_timer >= iv:
                        self._run_stress_tick()
                        stress_timer = now

                # 하트비트
                if now - self._last_heartbeat > 5.0:
                    self._print_heartbeat(now)
                    self._last_heartbeat = now

            except Exception as ex:
                print(f"[perf_real] bg error: {ex}")
            time.sleep(0.02)

    # ─── 부하테스트: 캔들 리플레이 ──────────────────────────────────

    def _run_stress_tick(self) -> None:
        self._stress_cycle += 1
        with self._lock:
            targets = self.stocks[:self._stress_batch]

        for s in targets:
            code = s["code"]
            series = self._candles.get(code, [])
            if not series:
                continue
            idx = self._stress_candle_replay_idx.get(code, 0)
            if idx >= len(series):
                idx = 0
            candle = series[idx]
            self._stress_candle_replay_idx[code] = idx + 1

            with self._lock:
                sr = self._stock_by_code.get(code)
                if not sr:
                    continue
                sr["price"] = candle["c"]
                if candle["o"] > 0:
                    sr["open_price"] = candle["o"]
                sr["high"] = max(sr.get("high", 0), candle["h"])
                lo_cur = sr.get("low", 0)
                sr["low"] = (min(lo_cur, candle["l"])
                             if lo_cur > 0 else candle["l"])
                sr["volume_acc"] += candle["v"]
                sr["tick_count"] += 1
                rate = 0.0
                op = _to_num(sr.get("open_price", 0))
                if op > 0:
                    rate = (candle["c"] - op) / op * 100.0
                self._recompute_scores(sr, rate=rate)

    # ─── 주기적 리프레시 ───────────────────────────────────────────

    def _refresh_quotes(self) -> None:
        with self._lock:
            codes = [s["code"] for s in self.stocks if s.get("code")]
        for code in codes[:min(20, len(codes))]:
            sym = self._api_get("/api/market/symbol", {"code": code})
            if not self._ok(sym):
                continue
            data = self._data(sym, {})
            if not isinstance(data, dict):
                continue

            price = _abs_num(_coalesce(data,
                ["last_price", "current_price", "price", K_CLOSE], 0))
            op = _abs_num(_coalesce(data, ["open", K_OPEN], 0))
            vol = _abs_num(_coalesce(data,
                ["cum_volume", "volume", K_VOL], 0))

            with self._lock:
                s = self._stock_by_code.get(code)
                if not s:
                    continue
                prev = _to_num(s.get("price", 0))
                if price > 0:
                    s["price"] = price
                if op > 0:
                    s["open_price"] = op
                if vol > 0:
                    s["volume_acc"] = vol
                if price > 0 and price != prev:
                    s["tick_count"] += 1
                    self._recompute_scores(s)

    def _refresh_dashboard(self, force: bool) -> None:
        path = "/api/dashboard/refresh" if force else "/api/dashboard"
        resp = self._api_get(path)
        if self._ok(resp):
            data = self._data(resp, {})
            if isinstance(data, dict):
                with self._lock:
                    self._last_dashboard = data
        else:
            msg = str(resp.get("Message", "")).lower()
            if "not logged in" in msg:
                self._account_no = ""

    def _print_heartbeat(self, now_ts: float) -> None:
        with self._lock:
            s = self.stocks[0] if self.stocks else None
            sample = "-"
            if s:
                sample = (f"{s.get('code','-')}:"
                          f"{_to_num(s.get('price')):,.0f} "
                          f"t={int(_to_num(s.get('tick_count')))}")
            # 캔들 로드 상태
            loaded = sum(1 for c in self._candles.values() if c)
            total = len(self.stocks)
            pending = len(self._candle_req_queue)

        last_sec = (int(now_ts - self._rt_last_recv_ts)
                    if self._rt_last_recv_ts > 0 else -1)
        st = f" stress_cyc={self._stress_cycle}" if self.stress_active else ""
        print(
            f"[perf_real] hb rt={'on' if self._rt_connected else 'off'} "
            f"sub={'on' if self._rt_subscribed else 'off'} "
            f"acct={self._account_no or '-'} mode={self._mode} "
            f"recv={self._rt_recv_count} last={last_sec}s "
            f"api={self._api_calls} candles={loaded}/{total}(pend={pending})"
            f"{st} sample={sample}"
        )

    # ─── UI 인터페이스 (DummyDataSimulator 호환) ──────────────────

    def tick(self) -> None:
        pass

    def get_universe_grid(self) -> List[list]:
        with self._lock:
            ss = sorted(self.stocks,
                        key=lambda x: x.get("frs", 0.0), reverse=True)
            rows = []
            for rank, s in enumerate(ss, 1):
                op = max(1.0, _to_num(s.get("open_price")))
                p = _to_num(s.get("price"))
                chg = (p - op) / op * 100.0
                tv = _to_num(s.get("volume_acc")) * p / 1e8
                a5 = max(1.0, _to_num(s.get("avg5d", 1000)))
                pd = max(1.0, _to_num(s.get("prev_d", 1000)))
                tc = max(1.0, _to_num(s.get("tick_count", 1)))
                r1 = tc / (a5 * 0.0385) if a5 > 0 else 0
                r2 = tc / (pd * 0.0385) if pd > 0 else 0
                r3 = pd / a5 if a5 > 0 else 1.0
                rows.append([
                    rank, s.get("code", ""), s.get("name", ""),
                    p, chg, tv,
                    _to_num(s.get("tes")), _to_num(s.get("ucs")),
                    _to_num(s.get("frs")),
                    r1, r2, r3, int(_to_num(s.get("axes", 0))),
                    ("ENTRY" if rank <= 5 else
                     "WATCH" if rank <= 15 else "IDLE"),
                    s.get("sector", "UNKNOWN"),
                ])
            return rows

    def get_universe_tree(self) -> List[dict]:
        with self._lock:
            ss = sorted(self.stocks,
                        key=lambda x: x.get("frs", 0.0), reverse=True)
            out = []
            for rank, s in enumerate(ss, 1):
                op = max(1.0, _to_num(s.get("open_price")))
                p = _to_num(s.get("price"))
                chg = (p - op) / op * 100.0
                out.append({
                    "code": s.get("code", ""),
                    "name": s.get("name", ""),
                    "change": chg,
                    "tes": _to_num(s.get("tes")),
                    "ucs": _to_num(s.get("ucs")),
                    "frs": _to_num(s.get("frs")),
                    "axes": int(_to_num(s.get("axes", 0))),
                    "is_target": rank <= 5,
                    "sector": s.get("sector", "UNKNOWN"),
                })
            return out

    def get_stock_detail(self, code: str) -> dict:
        with self._lock:
            s = self._stock_by_code.get(code)
            if s is None:
                return {}
            p = _to_num(s.get("price"))
            op = max(1.0, _to_num(s.get("open_price")))
            chg = (p - op) / op * 100.0
            a5 = max(1.0, _to_num(s.get("avg5d", 1000)))
            pd = max(1.0, _to_num(s.get("prev_d", 1000)))
            tc = max(1.0, _to_num(s.get("tick_count", 1)))
            r1 = tc / (a5 * 0.0385) if a5 > 0 else 0
            r2 = tc / (pd * 0.0385) if pd > 0 else 0
            r3 = pd / a5 if a5 > 0 else 1.0

            atr_val = 0.0
            daily = self._candles_daily.get(code, [])
            if len(daily) >= 14:
                trs = [d.get("high", 0) - d.get("low", 0)
                       for d in daily[:14]]
                atr_val = sum(trs) / len(trs) if trs else 0

            return {
                "code": s.get("code", ""), "name": s.get("name", ""),
                "price": p, "change": chg,
                "market_cap": "-",
                "trade_value": f"{_to_num(s.get('volume_acc'))*p/1e8:,.1f}",
                "tes": _to_num(s.get("tes")),
                "ucs": _to_num(s.get("ucs")),
                "frs": _to_num(s.get("frs")),
                "AVG5D": f"{int(a5):,}",
                "PREV_D": f"{int(pd):,}",
                "TODAY_15M": f"{int(tc):,}",
                "R1": f"{r1:.2f}", "R2": f"{r2:.2f}", "R3": f"{r3:.2f}",
                "change_rate": f"{chg:+.2f}%",
                "TES Z": f"{_to_num(s.get('tes')):.3f}",
                "ATR\u2081\u2084": f"{atr_val:.0f}",
                "HMS": _to_num(s.get("hms")),
                "BMS": _to_num(s.get("bms")),
                "SLS": _to_num(s.get("sls")),
            }

    def get_positions(self) -> List[list]:
        with self._lock:
            holdings = self._last_dashboard.get("Holdings") or []
            rows = []
            for h in holdings:
                if not isinstance(h, dict):
                    continue
                code = str(_coalesce(h, ["code", K_CODE], "")).strip()
                name = str(_coalesce(h, ["name", K_NAME], code)).strip()
                qty = int(_abs_num(_coalesce(h, ["qty", K_HOLD_QTY], 0)))
                avg = _abs_num(_coalesce(h, ["avg_price"], 0))
                cur = _abs_num(_coalesce(h, ["price", K_CLOSE], 0))
                pnl = _to_num(_coalesce(h, ["pnl"], 0))
                pnl_pct = _to_num(_coalesce(h, ["pnl_rate"], 0))
                stop = avg * 0.97 if avg > 0 else 0.0
                tes = _to_num(self._stock_by_code.get(code, {}).get("tes", 0))
                rows.append([code, name, qty, avg, cur, pnl_pct, pnl,
                             stop, "1\ucc28(50%)", tes])
            return rows

    def get_pending(self) -> List[list]:
        with self._lock:
            outs = self._last_dashboard.get("Outstanding") or []
            rows = []
            for o in outs:
                if not isinstance(o, dict):
                    continue
                rows.append([
                    str(_coalesce(o, ["order_no", K_ORDER_NO], "")),
                    str(_coalesce(o, ["code", K_CODE], "")),
                    str(_coalesce(o, ["name", K_NAME], "")),
                    str(_coalesce(o, ["type"], "")),
                    _abs_num(_coalesce(o, ["price", K_CLOSE], 0)),
                    int(_abs_num(_coalesce(o, ["qty"], 0))),
                    int(_abs_num(_coalesce(o, ["remain", K_UNFILLED], 0))),
                    str(_coalesce(o, ["status"], "")),
                ])
            return rows

    def generate_candle(self, stock_idx: int
                        ) -> Tuple[float, float, float, float, float, int]:
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
                return p, p, p, p, 0.0, s["candle_idx"]

            if i >= len(series):
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
            return (row["o"], row["h"], row["l"], row["c"],
                    row["v"], s["candle_idx"])

    # ─── 검증 & MySQL ─────────────────────────────────────────────

    def _run_contract_checks(self) -> None:
        code = "000660"
        day = self._now_kst().strftime("%Y%m%d")
        stop = self._history_stop_time()
        daily = self._api_get("/api/market/candles/daily",
                              {"code": code, "date": day,
                               "stopDate": "20180101"}, timeout=10)
        minute = self._api_get("/api/market/candles/minute",
                               {"code": code, "tick": 1,
                                "stopTime": stop}, timeout=10)
        tick = self._api_get("/api/market/candles/tick",
                             {"code": code, "tick": 1,
                              "stopTime": stop}, timeout=10)
        dc = len(self._data(daily, []) or [])
        mc = len(self._data(minute, []) or [])
        tc = len(self._data(tick, []) or [])
        print(f"[perf_real] contract {code}: daily={dc} min={mc} tick={tc}")

        # 첫 번째 캔들 데이터 디버그 출력
        daily_rows = self._data(daily, [])
        if isinstance(daily_rows, list) and daily_rows:
            sample = daily_rows[0]
            print(f"[perf_real] CANDLE SAMPLE (raw): {json.dumps(sample, ensure_ascii=False)[:300]}")
            parsed = self._parse_candle_rows([sample])
            if parsed:
                print(f"[perf_real] CANDLE SAMPLE (parsed): {parsed[0]}")

        minute_rows = self._data(minute, [])
        if isinstance(minute_rows, list) and minute_rows:
            sample = minute_rows[0]
            print(f"[perf_real] MINUTE SAMPLE (raw): {json.dumps(sample, ensure_ascii=False)[:300]}")
            parsed = self._parse_candle_rows([sample])
            if parsed:
                print(f"[perf_real] MINUTE SAMPLE (parsed): {parsed[0]}")

    def _setup_mysql(self) -> None:
        host = os.getenv("MYSQL_HOST", "").strip()
        user = os.getenv("MYSQL_USER", "").strip()
        pw = os.getenv("MYSQL_PASSWORD", "").strip()
        db = os.getenv("MYSQL_DB", "stock_info").strip()
        if not (host and user and pw):
            return
        if pymysql is None:
            print("[perf_real] pymysql not installed")
            return
        self._mysql_cfg = {"host": host, "user": user, "password": pw,
                           "database": db, "charset": "utf8mb4",
                           "autocommit": True}
        self._mysql_enabled = True
        print(f"[perf_real] MySQL: {user}@{host}/{db}")
        self._sync_base_info_to_mysql()

    def _mysql_conn(self):
        if not self._mysql_enabled:
            return None
        return pymysql.connect(**self._mysql_cfg)

    def _sync_base_info_to_mysql(self) -> None:
        if not self._mysql_enabled:
            return
        sql = (
            "INSERT INTO stock_base_info(code,name,market,instrument_type,"
            "is_common_stock,is_excluded,sector_role) "
            "VALUES(%s,%s,%s,'STOCK',1,0,'NONE') "
            "ON DUPLICATE KEY UPDATE name=VALUES(name)")
        try:
            conn = self._mysql_conn()
            if not conn:
                return
            with conn:
                with conn.cursor() as cur:
                    with self._lock:
                        rows = [(s["code"], s["name"], "KOSPI")
                                for s in self.stocks if s.get("code")]
                    if rows:
                        cur.executemany(sql, rows)
            print(f"[perf_real] base_info upsert: {len(rows)}")
        except Exception as ex:
            print(f"[perf_real] MySQL error: {ex}")

    def _flush_daily_to_mysql(self, code: str) -> None:
        if not self._mysql_enabled:
            return
        day = datetime.now().strftime("%Y%m%d")
        resp = self._api_get("/api/market/candles/daily",
                             {"code": code, "date": day,
                              "stopDate": "20180101"}, timeout=10)
        rows = self._data(resp, [])
        if not isinstance(rows, list) or not rows:
            return
        sql = (
            "INSERT INTO daily_candles(code,`date`,open,high,low,`close`,"
            "volume,tramount,change_pct) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE open=VALUES(open),high=VALUES(high),"
            "low=VALUES(low),`close`=VALUES(`close`),volume=VALUES(volume),"
            "tramount=VALUES(tramount),change_pct=VALUES(change_pct)")
        params = []
        prev_c = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            dt_raw = str(_coalesce(r, ["date", K_DATE], "")).strip()
            if len(dt_raw) < 8:
                continue
            dt = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}"
            o = int(_abs_num(_coalesce(r, ["open", K_OPEN], 0)))
            h = int(_abs_num(_coalesce(r, ["high", K_HIGH], 0)))
            lo = int(_abs_num(_coalesce(r, ["low", K_LOW], 0)))
            c = int(_abs_num(_coalesce(r, [K_CLOSE, K_CLOSE_ALT, "close"], 0)))
            v = int(_abs_num(_coalesce(r, [K_VOL, "volume"], 0)))
            tra = c * v
            cpct = (round((c - prev_c) / prev_c * 100, 2)
                    if prev_c and prev_c > 0 else None)
            prev_c = c
            params.append((code, dt, o, h, lo, c, v, tra, cpct))
        if not params:
            return
        try:
            conn = self._mysql_conn()
            if not conn:
                return
            with conn:
                with conn.cursor() as cur:
                    cur.executemany(sql, params)
            print(f"[perf_real] daily upsert {code}: {len(params)}")
        except Exception as ex:
            print(f"[perf_real] MySQL daily error: {ex}")

    # ─── 종료 ─────────────────────────────────────────────────────

    def close(self) -> None:
        self._bg_stop.set()
        self._rt_stop.set()
        self._exec_stop.set()
        try:
            self._api_get("/api/realtime/unsubscribe",
                          {"screen": self.screen, "code": "ALL"})
        except Exception:
            pass
        for t in [self._bg_thread, self._rt_thread, self._exec_thread]:
            if t is not None and t.is_alive():
                t.join(timeout=1.5)
        print("[perf_real] shutdown complete")


###############################################################################
# 차트 패치 — ChartSubWindow.add_candle 수정
###############################################################################

def _patch_chart_add_candle():
    """
    Perf_Test.ChartSubWindow.add_candle()의 BarGraphItem 버그 수정:
    1) y0 → y 파라미터 사용
    2) 음수 가격 방어 (abs)
    3) O==C일 때 최소 body height 보장 (십자형 doji)
    """
    try:
        import Perf_Test as pt
        import pyqtgraph as pg
    except ImportError:
        return

    original_cls = pt.ChartSubWindow

    def patched_add_candle(self, o, h, l, c, v, idx):
        """수정된 캔들 추가 — 올바른 pyqtgraph BarGraphItem 사용"""
        # 절대값 보장
        o, h, l, c, v = abs(o), abs(h), abs(l), abs(c), abs(v)

        # 0 가격 방어
        if c <= 0:
            return
        if o <= 0:
            o = c
        if h <= 0:
            h = max(o, c)
        if l <= 0:
            l = min(o, c)

        # OHLC 정합성
        h = max(h, o, c)
        l = min(l, o, c)

        self._candles.append({
            'o': o, 'h': h, 'l': l, 'c': c, 'v': v, 'idx': idx
        })

        color = pt.Theme.BULL if c >= o else pt.Theme.BEAR

        # 심지 (wick) — 저가~고가 수직선
        wick = pg.PlotDataItem(
            [idx, idx], [l, h],
            pen=pg.mkPen(color, width=1))
        self.chart_widget.addItem(wick)

        # 몸통 (body) — 시가~종가
        body_bottom = min(o, c)
        body_height = abs(c - o)

        # Doji (시가==종가) → 최소 높이 보장
        if body_height < (h - l) * 0.01 + 0.5:
            body_height = max(1.0, (h - l) * 0.02, h * 0.0002)
            body_bottom = c - body_height / 2

        body = pg.BarGraphItem(
            x=[idx],
            height=[body_height],
            width=0.6,
            y0=[body_bottom],  # ← 핵심: 리스트로 전달
            brush=pg.mkBrush(color),
            pen=pg.mkPen(color, width=0.5))
        self.chart_widget.addItem(body)
        self._candle_items.append((wick, body))

        # 오래된 캔들 제거
        while len(self._candles) > self._max_candles:
            self._candles.pop(0)
            old_wick, old_body = self._candle_items.pop(0)
            self.chart_widget.removeItem(old_wick)
            self.chart_widget.removeItem(old_body)

        # 거래량 바 갱신
        try:
            xs = [c_['idx'] for c_ in self._candles]
            hs = [c_['v'] for c_ in self._candles]
            self.volume_bars.setOpts(x=xs, height=hs, width=0.6)
        except Exception:
            pass

        # 이동평균 갱신
        try:
            import numpy as np
            closes = [c_['c'] for c_ in self._candles]
            idxs = [c_['idx'] for c_ in self._candles]
            for period, ma_info in self.ma_lines.items():
                if len(closes) >= period:
                    ma_vals = np.convolve(
                        closes, np.ones(period) / period, 'valid')
                    start = len(closes) - len(ma_vals)
                    x_vals = idxs[start:]
                    ma_info['line'].setData(x_vals, list(ma_vals))
        except Exception:
            pass

        # 자동 범위 조정 — 최근 N봉 기준
        try:
            visible = self._candles[-min(60, len(self._candles)):]
            if visible:
                min_x = visible[0]['idx']
                max_x = visible[-1]['idx']
                min_y = min(c_['l'] for c_ in visible)
                max_y = max(c_['h'] for c_ in visible)
                margin = (max_y - min_y) * 0.05 + 1
                self.chart_widget.setXRange(
                    min_x - 2, max_x + 5, padding=0)
                self.chart_widget.setYRange(
                    min_y - margin, max_y + margin, padding=0)
        except Exception:
            pass

        # 가격/등락률 표시
        self.lbl_price.setText(f"{c:,.0f}")
        chg_pct = (c - o) / o * 100 if o != 0 else 0
        self.lbl_change.setText(f"{chg_pct:+.2f}%")
        self.lbl_change.setStyleSheet(
            f"color: {pt.Theme.BULL if chg_pct > 0 else pt.Theme.BEAR};")

    original_cls.add_candle = patched_add_candle
    print("[perf_real] ChartSubWindow.add_candle PATCHED")


###############################################################################
# Entry Point
###############################################################################

def _add_stress_controls(win) -> None:
    """툴바에 부하테스트 제어 위젯 추가"""
    try:
        from PySide6.QtWidgets import (QPushButton, QLabel, QSpinBox,
                                        QToolBar)
        from PySide6.QtGui import QFont
        from PySide6.QtCore import QTimer as QtTimer
    except ImportError:
        return

    sim = win.sim
    toolbars = win.findChildren(QToolBar)
    if not toolbars:
        return
    tb = toolbars[0]

    tb.addSeparator()
    lbl = QLabel("  STRESS: --  ")
    lbl.setFont(QFont("Consolas", 9))
    tb.addWidget(lbl)

    btn = QPushButton("Auto")
    btn.setFixedWidth(80)
    state = {"mode": "auto"}

    def toggle():
        if state["mode"] == "auto":
            state["mode"] = "on"
            sim.set_stress_enabled(True)
            btn.setText("ON")
            btn.setStyleSheet(
                "background:#7f1d1d;color:#ef4444;font-weight:bold;")
        elif state["mode"] == "on":
            state["mode"] = "off"
            sim.set_stress_enabled(False)
            btn.setText("OFF")
            btn.setStyleSheet(
                "background:#14532d;color:#22c55e;font-weight:bold;")
        else:
            state["mode"] = "auto"
            sim.set_stress_enabled(None)
            btn.setText("Auto")
            btn.setStyleSheet("")

    btn.clicked.connect(toggle)
    tb.addWidget(btn)

    tb.addWidget(QLabel("  ms:"))
    spin_ms = QSpinBox()
    spin_ms.setRange(10, 2000)
    spin_ms.setValue(sim._stress_interval_ms)
    spin_ms.setSuffix("ms")
    spin_ms.setFixedWidth(80)
    spin_ms.valueChanged.connect(lambda v: sim.set_stress_interval(v))
    tb.addWidget(spin_ms)

    tb.addWidget(QLabel("  batch:"))
    spin_b = QSpinBox()
    spin_b.setRange(1, 100)
    spin_b.setValue(sim._stress_batch)
    spin_b.setFixedWidth(60)
    spin_b.valueChanged.connect(lambda v: sim.set_stress_batch(v))
    tb.addWidget(spin_b)

    def update_lbl():
        active = sim.stress_active
        color = "#ef4444" if active else "#22c55e"
        st = "ACTIVE" if active else "OFF"
        lbl.setText(
            f"  STRESS: {st} | {sim._mode} | cyc={sim._stress_cycle}  ")
        lbl.setStyleSheet(f"color:{color};font-weight:bold;")

    timer = QtTimer()
    timer.timeout.connect(update_lbl)
    timer.start(1000)
    lbl._keep = timer


def main() -> None:
    nogui = (os.getenv("PERF_NOGUI", "").strip() == "1"
             or "--nogui" in sys.argv)
    prefer_tk = (os.getenv("PERF_UI", "").strip().lower() == "tk"
                 or "--tk" in sys.argv)

    if nogui:
        sim = RealDataSimulator(50)
        print(f"[perf_real] nogui: stress={sim.stress_active} mode={sim._mode}")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            sim.close()
        return

    if prefer_tk:
        try:
            import tkinter as tk
            from tester_ui import ServerTesterUI
            root = tk.Tk()
            ServerTesterUI(root)
            root.mainloop()
            return
        except Exception as ex:
            print(f"[perf_real] tkinter failed: {ex}")
            traceback.print_exc()

    # Qt + OpenGL
    os.environ.setdefault("QT_OPENGL", "desktop")
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
    os.environ.setdefault("QT_QUICK_BACKEND", "opengl")
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QStyleFactory
        import pyqtgraph as pg
        import Perf_Test as pt
    except Exception as ex:
        print(f"GUI init failed: {ex}")
        print("pip install PySide6 pyqtgraph")
        print("Fallback: python perf_real.py --nogui")
        traceback.print_exc()
        return

    # DummyDataSimulator → RealDataSimulator 교체
    pt.DummyDataSimulator = RealDataSimulator

    # ★ 차트 렌더링 버그 패치 적용 ★
    _patch_chart_add_candle()

    use_gl = os.environ.get("PERF_REAL_OPENGL", "1").strip().lower() not in (
        "0", "false", "off", "no")
    pg.setConfigOptions(antialias=False, useOpenGL=use_gl,
                        enableExperimental=True)

    app = QApplication([])
    app.setStyle(QStyleFactory.create("Fusion"))
    pt.Theme.apply_dark_palette(app)
    app.setStyleSheet(pt.Theme.STYLESHEET)
    app.setFont(QFont(pt.Theme.FONT_FAMILY, pt.Theme.FONT_SIZE_M))

    win = pt.TESMainWindow()
    win.setWindowTitle(
        "TES-Universe Trading Platform (REAL DATA) | KiwoomServer")
    _add_stress_controls(win)
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
