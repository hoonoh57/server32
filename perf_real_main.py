#!/usr/bin/env python3
"""
perf_real.py — KiwoomServer Real-Data Adapter
==============================================
외부 모듈:
  candle_keys.py   서버 캔들 키 자동 탐지
  chart_patch.py   차트 렌더링 패치
  strategy.py      매매 전략/스코어

부팅 흐름:
  1) 서버 대기 → 로그인
  2) 조건식 목록만 로드 (실행 안 함)
  3) 사용자가 UI에서 조건식 선택 → 실행 → 유니버스 구성
     또는 PERF_CONDITION_INDEX 환경변수로 사전 지정
     또는 PERF_CODES로 종목 직접 지정
  4) 백그라운드: 캔들 프리로드, 히스토리 메트릭, 부하테스트

Env:
  PERF_BASE_URL            http://localhost:8082
  PERF_CODES               종목 직접 지정 (;구분)
  PERF_CONDITION_INDEX     자동 실행할 조건식 인덱스
  PERF_SCREEN              1000
  PERF_TICK                1
  PERF_API_THROTTLE        0.3  (요청 간 대기 초)
  PERF_STRESS              1|0
  PERF_STRESS_INTERVAL_MS  50
  PERF_STRESS_BATCH        20
  PERF_CANDLE_STOP         20180101090000
  PERF_REAL_OPENGL         1
  PERF_DIAG                1  (부팅 시 진단 출력)
  PERF_NOGUI               1
  MYSQL_HOST / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
"""

from __future__ import annotations

import asyncio
import atexit
import json
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
    ZoneInfo = None

try:
    import websockets
except Exception:
    websockets = None

try:
    import pymysql
except Exception:
    pymysql = None

import candle_keys
import strategy

# ── 설정 상수 ──
API_THROTTLE_SEC     = float(os.getenv("PERF_API_THROTTLE", "0.3"))
PERF_CONDITION_INDEX = os.getenv("PERF_CONDITION_INDEX", "").strip()

_FALLBACK_CODES = [
    "005930", "000660", "035420", "035720", "051910",
    "005380", "068270", "207940", "012330", "066570",
]


###############################################################################
# 유틸리티
###############################################################################

def _to_num(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s:
        return 0.0
    sign = 1
    while s.startswith("-"):
        sign *= -1
        s = s[1:]
    s = s.lstrip("+").lstrip("0") or "0"
    try:
        return float(s) * sign
    except Exception:
        return 0.0


def _abs_num(v: Any) -> float:
    return abs(_to_num(v))


def _first_valid(d: Dict[str, Any], keys: List[str],
                 default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", " "):
            return d[k]
    return default


_RT_PRICE_KEYS = ["current_price", "price", "\ud604\uc7ac\uac00"]
_RT_OPEN_KEYS  = ["open", "\uc2dc\uac00"]
_RT_HIGH_KEYS  = ["high", "\uace0\uac00"]
_RT_LOW_KEYS   = ["low", "\uc800\uac00"]
_RT_VOL_KEYS   = ["cum_volume", "volume", "\uac70\ub798\ub7c9"]
_RT_RATE_KEYS  = ["rate", "change_rate"]
_RT_DIFF_KEYS  = ["diff", "change"]
_RT_INTEN_KEYS = ["intensity"]


###############################################################################
# RealDataSimulator
###############################################################################

class RealDataSimulator:

    def __init__(self, n: int = 50):
        self.n = n
        self.base_url = os.getenv(
            "PERF_BASE_URL", "http://localhost:8082").rstrip("/")
        self.ws_url = (self.base_url
                       .replace("http://", "ws://")
                       .replace("https://", "wss://"))
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
        self._api_errors = 0
        self._mode = "bootstrap"

        self.stocks: List[Dict[str, Any]] = []
        self._stock_by_code: Dict[str, Dict[str, Any]] = {}
        self._condition_list: List[Dict[str, Any]] = []

        self._candles: Dict[str, List[Dict[str, Any]]] = {}
        self._candle_idx: Dict[str, int] = {}
        self._candle_req_queue: deque[str] = deque()
        self._candle_req_set: set[str] = set()
        self._candles_daily: Dict[str, List[Dict[str, Any]]] = {}
        self._hist_metrics_done = False

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

        self._stress_enabled: Optional[bool] = None
        self._stress_override = os.getenv("PERF_STRESS", "").strip()
        self._stress_interval_ms = int(
            os.getenv("PERF_STRESS_INTERVAL_MS", "50"))
        self._stress_batch = int(os.getenv("PERF_STRESS_BATCH", "20"))
        self._stress_cycle = 0
        self._stress_candle_replay_idx: Dict[str, int] = {}

        self._mysql_enabled = False
        self._mysql_cfg: Dict[str, Any] = {}

        # ═══ 부트 시퀀스 ═══
        self._wait_for_server_ready()
        self._ensure_login(max_wait_sec=12.0)
        self._bootstrap_universe()

        print(f"[perf_real] boot: base={self.base_url} "
              f"account={self._account_no or '-'} "
              f"symbols={len(self.stocks)}")

        self._start_realtime_listener()
        self._start_execution_listener()
        if self.stocks:
            self._subscribe_realtime(force=True)
        self._refresh_dashboard(force=True)
        self._setup_mysql()

        if "--diag" in sys.argv or os.getenv("PERF_DIAG") == "1":
            self._run_diagnostics()

        self._start_background_worker()
        atexit.register(self.close)

    # ═════════════════════════════════════════════════════════
    # HTTP
    # ═════════════════════════════════════════════════════════

    def _request_json(self, method: str, path: str,
                      params: Optional[Dict[str, Any]] = None,
                      body: Any = None,
                      timeout: float = 5.0) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(
            url=url, method=method, data=data, headers=headers)
        self._api_calls += 1
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}

    def _api_get(self, path: str,
                 params: Optional[Dict[str, Any]] = None,
                 timeout: float = 5.0) -> Dict[str, Any]:
        for attempt in range(3):
            try:
                result = self._request_json(
                    "GET", path, params=params, timeout=timeout)
                time.sleep(API_THROTTLE_SEC)
                return result
            except Exception as ex:
                self._api_errors += 1
                if attempt < 2:
                    time.sleep(API_THROTTLE_SEC * (attempt + 2))
                    continue
                return {"Success": False,
                        "Message": str(ex), "Data": None}

    @staticmethod
    def _ok(r: Dict[str, Any]) -> bool:
        return bool(r and r.get("Success"))

    @staticmethod
    def _data(r: Dict[str, Any], default: Any) -> Any:
        if isinstance(r, dict) and "Data" in r:
            v = r.get("Data")
            return v if v is not None else default
        return default

    # ═════════════════════════════════════════════════════════
    # 시간
    # ═════════════════════════════════════════════════════════

    @staticmethod
    def _now_kst() -> datetime:
        return (datetime.now(ZoneInfo("Asia/Seoul"))
                if ZoneInfo else datetime.now())

    def _is_market_open(self) -> bool:
        now = self._now_kst()
        if now.weekday() >= 5:
            return False
        hhmm = now.hour * 100 + now.minute
        return 900 <= hhmm <= 1530

    def _history_stop_time(self) -> str:
        return (os.getenv("PERF_CANDLE_STOP", "20180101090000").strip()
                or "20180101090000")

    # ═════════════════════════════════════════════════════════
    # 부하테스트 제어
    # ═════════════════════════════════════════════════════════

    @property
    def stress_active(self) -> bool:
        if self._stress_override == "1": return True
        if self._stress_override == "0": return False
        if self._stress_enabled is not None: return self._stress_enabled
        return not self._is_market_open()

    def set_stress_enabled(self, v: Optional[bool]):
        self._stress_enabled = v
        print(f"[perf_real] stress -> "
              f"{'AUTO' if v is None else ('ON' if v else 'OFF')}")

    def set_stress_interval(self, ms: int):
        self._stress_interval_ms = max(10, ms)

    def set_stress_batch(self, n: int):
        self._stress_batch = max(1, min(n, 100))

    # ═════════════════════════════════════════════════════════
    # 부트: 로그인
    # ═════════════════════════════════════════════════════════

    def _wait_for_server_ready(self, timeout_sec=15.0):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self._ok(self._api_get("/api/status")): return
            time.sleep(0.4)
        print("[perf_real] WARN: server not ready")

    def _is_logged_in(self) -> bool:
        st = self._api_get("/api/status")
        d = self._data(st, {})
        if isinstance(d, dict) and d.get("IsLoggedIn"):
            self._account_no = str(d.get("AccountNo") or "")
            return True
        self._account_no = ""
        return False

    def _ensure_login(self, max_wait_sec=8.0) -> bool:
        if self._is_logged_in(): return True
        self._api_get("/api/auth/login")
        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            time.sleep(0.4)
            if self._is_logged_in():
                print(f"[perf_real] login ok: {self._account_no}")
                return True
        print("[perf_real] WARN: login not ready")
        return False

    # ═════════════════════════════════════════════════════════
    # 부트: 유니버스
    # ═════════════════════════════════════════════════════════

    def _bootstrap_universe(self) -> None:
        # 1) PERF_CODES 직접 지정
        codes_env = os.getenv("PERF_CODES", "").strip()
        if codes_env:
            forced = [c.strip() for c in codes_env.split(";") if c.strip()]
            print(f"[perf_real] PERF_CODES: {len(forced)}")
            self._load_stocks_by_codes(forced, {})
            return

        # 2) 조건식 목록만 로드
        self._load_condition_list()

        # 3) PERF_CONDITION_INDEX 사전 지정
        if PERF_CONDITION_INDEX:
            try:
                idx = int(PERF_CONDITION_INDEX)
            except ValueError:
                print(f"[perf_real] WARN: invalid PERF_CONDITION_INDEX")
                return
            cond = self._find_condition_by_index(idx)
            if cond:
                nm = _first_valid(cond, ["Name", "name"], "")
                print(f"[perf_real] auto-run: '{nm}' (idx={idx})")
                self.execute_condition(idx, nm)
            else:
                print(f"[perf_real] WARN: idx={idx} not found")
            return

        # 4) stocks가 비어 있으면 플레이스홀더 삽입 (Perf_Test.py 크래시 방지)
        if len(self.stocks) < 5:
            for i in range(5 - len(self.stocks)):
                dummy_code = f"00000{i}"
                self.stocks.append({
                    "code": dummy_code, "name": f"대기중 #{i+1}",
                    "sector": "NONE",
                    "base_price": 1, "open_price": 1, "price": 1,
                    "prev_close": 1, "high": 1, "low": 1,

                    "prev_close": 0, "high": 0, "low": 0,
                    "volume_acc": 0, "tick_count": 0,
                    "avg5d": 1.0, "prev_d": 1.0,
                    "tes": 0, "ucs": 0, "frs": 0,
                    "hms": 0, "bms": 0, "sls": 0,
                    "axes": 0, "candle_idx": 0,
                    "_placeholder": True,
                })
                self._stock_by_code[dummy_code] = self.stocks[-1]


        print(f"[perf_real] {len(self._condition_list)} conditions. "
              f"Select one to start.")


    def _load_condition_list(self) -> None:
        resp = self._api_get("/api/conditions")
        cl = self._data(resp, [])
        if isinstance(cl, list):
            self._condition_list = cl
            for c in cl:
                idx = _first_valid(c, ["Index", "index"], "?")
                nm = _first_valid(c, ["Name", "name"], "?")
                print(f"[perf_real]   [{idx}] {nm}")
        else:
            self._condition_list = []

    def _find_condition_by_index(self, idx: int) -> Optional[Dict]:
        for c in self._condition_list:
            ci = _first_valid(c, ["Index", "index"], None)
            if ci is not None and int(ci) == idx:
                return c
        return None

    def execute_condition(self, index: int, name: str) -> bool:
        """조건식 1개 실행 → 유니버스 구성. UI/환경변수에서 호출."""
        print(f"[perf_real] condition '{name}' (idx={index})...")

        rs = self._api_get("/api/conditions/search",
                           {"index": index, "name": name}, timeout=8)
        if not self._ok(rs):
            print(f"[perf_real] search failed: {rs.get('Message')}")
            return False

        payload = self._data(rs, {})
        if not isinstance(payload, dict):
            return False

        codes = [str(c).strip()
                 for c in (_first_valid(payload, ["Codes"], []) or [])
                 if str(c).strip()]
        names: Dict[str, str] = {}
        for row in (_first_valid(payload, ["Stocks"], []) or []):
            if not isinstance(row, dict): continue
            c = str(_first_valid(row,
                    ["code", "\uc885\ubaa9\ucf54\ub4dc"], "")).strip()
            n = str(_first_valid(row,
                    ["name", "\uc885\ubaa9\uba85"], "")).strip()
            if c and n:
                names[c] = n

        if not codes:
            print(f"[perf_real] '{name}': 0 stocks")
            return False

        print(f"[perf_real] '{name}': {len(codes)} stocks")
        self._load_stocks_by_codes(codes, names)
        return True

    def _load_stocks_by_codes(self, codes: List[str],
                              names: Dict[str, str]) -> None:
        # 플레이스홀더 제거
        with self._lock:
            self.stocks = [s for s in self.stocks if not s.get("_placeholder")]
            self._stock_by_code.pop("000000", None)

        codes = list(dict.fromkeys(codes))[:max(1, self.n)]
        stocks: List[Dict[str, Any]] = []
        print(f"[perf_real] loading {len(codes)} symbols...")


        for i, code in enumerate(codes):
            sym = self._api_get("/api/market/symbol", {"code": code})
            sd = self._data(sym, {})
            name = (names.get(code)
                    or str(_first_valid(sd,
                           ["name", "\uc885\ubaa9\uba85"], code)))
            last = _abs_num(_first_valid(sd,
                            ["last_price", "current_price"], 0))
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
            if (i + 1) % 10 == 0:
                print(f"[perf_real]   {i+1}/{len(codes)}")

        with self._lock:
            self.stocks = stocks
            self._stock_by_code = {s["code"]: s for s in stocks}
            self._candles.clear()
            self._candle_idx.clear()
            self._candle_req_queue.clear()
            self._candle_req_set.clear()
            self._candles_daily.clear()
            self._stress_candle_replay_idx.clear()
            self._hist_metrics_done = False

        print(f"[perf_real] universe: {len(stocks)} "
              f"[{', '.join(s['code'] for s in stocks[:5])}...]")

        for s in stocks:
            self._enqueue_candle_fetch(s["code"])

        if self._rt_connected:
            self._subscribe_realtime(force=True)

    # ═════════════════════════════════════════════════════════
    # 히스토리 메트릭 (백그라운드 점진 로드)
    # ═════════════════════════════════════════════════════════

    def _compute_historical_metrics_one(self) -> None:
        with self._lock:
            pending = [s["code"] for s in self.stocks
                       if s.get("avg5d") == 1000.0]
            if not pending:
                self._hist_metrics_done = True
                return

        code = pending[0]
        day = self._now_kst().strftime("%Y%m%d")
        resp = self._api_get("/api/market/candles/daily",
                             {"code": code, "date": day,
                              "stopDate": "20240101"}, timeout=8)
        rows = self._data(resp, [])

        if not isinstance(rows, list) or len(rows) < 2:
            with self._lock:
                s = self._stock_by_code.get(code)
                if s: s["avg5d"] = 1001.0
            return

        parsed = []
        for r in rows:
            if not isinstance(r, dict): continue
            p = candle_keys.keymap_daily.parse(r)
            if p and p["c"] > 0:
                parsed.append({"date": p["t"], "volume": p["v"],
                                "close": p["c"], "open": p["o"],
                                "high": p["h"], "low": p["l"]})

        parsed.sort(key=lambda x: x["date"], reverse=True)
        if len(parsed) < 2:
            with self._lock:
                s = self._stock_by_code.get(code)
                if s: s["avg5d"] = 1001.0
            return

        pv = parsed[0]["volume"] if parsed[0]["volume"] > 0 else parsed[1]["volume"]
        a5 = sum(p["volume"] for p in parsed[:5]) / min(5, len(parsed[:5]))
        pc = parsed[1]["close"] if len(parsed) > 1 else parsed[0]["close"]

        with self._lock:
            s = self._stock_by_code.get(code)
            if s:
                s["avg5d"] = max(1.0, a5)
                s["prev_d"] = max(1.0, pv)
                s["prev_close"] = pc
            self._candles_daily[code] = parsed

    # ═════════════════════════════════════════════════════════
    # 실시간 구독
    # ═════════════════════════════════════════════════════════

    def _subscribe_realtime(self, force=False) -> bool:
        if not self._account_no:
            self._rt_subscribed = False
            return False
        with self._lock:
            codes = [s["code"] for s in self.stocks]
        if not codes: return False
        if self._rt_subscribed and not force: return True
        resp = self._api_get("/api/realtime/subscribe",
                             {"codes": ";".join(codes),
                              "screen": self.screen})
        self._rt_subscribed = self._ok(resp)
        if self._rt_subscribed:
            print(f"[perf_real] RT subscribed: {len(codes)}")
        return self._rt_subscribed

    # ═════════════════════════════════════════════════════════
    # 캔들 프리로드
    # ═════════════════════════════════════════════════════════

    def _enqueue_candle_fetch(self, code: str):
        code = str(code).strip()
        if not code: return
        with self._lock:
            if code in self._candle_req_set: return
            self._candle_req_set.add(code)
            self._candle_req_queue.append(code)

    def _process_candle_fetch_once(self):
        code = ""
        with self._lock:
            if self._candle_req_queue:
                code = self._candle_req_queue.popleft()
                self._candle_req_set.discard(code)
        if not code: return

        rows = self._fetch_candles_minute(code)
        if rows:
            spread = any(abs(r["h"] - r["l"]) > 0.01 for r in rows[:20])
            with self._lock:
                self._candles[code] = rows
                self._candle_idx[code] = max(0, len(rows) - min(120, len(rows)))
            print(f"[perf_real] candle {code}: {len(rows)} bars "
                  f"spread={'OK' if spread else 'FLAT!'}")

    def _fetch_candles_minute(self, code: str) -> List[Dict[str, Any]]:
        if not code or code.startswith("0000"):
            return []
        # 자정 넘김 대비: 18시 이전이면 당일, 이후면 당일(=전날 장)
        now = datetime.now()
        if now.hour < 18:
            # 아직 장중이거나 장 직후 → 당일
            trade_date = now.strftime("%Y%m%d")
        else:
            # 18시 이후(자정 포함) → 전 거래일
            trade_date = now.strftime("%Y%m%d")
        # 주말/자정 넘김 보정: 현재 시각이 장 마감(15:30) 이후면 오늘 날짜 사용
        # 자정 넘기면(0~8시) 전일 날짜 사용
        if now.hour < 9:
            from datetime import timedelta
            trade_date = (now - timedelta(days=1)).strftime("%Y%m%d")

        stop = trade_date + "090000"
        resp = self._api_get("/api/market/candles/minute",
                             {"code": code, "tick": self.tick_unit,
                              "stopTime": stop}, timeout=10)
        rows = self._data(resp, [])
        return self._parse_rows(rows, candle_keys.keymap_minute)





    @staticmethod
    def _parse_rows(rows, keymap):
        out = []
        if not isinstance(rows, list): return out
        for row in rows:
            if not isinstance(row, dict): continue
            p = keymap.parse(row)
            if p: out.append(p)
        out.sort(key=lambda x: x["t"])
        return out

    # ═════════════════════════════════════════════════════════
    # 진단
    # ═════════════════════════════════════════════════════════

    def _run_diagnostics(self):
        print("\n" + "=" * 70)
        print("  SERVER DATA DIAGNOSTICS")
        print("=" * 70)
        code = "005930"
        with self._lock:
            # 플레이스홀더가 아닌 실제 종목 찾기
            for s in self.stocks:
                if not s.get("_placeholder"):
                    code = s["code"]
                    break

        from datetime import timedelta
        trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d") if datetime.now().hour < 9 else datetime.now().strftime("%Y%m%d")


        day = self._now_kst().strftime("%Y%m%d")
        stop = self._history_stop_time()

        for label, path, params, km in [
            ("MINUTE", "/api/market/candles/minute",
             {"code": code, "tick": 1,
              "stopTime": trade_date + "090000"},
             candle_keys.keymap_minute),


            ("DAILY", "/api/market/candles/daily",
             {"code": code, "date": day, "stopDate": "20240101"},
             candle_keys.keymap_daily),
            ("TICK", "/api/market/candles/tick",
             {"code": code, "tick": 1,
              "stopTime": trade_date + "090000"},
             candle_keys.keymap_tick),

        ]:
            resp = self._api_get(path, params, timeout=10)
            print(f"  URL: {path}?{urllib.parse.urlencode(params)}")
            print(f"  RESP: Success={resp.get('Success')} Message={resp.get('Message','')[:100]}")

            rows = self._data(resp, [])
            if not isinstance(rows, list) or not rows:
                print(f"\n[{label}] {code}: NO DATA"); continue
            sample = rows[0]
            print(f"\n[{label}] {code}: {len(rows)} rows")
            print(f"  KEYS: {list(sample.keys())}")
            print(f"  RAW:  {json.dumps(sample, ensure_ascii=False, default=str)[:400]}")
            if km.detect(sample):
                print(f"  MAP:  {km.summary()}")
                p = km.parse(sample)
                if p:
                    sp = p["h"] - p["l"]
                    print(f"  OHLC: O={p['o']} H={p['h']} L={p['l']} C={p['c']} V={p['v']}")
                    print(f"  SPREAD: {sp:.2f} {'OK' if sp > 0 else 'ZERO!'}")
            else:
                print(f"  MAP FAILED! keys={list(sample.keys())}")

    # ═════════════════════════════════════════════════════════
    # WebSocket: 실시간 시세
    # ═════════════════════════════════════════════════════════

    def _start_realtime_listener(self):
        if not websockets: return
        self._rt_thread = threading.Thread(
            target=self._rt_runner, daemon=True)
        self._rt_thread.start()

    def _rt_runner(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try: loop.run_until_complete(self._rt_loop())
        finally: loop.close()

    async def _rt_loop(self):
        uri = f"{self.ws_url}/ws/realtime"
        while not self._rt_stop.is_set():
            try:
                async with websockets.connect(uri) as ws:
                    self._rt_connected = True
                    print("[perf_real] RT WS connected")
                    self._subscribe_realtime(force=True)
                    while not self._rt_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=20)
                        except asyncio.TimeoutError: continue
                        self._on_realtime(json.loads(raw))
            except Exception as ex:
                if self._rt_connected:
                    print(f"[perf_real] RT WS lost: {ex}")
                self._rt_connected = False
                self._rt_subscribed = False
                await asyncio.sleep(1.5)

    def _on_realtime(self, evt):
        code = str(evt.get("code", "")).strip()
        data = evt.get("data", {}) or {}
        if not code: return
        with self._lock:
            s = self._stock_by_code.get(code)
            if not s: return
            price = _abs_num(_first_valid(data, _RT_PRICE_KEYS, 0))
            op    = _abs_num(_first_valid(data, _RT_OPEN_KEYS, 0))
            hi    = _abs_num(_first_valid(data, _RT_HIGH_KEYS, 0))
            lo    = _abs_num(_first_valid(data, _RT_LOW_KEYS, 0))
            vol   = _abs_num(_first_valid(data, _RT_VOL_KEYS, 0))
            rate  = _to_num(_first_valid(data, _RT_RATE_KEYS, 0))
            diff  = _to_num(_first_valid(data, _RT_DIFF_KEYS, 0))
            inten = _abs_num(_first_valid(data, _RT_INTEN_KEYS, 0))
            if price > 0: s["price"] = price
            if op > 0:    s["open_price"] = op
            if hi > 0:    s["high"] = max(s.get("high", 0), hi)
            if lo > 0:
                cur = s.get("low", 0)
                s["low"] = min(cur, lo) if cur > 0 else lo
            if vol > 0:   s["volume_acc"] = vol
            strategy.recompute_scores(s, rate, diff, inten)
            s["tick_count"] += 1
            self._rt_recv_count += 1
            self._rt_last_recv_ts = time.time()

    # ═════════════════════════════════════════════════════════
    # WebSocket: 체결/잔고
    # ═════════════════════════════════════════════════════════

    def _start_execution_listener(self):
        if not websockets: return
        self._exec_thread = threading.Thread(
            target=self._exec_runner, daemon=True)
        self._exec_thread.start()

    def _exec_runner(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try: loop.run_until_complete(self._exec_loop())
        finally: loop.close()

    async def _exec_loop(self):
        uri = f"{self.ws_url}/ws/execution"
        while not self._exec_stop.is_set():
            try:
                async with websockets.connect(uri) as ws:
                    self._exec_connected = True
                    while not self._exec_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError: continue
                        evt = json.loads(raw)
                        t = str(evt.get("type", "")).lower()
                        d = evt.get("data", {})
                        self._exec_recv_count += 1
                        if t == "dashboard" and isinstance(d, dict):
                            with self._lock: self._last_dashboard = d
                        elif t in ("order", "balance"):
                            self._refresh_dashboard(force=True)
            except Exception:
                self._exec_connected = False
                await asyncio.sleep(2.0)

    # ═════════════════════════════════════════════════════════
    # 백그라운드 워커
    # ═════════════════════════════════════════════════════════

    def _start_background_worker(self):
        self._bg_thread = threading.Thread(
            target=self._bg_loop, daemon=True)
        self._bg_thread.start()

    def _bg_loop(self):
        stress_timer = 0.0
        hist_timer = 0.0
        while not self._bg_stop.is_set():
            try:
                now = time.time()
                mo = self._is_market_open()
                st = self.stress_active
                self._mode = ("realtime" if mo
                              else "stress_test" if st
                              else "closed_idle")

                if not self._account_no and now - self._last_login_retry > 3:
                    self._ensure_login(max_wait_sec=2.0)
                    self._last_login_retry = now

                if (self._account_no
                        and now - self._last_subscribe_retry > (4 if mo else 30)):
                    stale = self._rt_last_recv_ts <= 0 or now - self._rt_last_recv_ts > 15
                    if self._rt_connected and (not self._rt_subscribed or (mo and stale)):
                        self._subscribe_realtime(force=True)
                    self._last_subscribe_retry = now

                if now - self._last_dashboard_poll > 5:
                    self._refresh_dashboard(force=False)
                    self._last_dashboard_poll = now

                if now - self._last_quote_poll > (2.0 if mo else 30.0):
                    self._refresh_quotes()
                    self._last_quote_poll = now

                if not self._hist_metrics_done and now - hist_timer > 1.0:
                    self._compute_historical_metrics_one()
                    hist_timer = now

                self._process_candle_fetch_once()

                if st and not mo:
                    if now - stress_timer >= self._stress_interval_ms / 1000.0:
                        self._run_stress_tick()
                        stress_timer = now

                if now - self._last_heartbeat > 5:
                    self._print_heartbeat(now)
                    self._last_heartbeat = now
            except Exception as ex:
                print(f"[perf_real] bg err: {ex}")
            time.sleep(0.05)

    # ═════════════════════════════════════════════════════════
    # 부하테스트
    # ═════════════════════════════════════════════════════════

    def _run_stress_tick(self):
        self._stress_cycle += 1
        with self._lock:
            targets = self.stocks[:self._stress_batch]
        for s in targets:
            code = s["code"]
            series = self._candles.get(code, [])
            if not series: continue
            idx = self._stress_candle_replay_idx.get(code, 0)
            if idx >= len(series): idx = 0
            candle = series[idx]
            self._stress_candle_replay_idx[code] = idx + 1
            with self._lock:
                sr = self._stock_by_code.get(code)
                if not sr: continue
                sr["price"] = candle["c"]
                if candle["o"] > 0: sr["open_price"] = candle["o"]
                sr["high"] = max(sr.get("high", 0), candle["h"])
                lc = sr.get("low", 0)
                sr["low"] = min(lc, candle["l"]) if lc > 0 else candle["l"]
                sr["volume_acc"] += candle["v"]
                sr["tick_count"] += 1
                rate = 0.0
                op = _to_num(sr.get("open_price", 0))
                if op > 0: rate = (candle["c"] - op) / op * 100
                strategy.recompute_scores(sr, rate=rate)

    # ═════════════════════════════════════════════════════════
    # 주기적 리프레시
    # ═════════════════════════════════════════════════════════

    def _refresh_quotes(self):
        with self._lock:
            codes = [s["code"] for s in self.stocks if s.get("code")]
        for code in codes[:20]:
            sym = self._api_get("/api/market/symbol", {"code": code})
            if not self._ok(sym): continue
            d = self._data(sym, {})
            if not isinstance(d, dict): continue
            price = _abs_num(_first_valid(d, _RT_PRICE_KEYS + ["last_price"], 0))
            op    = _abs_num(_first_valid(d, _RT_OPEN_KEYS, 0))
            vol   = _abs_num(_first_valid(d, _RT_VOL_KEYS, 0))
            with self._lock:
                s = self._stock_by_code.get(code)
                if not s: continue
                prev = _to_num(s.get("price", 0))
                if price > 0: s["price"] = price
                if op > 0:    s["open_price"] = op
                if vol > 0:   s["volume_acc"] = vol
                if price > 0 and price != prev:
                    s["tick_count"] += 1
                    strategy.recompute_scores(s)

    def _refresh_dashboard(self, force):
        path = "/api/dashboard/refresh" if force else "/api/dashboard"
        resp = self._api_get(path)
        if self._ok(resp):
            d = self._data(resp, {})
            if isinstance(d, dict):
                with self._lock: self._last_dashboard = d
        elif "not logged in" in str(resp.get("Message", "")).lower():
            self._account_no = ""

    def _print_heartbeat(self, now_ts):
        with self._lock:
            s = self.stocks[0] if self.stocks else None
            sample = (f"{s['code']}:{_to_num(s['price']):,.0f} "
                      f"t={int(_to_num(s['tick_count']))}" if s else "-")
            loaded = sum(1 for c in self._candles.values() if c)
            total = len(self.stocks)
            pend = len(self._candle_req_queue)
        ls = int(now_ts - self._rt_last_recv_ts) if self._rt_last_recv_ts > 0 else -1
        si = f" stress={self._stress_cycle}" if self.stress_active else ""
        print(f"[perf_real] hb mode={self._mode} "
              f"rt={'Y' if self._rt_connected else 'N'} "
              f"recv={self._rt_recv_count} last={ls}s "
              f"candles={loaded}/{total}(q={pend}){si} {sample}")

    # ═════════════════════════════════════════════════════════
    # UI 인터페이스 (DummyDataSimulator 호환)
    # ═════════════════════════════════════════════════════════

    def tick(self):
        pass

    def get_universe_grid(self) -> List[list]:
        with self._lock:
            ss = sorted(self.stocks, key=lambda x: x.get("frs", 0), reverse=True)
            rows = []
            for rank, s in enumerate(ss, 1):
                op = max(1, _to_num(s.get("open_price")))
                p = _to_num(s.get("price"))
                chg = (p - op) / op * 100
                tv = _to_num(s.get("volume_acc")) * p / 1e8
                a5 = max(1, _to_num(s.get("avg5d", 1000)))
                pd = max(1, _to_num(s.get("prev_d", 1000)))
                tc = max(1, _to_num(s.get("tick_count", 1)))
                rows.append([
                    rank, s["code"], s["name"], p, chg, tv,
                    _to_num(s.get("tes")), _to_num(s.get("ucs")),
                    _to_num(s.get("frs")),
                    tc/(a5*0.0385), tc/(pd*0.0385), pd/a5,
                    int(_to_num(s.get("axes", 0))),
                    "ENTRY" if rank <= 5 else "WATCH" if rank <= 15 else "IDLE",
                    s.get("sector", "UNKNOWN"),
                ])
            return rows

    def get_universe_tree(self) -> List[dict]:
        with self._lock:
            ss = sorted(self.stocks, key=lambda x: x.get("frs", 0), reverse=True)
            return [{
                "code": s["code"], "name": s["name"],
                "change": ((_to_num(s["price"]) - max(1, _to_num(s["open_price"])))
                           / max(1, _to_num(s["open_price"])) * 100),
                "tes": _to_num(s.get("tes")),
                "ucs": _to_num(s.get("ucs")),
                "frs": _to_num(s.get("frs")),
                "axes": int(_to_num(s.get("axes", 0))),
                "is_target": rank <= 5,
                "sector": s.get("sector", "UNKNOWN"),
            } for rank, s in enumerate(ss, 1)]

    def get_stock_detail(self, code: str) -> dict:
        with self._lock:
            s = self._stock_by_code.get(code)
            if not s: return {}
            p = _to_num(s["price"])
            op = max(1, _to_num(s["open_price"]))
            chg = (p - op) / op * 100
            a5 = max(1, _to_num(s.get("avg5d", 1000)))
            pd = max(1, _to_num(s.get("prev_d", 1000)))
            tc = max(1, _to_num(s.get("tick_count", 1)))
            atr = 0.0
            dl = self._candles_daily.get(code, [])
            if len(dl) >= 14:
                atr = sum(d["high"]-d["low"] for d in dl[:14]) / 14
            return {
                "code": s["code"], "name": s["name"],
                "price": p, "change": chg, "market_cap": "-",
                "trade_value": f"{_to_num(s['volume_acc'])*p/1e8:,.1f}",
                "tes": _to_num(s.get("tes")), "ucs": _to_num(s.get("ucs")),
                "frs": _to_num(s.get("frs")),
                "AVG5D": f"{int(a5):,}", "PREV_D": f"{int(pd):,}",
                "TODAY_15M": f"{int(tc):,}",
                "R1": f"{tc/(a5*0.0385):.2f}",
                "R2": f"{tc/(pd*0.0385):.2f}",
                "R3": f"{pd/a5:.2f}",
                "change_rate": f"{chg:+.2f}%",
                "TES Z": f"{_to_num(s.get('tes')):.3f}",
                "ATR\u2081\u2084": f"{atr:.0f}",
                "HMS": _to_num(s.get("hms")),
                "BMS": _to_num(s.get("bms")),
                "SLS": _to_num(s.get("sls")),
            }

    def get_positions(self) -> List[list]:
        with self._lock:
            rows = []
            for h in (self._last_dashboard.get("Holdings") or []):
                if not isinstance(h, dict): continue
                code = str(_first_valid(h, ["code", "\uc885\ubaa9\ucf54\ub4dc"], "")).strip()
                name = str(_first_valid(h, ["name", "\uc885\ubaa9\uba85"], code)).strip()
                qty = int(_abs_num(_first_valid(h, ["qty", "\ubcf4\uc720\uc218\ub7c9"], 0)))
                avg = _abs_num(_first_valid(h, ["avg_price"], 0))
                cur = _abs_num(_first_valid(h, ["price", "\ud604\uc7ac\uac00"], 0))
                pnl = _to_num(_first_valid(h, ["pnl"], 0))
                pp = _to_num(_first_valid(h, ["pnl_rate"], 0))
                stop = avg * 0.97 if avg > 0 else 0
                tes = _to_num(self._stock_by_code.get(code, {}).get("tes", 0))
                rows.append([code, name, qty, avg, cur, pp, pnl, stop, "1\ucc28(50%)", tes])
            return rows

    def get_pending(self) -> List[list]:
        with self._lock:
            rows = []
            for o in (self._last_dashboard.get("Outstanding") or []):
                if not isinstance(o, dict): continue
                rows.append([
                    str(_first_valid(o, ["order_no", "\uc8fc\ubb38\ubc88\ud638"], "")),
                    str(_first_valid(o, ["code", "\uc885\ubaa9\ucf54\ub4dc"], "")),
                    str(_first_valid(o, ["name", "\uc885\ubaa9\uba85"], "")),
                    str(_first_valid(o, ["type"], "")),
                    _abs_num(_first_valid(o, ["price", "\ud604\uc7ac\uac00"], 0)),
                    int(_abs_num(_first_valid(o, ["qty"], 0))),
                    int(_abs_num(_first_valid(o, ["remain", "\ubbf8\uccb4\uacb0\uc218\ub7c9"], 0))),
                    str(_first_valid(o, ["status"], "")),
                ])
            return rows

    def generate_candle(self, stock_idx):
        with self._lock:
            if not self.stocks: return 0, 0, 0, 0, 0, 0
            s = self.stocks[max(0, min(stock_idx, len(self.stocks)-1))]
            if s.get("_placeholder"):
                return 0, 0, 0, 0, 0, 0
            code = s["code"]

            if code not in self._candles:
                self._enqueue_candle_fetch(code)
                self._candles[code] = []
                self._candle_idx[code] = 0
            series = self._candles.get(code, [])
            i = self._candle_idx.get(code, 0)
            if not series:
                p = _to_num(s.get("price", 0))
                s["candle_idx"] = int(s.get("candle_idx", 0)) + 1
                return p, p, p, p, 0, s["candle_idx"]
            if i >= len(series):
                if not self._is_market_open() and len(series) > 1:
                    i = max(0, len(series) - min(120, len(series)))
                    self._candle_idx[code] = i + 1
                else:
                    i = len(series) - 1
            row = series[i]
            if i < len(series) - 1: self._candle_idx[code] = i + 1
            s["price"] = row["c"]
            s["candle_idx"] = int(s.get("candle_idx", 0)) + 1
            return row["o"], row["h"], row["l"], row["c"], row["v"], s["candle_idx"]

    # ═════════════════════════════════════════════════════════
    # MySQL
    # ═════════════════════════════════════════════════════════

    def _setup_mysql(self):
        host = os.getenv("MYSQL_HOST", "").strip()
        user = os.getenv("MYSQL_USER", "").strip()
        pw = os.getenv("MYSQL_PASSWORD", "").strip()
        db = os.getenv("MYSQL_DB", "stock_info").strip()
        if not (host and user and pw): return
        if not pymysql: return
        self._mysql_cfg = {"host": host, "user": user, "password": pw,
                           "database": db, "charset": "utf8mb4", "autocommit": True}
        self._mysql_enabled = True
        print(f"[perf_real] MySQL: {user}@{host}/{db}")

    # ═════════════════════════════════════════════════════════
    # 종료
    # ═════════════════════════════════════════════════════════

    def close(self):
        self._bg_stop.set()
        self._rt_stop.set()
        self._exec_stop.set()
        try: self._api_get("/api/realtime/unsubscribe",
                           {"screen": self.screen, "code": "ALL"})
        except: pass
        for t in [self._bg_thread, self._rt_thread, self._exec_thread]:
            if t and t.is_alive(): t.join(timeout=1.5)
        print("[perf_real] shutdown")


###############################################################################
# 툴바: 조건식 선택 + 부하테스트 컨트롤
###############################################################################

def _add_toolbar_controls(win):
    try:
        from PySide6.QtWidgets import (QPushButton, QLabel,
                                        QSpinBox, QComboBox, QToolBar)
        from PySide6.QtGui import QFont
        from PySide6.QtCore import QTimer
    except ImportError:
        return

    sim = win.sim
    tbs = win.findChildren(QToolBar)
    if not tbs: return
    tb = tbs[0]

    # ═══ 조건식 선택 ═══
    tb.addSeparator()
    tb.addWidget(QLabel("  조건식: "))

    combo = QComboBox()
    combo.setFixedWidth(220)
    combo.addItem("-- 선택하세요 --", None)
    for c in sim._condition_list:
        idx = _first_valid(c, ["Index", "index"], "?")
        nm = _first_valid(c, ["Name", "name"], "?")
        combo.addItem(f"[{idx}] {nm}", c)
    tb.addWidget(combo)

    btn_run = QPushButton("실행")
    btn_run.setFixedWidth(50)
    btn_run.setStyleSheet("background:#14532d;color:#22c55e;font-weight:bold;")

    def on_run():
        data = combo.currentData()
        if data is None: return
        idx = _first_valid(data, ["Index", "index"], None)
        nm = _first_valid(data, ["Name", "name"], None)
        if idx is None or nm is None: return
        btn_run.setEnabled(False)
        btn_run.setText("...")
        def _run():
            try: sim.execute_condition(int(idx), str(nm))
            finally:
                btn_run.setEnabled(True)
                btn_run.setText("실행")
        threading.Thread(target=_run, daemon=True).start()

    btn_run.clicked.connect(on_run)
    tb.addWidget(btn_run)

    lbl_uni = QLabel("  종목: 0  ")
    lbl_uni.setFont(QFont("Consolas", 9))
    tb.addWidget(lbl_uni)

    # ═══ 부하테스트 ═══
    tb.addSeparator()
    lbl_st = QLabel("  STRESS: --  ")
    lbl_st.setFont(QFont("Consolas", 9))
    tb.addWidget(lbl_st)

    btn_st = QPushButton("Auto")
    btn_st.setFixedWidth(80)
    state = {"m": "auto"}

    def toggle():
        if state["m"] == "auto":
            state["m"] = "on"; sim.set_stress_enabled(True)
            btn_st.setText("ON")
            btn_st.setStyleSheet("background:#7f1d1d;color:#ef4444;font-weight:bold;")
        elif state["m"] == "on":
            state["m"] = "off"; sim.set_stress_enabled(False)
            btn_st.setText("OFF")
            btn_st.setStyleSheet("background:#14532d;color:#22c55e;font-weight:bold;")
        else:
            state["m"] = "auto"; sim.set_stress_enabled(None)
            btn_st.setText("Auto"); btn_st.setStyleSheet("")

    btn_st.clicked.connect(toggle)
    tb.addWidget(btn_st)

    tb.addWidget(QLabel(" ms:"))
    sp1 = QSpinBox(); sp1.setRange(10, 2000)
    sp1.setValue(sim._stress_interval_ms); sp1.setSuffix("ms"); sp1.setFixedWidth(80)
    sp1.valueChanged.connect(lambda v: sim.set_stress_interval(v))
    tb.addWidget(sp1)

    tb.addWidget(QLabel(" batch:"))
    sp2 = QSpinBox(); sp2.setRange(1, 100)
    sp2.setValue(sim._stress_batch); sp2.setFixedWidth(60)
    sp2.valueChanged.connect(lambda v: sim.set_stress_batch(v))
    tb.addWidget(sp2)

    # ═══ 주기적 갱신 ═══
    def upd():
        lbl_uni.setText(f"  종목: {len(sim.stocks)}  ")
        a = sim.stress_active
        col = "#ef4444" if a else "#22c55e"
        lbl_st.setText(f"  STRESS: {'ACTIVE' if a else 'OFF'} | "
                       f"{sim._mode} | cyc={sim._stress_cycle}  ")
        lbl_st.setStyleSheet(f"color:{col};font-weight:bold;")

    tmr = QTimer(); tmr.timeout.connect(upd); tmr.start(1000)
    lbl_st._k = tmr


###############################################################################
# main
###############################################################################

def main():
    if "--diag" in sys.argv:
        os.environ["PERF_DIAG"] = "1"
        sim = RealDataSimulator(50)
        time.sleep(3)
        sim.close()
        return

    nogui = os.getenv("PERF_NOGUI", "").strip() == "1" or "--nogui" in sys.argv
    prefer_tk = os.getenv("PERF_UI", "").strip().lower() == "tk" or "--tk" in sys.argv

    if nogui:
        sim = RealDataSimulator(50)
        print(f"[perf_real] nogui stress={sim.stress_active}")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
        finally: sim.close()
        return

    if prefer_tk:
        try:
            import tkinter as tk
            from tester_ui import ServerTesterUI
            root = tk.Tk(); ServerTesterUI(root); root.mainloop(); return
        except Exception as ex:
            print(f"tkinter failed: {ex}"); traceback.print_exc()

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
        print(f"GUI failed: {ex}"); traceback.print_exc(); return

    pt.DummyDataSimulator = RealDataSimulator

    import chart_patch
    chart_patch.apply()

    use_gl = os.environ.get("PERF_REAL_OPENGL", "1").strip().lower() not in ("0", "false", "off", "no")
    pg.setConfigOptions(antialias=False, useOpenGL=use_gl, enableExperimental=True)

    app = QApplication([])
    app.setStyle(QStyleFactory.create("Fusion"))
    pt.Theme.apply_dark_palette(app)
    app.setStyleSheet(pt.Theme.STYLESHEET)
    app.setFont(QFont(pt.Theme.FONT_FAMILY, pt.Theme.FONT_SIZE_M))

    win = pt.TESMainWindow()
    win.setWindowTitle("TES-Universe (REAL DATA) | KiwoomServer")
    _add_toolbar_controls(win)
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
