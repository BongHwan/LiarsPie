// 계좌 카드의 작은 그래프 (코인·주식 화면 공용): 첫 매매부터 이 계좌 전략(보라 실선) vs 그냥 들고 있었다면(회색 점선).
// 서버 /api/curve가 실제 매매 기록과 봉 종가로 다시 그린 값을 준다. 1분 동안은 받아 둔 걸 다시 쓴다.
// curveBox(kind, slotId)가 돌려준 칸을 카드에 넣으면, 값이 오는 대로 그 칸에 그린다 (카드를 다시 그려도 이어서).
const CURVES = {};  // 'coin:s1' → { at, data, loading }

function curveBox(kind, slotId) {
  const key = `${kind}:${slotId}`;
  const box = document.createElement('div');
  box.className = 'curve';
  box.dataset.curve = key;
  const c = CURVES[key];
  if (c && c.data) drawCurve(box, c.data);
  else { box.classList.add('empty'); box.textContent = '그래프를 불러오는 중…'; }
  if (!c || (!c.loading && Date.now() - c.at > 60000)) loadCurve(kind, slotId);
  return box;
}

async function loadCurve(kind, slotId) {
  const key = `${kind}:${slotId}`;
  CURVES[key] = { ...(CURVES[key] || {}), loading: true };
  try {
    const r = await fetch(`/api/curve?kind=${kind}&slot=${encodeURIComponent(slotId)}`, { cache: 'no-store' });
    if (r.status === 401) { location.reload(); return; }
    CURVES[key] = { at: Date.now(), data: await r.json(), loading: false };
  } catch (e) {
    CURVES[key] = { at: Date.now(), data: CURVES[key].data || null, loading: false };
  }
  for (const box of document.querySelectorAll(`.curve[data-curve="${key}"]`)) drawCurve(box, CURVES[key].data);
}

function drawCurve(box, data) {
  box.replaceChildren();
  const pts = (data && data.points) || [];
  box.classList.toggle('empty', pts.length < 2);
  if (pts.length < 2) { box.textContent = '📈 첫 매매부터 수익 그래프를 그려요'; return; }
  const time = (s) => new Date(s.replace(' ', 'T') + '+09:00').getTime();
  const t0 = time(pts[0][0]), t1 = time(pts[pts.length - 1][0]) || t0 + 1;
  let lo = 0, hi = 0;
  for (const [, a, b] of pts) { lo = Math.min(lo, a, b); hi = Math.max(hi, a, b); }
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const W = 300, H = 76;
  const x = (s) => ((time(s) - t0) / (t1 - t0 || 1)) * W;
  const y = (v) => H - ((v - lo) / (hi - lo)) * H;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('role', 'img');
  const last = pts[pts.length - 1];
  svg.setAttribute('aria-label', `첫 매매부터 전략 ${last[1].toFixed(1)}%, 그냥 들고 있었다면 ${last[2].toFixed(1)}%`);
  const line = (cls, d) => { const p = document.createElementNS(NS, 'path'); p.setAttribute('class', cls); p.setAttribute('d', d); svg.append(p); };
  line('curve-zero', `M0 ${y(0).toFixed(1)}H${W}`);
  const path = (i) => pts.map((p, k) => `${k ? 'L' : 'M'}${x(p[0]).toFixed(1)} ${y(p[i]).toFixed(1)}`).join('');
  line('curve-hold', path(2));
  line('curve-strat', path(1));
  const pct = (v) => (v > 0 ? '+' : '') + v.toFixed(1) + '%';
  const tone = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '');
  const span = (cls, text) => { const s = document.createElement('span'); s.className = cls; s.textContent = text; return s; };
  const head = document.createElement('div');
  head.className = 'curve-head';
  const legend = document.createElement('span');
  legend.className = 'curve-legend';
  const strat = span('c-strat', '━ 전략 '), hold = span('c-hold', '┅ 들고만 있었다면 ');
  strat.append(span('num ' + tone(last[1]), pct(last[1])));
  hold.append(span('num ' + tone(last[2]), pct(last[2])));
  legend.append(strat, hold);
  head.append(span('', `📈 첫 매매(${pts[0][0].slice(5, 10)})부터`), legend);
  const foot = document.createElement('div');
  foot.className = 'curve-foot';
  foot.append(span('', pts[0][0].slice(5, 16)), span('', last[0].slice(5, 16)));
  box.append(head, svg, foot);
}
