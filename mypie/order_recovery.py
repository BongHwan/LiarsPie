"""웹에 표시할 미확정 주문 정보와 최근 복구 오류."""

from . import toss, upbit

ISSUE_KEY = "pending_order_recovery_issue"


def _identity(pending: dict) -> str | None:
    return pending.get("identifier") or pending.get("client_id")


def recover(db, pending_key, check):
    try:
        return check()
    except (upbit.UpbitError, toss.TossError) as e:
        pending = db.get_state(pending_key)
        if pending and _identity(pending):
            issue = {"id": _identity(pending), "order_id": pending.get("order_id"), "reason": str(e)[:400]}
            if db.get_state(ISSUE_KEY) != issue:
                db.set_state(ISSUE_KEY, issue)
        raise


def summary(db, pending_key):
    pending = db.get_state(pending_key)
    if not pending:
        return None
    issue = db.get_state(ISSUE_KEY) or {}
    reason = issue.get("reason") if (issue.get("id") == _identity(pending)
                                     and issue.get("order_id") == pending.get("order_id")) else None
    return {"request_id": _identity(pending), "at": pending.get("at"),
            "symbol": pending.get("symbol") or pending.get("market"), "side": pending.get("side"),
            "order_id": pending.get("order_id"), "reason": reason,
            "can_link": bool(pending.get("client_id") and not pending.get("order_id") and reason)}
