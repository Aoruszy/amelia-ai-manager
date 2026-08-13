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
})();
