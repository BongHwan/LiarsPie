"""계좌 카드의 작은 그래프: 이 계좌가 첫 매매부터 전략대로 사고판 수익률과, 그때 사서 그냥 들고 있었다면의 수익률.

실제 체결 수량과 결제 금액으로 보유 수량과 현금을 재구성하고, 봉 종가로 평가한다.
시작 자산과 이후 자금 이동은 매매 기록에서 확인할 수 있는 범위에서 추정한다.
"""

from datetime import date, datetime, timedelta

from . import timeframes
from .db import Database
from .timeutil import KST, now_kst, ts

MAX_POINTS = 160  # 카드 안 작은 그래프라 이 정도면 충분하다


def build(trades: list[dict], bars: list[tuple[str, float]], price_now: float | None = None,
          now: str | None = None) -> dict:
    """trades: 이 계좌 매매 (오래된 것부터, ts·side·price·krw·volume). bars: (봉이 끝나는 시각, 종가) 오래된 것부터.
    {"start": 첫 매매 시각, "points": [[시각, 전략 %, 그냥 들고 있었다면 %], ...]}. 매매가 없으면 points가 비어 있다."""
    if not trades:
        return {"start": None, "points": []}
    first = trades[0]
    start, ref = first["ts"], float(first["price"])
    cash = float(first["krw"]) if first["side"] == "buy" else 0.0
    units = float(first["volume"]) if first["side"] == "sell" else 0.0
    basis, i = cash + units * ref, 0
    points = [[start, 0.0, 0.0]]

    def trade_until(when: str | None) -> None:
        nonlocal cash, units, basis, i
        while i < len(trades) and (when is None or trades[i]["ts"] <= when):
            t = trades[i]
            price, volume, amount = float(t["price"]), float(t["volume"]), float(t["krw"])
            buying = t["side"] == "buy"
            # 기록에 없는 현금·현물 유입은 수익으로 계산하지 않는다.
            missing = max(amount - cash, 0.0) if buying else max(volume - units, 0.0) * price
            if missing:
                equity = cash + units * price
                basis = basis * (1 + missing / equity) if equity > 0 else missing
            if buying:
                cash = max(cash - amount, 0.0)
                units += volume
            else:
                cash += amount
                units = max(units - volume, 0.0)
            i += 1

    def point(when: str, price: float) -> None:
        equity = cash + units * price
        points.append([when, (equity / basis - 1) * 100, (price / ref - 1) * 100])

    for end, close in bars:
        if end <= start:
            continue
        trade_until(end)
        point(end, float(close))
    trade_until(None)
    if price_now:
        point(now or ts(), float(price_now))
    if len(points) > MAX_POINTS:  # 골고루 줄이되 처음과 끝은 남긴다
        step = (len(points) - 1) / (MAX_POINTS - 1)
        points = [points[round(k * step)] for k in range(MAX_POINTS)]
    return {"start": start, "points": points}


def slot_trades(db: Database, mode: str, slot: str) -> list[dict]:
    return db._rows("SELECT ts, side, price, krw, volume FROM trades WHERE mode = ? AND slot = ? ORDER BY id", (mode, slot))


def coin(db: Database, status: dict, slot_id: str) -> dict:
    """코인 계좌: 그 계좌의 판단 주기 봉으로."""
    x = next((s for s in (status or {}).get("slots", []) if s["id"] == slot_id), None)
    if not x:
        return {"start": None, "points": []}
    trades = slot_trades(db, status["mode"], slot_id)
    if not trades:
        return {"start": None, "points": []}
    minutes = timeframes.minutes(x["tf"])
    first = datetime.fromisoformat(trades[0]["ts"]).replace(tzinfo=KST)
    count = min(int((now_kst() - first).total_seconds() // 60 // minutes) + 3, 6000)  # 첫 매매 뒤의 봉 수
    bars = [(ts(timeframes.key_to_utc(b["day"]) + timedelta(minutes=minutes)), b["close"])
            for b in db.candle_history(x["market"], count, x["tf"])]
    return build(trades, bars, x.get("price"))


def stock(db: Database, status: dict, slot_id: str, day_tf: str) -> dict:
    """주식 계좌: 일봉으로 (KRX·NXT 통합이라 봉은 그날 20:00에 끝난다)."""
    x = next((s for s in (status or {}).get("slots", []) if s["id"] == slot_id), None)
    if not x:
        return {"start": None, "points": []}
    trades = slot_trades(db, status["mode"], slot_id)
    if not trades:
        return {"start": None, "points": []}
    days = (now_kst().date() - date.fromisoformat(trades[0]["ts"][:10])).days
    bars = [(f"{b['day']} 20:00:00", b["close"]) for b in db.candle_history(x["symbol"], min(days + 3, 3000), day_tf)]
    return build(trades, bars, x.get("price"))
