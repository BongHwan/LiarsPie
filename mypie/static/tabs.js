// 화면 탭 (코인·주식 화면 공용): 🏠 홈 · 🔬 연구 · 🧾 기록 · 🍓 파이. 칸마다 data-tab으로 어느 탭에 있는지 정한다.
// 고른 탭은 이 기기에 기억한다. 주소 끝에 #sim처럼 칸 이름을 붙이면 그 칸이 있는 탭을 열고 그리로 간다.
// Tabs.reveal(칸): 다른 탭에 있는 칸이면 그 탭을 열고 보여준다 (예: 연구 탭의 '계좌 만들기' → 홈 탭의 만들기 칸)
const Tabs = (() => {
  const KEY = 'mypie.tab';
  const bar = document.getElementById('tabs');
  function show(name, save = true) {
    if (!bar.querySelector(`[data-go="${name}"]`)) name = 'home';
    document.body.dataset.tab = name;
    for (const b of bar.querySelectorAll('[data-go]')) b.setAttribute('aria-selected', String(b.dataset.go === name));
    if (save) {
      try { localStorage.setItem(KEY, name); } catch (e) { /* 기억만 못 한다 */ }
    }
    window.dispatchEvent(new Event('resize'));  // 숨어 있던 차트를 지금 너비로 다시 그린다
  }
  function reveal(el, block = 'start') {
    if (!el) return;
    const tab = el.closest('[data-tab]');
    if (tab && tab.dataset.tab !== document.body.dataset.tab) show(tab.dataset.tab);
    el.scrollIntoView({ behavior: 'smooth', block });
  }
  bar.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-go]');
    if (!b) return;
    show(b.dataset.go);
    window.scrollTo({ top: 0 });
  });
  let first = 'home';
  try { first = localStorage.getItem(KEY) || 'home'; } catch (e) { /* 처음은 홈 */ }
  const target = location.hash.length > 1 ? document.getElementById(location.hash.slice(1)) : null;
  const tab = target && target.closest('[data-tab]');
  show(tab ? tab.dataset.tab : first, !tab);
  if (tab) setTimeout(() => reveal(target), 300);
  return { show, reveal };
})();
