// DivDesk 서비스 워커 — 웹푸시 수신 전용.
// 오프라인 캐싱은 하지 않는다. 배당 데이터는 오래된 값을 보여주면 안 되므로
// 캐시된 숫자를 띄우느니 못 불러왔다고 말하는 편이 낫다.

self.addEventListener('install', (e) => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = { title: 'DivDesk', body: '새 알림', url: '/', tag: 'divdesk' }
  try { if (event.data) data = { ...data, ...event.data.json() } } catch { /* 평문 */ }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: data.tag,
      data: { url: data.url },
      badge: '/icon-badge.png',
      icon: '/icon-192.png',
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = event.notification.data?.url || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) { client.navigate(target); return client.focus() }
      }
      return self.clients.openWindow(target)
    })
  )
})
