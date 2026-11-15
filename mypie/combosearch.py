"""좋은 조합 찾기 (가볍게): 한 종목·주기·기간에서 살 때·팔 때 조합을 많이 굴려 보고 순위를 매긴다.

파이에서도 돌 수 있게 이렇게 가볍게 한다.
  1) 전략마다 봉마다의 계획과 '혼자 굴렸다면 들고 있을까'(combo.Shadow)를 딱 한 번만 계산해서 작은 배열로 둔다.
     지표 계산이 제일 무거운데, 조합이 몇 개든 이건 전략 수만큼만 한다.
  2) 살 때 쪽·팔 때 쪽의 판단(그리고·또는)도 쪽마다 한 번만 합쳐 둔다. 조합 하나는 그 둘을 읽으며 사고팔기만 한다.
  3) 후보를 줄인다: 그 기간 단일 전략 순위 상위 TOP개만 한쪽에 하나 또는 둘(그리고·또는)로 섞는다.
     (그냥 들고 있기는 섞지 않는다.) TOP 6이면 한쪽 36가지 × 다른 쪽 36가지 = 1,296개.
사고파는 규칙은 backtest.simulate · combo.Combo와 똑같다 (테스트가 둘을 맞춰 본다).
과거에 우연히 맞은 조합을 거르게 기간 앞 절반 · 뒤 절반의 수익률도 따로 낸다.
"""

import math
import multiprocessing as mp
import time
from array import array
from itertools import combinations

from . import backtest, simulation, stoploss
from .strategies import create_strategy
from .strategies.combo import OP_TEXT, SHORT, Shadow, rule_label

TOP = 6            # 섞을 단일 전략 수 (그 기간 순위 상위)
KEEP = 30          # 계산 하나마다 남기는 조합 수 (화면은 앞의 몇 개만)
RECENT = 5         # 코인·주식마다 저절로 남겨 두는 최근 계산 수
SAVED = 50         # ⭐ 저장해 둘 수 있는 계산 수 (최근 것과 따로)
MIN_BARS = 60      # 상장한 지 얼마 안 된 종목은 있는 만큼으로 계산하되, 이보다 짧으면 못 한다
HOLD = "buy_and_hold"
YEARS = (1, 2, 3, 5, 8)
MAX_YEARS = {"15m": 2}  # 15분봉은 봉이 너무 많아(8년이면 28만 개) 파이 메모리·시간으로 2년까지
SEC_PER_BAR = 0.000005  # 파이 3B에서 조합 하나 × 봉 하나 (사고팔기만, 4시간봉 3년 1,296가지가 26초 걸린 걸로 잼)
BAO, SAO, KNOWN, NOW, BEFORE = 1, 2, 4, 8, 16  # 봉마다의 표시 (계획: 시작가 사자·팔자, 판단 가능 · 혼자였다면 지금·직전 보유)
NAN = float("nan")


# ---- 1) 전략마다 한 번 ----

def precompute(strategy, candles: list[dict], start: int, window: int) -> tuple[array, array, array]:
    """봉 start부터 끝까지 (표시, 돌파 가격, 이탈 가격). Combo가 굴리는 것과 똑같이 window개 과거 봉을 넘긴다."""
    shadow = Shadow(strategy)
    flags, buy_stop, sell_stop = array("B"), array("d"), array("d")
    for i in range(start, len(candles)):
        plan = shadow.advance(candles[max(0, i - window):i], candles[i]["open"])
        flags.append((BAO if plan.buy_at_open else 0) | (SAO if plan.sell_at_open else 0)
                     | (0 if plan.note.startswith(SHORT) else KNOWN)
                     | (NOW if shadow.state else 0) | (BEFORE if shadow.prev_state else 0))
        buy_stop.append(NAN if plan.buy_stop is None else plan.buy_stop)
        sell_stop.append(NAN if plan.sell_stop is None else plan.sell_stop)
    return flags, buy_stop, sell_stop


# ---- 2) 쪽마다 한 번 (combo.Combo.plan과 같은 규칙) ----

def buy_side(parts: list, op: str) -> tuple[array, array]:
    """살 때 쪽: (시작가에 살지, 돌파 가격). parts: 그 쪽 전략들의 precompute 결과."""
    n = len(parts[0][0])
    at_open, stop = array("B", bytes(n)), array("d", [NAN]) * n
    joined = all if op == "and" else any
    for k in range(n):
        flags = [p[0][k] for p in parts]
        now = joined(f & NOW for f in flags)
        if now and not joined(f & BEFORE for f in flags):
            at_open[k] = 1
        elif not now:
            waiting = [p[1][k] for p, f in zip(parts, flags) if not f & NOW]
            stops = [s for s in waiting if s == s]
            if stops:
                if op == "or":
                    stop[k] = min(stops)
                elif len(stops) == len(waiting):
                    stop[k] = max(stops)
    return at_open, stop


def sell_side(parts: list, op: str) -> tuple[array, array]:
    """팔 때 쪽: (시작가에 팔지, 이탈 가격). 과거 봉이 모자라 판단 못 하는 전략은 '팔자'로 치지 않는다."""
    n = len(parts[0][0])
    at_open, stop = array("B", bytes(n)), array("d", [NAN]) * n
    for k in range(n):
        flags = [p[0][k] for p in parts]
        out = sum(1 for f in flags if f & KNOWN and not f & NOW)
        if (out == len(parts)) if op == "and" else out:
            at_open[k] = 1
            continue
        holding = [p[2][k] for p, f in zip(parts, flags) if f & NOW]
        stops = [s for s in holding if s == s]
        if stops and op == "or":
            stop[k] = max(stops)
        elif stops and len(stops) == len(holding):
            stop[k] = min(stops)
    return at_open, stop


def single_side(pre: tuple) -> tuple[array, array, array, array]:
    """전략 하나를 그대로 쓸 때 (살 때·팔 때가 같은 전략 하나): 그 전략의 계획 그대로."""
    flags, buy_stop, sell_stop = pre
    return (array("B", (1 if f & BAO else 0 for f in flags)), buy_stop,
            array("B", (1 if f & SAO else 0 for f in flags)), sell_stop)


# ---- 3) 조합 하나: 사고팔기만 (backtest.simulate와 같은 규칙) ----

def trade(buy_open, buy_stop, sell_open, sell_stop, bars: dict, ctx: dict, mid: int) -> dict:
    o, h, lo, c = bars["open"], bars["high"], bars["low"], bars["close"]
    fee, cost_out, stop_pct = ctx["fee"], ctx["sell_cost"], ctx["stop_loss"]
    tick = ctx.get("tick")  # 주식: 살 때 한 칸 비싸게, 팔 때 한 칸 싸게 (backtest.simulate와 같다)
    up = (lambda p: p + tick(p)) if tick else (lambda p: p)
    down = (lambda p: max(p - tick(p), tick(p))) if tick else (lambda p: p)
    cash, coin, cost, cut = 1.0, 0.0, 0.0, False
    peak, mdd, wins, trades, held, first = 1.0, 0.0, 0, 0, 0, None
    for k in range(len(o)):
        bought = stopped = False
        if cut and not buy_open[k]:
            cut = False
        if coin and sell_open[k]:
            cash = coin * down(o[k]) * (1 - fee - cost_out)
            trades += 1
            wins += cash > cost
            coin = cost = 0.0
        elif not coin and buy_open[k] and not cut:
            coin, cost, cash = cash / ((1 + fee) * up(o[k])), cash, 0.0
            bought = True
        loss_line = stoploss.line(cost, coin, stop_pct)
        s_stop = sell_stop[k] if coin and not bought and sell_stop[k] == sell_stop[k] else None
        if loss_line is not None and lo[k] <= loss_line and (s_stop is None or loss_line >= s_stop):
            price = min(o[k], loss_line)
            stopped = cut = True
        elif s_stop is not None and lo[k] <= s_stop:
            price = min(o[k], s_stop)
            stopped = True
        b_stop = buy_stop[k]
        if not coin and not bought and not stopped and b_stop == b_stop and h[k] >= b_stop:
            price = up(max(o[k], b_stop))
            coin, cost, cash = cash / ((1 + fee) * price), cash, 0.0
            exit_price = stoploss.breakout_exit(stoploss.line(cost, coin, stop_pct), b_stop, o[k], lo[k], c[k])
            if exit_price is not None:
                price = exit_price
                stopped = cut = True
        if stopped:
            cash = coin * down(price) * (1 - fee - cost_out)
            trades += 1
            wins += cash > cost
            coin = cost = 0.0
        equity = cash + coin * c[k]
        held += 1 if coin else 0
        if equity > peak:
            peak = equity
        elif equity / peak - 1 < mdd:
            mdd = equity / peak - 1
        if k == mid:
            first = equity
    days = len(o)
    years = days / ctx["per_year"]
    final = equity if days else 1.0
    result = {"total_return": final - 1, "mdd": mdd, "trades": trades, "win_rate": wins / trades if trades else None,
              "cagr": final ** (1 / years) - 1 if years >= 0.5 and final > 0 else None,
              "exposure": held / days if days else 0.0,
              "first_half": first - 1 if first else None, "second_half": final / first - 1 if first else None}
    result["score"] = backtest.score(result, ctx["rank_by"])
    return result


# ---- 전체 ----

def side_options(names: list[str]) -> list[tuple[tuple[str, ...], str]]:
    """한쪽(살 때 또는 팔 때)에 넣을 수 있는 것: 전략 하나, 둘 다(그리고), 하나라도(또는)."""
    out = [((n,), "and") for n in names]
    for a, b in combinations(names, 2):
        out += [((a, b), "and"), ((a, b), "or")]
    return out


_shared: dict = {}  # 일꾼 프로세스가 물려받는 계산 재료 (fork)


def _prep(name: str) -> tuple[str, dict]:
    s = _shared
    return name, {w: precompute(create_strategy(name, s["params"][name], s["registry"]), s["candles"], s["start"], w)
                  for w in s["windows"]}


def _side(key: tuple) -> tuple[tuple, tuple]:
    kind, names, op, window = key
    s = _shared
    parts = [s["pre"][n][window] for n in names]
    return key, (buy_side if kind == "buy" else sell_side)(parts, op)


def _combo(task: tuple) -> tuple[tuple, dict]:
    buy, buy_op, sell, sell_op, window = task
    s = _shared
    if len(buy) == 1 and buy == sell:  # 같은 전략 하나: 그 전략 그대로
        sides = s["single"][buy[0]]
    else:
        sides = s["sides"][("buy", buy, buy_op, window)] + s["sides"][("sell", sell, sell_op, window)]
    return task, trade(*sides, s["bars"], s["ctx"], s["mid"])


def _map(fn, items: list, workers: int, done=None):
    """일꾼 여럿으로 나눠 계산한다 (한 개면 그냥). done(n): 끝난 개수를 알린다 (멈춤이면 예외)."""
    out = []
    if workers <= 1 or len(items) < 2 or "fork" not in mp.get_all_start_methods():  # 윈도(개발 PC)는 한 프로세스에서
        for item in items:
            out.append(fn(item))
            if done:
                done(len(out))
        return out
    with mp.get_context("fork").Pool(workers) as pool:
        for r in pool.imap_unordered(fn, items, chunksize=max(1, len(items) // (workers * 20))):
            out.append(r)
            if done:
                done(len(out))
    return out


def search(candles: list[dict], bars: int, ctx: dict, workers: int = 1, progress=None) -> dict:
    """candles: 기간 + 앞쪽 과거 봉. ctx: simulation.context (+ warmup은 여기서 정한다).
    progress(phase, done, total): 진행 상황 (멈춤이면 예외를 올린다)."""
    registry = ctx["strategies"]
    names = [n for n in registry if n != HOLD]
    start = len(candles) - bars
    tick = (lambda phase, total: (lambda done: progress(phase, done, total))) if progress else (lambda phase, total: None)
    windows = {n: registry[n].window for n in [*names, HOLD]}
    _shared.clear()
    _shared.update(candles=candles, start=start, params=ctx["params"], registry=registry, ctx=ctx,
                   windows=sorted({max(windows.values()), *windows.values()}))
    _shared["bars"] = {k: array("d", (x[k] for x in candles[start:])) for k in ("open", "high", "low", "close")}
    _shared["mid"] = bars // 2 - 1

    # 1) 전략마다 (창 크기마다) 한 번
    started = time.time()
    if progress:
        progress("prep", 0, len(names) + 1)
    pre = dict(_map(_prep, [*names, HOLD], workers, tick("prep", len(names) + 1)))
    _shared["pre"] = pre
    _shared["single"] = {n: single_side(pre[n][windows[n]]) for n in [*names, HOLD]}
    singles = {n: trade(*_shared["single"][n], _shared["bars"], ctx, _shared["mid"]) for n in [*names, HOLD]}
    hold = singles.pop(HOLD)
    top = sorted(names, key=lambda n: singles[n]["score"], reverse=True)[:TOP]

    # 2) 쪽마다 한 번: 조합의 창 크기는 들어간 전략 중 가장 큰 것 (Combo.window)
    options = side_options(top)
    tasks = []
    for buy, buy_op in options:
        for sell, sell_op in options:
            tasks.append((buy, buy_op, sell, sell_op, max(windows[n] for n in {*buy, *sell})))
    side_keys = sorted({("buy", t[0], t[1], t[4]) for t in tasks if not (len(t[0]) == 1 and t[0] == t[2])}
                       | {("sell", t[2], t[3], t[4]) for t in tasks if not (len(t[0]) == 1 and t[0] == t[2])})
    if progress:
        progress("sides", 0, len(side_keys))
    _shared["sides"] = dict(_map(_side, side_keys, workers, tick("sides", len(side_keys))))

    # 3) 조합마다: 사고팔기만
    if progress:
        progress("search", 0, len(tasks))
    results = _map(_combo, tasks, workers, tick("search", len(tasks)))
    _shared.clear()
    # 점수 순, 같으면 전략이 적은(단순한) 조합 먼저. 사고판 결과가 똑같은 조합은 맨 앞 하나만 남기고 몇 개인지 센다
    ranked = sorted(results, key=lambda r: (-r[1]["score"], len(r[0][0]) + len(r[0][2])))
    label_of = lambda n: registry[n].label
    side = lambda names, op: f" {OP_TEXT[op]} ".join(label_of(n) for n in names)
    out, seen = [], {}
    for (buy, buy_op, sell, sell_op, _), r in ranked:
        same = (round(r["total_return"], 9), round(r["mdd"], 9), r["trades"])
        if same in seen:
            seen[same]["same"] += 1
            continue
        if len(out) == KEEP:
            continue  # 남길 만큼 찼어도 똑같은 결과는 끝까지 센다
        rule = {"strategy": buy[0], "buy": list(buy), "buy_op": buy_op, "sell": list(sell), "sell_op": sell_op}
        seen[same] = {"rule": rule, "label": rule_label(rule, label_of), "buy_text": side(buy, buy_op),
                      "sell_text": side(sell, sell_op), "same": 0, **_round(r)}
        out.append(seen[same])
    return {"results": out, "count": len(tasks), "top": top, "hold": _round(hold),
            "singles": [{"name": n, "label": label_of(n), **_round(singles[n])} for n in sorted(names, key=lambda n: singles[n]["score"], reverse=True)],
            "seconds": round(time.time() - started, 1)}


def telegram_text(r: dict, rows: int = 5) -> str:
    """오래 걸린 계산이 끝나면 텔레그램으로 보내는 요약 (1~rows위)."""
    pct = lambda v: "-" if v is None else f"{v * 100:+,.1f}%"
    hold = r.get("hold") or {}
    lines = [f"🔍 좋은 조합 찾기 끝 · {r['name']} {r['tf_label']} {r['years']}년",
             f"{r['from']} ~ {r['to']} · {r['count']:,}가지 · {round(r['seconds'])}초",
             f"그냥 들고 있었다면 {pct(hold.get('total_return'))} (최대 낙폭 {pct(hold.get('mdd'))})", ""]
    for i, x in enumerate(r["results"][:rows], 1):
        simple = len(x["rule"]["buy"]) == 1 and x["rule"]["buy"] == x["rule"]["sell"]
        steady = (x.get("first_half") is not None and hold.get("first_half") is not None
                  and x["first_half"] > hold["first_half"] and x["second_half"] > hold["second_half"])
        lines.append(f"{i}. " + (f"단일 {x['buy_text']}" if simple else f"살 때 {x['buy_text']} · 팔 때 {x['sell_text']}"))
        lines.append(f"   {pct(x['total_return'])} · 낙폭 {pct(x['mdd'])} · 매매 {x['trades']}번" + (" · 👍 두 절반 다 이김" if steady else ""))
    if r.get("short"):
        lines.append(f"\n※ 상장한 지 얼마 안 돼서 {r['from']}부터 있는 만큼만 계산했어요 (참고만)")
    lines.append("\n더 보기: 웹페이지 🔍 좋은 조합 찾기")
    return "\n".join(lines)


def history_file(kind: str) -> str:
    return f"search_{kind}.json"


def keep(items: list[dict]) -> list[dict]:
    """남길 계산: ⭐ 저장한 것(SAVED개까지) + 저장 안 한 최근 것(RECENT개). 최근 것부터."""
    recent = [r for r in items if not r.get("saved")][:RECENT]
    saved = [r for r in items if r.get("saved")][:SAVED]
    return sorted(recent + saved, key=lambda r: r.get("computed_at") or "", reverse=True)


def _round(r: dict) -> dict:
    return {k: (round(v, 5) if isinstance(v, float) and math.isfinite(v) else v) for k, v in r.items()}


def estimate(bars: int, n_strategies: int, workers: int, fetch_bars: int = 0) -> float:
    """대략 걸리는 시간(초): 전략 계산 + 조합 굴리기 + 모자란 봉 받기."""
    combos = (TOP + TOP * (TOP - 1)) ** 2
    prep = n_strategies * bars * simulation.SEC_PER_STEP
    return (prep + combos * bars * SEC_PER_BAR) / max(1, workers) + fetch_bars / 200 * simulation.SEC_PER_FETCH
