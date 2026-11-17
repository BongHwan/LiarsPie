"""거래 장부와 별도로 저장하는 신규 매수 일시정지 상태."""

import sqlite3
from pathlib import Path

from .db import Database

STATE_KEY = "buy_paused"
ACTIONS = {"pause_buy": True, "resume_buy": False}


class BuyPaused(Exception):
    """주문 준비 중 신규 매수가 중단됐다."""


def paused(db: Database) -> bool:
    return db.get_state(STATE_KEY) is True


def set_paused(db: Database, value: bool) -> str:
    db.set_state(STATE_KEY, value)
    return "신규 매수를 일시정지했어요." if value else "신규 매수를 재개했어요."


def telegram_command(text: str, coin_db: Database, stock_path: str) -> str | None:
    """연결된 채팅의 신규 매수 제어 명령에 답한다."""
    parts = text.lower().split()
    cmd = parts[0].split("@", 1)[0] if parts else ""
    commands = {"/pausebuy": True, "/매수정지": True, "/resumebuy": False, "/매수재개": False}
    if cmd not in commands:
        return None
    if len(parts) != 2 or parts[1] not in ("coin", "stock", "코인", "주식"):
        return "사용법: /pausebuy coin 또는 /pausebuy stock · 재개: /resumebuy coin 또는 /resumebuy stock"
    coin = parts[1] in ("coin", "코인")
    try:
        if coin:
            return "코인 · " + set_paused(coin_db, commands[cmd])
        if not Path(stock_path).is_file():
            return "주식 봇이 아직 시작되지 않았어요."
        db = Database(stock_path, create=False)
        try:
            return "주식 · " + set_paused(db, commands[cmd])
        finally:
            db.close()
    except sqlite3.Error:
        return "신규 매수 설정을 저장하지 못했어요. 다시 시도해 주세요."
