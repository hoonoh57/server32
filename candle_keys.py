# candle_keys.py
"""
서버 캔들 키 자동 탐지 — 이 파일만 수정하면 새로운 서버 형식 지원 가능.
perf_real.py가 import하여 사용.
"""
from typing import Any, Dict, List, Optional


def _abs_num(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return abs(float(v))
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s:
        return 0.0
    neg = s.count("-") % 2 == 1
    s = s.replace("-", "").replace("+", "").lstrip("0") or "0"
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class CandleKeyMap:
    """
    서버 캔들 JSON의 키 이름 자동 탐지.
    후보 목록을 수정하면 새 서버 형식을 즉시 지원 가능.
    """

    # ── 후보 목록: 여기만 수정하면 새 서버 대응 ──
    CANDIDATES = {
        "time": [
            "time", "date", "t", "timestamp",
            "\uccb4\uacb0\uc2dc\uac04",    # 체결시간
            "\uc77c\uc790",                 # 일자
            "Date", "Time",
        ],
        "open": [
            "open", "o", "Open",
            "\uc2dc\uac00",                 # 시가
            "start_price", "OPEN",
        ],
        "high": [
            "high", "h", "High",
            "\uace0\uac00",                 # 고가
            "max_price", "HIGH",
        ],
        "low": [
            "low", "l", "Low",
            "\uc800\uac00",                 # 저가
            "min_price", "LOW",
        ],
        "close": [
            "close", "c", "Close",
            "\ud604\uc7ac\uac00",           # 현재가
            "\uc885\uac00",                 # 종가
            "last_price", "CLOSE",
        ],
        "volume": [
            "volume", "v", "Volume", "vol",
            "\uac70\ub798\ub7c9",           # 거래량
            "cumVolume", "VOL", "VOLUME",
        ],
    }

    def __init__(self):
        self.resolved: Dict[str, str] = {}
        self._locked = False

    def detect(self, sample: Dict[str, Any]) -> bool:
        if self._locked:
            return True
        found = {}
        keys = set(sample.keys())
        for role, cands in self.CANDIDATES.items():
            for c in cands:
                if c in keys and sample[c] not in (None, "", " "):
                    found[role] = c
                    break
        if "close" not in found:
            return False
        self.resolved = found
        self._locked = True
        return True

    def parse(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._locked and not self.detect(row):
            return None

        c = _abs_num(row.get(self.resolved.get("close", ""), 0))
        if c <= 0:
            return None

        t  = str(row.get(self.resolved.get("time", ""), "")).strip()
        o  = _abs_num(row.get(self.resolved.get("open", ""), 0))
        h  = _abs_num(row.get(self.resolved.get("high", ""), 0))
        lo = _abs_num(row.get(self.resolved.get("low", ""), 0))
        v  = _abs_num(row.get(self.resolved.get("volume", ""), 0))

        if o  <= 0: o  = c
        if h  <= 0: h  = max(o, c)
        if lo <= 0: lo = min(o, c) if min(o, c) > 0 else c

        h  = max(h, o, c)
        lo = min(lo, o, c)

        return {"t": t, "o": o, "h": h, "l": lo, "c": c, "v": v}

    def summary(self) -> str:
        if not self.resolved:
            return "NOT DETECTED"
        return " | ".join(
            f"{r}='{k}'" for r, k in self.resolved.items())


# 엔드포인트별 싱글턴
keymap_minute = CandleKeyMap()
keymap_daily  = CandleKeyMap()
keymap_tick   = CandleKeyMap()
