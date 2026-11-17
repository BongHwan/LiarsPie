"""봇의 정상 실행 기록과 별도 기기에서 실행하는 상태 감시."""

import argparse
import json
import logging
import math
import os
import sqlite3
import time
import urllib.request
from contextlib import closing
from http.client import HTTPException
from pathlib import Path

from . import telegram
from .db import Database

HEARTBEAT = "last_successful_step"
HEALTH_PATH = "/healthz/bots"
BOT_LABELS = {"coin": "코인 봇", "stock": "주식 봇"}
log = logging.getLogger(__name__)


def record_success(db: Database) -> None:
    db.set_state(HEARTBEAT, time.time())


def _last_success(path: str) -> float | None:
    if not path:
        return None
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (HEARTBEAT,)).fetchone()
        value = json.loads(row[0]) if row else None
    except (OSError, sqlite3.Error, ValueError):
        return None
    return value if _timestamp(value) else None


def bot_status(coin_db: str, stock_db: str) -> dict:
    return {"last_success": {"coin": _last_success(coin_db), "stock": _last_success(stock_db)}}


def _timestamp(value) -> bool:
    return type(value) in (int, float) and 0 < value < math.inf


def fetch_status(base_url: str) -> dict:
    with urllib.request.urlopen(base_url.rstrip("/") + HEALTH_PATH, timeout=10) as response:
        data = json.loads(response.read(4096))
    timestamps = data.get("last_success") if isinstance(data, dict) else None
    if not isinstance(timestamps, dict) or any(
        name not in timestamps or (timestamps[name] is not None and not _timestamp(timestamps[name]))
        for name in BOT_LABELS
    ):
        raise ValueError("봇 상태 응답 형식이 올바르지 않아요")
    return timestamps


class Monitor:
    def __init__(self, stale_after: int, notify):
        self.stale_after = stale_after
        self.notify = notify
        self.failed_checks = 0
        self.alerted = set()

    def _update(self, name: str, down: bool, message: str, recovery: str) -> None:
        if down == (name in self.alerted):
            return
        try:
            self.notify(message if down else recovery)
        except telegram.TelegramError:
            log.warning("상태 알림 전송 실패. 다음 검사에서 다시 보냅니다.")
            return
        if down:
            self.alerted.add(name)
        else:
            self.alerted.remove(name)

    def check(self, timestamps: dict | None, now: float) -> None:
        if timestamps is None:
            self.failed_checks += 1
            if self.failed_checks >= 2:
                self._update("server", True, "AntLab 서버 상태 확인에 연속으로 실패했습니다.", "")
            return
        self.failed_checks = 0
        self._update("server", False, "", "AntLab 서버 상태 확인이 다시 정상입니다.")
        for name, label in BOT_LABELS.items():
            last = timestamps[name]
            stale = last is None or now - last >= self.stale_after
            detail = ("정상 실행 기록이 없습니다." if last is None else
                      f"마지막 정상 실행 후 {int(now - last) // 60}분이 지났습니다.")
            self._update(name, stale, f"AntLab {label}: {detail}", f"AntLab {label}의 정상 실행이 다시 확인됐습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="별도 기기에서 AntLab 상태를 감시하고 텔레그램으로 알립니다")
    parser.add_argument("url", help="AntLab 서버 주소")
    parser.add_argument("--interval", type=int, default=60, help="확인 주기(초)")
    parser.add_argument("--stale-after", type=int, default=600, help="봇 중단 판단 기준(초)")
    args = parser.parse_args()
    if not args.url.startswith(("http://", "https://")) or args.interval <= 0 or args.stale_after <= 0:
        parser.error("http(s) 서버 주소와 양수 시간 값을 입력해 주세요")
    token, chat = os.getenv(telegram.TOKEN), os.getenv(telegram.CHAT)
    creds = (token, chat) if token and chat else telegram.load()
    if not creds:
        parser.error("감시 기기에서 텔레그램 봇 토큰과 채팅 ID를 설정해 주세요")
    logging.basicConfig(level=logging.INFO)
    monitor = Monitor(args.stale_after, lambda message: telegram.send(message, creds))
    try:
        while True:
            try:
                timestamps = fetch_status(args.url)
            except (OSError, ValueError, HTTPException):
                timestamps = None
            monitor.check(timestamps, time.time())
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
