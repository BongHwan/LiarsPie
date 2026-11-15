"""주식 주문 실행.

  - PaperStockExecutor: 모의투자. 정해 준 지정가(그 순간의 호가)에 바로 체결됐다고 보고 수수료·세금만 뗀다.
  - LiveStockExecutor: 토스증권 실거래. 주문마다 우리가 만든 번호(client_id)를 붙이고, 주문 직전에
    '진행 중인 주문'으로 DB에 적어 둔다. 정전·통신 끊김으로 결과를 모르게 되면 recover()가
    토스증권에 물어서 확인한 체결만 장부에 반영하게 한다. 주문을 특정할 수 없으면 확인을 보류한다.

주문은 시장가 대신 지정가로 낸다. 값은 주식 봇이 그 순간의 호가로 정해 준다 (살 때는 가장 싼 매도 호가, 팔 때는 가장
비싼 매수 호가: 바로 체결되는 값). 국내 시장가 매수가 상한가 기준으로 돈을 묶어서 살 수 있는 수량이 줄어드는 문제도 없다.
정해진 시간 안에 다 체결되지 않으면 남은 수량은 취소하고 체결된 만큼만 장부에 적는다. 남은 건 주식 봇이 다음 루프에
그때의 호가로 다시 낸다 (폭등·폭락 때 처음 값에 묶여 있지 않게).
"""

import time
import uuid
from datetime import date

from . import krx, toss
from .db import Database
from .timeutil import ts

FILL_WAIT_SEC = 10    # 이 시간 안에 다 안 되면 남은 수량을 취소한다 (다음 루프에 그때 호가로 다시)
FINAL = ("filled", "cancelled", "rejected")


class PaperStockExecutor:
    mode = "paper"

    def __init__(self, fee_rate: float, sell_tax: float):
        self.fee_rate, self.sell_tax = fee_rate, sell_tax

    def buy(self, symbol: str, cash: float, limit: float, note: dict) -> tuple[int, float, float] | None:
        """(주수, 체결가, 수수료). 1주도 못 사면 None."""
        qty = int(cash // (limit * (1 + self.fee_rate)))
        if qty < 1:
            return None
        return qty, limit, qty * limit * self.fee_rate

    def sell(self, symbol: str, qty: int, limit: float, note: dict) -> tuple[int, float, float, float]:
        """(주수, 체결가, 수수료, 세금)."""
        value = qty * limit
        return qty, limit, value * self.fee_rate, value * self.sell_tax

    def recover(self):
        return None

    def clear_pending(self) -> None:
        pass


class LiveStockExecutor:
    mode = "live"
    PENDING_KEY = "stock_pending_order"

    def __init__(self, db: Database, client, fee_rate: float, sell_tax: float,
                 wait_sec: float = FILL_WAIT_SEC, sleep=time.sleep):
        self.db, self.client = db, client
        self.fee_rate, self.sell_tax = fee_rate, sell_tax
        self.wait_sec, self.sleep = wait_sec, sleep

    def buy(self, symbol: str, cash: float, limit: float, note: dict) -> tuple[int, float, float] | None:
        limit = int(limit)
        qty = int(cash // (limit * (1 + self.fee_rate)))
        if qty < 1:
            return None
        fill = self._place(symbol, "buy", qty, limit, note)
        return fill["qty"], fill["price"], fill["fee"]

    def sell(self, symbol: str, qty: int, limit: float, note: dict) -> tuple[int, float, float, float]:
        fill = self._place(symbol, "sell", qty, max(int(limit), 1), note)
        return fill["qty"], fill["price"], fill["fee"], fill["tax"]

    def _place(self, symbol: str, side: str, qty: int, limit: int, note: dict) -> dict:
        pending = {"client_id": "mypie-" + uuid.uuid4().hex[:20], "symbol": symbol, "side": side, "qty": qty,
                   "price": limit, "at": ts(), **note}
        self.db.set_state(self.PENDING_KEY, pending)  # 주문 직전에 적어 둔다 (정전 대비)
        try:
            order_id = self.client.place_order(symbol, side, qty, limit, pending["client_id"])
        except toss.OrderRejected:
            self.db.delete_state(self.PENDING_KEY)  # 확실히 거절됐으면 진행 중인 주문이 아니다
            raise
        except toss.TossError as e:
            raise toss.OrderUnknown(f"주문 결과를 확인하지 못했어요: {e}") from e
        pending["order_id"] = order_id
        self.db.set_state(self.PENDING_KEY, pending)
        return self._fill(self._settle(order_id), side)

    def _settle(self, order_id: str) -> dict:
        """다 체결되거나 끝날 때까지 기다린다. 시간이 지나면 남은 수량을 취소하고 최종 결과를 돌려준다."""
        deadline = time.monotonic() + self.wait_sec
        try:
            while True:
                order = self.client.order(order_id)
                if order["status"] in FINAL:
                    return order
                if time.monotonic() >= deadline:
                    break
                self.sleep(1)
            self.client.cancel(order_id)
            for _ in range(10):
                order = self.client.order(order_id)
                if order["status"] in FINAL:
                    return order
                self.sleep(1)
        except toss.TossError as e:
            raise toss.OrderUnknown(f"주문 체결을 확인하지 못했어요: {e}") from e
        raise toss.OrderUnknown("주문 취소를 확인하지 못했어요")

    def _fill(self, order: dict, side: str) -> dict:
        qty = int(order.get("filled_qty") or 0)
        price = float(order.get("avg_price") or 0)
        value = qty * price
        fee = order.get("fee")
        tax = order.get("tax")
        return {"qty": qty, "price": price,
                "fee": float(fee) if fee is not None else value * self.fee_rate,
                "tax": float(tax) if tax is not None else (value * self.sell_tax if side == "sell" else 0.0)}

    def pending(self) -> dict | None:
        return self.db.get_state(self.PENDING_KEY)

    def clear_pending(self) -> None:
        self.db.delete_state(self.PENDING_KEY)

    def recover(self) -> dict | None:
        """끊기기 전 주문이 있으면 확인된 체결 결과를 돌려준다. 미확정 주문은 남겨 둔다."""
        pending = self.pending()
        if not pending:
            return None
        try:
            if pending.get("order_id"):
                order = self.client.order(pending["order_id"])
            else:
                client_id, submitted_at = pending.get("client_id"), pending.get("at")
                if not client_id or not submitted_at:
                    raise toss.OrderUnknown("미확정 주문의 요청 ID 또는 제출 시각이 없어요")
                order = self.client.find_order(client_id, pending["symbol"],
                                               submitted_on=date.fromisoformat(submitted_at[:10]))
                if order is None:
                    raise toss.OrderUnknown("주문 요청 ID가 일치하는 주문을 아직 찾지 못했어요")
                pending["order_id"] = order["id"]
                self.db.set_state(self.PENDING_KEY, pending)
            if order["status"] not in FINAL:
                order = self._settle(order["id"])
        except toss.TossError as e:
            raise toss.OrderUnknown(f"끊기기 전 주문을 확인하지 못했어요: {e}") from e
        fill = self._fill(order, pending["side"])
        return {"pending": pending, "fill": fill if fill["qty"] else None}
