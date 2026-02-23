# strategy.py
"""
매매 전략 로직 — 이 파일만 수정하면 전략이 바뀜.
perf_real.py의 RealDataSimulator가 import하여 사용.
"""
from typing import Any, Dict


def recompute_scores(s: Dict[str, Any],
                     rate: float = 0.0,
                     diff: float = 0.0,
                     intensity: float = 0.0) -> None:
    """
    실시간 틱 데이터로 TES/UCS/FRS 등 재계산.
    s: 종목 상태 딕셔너리 (in-place 수정)
    """
    p  = abs(float(s.get("price", 0) or 0))
    op = abs(float(s.get("open_price", 0) or 0))

    if rate == 0 and op > 0 and p > 0:
        rate = (p - op) / op * 100.0

    abs_rate = abs(rate)
    vol = abs(float(s.get("volume_acc", 0) or 0))
    a5  = max(1.0, abs(float(s.get("avg5d", 1000) or 1000)))
    pd  = max(1.0, abs(float(s.get("prev_d", 1000) or 1000)))
    tc  = max(1.0, abs(float(s.get("tick_count", 1) or 1)))
    vr  = vol / a5 if a5 > 0 else 0

    # ── TES: 체결강도 + 등락률 기반 활성도 ──
    s["tes"] = max(0.0, min(3.0,
        abs_rate / 2.5
        + intensity / 200.0
        + min(tc / (a5 * 0.0385), 1.0) * 0.5))

    # ── HMS: 강세이력 ──
    s["hms"] = max(0.0, min(1.0,
        (rate / 10.0 + 0.5) * 0.6
        + min(vr, 1.0) * 0.4))

    # ── BMS: 돌파모멘텀 ──
    s["bms"] = max(0.0, min(1.0,
        abs_rate / 5.0 * 0.5
        + min(intensity / 120.0, 1.0) * 0.5))

    # ── SLS: 섹터주도 ──
    s["sls"] = max(0.0, min(1.0,
        min(1.0, vol / 5e6) * 0.7
        + min(vr, 1.0) * 0.3))

    # ── UCS: 3축 가중평균 ──
    s["ucs"] = max(0.0, min(1.0,
        s["hms"] * 0.4
        + s["bms"] * 0.35
        + s["sls"] * 0.25))

    # ── FRS: 종합 순위 점수 ──
    s["frs"] = max(0.0, min(2.5,
        s["tes"] * 0.5
        + s["ucs"] * 1.0
        + min(tc / (a5 * 0.0385), 1.5) * 0.3))

    # ── 축 통과 판정 ──
    axes = 0
    if s["hms"] >= 0.4: axes += 1
    if s["bms"] >= 0.4: axes += 1
    if s["sls"] >= 0.4: axes += 1
    s["axes"] = axes


def compute_entry_signal(s: Dict[str, Any]) -> str:
    """
    진입 시그널 판정. 반환값: "ENTRY" / "WATCH" / "IDLE"
    향후 여기에 복잡한 진입 조건 추가.
    """
    frs = float(s.get("frs", 0) or 0)
    ucs = float(s.get("ucs", 0) or 0)
    axes = int(s.get("axes", 0) or 0)

    if frs >= 1.5 and ucs >= 0.6 and axes >= 3:
        return "ENTRY"
    elif frs >= 0.8 and axes >= 2:
        return "WATCH"
    return "IDLE"


def compute_exit_signal(s: Dict[str, Any],
                        avg_price: float,
                        current_price: float) -> str:
    """
    청산 시그널 판정. 반환값: "HOLD" / "STOP_LOSS" / "TAKE_PROFIT_1" / "TAKE_PROFIT_2"
    향후 여기에 ATR 기반 트레일링 스톱 등 추가.
    """
    if avg_price <= 0 or current_price <= 0:
        return "HOLD"

    pnl_pct = (current_price - avg_price) / avg_price * 100

    if pnl_pct <= -2.0:
        return "STOP_LOSS"
    elif pnl_pct >= 10.0:
        return "TAKE_PROFIT_2"
    elif pnl_pct >= 7.0:
        return "TAKE_PROFIT_1"
    return "HOLD"
