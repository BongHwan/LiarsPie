// 숫자 칸 (코인·주식 화면 공용): '이 전략'과 '그냥 들고 있었다면'(같은 돈을 같은 때 넣고 사서 그냥 들고 있었다면)을
// 나란히 놓은 비교표 + 한 줄 판정 + 이름·값 줄들. 펼친 계좌 카드(slotNumbers)와 전략 시뮬레이션(NumBox.sim)이 쓴다.
const NumBox = (() => {
  const node = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'text') e.textContent = v; else if (k === 'class') e.className = v; else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k);
    return e;
  };
  const won = (n) => (n == null || isNaN(n) ? '-' : Math.round(n).toLocaleString('ko-KR') + '원');
  const signedWon = (n) => (n == null || isNaN(n) ? '-' : (n > 0 ? '+' : '') + won(n));
  const pct = (n, d = 2) => (n == null || isNaN(n) ? '-' : (n > 0 ? '+' : '') + n.toFixed(d) + '%');
  const tone = (e, n) => { if (n > 0) e.classList.add('up'); else if (n < 0) e.classList.add('down'); return e; };

  // rows: [이름, 이 전략 글자, 색 기준, 그냥 들고 있었다면 글자, 색 기준]
  function table(rows) {
    const cell = (text, n, me) => tone(node('td', { class: me ? 'num me' : 'num', text }), n);
    return node('table', { class: 'cmp-t' },
      node('tr', {}, node('th'), node('th', { text: '이 전략' }),
           node('th', { text: '그냥 들고 있었다면', title: '같은 돈을 같은 때 넣고 사서 그냥 들고 있었다면 (바이앤홀드)' })),
      ...rows.map(([label, mine, mn, hold, hn]) => node('tr', {}, node('td', { text: label }), cell(mine, mn, true), cell(hold, hn))));
  }
  function verdict(ret, hold) {  // 수익률(%) 두 개 → 한 줄 판정 (앞섰으면 빨강, 뒤처졌으면 파랑)
    if (ret == null || hold == null) return null;
    const d = ret - hold, a = Math.abs(d).toFixed(1);
    const text = Math.abs(d) < 0.05 ? '그냥 들고 있기와 거의 같아요'
      : d > 0 ? `그냥 들고 있기보다 ${a}%p ${ret < 0 ? '덜 잃었어요' : '더 벌었어요'}`
        : `그냥 들고 있기보다 ${a}%p ${ret > 0 ? '덜 벌었어요' : hold < 0 ? '더 잃었어요' : '뒤처졌어요'}`;
    return tone(node('div', { class: 'cmp-verdict', text }), Math.abs(d) < 0.05 ? 0 : d);
  }
  // list: [{ label, value, n(색 기준), sub(아래 작은 줄), indent, title }]
  function rows(list) {
    const box = node('div', { class: 'nums-rows' });
    for (const r of list) {
      box.append(...[
        node('span', { class: 'k' + (r.indent ? ' indent' : ''), ...(r.title ? { title: r.title } : {}) }, r.label),
        node('span', { class: 'v' }, tone(node('b', { class: 'num', text: r.value }), r.n)),
        r.sub ? node('small', { class: 'sub-line', text: r.sub }) : null].filter(Boolean));
    }
    return box;
  }

  // 펼친 계좌 카드: 수익률·손익 비교 → 계좌 금액 (들고 있으면 그 안의 코인·주식 · 현금 · 평가 손익) · 넣은 돈 · 확정 손익
  // o: { contrib, cash, held: 'BTC' | '주식 10주', costNote }
  function slot(x, o) {
    const pnl = o.contrib > 0 && x.equity != null ? x.equity - o.contrib : null;
    const list = [{ label: '계좌 금액', value: won(x.equity) }];
    if (x.holding) {  // 계좌 금액 = 들고 있는 것 + 현금
      list.push({ label: `들고 있는 ${o.held}`, value: won(x.value), indent: true },
                { label: '현금 (살 돈)', value: won(o.cash), indent: true },
                { label: '평가 손익', value: `${signedWon(x.unrealized)} (${pct(x.unrealized_pct, 1)})`, n: x.unrealized, indent: true,
                  title: '지금 들고 있는 것을 산 값과 비교한 손익' });
    }
    list.push({ label: '넣은 돈', value: won(o.contrib), title: '이 계좌에 넣은 돈 − 뺀 돈' },
              { label: x.sells ? `확정 손익 · ${x.wins}승 ${x.sells - x.wins}패` : '확정 손익', value: x.sells ? signedWon(x.realized) : '0원',
                n: x.realized, sub: x.sells ? `번 돈 ${signedWon(x.gains)} · 잃은 돈 ${signedWon(x.losses)}` : '아직 판 매매가 없어요',
                title: `판 매매로 확정된 손익이에요. ${o.costNote}` });
    return node('div', { class: 'slot-nums' },
      table([['수익률', pct(x.return_pct), x.return_pct, pct(x.hold_return_pct), x.hold_return_pct],
             ['손익', signedWon(pnl), pnl, signedWon(x.hold_pnl), x.hold_pnl]]),
      verdict(x.return_pct, x.hold_return_pct), rows(list));
  }

  // 전략 시뮬레이션: [100만 원이 얼마 · 수익률 · 최대 낙폭 비교표 + 판정, 사고판 횟수 · 순위 · 마지막 상태]
  // o: { base(시작 돈), count(전략 수), combo, holding, thing: '코인' | '주식' }
  function sim(res, hold, o) {
    const r1 = res.total_return * 100, r2 = hold.total_return * 100;
    const cmp = node('div', { class: 'slot-nums' },
      table([[`${(o.base / 10000).toLocaleString('ko-KR')}만 원`, won(o.base * (1 + res.total_return)), r1, won(o.base * (1 + hold.total_return)), r2],
             ['수익률', pct(r1, 1), r1, pct(r2, 1), r2],
             ['최대 낙폭', pct(res.mdd * 100, 1), res.mdd < 0 ? -1 : 0, pct(hold.mdd * 100, 1), hold.mdd < 0 ? -1 : 0]]),
      verdict(r1, r2));
    const more = rows([
      { label: '사고판 횟수', value: `${res.trades}번`, sub: res.win_rate == null ? '아직 판 적 없음' : `이긴 비율 ${Math.round(res.win_rate * 100)}%` },
      { label: '이 기간 순위', value: `${res.rank}위`, sub: o.combo ? `전략 ${o.count}개 사이에 넣으면` : `전략 ${o.count}개 중` },
      { label: '마지막엔', value: o.holding ? `${o.thing}을 들고 있었어요` : '현금으로 기다렸어요' },
    ]);
    more.classList.add('slot-nums', 'sim-more');
    return [cmp, more];
  }

  return { table, verdict, rows, slot, sim };
})();
const slotNumbers = NumBox.slot;
