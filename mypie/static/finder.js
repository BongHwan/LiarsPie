// 좋은 조합 찾기 (코인·주식 화면 공용): 종목·판단 주기·기간을 골라 파이에게 맡기면, 그 기간 단일 전략 상위 6개를
// 살 때·팔 때에 섞은 조합을 모두 굴려 보고 순위를 보여준다. 계산은 긴 시뮬레이션과 같은 자리(한 번에 하나)에서 하고,
// 계산 중이면 진행률·멈춤을 보여준다. 최근 계산 5개는 저절로 남고(눌러서 다시 보기), ⭐ 저장한 건 50개까지 따로 남는다.
// 화면에는 마지막 계산이 뜬다.
// Finder.init({ kind, markets: () => [{value, text}], current: () => value, onUse: (result, row) => {}, onCreate: (result, row) => {},
//               search: async (q) => [{value, text, sub}] (주식: 아무 종목이나 찾기, 없으면 markets 안에서만) })
// 종목 칸은 시뮬레이션처럼 이름이나 코드를 쳐서 찾는다. 비워 두고 누르면 markets(코인은 거래대금 상위, 주식은 계좌 종목)가 뜬다.
const Finder = (() => {
  const TF = [['1d', '일봉'], ['240m', '4시간봉'], ['60m', '1시간봉'], ['15m', '15분봉']];
  const SHOW = 10;
  const box = document.getElementById('finder');
  let opt = null, data = null, viewing = '', more = false, timer = null, estTimer = null, findTimer = null, findSeq = 0;
  let picked = { value: '', text: '' };  // 고른 종목
  const ui = {};

  const node = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'text') e.textContent = v; else if (k === 'class') e.className = v; else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k);
    return e;
  };
  const pct = (v, d = 1) => (v == null ? '-' : (v > 0 ? '+' : '') + (v * 100).toLocaleString('ko-KR', { maximumFractionDigits: d, minimumFractionDigits: d }) + '%');
  const tone = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '');
  const num = (v, cls) => node('span', { class: `num ${cls || tone(v)}`, text: pct(v) });
  const dur = (sec) => {
    sec = Math.max(1, Math.round(sec));
    return sec >= 3600 ? `${Math.floor(sec / 3600)}시간 ${Math.round(sec % 3600 / 60)}분`
      : sec >= 60 ? `${Math.floor(sec / 60)}분${sec % 60 ? ` ${sec % 60}초` : ''}` : `${sec}초`;
  };
  async function api(path, body) {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : { cache: 'no-store' });
    if (r.status === 401) { location.reload(); throw new Error('login'); }
    return r.json();
  }

  function build() {
    ui.market = node('input', { 'aria-label': '종목', placeholder: '이름이나 코드로 찾기', autocomplete: 'off', enterkeyhint: 'search' });
    ui.suggest = node('div', { class: 'suggest', hidden: '' });
    ui.tf = node('select', { 'aria-label': '판단 주기' });
    for (const [v, t] of TF) ui.tf.append(node('option', { value: v, text: t + (v === '60m' || v === '15m' ? ' (재미로)' : '') }));
    ui.tf.value = '240m';
    ui.years = node('select', { 'aria-label': '기간' });
    ui.go = node('button', { type: 'button', class: 'primary', text: '🔍 찾기' });
    ui.est = node('span', { class: 'hint' });
    ui.job = node('div', { class: 'simjob', hidden: '' });
    ui.hist = node('div', { class: 'finder-hist' });
    ui.result = node('div', { class: 'finder-result' });
    box.append(
      node('h2', {}, node('span', { class: 'ico', text: '🔍' }), '좋은 조합 찾기 ',
        node('small', { text: '그 기간 단일 전략 상위 6개를 살 때·팔 때에 섞어 1,296가지를 굴려 봐요 · 파이가 따로 계산해요' })),
      node('div', { class: 'finder-form' }, node('div', { class: 'search finder-search' }, ui.market, ui.suggest),
        opt.kind === 'coin' ? ui.tf : null, ui.years, ui.go, ui.est),
      ui.job, ui.hist, ui.result);
    for (const s of [ui.tf, ui.years]) s.onchange = () => { fillYears(); estimate(); };
    ui.go.onclick = start;
    ui.market.addEventListener('focus', () => {  // 누르면 비워서 바로 칠 수 있게 (고른 종목은 흐린 글씨로)
      ui.market.placeholder = picked.text ? `${picked.text} · 이름이나 코드로 찾기` : '이름이나 코드로 찾기';
      ui.market.value = '';
      suggest();
    });
    ui.market.addEventListener('input', () => { clearTimeout(findTimer); findTimer = setTimeout(suggest, 200); });
    ui.market.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {  // 맨 위 것을 고른다
        e.preventDefault();
        const first = ui.suggest.hidden ? null : ui.suggest.querySelector('button');
        if (first) first.click();
      } else if (e.key === 'Escape') ui.market.blur();
    });
    ui.market.addEventListener('blur', () => setTimeout(() => { ui.suggest.hidden = true; ui.market.value = picked.text; ui.market.placeholder = '이름이나 코드로 찾기'; }, 150));
    ui.suggest.addEventListener('mousedown', (e) => e.preventDefault());  // 목록을 눌러도 칸에서 포커스가 빠지지 않게
  }

  async function suggest() {  // 친 글자로 찾기: markets 안에서 먼저, 주식은 전체 종목에서도
    const q = ui.market.value.trim(), seq = ++findSeq;
    const typed = q && q !== picked.text, low = q.toLowerCase();
    let list = opt.markets();
    if (typed) list = list.filter((m) => m.text.toLowerCase().includes(low) || m.value.toLowerCase().includes(low));
    if (typed && opt.search) {
      try {
        const found = await opt.search(q);
        const seen = new Set(list.map((m) => m.value));
        list = list.concat(found.filter((m) => !seen.has(m.value)));
      } catch (e) { /* 있는 것만 */ }
    }
    if (seq !== findSeq || document.activeElement !== ui.market) return;
    ui.suggest.replaceChildren(...list.slice(0, 30).map((m) => {
      const b = node('button', { type: 'button' }, node('span', { text: m.text }), m.sub ? node('small', { text: m.sub }) : null);
      b.onclick = () => pick(m);
      return b;
    }));
    if (!list.length) ui.suggest.append(node('div', { class: 'empty', text: '못 찾았어요' }));
    ui.suggest.hidden = false;
  }
  function pick(m) {
    picked = { value: m.value, text: m.text };
    ui.market.value = m.text;
    ui.suggest.hidden = true;
    ui.market.blur();
    estimate();
  }
  function fillMarkets() {  // 처음엔 지금 보는 종목을 골라 둔다 (목록이 늦게 오면 이름은 그때 채운다)
    const cur = picked.value || opt.current();
    if (!cur) return;
    const m = opt.markets().find((x) => x.value === cur);
    if (picked.value && !(m && picked.text === picked.value)) return;
    picked = m ? { value: m.value, text: m.text } : { value: cur, text: cur };
    if (document.activeElement !== ui.market) ui.market.value = picked.text;
    estimate();
  }
  function fillYears() {
    const tf = opt.kind === 'coin' ? ui.tf.value : '1d';
    const max = (data && data.max_years[tf]) || 8, keep = Number(ui.years.value) || 3;
    const years = ((data && data.years) || [1, 2, 3, 5, 8]).filter((y) => y <= max);
    ui.years.replaceChildren(...years.map((y) => node('option', { value: String(y), text: `${y}년` + (y === 8 ? ' (2018년쯤부터)' : '') })));
    ui.years.value = String(years.includes(keep) ? keep : years[years.length - 1]);
  }
  function choice() {
    return { kind: opt.kind, market: picked.value, tf: opt.kind === 'coin' ? ui.tf.value : '1d', years: Number(ui.years.value) };
  }
  function estimate() {  // 고른 조건으로 걸리는 시간 (조금 기다렸다가 한 번)
    clearTimeout(estTimer);
    estTimer = setTimeout(async () => {
      const c = choice();
      if (!c.market) return;
      try {
        const r = await api(`/api/search?only=estimate&kind=${c.kind}&market=${encodeURIComponent(c.market)}&tf=${c.tf}&years=${c.years}`);
        const e = r.estimate || {};
        ui.est.textContent = e.problem || `약 ${dur(e.sec)}` + (e.fetch_bars ? ` (과거 봉 ${e.fetch_bars.toLocaleString('ko-KR')}개를 먼저 받아요)` : '');
      } catch (err) { /* 그대로 */ }
    }, 300);
  }

  async function load(id) {
    try {
      data = await api(`/api/search?kind=${opt.kind}` + (id ? `&id=${encodeURIComponent(id)}` : ''));
    } catch (e) { return; }
    viewing = data.result ? data.result.id : '';
    if (!ui.years.options.length) fillYears();
    drawJob(data.job);
    drawHistory();
    drawResult(data.result);
  }
  async function start() {
    try {
      const r = await api('/api/search', { action: 'start', ...choice() });
      if (!r.ok && !r.busy && window.toast) window.toast(r.message, 'bad');
      drawJob(r.job);
      poll();
    } catch (e) { /* 다음에 */ }
  }
  async function stop() {
    try { drawJob((await api('/api/search', { action: 'stop' })).job); poll(); } catch (e) { /* 그대로 */ }
  }
  function poll() {  // 계산 중에는 가벼운 상태만 묻고, 끝나면 결과를 다시 받는다
    if (timer) return;
    timer = setInterval(async () => {
      let job;
      try { job = (await api('/api/simjob')).job; } catch (e) { return; }
      drawJob(job);
      if (job.state !== 'running') {
        clearInterval(timer); timer = null;
        if (job.state === 'done' && String(job.id || '').startsWith(`search-${opt.kind}-`)) load();
      }
    }, 1500);
  }

  const PHASES = { data: '과거 봉을 받는 중', prep: '전략 계산 중', sides: '살 때·팔 때 판단 합치는 중', search: '조합 굴리는 중' };
  function drawJob(job) {
    const mine = job && String(job.id || '').startsWith(`search-${opt.kind}-`);
    const running = job && job.state === 'running';
    ui.go.disabled = !!running;
    ui.job.replaceChildren();
    ui.job.hidden = !(running || (mine && (job.state === 'stopped' || job.state === 'error')));
    if (ui.job.hidden) return;
    if (!running) { ui.job.append(node('div', { class: 'simjob-head' }, node('span', { text: job.message || '멈췄어요' }))); return; }
    if (!mine) {
      ui.job.append(node('div', { class: 'simjob-head' }, node('span', { class: 'muted', text: `다른 계산 중 · ${job.label} · 끝나면 찾을 수 있어요` })));
      return;
    }
    const frac = job.total ? Math.min(1, job.done / job.total) : 0;
    const spent = Date.now() / 1000 - (job.started || Date.now() / 1000);
    const rest = job.phase === 'search' && frac > 0.05
      ? (Date.now() / 1000 - job.phase_started) * (1 - frac) / frac : Math.max(0, (job.estimate_sec || 0) - spent);
    const stopBtn = node('button', { type: 'button', class: 'ghost small', text: '■ 멈춤' });
    stopBtn.onclick = stop;
    ui.job.append(
      node('div', { class: 'simjob-head' }, node('b', { text: `${job.label} · ${PHASES[job.phase] || '준비 중'}` }),
        node('span', { class: 'muted', text: [job.total ? `${job.done.toLocaleString('ko-KR')} / ${job.total.toLocaleString('ko-KR')}` : '',
          rest > 1 ? `남은 시간 약 ${dur(rest)}` : '마무리 중'].filter(Boolean).join(' · ') }), stopBtn),
      node('div', { class: 'simjob-bar' }, node('i', { style: `width:${Math.max(2, frac * 100)}%` })),
      node('div', { class: 'simjob-note muted', text: '파이가 매매를 먼저 하고 남는 힘으로 계산해요. 이 화면을 닫아도 계속 계산하고, 끝나면 결과가 여기 떠요.' }));
    poll();
  }

  function drawHistory() {  // 최근 계산 몇 개는 버튼으로, ⭐ 저장한 건 고르는 칸으로
    ui.hist.replaceChildren();
    const items = (data && data.history) || [];
    if (!items.length) return;
    const label = (h) => `${h.saved ? '⭐ ' : ''}${h.name} ${h.tf_label} ${h.years}년 · ${String(h.computed_at || '').slice(5, 16)}`;
    for (const h of items.slice(0, data.recent || 5)) {
      const b = node('button', { type: 'button', class: 'pill', 'aria-pressed': String(h.id === viewing), text: label(h) });
      b.onclick = () => load(h.id);
      ui.hist.append(b);
    }
    const saved = items.filter((h) => h.saved);
    if (saved.length) {
      const pick = node('select', { 'aria-label': '저장한 결과' },
        node('option', { value: '', text: `⭐ 저장한 결과 ${saved.length}개 (${data.saved_max || 50}개까지)` }),
        ...saved.map((h) => node('option', { value: h.id, text: label(h).replace('⭐ ', '') })));
      if (saved.some((h) => h.id === viewing)) pick.value = viewing;
      pick.onchange = () => { if (pick.value) load(pick.value); };
      ui.hist.append(pick);
    }
  }
  async function toggleSave(r) {
    try {
      const res = await api('/api/search', { action: r.saved ? 'unsave' : 'save', kind: opt.kind, id: r.id });
      if (window.toast) window.toast(res.message, res.ok ? 'ok' : 'bad');
      if (res.ok) load(r.id);
    } catch (e) { /* 그대로 */ }
  }

  function drawResult(r) {
    ui.result.replaceChildren();
    if (!r) {
      ui.result.append(node('p', { class: 'muted', text: '아직 찾아본 적이 없어요. 종목·기간을 고르고 🔍 찾기를 눌러 보세요.' }));
      return;
    }
    const h = r.hold || {};
    const star = node('button', { type: 'button', class: r.saved ? 'small' : 'ghost small', text: r.saved ? '★ 저장됨' : '☆ 저장',
                                  title: r.saved ? '눌러서 저장에서 빼기' : `저장해 두면 최근 ${(data && data.recent) || 5}개에서 밀려나도 남아요` });
    star.onclick = () => toggleSave(r);
    ui.result.append(...[
      node('div', { class: 'finder-head' },
        node('b', { text: `${r.name} · ${r.tf_label} · ${r.from} ~ ${r.to}` }),
        node('span', { class: 'muted', text: ` (${r.short ? `${r.years}년 중 있는 만큼` : `${r.years}년`}) · ${r.count.toLocaleString('ko-KR')}가지 · ${dur(r.seconds)} 걸림 · ${String(r.computed_at).slice(5, 16)} ` }),
        star),
      r.short ? node('div', { class: 'finder-short', text: `※ 상장한 지 얼마 안 돼서 ${r.years}년 대신 있는 만큼(${r.from}부터 ${r.bars.toLocaleString('ko-KR')}봉)만 계산했어요. 기간이 짧아서 참고만 하세요.` }) : null,
      node('div', { class: 'finder-sub' }, '그냥 들고 있었다면 ', num(h.total_return), ` · 최대 낙폭 ${pct(h.mdd)} · 섞은 전략: `,
        (r.singles || []).filter((s) => r.top.includes(s.name)).map((s) => s.label).join(', ')),
    ].filter(Boolean));
    const list = node('div', { class: 'finder-list' });
    (r.results || []).slice(0, more ? r.results.length : SHOW).forEach((x, i) => {
      const steady = x.first_half != null && h.first_half != null && x.first_half > h.first_half && x.second_half > h.second_half;
      const simple = x.rule.buy.length === 1 && x.rule.sell.length === 1 && x.rule.buy[0] === x.rule.sell[0];
      const rule = simple ? node('div', { class: 'finder-rule' }, '단일 ', node('b', { text: x.buy_text }))
        : node('div', { class: 'finder-rule' }, '살 때 ', node('b', { text: x.buy_text }), ' · 팔 때 ', node('b', { text: x.sell_text }));
      const use = node('button', { type: 'button', class: 'ghost small', text: '📊 시뮬레이션' });
      use.onclick = () => opt.onUse(r, x);
      const make = node('button', { type: 'button', class: 'small', text: '➕ 계좌 만들기' });
      make.onclick = () => opt.onCreate(r, x);
      const stat = (label, value, cls) => node('span', { class: 'finder-stat' }, node('small', { text: label }), ' ',
                                                 node('b', { class: `num ${cls || ''}`, text: value }));
      list.append(node('div', { class: 'finder-row' },
        node('div', { class: 'finder-rank num', text: String(i + 1) }),
        node('div', { class: 'finder-main' }, rule,
          node('div', { class: 'finder-top' }, node('span', { class: `finder-ret num ${tone(x.total_return)}`, text: pct(x.total_return) }),
            steady ? node('span', { class: 'finder-ok', text: '👍 두 절반 다 이김' }) : null),
          node('div', { class: 'finder-stats' }, stat('낙폭', pct(x.mdd), 'down'), stat('매매', `${x.trades}번`),
            x.win_rate != null ? stat('승률', `${Math.round(x.win_rate * 100)}%`) : null,
            stat('앞 절반', pct(x.first_half), tone(x.first_half)), stat('뒤 절반', pct(x.second_half), tone(x.second_half))),
          x.same ? node('div', { class: 'finder-same', text: `결과가 똑같은 조합 ${x.same}개 더`,
                                 title: '사고판 때가 똑같아서 결과가 같은 조합이에요. 전략이 가장 적은 것만 보여줘요.' }) : null),
        node('div', { class: 'finder-acts' }, use, make)));
    });
    ui.result.append(list);
    if ((r.results || []).length > SHOW) {
      const b = node('button', { type: 'button', class: 'ghost small', text: more ? '접기' : `더 보기 (${r.results.length}개까지)` });
      b.onclick = () => { more = !more; drawResult(r); };
      ui.result.append(b);
    }
    ui.result.append(node('p', { class: 'note', text: '과거 성적이에요. 많이 비교해서 고를수록 과거에만 우연히 맞은 조합이 뽑히기 쉬워요. '
      + "'두 절반 다 이김'(앞 절반·뒤 절반 모두 그냥 들고 있기보다 나음)인 것을 먼저 보세요." }));
  }

  function init(o) {
    opt = o;
    if (!box) return;
    build();
    load();
  }
  function refresh() { if (opt && box) fillMarkets(); }  // 화면이 새 데이터를 받을 때마다 (종목 목록)
  return { init, refresh };
})();
