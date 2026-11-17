// 미확정 주문 상세 및 토스증권 주문번호 연결.
let pendingOrderKey;

function renderPendingOrder(order, reload) {
  const panel = document.getElementById('pendingOrder');
  panel.hidden = !order;
  const key = order ? JSON.stringify(order) : '';
  if (key === pendingOrderKey) return;
  pendingOrderKey = key;
  panel.replaceChildren();
  if (!order) return;
  const side = (value) => ({buy: '매수', bid: '매수', sell: '매도', ask: '매도'})[value] || '미확인';
  const message = order.reason || '거래소에서 주문 결과를 확인하고 있어요.';
  panel.append(el('h3', {text: '미확정 주문'}),
    el('p', {text: [order.at ? order.at + ' KST' : '제출 시각 미확인', order.symbol || '종목 미확인', side(order.side)].join(' · ')}),
    el('p', {text: message}));
  if (order.order_id) panel.append(el('p', {text: '연결된 주문번호 ' + order.order_id}));
  if (!order.can_link) return;

  const number = el('input', {type: 'text', maxlength: 256, autocomplete: 'off', 'aria-label': '토스증권 주문번호',
    placeholder: '토스증권 주문번호'});
  const pin = el('input', {type: 'password', inputmode: 'numeric', maxlength: 32, autocomplete: 'off', 'aria-label': 'PIN', placeholder: 'PIN'});
  const verify = el('button', {type: 'button', text: '주문 확인'});
  const link = el('button', {type: 'button', text: '확인한 주문 연결'});
  link.hidden = true;
  const result = el('p', {role: 'status'});
  panel.append(el('p', {text: '토스증권에서 확인한 종료 주문의 API 주문번호를 입력하세요.'}),
    el('div', {class: 'actions'}, number, pin, verify, link), result);
  let verified = null;
  number.addEventListener('input', () => {
    verified = null;
    link.hidden = true;
    result.textContent = '';
  });

  async function submit(action) {
    const id = number.value.trim();
    if (!id || !pin.value || (action === 'link' && verified !== id)) {
      result.textContent = '확인할 주문번호와 PIN을 입력해 주세요.';
      return;
    }
    verify.disabled = link.disabled = number.disabled = pin.disabled = true;
    link.hidden = true;
    try {
      const response = await postJSON('/api/stock/recovery', {
        action, request_id: order.request_id, order_id: id, pin: pin.value
      });
      if (!response.ok) {
        verified = null;
        result.textContent = response.message || '주문을 확인하지 못했어요.';
      } else if (action === 'verify') {
        const o = response.order;
        const status = {filled: '체결 완료', cancelled: '취소', rejected: '거절'}[o.status];
        verified = id;
        result.textContent = [o.ordered_at, o.symbol, side(o.side), o.qty + '주',
          o.price.toLocaleString() + '원', status, '체결 ' + o.filled_qty + '주'].join(' · ');
        link.hidden = false;
      } else {
        verified = null;
        pin.value = '';
        result.textContent = response.message;
        await reload();
      }
    } catch {
      verified = null;
      result.textContent = '주문 확인 요청에 실패했어요. 현재 상태를 새로 확인해 주세요.';
    } finally {
      verify.disabled = link.disabled = number.disabled = pin.disabled = false;
    }
  }
  verify.onclick = () => submit('verify');
  link.onclick = () => submit('link');
}
