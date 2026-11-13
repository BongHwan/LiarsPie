"""텔레그램으로 보내는 글: 매일 아침 리포트, /기록 · /상태 · /주식 · /신호 · /파이 · /도움 명령에 대한 답장.
/상태 · /주식 · /신호 · /파이 답장 아래에는 [🪙 코인] [📈 주식] [🚦 신호] [🍓 파이] [🔄 새로고침] 버튼이 붙어서,
누르면 같은 메시지 안에서 바뀐다. /차단목록 · /차단해제는 sshwatch, /알림은 alerts가 답한다."""

from pathlib import Path

from .db import Database
from .strategies import STOCK_STRATEGIES, STRATEGIES
from .strategies.combo import OP_TEXT

HELP = ("🥧 My_Pie 명령어\n"
        "/상태 (/status) — 지금 포트폴리오와 총 자산\n"
        "/기록 (/trades) — 최근 매매 기록 10건\n"
        "/주식 (/stock) — 주식 금고와 종목 계좌\n"
        "/신호 (/signal) — 계좌마다 전략이 지금 🔴 사자인지 🔵 팔자인지\n"
        "/파이 (/pi) — 라즈베리파이 온도·CPU·메모리·전력\n"
        "/알림 BTC 1억 (/alert) — 가격에 닿으면 알려 주기 (/알림 만 보내면 목록)\n"
        "/재부팅 (/reboot) — 라즈베리파이 재부팅 (뒤에 '확인'을 붙여야 해요)\n"
        "/차단목록 (/blocked) — SSH 알림의 '막기' 버튼으로 막은 IP\n"
        "/차단해제 IP (/unblock) — 막은 IP 풀기\n"
        "/도움 (/help) — 이 안내")

COMMANDS = {  # 텔레그램 메뉴에 보일 영어 명령 (한글 명령도 똑같이 알아듣는다)
    "status": "지금 포트폴리오와 총 자산",
    "trades": "최근 매매 기록 10건",
    "stock": "주식 금고와 종목 계좌",
    "signal": "전략마다 지금 사자·팔자",
    "pi": "라즈베리파이 온도·CPU·전력",
    "alert": "가격 알림 (예: /alert BTC 1억)",
    "reboot": "라즈베리파이 재부팅 (뒤에 '확인')",
    "blocked": "SSH 때문에 막은 IP 목록",
    "unblock": "막은 IP 풀기 (뒤에 IP)",
    "help": "명령어 안내",
}


def _sym(market: str) -> str:
    return market.split("-")[-1]


def _price(v: float) -> str:
    return f"{v:,.0f}" if v >= 100 else f"{v:,.4g}"


def trade_line(t: dict) -> str:
    side = "🔴 매수" if t["side"] == "buy" else "🔵 매도"
    tag = "[실거래] " if t.get("mode") == "live" else ""
    line = f"{t['ts'][5:16]} {tag}{side} {_sym(t['market'])} @{_price(t['price'])}원 · {t['krw']:,.0f}원"
    if t.get("profit") is not None:
        line += f" · 손익 {t['profit']:+,.0f}원"
    return line


def trades_text(trades: list[dict], title: str = "🧾 최근 매매 기록") -> str:
    if not trades:
        return f"{title}\n아직 매매 기록이 없어요."
    return title + "\n" + "\n".join(trade_line(t) for t in trades)


def status_text(status: dict | None) -> str:
    if not status:
        return "봇이 아직 상태를 남기지 않았어요. 잠시 뒤에 다시 물어봐 주세요."
    a = status["account"]
    mode = "실거래" if status["mode"] == "live" else "모의투자"
    ret = f"{a['return_pct']:+.2f}%" if a.get("return_pct") is not None else "-"
    lines = [f"💰 총 자산 {a['equity']:,.0f}원 ({ret}) · {mode}",
             f"넣은 돈 {a['contributions']:,.0f}원 · 금고 {a.get('vault', a.get('reserve', 0)):,.0f}원"]
    for s in status["slots"]:
        held = "🟢 보유" if s["holding"] else "⏳ 대기"
        slot_ret = f" · 계좌 수익률 {s['return_pct']:+.2f}%" if s.get("return_pct") is not None else ""
        lines.append(f"\n• {s.get('name') or _sym(s['market'])} {s.get('tf_label', '일봉')} · {s['strategy']['label']}"
                     f" · 원화 {s['book']['krw']:,.0f}원")
        lines.append(f"  {held} · 현재가 {_price(s['price'])}원{slot_ret}")
        lines.append(f"  {s['state_text']}")
    lines.append(f"\n({status['updated_at'][5:16]} 기준)")
    return "\n".join(lines)


LABELS = {name: cls.label for name, cls in {**STRATEGIES, **STOCK_STRATEGIES}.items()}
SIGNAL_MARK = {True: "🔴", False: "🔵", None: "⚪"}


def slot_signals(x: dict) -> dict:
    """계좌 하나의 전략마다 지금 판단: True 사자 · False 팔자 · None 데이터 부족 (웹페이지 rules.js의 ruleSignals와 같다).
    조합은 봇이 계산한 plan.signals, 전략 하나면 계획대로 · 계획이 '그대로'면 지금 들고 있는지. 주식은 장 밖에서 judged."""
    plan = x.get("plan") or x.get("judged")
    if not plan:
        return {}
    if plan.get("signals"):
        return plan["signals"]
    name = (x.get("rule") or {}).get("buy", [x["strategy"]["name"]])[0]
    if (plan.get("note") or "").startswith("데이터 부족"):
        return {name: None}
    return {name: True if plan.get("buy_at_open") else False if plan.get("sell_at_open") else bool(x.get("holding"))}


def rule_signal_text(x: dict) -> str:
    """'살 때 🔴MACD 그리고 🔵모멘텀 · 팔 때 🔴MACD 그리고 🔴터틀 트레이딩' (전략 하나면 '🔴이동평균 골든크로스')."""
    rule = x.get("rule") or {"buy": [x["strategy"]["name"]], "sell": [x["strategy"]["name"]], "buy_op": "and", "sell_op": "and"}
    signals = slot_signals(x)
    mark = lambda n: (SIGNAL_MARK[signals[n]] if n in signals else "") + LABELS.get(n, n)
    side = lambda names, op: f" {OP_TEXT[op]} ".join(mark(n) for n in names)
    if len(rule["buy"]) == 1 and rule["buy"] == rule["sell"]:
        return side(rule["buy"], "and")
    return f"살 때 {side(rule['buy'], rule['buy_op'])} · 팔 때 {side(rule['sell'], rule['sell_op'])}"


def signals_text(coin: dict | None, stock: dict | None) -> str:
    lines = ["🚦 전략 신호 · 🔴 사자 · 🔵 팔자 · ⚪ 데이터 부족"]
    for title, status, coin_page in (("🪙 코인", coin, True), ("📈 주식", stock, False)):
        slots = (status or {}).get("slots") or []
        if not slots:
            continue
        lines.append(f"\n{title}")
        for x in slots:
            held = ("🟢 보유" if coin_page else f"🟢 {x['qty']:,}주") if x["holding"] else "⏳ 대기"
            when = f" {x.get('tf_label', '')}" if coin_page else ""
            judged = x.get("judged") if not coin_page and not x.get("plan") else None
            day = f" · {judged['day'][5:]} 장 판단" if judged else ""
            lines.append(f"• {x.get('name') or _sym(x['market'])}{when} · {held}{day}")
            lines.append(f"  {rule_signal_text(x)}" + ("" if slot_signals(x) else " (아직 판단 전)"))
    if len(lines) == 1:
        lines.append("\n아직 계좌가 없어요.")
    updated = (coin or stock or {}).get("updated_at")
    if updated:
        lines.append(f"\n({updated[5:16]} 기준)")
    return "\n".join(lines)


def _uptime(sec: int) -> str:
    days, rest = divmod(sec, 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    return " ".join(p for p in (f"{days}일" if days else "", f"{hours}시간" if hours else "", f"{minutes}분") if p)


def pi_text(info: dict) -> str:
    """/파이 답장: 웹페이지 라즈베리파이 카드와 같은 값 (web.build_system)."""
    lines = ["🍓 라즈베리파이" + (f" · {info['model']}" if info.get("model") else "")]
    if info.get("temp_c") is not None:
        temp = info["temp_c"]
        lines.append(f"🌡 온도 {temp:.1f}°C" + (" (뜨거워요)" if temp >= 80 else ""))
    if info.get("load") is not None and info.get("cpus"):
        busy = min(info["load"] / info["cpus"], 1) * 100
        lines.append(f"⚙️ CPU 약 {busy:.0f}% (1분 평균 부하 {info['load']:.2f} · 코어 {info['cpus']}개)")
    if info.get("mem_total_mb"):
        lines.append(f"🧠 메모리 {info['mem_used_mb']:,} / {info['mem_total_mb']:,}MB")
    if info.get("disk_total_gb"):
        lines.append(f"💾 저장공간 {info['disk_used_gb']:.1f} / {info['disk_total_gb']:.1f}GB"
                     + (f" · 기록 DB {info['db_mb']:.0f}MB" if info.get("db_mb") is not None else ""))
    if info.get("power_w") is not None:
        lines.append(f"🔌 전력 {'' if info.get('power_measured') else '약 '}{info['power_w']:.1f}W"
                     f" ({'실측' if info.get('power_measured') else '추정'}, 권장 어댑터 {info['power_w_recommended']:g}W)")
    if info.get("undervoltage_now"):
        lines.append("⚡ 지금 전압이 모자라요! 정격 어댑터와 짧고 굵은 케이블로 바꿔 주세요")
    elif info.get("undervoltage_ever"):
        lines.append("⚡ 켜진 뒤 전압이 모자란 적이 있어요")
    elif "undervoltage_now" in info:
        lines.append("⚡ 전압 정상")
    if info.get("throttled_now"):
        lines.append("🐢 지금 속도를 낮추는 중이에요 (뜨겁거나 전압이 모자라서)")
    if info.get("uptime_sec") is not None:
        lines.append(f"⏱ 켜진 지 {_uptime(info['uptime_sec'])}")
    lines.append(f"\n({info['server_time'][5:16]} 기준)")
    return "\n".join(lines)


# /상태 · /주식 · /신호 · /파이 답장 아래 버튼: 누르면 같은 메시지가 그 화면으로 바뀐다
VIEW = "view:"
VIEWS = {"coin": ("상태", "status"), "stock": ("주식", "stock"), "signal": ("신호", "signal"), "pi": ("파이", "pi")}


def view_of(text: str) -> str | None:
    """'/상태' → 'coin' 처럼 버튼 화면이 있는 명령이면 그 화면 이름."""
    word = (text or "").strip().split()[0].split("@")[0].lstrip("/").lower() if (text or "").strip() else ""
    return next((view for view, words in VIEWS.items() if word in words), None)


def view_buttons(view: str) -> list:
    return [[("🪙 코인", VIEW + "coin"), ("📈 주식", VIEW + "stock"), ("🚦 신호", VIEW + "signal"), ("🍓 파이", VIEW + "pi")],
            ("🔄 새로고침", VIEW + view)]


def _stock_status(stock_db: str | None) -> dict | None:
    if not stock_db or not Path(stock_db).exists():
        return None
    sdb = Database(stock_db, create=False)
    try:
        return sdb.get_state("status")
    finally:
        sdb.close()


def view_text(view: str, db: Database, stock_db: str | None = None) -> str:
    if view == "stock":
        from .stockbot import status_text as stock_status_text

        return stock_status_text(_stock_status(stock_db))
    if view == "signal":
        return signals_text(db.get_state("status"), _stock_status(stock_db))
    if view == "pi":
        from .web import build_system

        return pi_text(build_system(db.path))
    return status_text(db.get_state("status"))


def daily_text(trades: list[dict], status: dict | None) -> str:
    """아침 리포트: 지난 24시간 매매와 지금 상태."""
    sells = [t for t in trades if t["side"] == "sell" and t.get("profit") is not None]
    realized = sum(t["profit"] for t in sells)
    wins = sum(t["profit"] > 0 for t in sells)
    head = [f"📊 My_Pie 아침 리포트",
            f"지난 24시간 매매 {len(trades)}건" + (f" · 확정 손익 {realized:+,.0f}원 ({wins}승 {len(sells) - wins}패)" if sells else "")]
    body = [trade_line(t) for t in trades[-15:]]
    if len(trades) > 15:
        body.insert(0, f"(앞의 {len(trades) - 15}건 생략)")
    return "\n".join(head + body) + "\n\n" + status_text(status)


def reboot_step(text: str) -> str | None:
    """재부팅 명령인지: 'ask'(확인 안내만) | 'do'(확인까지 붙음) | None(다른 말). 실수로 눌러도 안 꺼지게 '확인'을 요구한다."""
    parts = (text or "").strip().split()
    if not parts or parts[0].split("@")[0].lstrip("/").lower() not in ("재부팅", "reboot"):
        return None
    return "do" if len(parts) > 1 and parts[1] in ("확인", "confirm", "yes") else "ask"


REBOOT_ASK = ("🔄 라즈베리파이를 재부팅할까요? 정말 하려면 아래처럼 보내세요.\n/재부팅 확인\n"
              "(1~2분 동안 매매·웹페이지가 멈췄다가 자동으로 다시 시작해요)")


def command_reply(text: str, db: Database, stock_db: str | None = None) -> str | None:
    """텔레그램 메시지 → 답장. 명령이 아닌 그냥 말에는 안내를 보낸다. stock_db: 주식 봇 DB 파일."""
    word = (text or "").strip().split()[0].split("@")[0].lstrip("/").lower() if (text or "").strip() else ""
    view = view_of(text)
    if view:
        return view_text(view, db, stock_db)
    if word in ("기록", "trades", "매매"):
        return trades_text(db.recent_trades(10))
    return HELP
