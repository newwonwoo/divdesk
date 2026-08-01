// 웹푸시 구독 관리.
//
// iOS 주의: 사파리는 홈 화면에 추가한 PWA에서만 푸시를 받는다.
// 브라우저 탭에서는 Notification.requestPermission 자체가 없거나 구독이 실패한다.
// 그래서 상태를 구분해 돌려주고, 화면에서 그에 맞는 안내를 띄운다.

const api = (p, o) => fetch((import.meta.env.VITE_API_BASE || '/api') + p, o)

export function pushStatus() {
  const standalone =
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent)

  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return iOS && !standalone
      ? { ok: false, reason: 'ios-needs-install',
          message: '아이폰은 홈 화면에 추가한 뒤에야 알림을 받을 수 있습니다. 공유 → 홈 화면에 추가를 눌러주세요.' }
      : { ok: false, reason: 'unsupported', message: '이 브라우저는 웹 알림을 지원하지 않습니다.' }
  }
  if (Notification.permission === 'denied') {
    return { ok: false, reason: 'denied',
             message: '알림이 차단돼 있습니다. 브라우저 설정에서 이 사이트의 알림을 허용해주세요.' }
  }
  return { ok: true, granted: Notification.permission === 'granted', standalone }
}

function toUint8(base64) {
  const padded = (base64 + '='.repeat((4 - base64.length % 4) % 4))
    .replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)))
}

export async function enablePush() {
  const status = pushStatus()
  if (!status.ok) throw new Error(status.message)

  const keyRes = await api('/push/key').then(r => r.json())
  if (!keyRes.enabled || !keyRes.public_key) {
    throw new Error('서버에 알림 키가 설정되지 않았습니다. VAPID 키를 먼저 만들어주세요.')
  }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('알림 권한이 허용되지 않았습니다.')

  const reg = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready

  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: toUint8(keyRes.public_key),
    })
  }

  const res = await api('/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sub.toJSON()),
  })
  if (!res.ok) throw new Error('구독 등록에 실패했습니다.')
  return true
}

export async function disablePush() {
  const reg = await navigator.serviceWorker.getRegistration()
  const sub = await reg?.pushManager.getSubscription()
  if (sub) {
    await api('/push/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sub.toJSON()),
    })
    await sub.unsubscribe()
  }
  return true
}

export async function isSubscribed() {
  if (!('serviceWorker' in navigator)) return false
  const reg = await navigator.serviceWorker.getRegistration()
  return !!(await reg?.pushManager.getSubscription())
}
