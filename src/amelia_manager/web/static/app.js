(function () {
  const root = document.documentElement;
  const savedTheme = localStorage.getItem('amelia-theme');
  if (savedTheme) root.setAttribute('data-theme', savedTheme);

  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      localStorage.setItem('amelia-theme', next);
    });
  }

  const chat = document.getElementById('chat-feed');
  if (chat) chat.scrollTop = chat.scrollHeight;

  document.querySelectorAll('[data-catalog-card]').forEach(function (card) {
    const id = card.getAttribute('data-item-id');
    const quantityInput = card.querySelector('[data-catalog-quantity]');
    const quantityLabel = card.querySelector('[data-quantity]');
    const setBusy = function (busy) { card.setAttribute('aria-busy', busy ? 'true' : 'false'); };
    const applyItem = function (item) {
      if (quantityInput) quantityInput.value = item.quantity_number ?? '';
      if (quantityLabel) quantityLabel.textContent = item.quantity_text || '';
      card.classList.remove('status-available', 'status-low', 'status-unavailable');
      card.classList.add('status-' + item.status);
    };
    const send = async function (payload) {
      const previous = quantityInput ? quantityInput.value : '';
      setBusy(true);
      try {
        const res = await fetch('/catalog/items/' + id + '/quick', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('save failed');
        const data = await res.json();
        applyItem(data.item);
        card.dataset.saved = 'Сохранено';
      } catch (err) {
        if (quantityInput) quantityInput.value = previous;
        card.dataset.saved = 'Ошибка сохранения';
      } finally {
        setBusy(false);
      }
    };
    card.querySelectorAll('[data-catalog-action]').forEach(function (button) {
      button.addEventListener('click', function () { send({action: button.dataset.catalogAction}); });
    });
    if (quantityInput) {
      quantityInput.addEventListener('change', function () { send({quantity_number: quantityInput.value}); });
    }
  });
})();
