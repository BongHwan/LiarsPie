"""가격 알림 (코인): 텔레그램에 '/알림 BTC 1억'을 보내 두면 그 가격에 닿을 때 한 번 알린다.

  - 지금보다 높게 정하면 올라서 넘을 때, 낮게 정하면 내려갈 때 알린다 (알린 뒤에는 지운다)
  - '/알림'만 보내면 걸어 둔 목록이 오고, 버튼을 누르면 지운다
  - 알림은 DB에 하나씩 따로 저장한다 (price_alert:<번호>). 텔레그램 명령 스레드와 매매 루프가 같이 써도 서로 덮어쓰지 않게
"""

import re
import secrets
import time

from . import upbit
from .db import Database
from .timeutil import ts

PREFIX = "price_alert:"
DELETE = "alert:del:"  # 지우기 버튼을 누르면 봇에게 오는 값의 앞부분
MAX_ALERTS = 20
USAGE = ("🔔 가격 알림 쓰는 법\n"
         "/알림 BTC 1억 — 비트코인이 1억 원에 닿으면 알려줘요\n"
         "/알림 이더리움 450만 · /알림 DOGE 250\n"
         "지금보다 높게 정하면 올라서 넘을 때, 낮게 정하면 내려갈 때 한 번 알려줘요. 목록과 지우기는 /알림")
WON = re.compile(r"(?:(\d+(?:\.\d+)?)억)?(?:(\d+(?:\.\d+)?)만)?(\d+(?:\.\d+)?)?")


def parse_won(text: str) -> float | None:
    """'1억', '9500만', '1억2000만', '95,000,000원', '250', '0.5' → 원. 못 알아들으면 None."""
    m = WON.fullmatch(text.replace(",", "").replace("원", "").replace(" ", ""))
    if not m or not any(m.groups()):
        return None
    eok, man, rest = m.groups()
    won = float(eok or 0) * 1e8 + float(man or 0) * 1e4 + float(rest or 0)
    return won if won > 0 else None


def won_text(v: float) -> str:
    """읽기 쉬운 금액: 1억원 · 9,500만원 · 1억 2,000만원 · 3,500원 · 0.25원."""
    if v >= 1e4 and v == int(v) and int(v) % 10000 == 0:  # 만 원 단위로 딱 떨어지면
        eok, man = divmod(int(v) // 10000, 10000)
        return " ".join(p for p in (f"{eok:,}억" if eok else "", f"{man:,}만" if man else "") if p) + "원"
    return (f"{v:,.0f}" if v >= 100 else f"{v:,.4g}") + "원"


def find_market(word: str, markets: list[dict]) -> dict | None:
    """'BTC', 'btc', 'KRW-BTC', '비트코인' → 업비트 원화 종목 {market, name}."""
    code = word.strip().upper().removeprefix("KRW-")
    for m in markets:
        if m["market"] == f"KRW-{code}" or (m.get("name") or "") == word.strip():
            return m
    return None


def alerts(db: Database) -> list[tuple[str, dict]]:
    """걸어 둔 알림 (먼저 건 것부터): [(DB 키, 알림)]."""
    return sorted(db.states(PREFIX), key=lambda kv: kv[1].get("made", 0))


def _name(a: dict) -> str:
    return f"{a['name']} {won_text(a['price'])} {'이상' if a['up'] else '이하'}"


def list_reply(db: Database) -> tuple[str, list | None]:
    items = alerts(db)
    if not items:
        return "🔔 걸어 둔 가격 알림이 없어요.\n\n" + USAGE, None
    lines = [f"🔔 가격 알림 {len(items)}개 · 아래 버튼을 누르면 지워요"] + [f"· {_name(a)}" for _, a in items]
    return "\n".join(lines), [(f"🗑 {_name(a)}", DELETE + key[len(PREFIX):]) for key, a in items]


def command(text: str, db: Database) -> tuple[str, list | None] | None:
    """텔레그램 /알림 (/alert). 이 명령이 아니면 None. (답장, 버튼)."""
    parts = (text or "").strip().split()
    if not parts or parts[0].split("@")[0].lstrip("/").lower() not in ("알림", "alert"):
        return None
    if len(parts) == 1:
        return list_reply(db)
    if len(parts) < 3:
        return USAGE, None
    market = find_market(parts[1], (db.get_state("markets") or {}).get("list", []))
    if not market:
        return f"'{parts[1]}' 종목을 못 찾았어요. BTC나 비트코인처럼 업비트 원화 종목으로 적어 주세요.", None
    price = parse_won("".join(parts[2:]))
    if not price:
        return "가격을 못 알아들었어요. 1억, 9500만, 3500처럼 적어 주세요.", None
    if len(alerts(db)) >= MAX_ALERTS:
        return f"알림은 {MAX_ALERTS}개까지예요. /알림 에서 몇 개 지우고 다시 걸어 주세요.", None
    try:
        now = upbit.get_prices([market["market"]]).get(market["market"])
    except upbit.UpbitError as e:
        return f"지금 가격을 받지 못했어요 ({e}). 잠시 뒤에 다시 해 주세요.", None
    if not now:
        return "지금 가격을 받지 못했어요. 잠시 뒤에 다시 해 주세요.", None
    alert = {"market": market["market"], "name": market.get("name") or market["market"], "price": price,
             "up": price > now, "set_at": ts(), "made": time.time()}
    db.set_state(PREFIX + secrets.token_hex(3), alert)
    return (f"🔔 {alert['name']}이(가) {won_text(price)} {'이상으로 오르면' if alert['up'] else '이하로 내리면'} "
            f"한 번 알려드릴게요.\n지금 {won_text(now)} · 목록은 /알림"), None


def delete(db: Database, alert_id: str) -> dict | None:
    """지우기 버튼. 지운 알림 (이미 없으면 None)."""
    key = PREFIX + alert_id
    alert = db.get_state(key)
    if alert:
        db.delete_state(key)
    return alert


def due(db: Database, prices: dict) -> list[tuple[dict, float]]:
    """가격이 닿은 알림을 지우고 돌려준다: [(알림, 지금 가격)]."""
    hits = []
    for key, a in alerts(db):
        p = prices.get(a["market"])
        if p and (p >= a["price"] if a["up"] else p <= a["price"]):
            db.delete_state(key)
            hits.append((a, p))
    return hits


def hit_text(alert: dict, price: float) -> str:
    moved = "넘었어요 📈" if alert["up"] else "아래로 내려왔어요 📉"
    return f"🔔 {alert['name']} {won_text(alert['price'])} {moved}\n지금 {won_text(price)}"
