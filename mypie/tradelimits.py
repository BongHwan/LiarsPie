"""계좌 전체 장부를 기준으로 신규 매수 한도를 판단한다."""

import math
from dataclasses import dataclass

from .db import Database
from .timeutil import now_kst


def _today() -> str:
    return now_kst().date().isoformat()


def _order_count(db: Database, mode: str, day: str) -> int:
    state = db.get_state(f"order_count:{mode}") or {}
    if state.get("day") == day:
        return state["count"]
    # 기능 도입 전에 이미 기록된 당일 체결도 초기 횟수에 포함한다.
    return db.daily_trade_count(mode, day)


def record_order(db: Database, mode: str) -> None:
    day = _today()
    with db.transaction():
        count = _order_count(db, mode, day) + 1
        db.set_state(f"order_count:{mode}", {"day": day, "count": count})


@dataclass(frozen=True)
class BuyLimits:
    daily_loss_krw: float = 0
    max_symbol_krw: float = 0
    max_daily_orders: int = 0

    @classmethod
    def from_config(cls, cfg: dict):
        amounts = {key: cfg.get(key, 0) for key in ("daily_loss_krw", "max_symbol_krw")}
        for key, value in amounts.items():
            if type(value) not in (int, float) or not 0 <= value < math.inf:
                raise ValueError(f"{key}는 0 이상의 유한한 금액이어야 해요")
        count = cfg.get("max_daily_orders", 0)
        if type(count) is not int or count < 0:
            raise ValueError("max_daily_orders는 0 이상의 정수여야 해요")
        return cls(**amounts, max_daily_orders=count)

    def budget(self, db: Database, mode: str, amount: float,
               exposure: float, minimum: float) -> tuple[float, str | None]:
        day = _today()
        if self.daily_loss_krw and db.daily_loss_limit_hit(mode, day, self.daily_loss_krw):
            return 0, f"하루 실현 손실 한도 {self.daily_loss_krw:,.0f}원에 도달했어요"
        if self.max_daily_orders and _order_count(db, mode, day) >= self.max_daily_orders:
            return 0, f"하루 주문 횟수 한도 {self.max_daily_orders:,}회에 도달했어요"
        if self.max_symbol_krw:
            remaining = self.max_symbol_krw - exposure
            if remaining < minimum and remaining < amount:
                return 0, f"종목별 최대 투자금 {self.max_symbol_krw:,.0f}원 제한으로 더 살 수 없어요"
            amount = min(amount, remaining)
        return amount, None
