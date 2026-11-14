// 🎨 테마 (코인·주식 화면 공용): 위쪽 🎨 버튼을 누르면 고르는 칸이 열리고, 누르는 대로 바로 바뀐다.
// 고른 테마는 이 기기에만 기억한다 (localStorage 'mypie.theme'). 페이지 맨 위 스크립트가 그리기 전에 적용한다.
(() => {
  const THEMES = [  // [번호, 이름, 설명, 미리보기 색 (바탕 · 포인트 · 오름 · 내림)]
    ['1', '라이트 퍼플', '기본 · 폰이 어두운 모드면 어둡게', ['#f3f4f8', '#6d4aff', '#e0313f', '#1f6fe5']],
    ['2', '다크 트레이딩', '늘 어둡게 · 민트 포인트', ['#0b1019', '#2dd4bf', '#ff5c6c', '#4f8fff']],
    ['3', '화이트 블루', '흰 카드 · 파랑 포인트', ['#f2f4f6', '#3182f6', '#f04452', '#3182f6']],
    ['4', '차분한 종이', '아이보리 · 남색 포인트', ['#f4efe6', '#1e3a5f', '#c8372d', '#2563a8']],
    ['5', '벚꽃 핑크', '핑크핑크 · 폰이 어두운 모드면 어둡게', ['#fff3f7', '#ff4f9a', '#e8335f', '#4d7cf0']],
  ];
  const btn = document.getElementById('themeBtn');
  if (!btn) return;
  const node = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'text') e.textContent = v; else if (k === 'class') e.className = v; else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k);
    return e;
  };
  const now = () => document.documentElement.dataset.theme || '1';
  const pop = node('div', { class: 'theme-pop', role: 'radiogroup', 'aria-label': '테마', hidden: '' });
  for (const [id, name, sub, colors] of THEMES) {
    const b = node('button', { type: 'button', role: 'radio', 'data-theme-id': id },
      node('span', { class: 'theme-dots' }, ...colors.map((c) => node('i', { style: `background:${c}` }))),
      node('span', {}, node('b', { text: `${id} · ${name}` }), node('small', { text: sub })));
    b.onclick = () => {
      if (id === '1') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = id;
      try { localStorage.setItem('mypie.theme', id); } catch (e) { /* 이번에만 */ }
      mark();
      window.dispatchEvent(new Event('resize'));  // 차트를 새 색으로 다시 그린다
    };
    pop.append(b);
  }
  btn.after(pop);
  function mark() {
    for (const b of pop.children) b.setAttribute('aria-checked', String(b.dataset.themeId === now()));
  }
  function show(open) {
    pop.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
    if (open) mark();
  }
  btn.onclick = (e) => { e.stopPropagation(); show(pop.hidden); };
  document.addEventListener('click', (e) => { if (!pop.hidden && !pop.contains(e.target)) show(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !pop.hidden) { show(false); btn.focus(); } });
})();
