/* Кабинет FPL: пуш-уведомления (17.10). Только показ уведомления и переход по нажатию — без кеширования страниц. */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('push', function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { body: e.data ? e.data.text() : '' }; }
  var base = self.registration.scope;
  e.waitUntil(self.registration.showNotification(d.title || 'Face Painting League', {
    body: d.body || '', tag: d.tag || undefined, data: { url: d.url || base },
    icon: base + 'assets/icon-192.png', badge: base + 'assets/icon-192.png', lang: 'ru'
  }));
});
self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || self.registration.scope;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].url.indexOf(self.registration.scope) === 0 && 'focus' in list[i]) { list[i].navigate(url); return list[i].focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
