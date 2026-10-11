/* FPL: работа с клавиатуры и экранными дикторами.
   Мобильное меню: при открытии фокус переходит в меню и не уходит за него по Tab,
   Escape закрывает меню (это делает скрипт страницы), после закрытия фокус возвращается на кнопку меню. */
(function () {
  var menu = document.getElementById('mmenu');
  if (!menu) return;
  var EN = (document.documentElement.lang || 'ru').slice(0, 2) === 'en';
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-modal', 'true');
  if (!menu.getAttribute('aria-label')) menu.setAttribute('aria-label', EN ? 'Site menu' : 'Меню сайта');
  var opener = null;
  function focusables() {
    return [].slice.call(menu.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'))
      .filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
  }
  function onOpen() {
    opener = document.activeElement && !menu.contains(document.activeElement) ? document.activeElement : null;
    var f = focusables();
    if (f.length) setTimeout(function () { f[0].focus(); }, 0);
  }
  function onClose() {
    var inside = menu.contains(document.activeElement) || document.activeElement === document.body;
    if (inside) {
      var back = opener && document.contains(opener) ? opener : document.querySelector('[data-menu-open]');
      if (back && back.focus) back.focus();
    }
    opener = null;
  }
  new MutationObserver(function () { if (menu.hidden) onClose(); else onOpen(); })
    .observe(menu, { attributes: true, attributeFilter: ['hidden'] });
  // Tab не выходит из открытого меню
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab' || menu.hidden) return;
    var f = focusables();
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (!menu.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
})();
