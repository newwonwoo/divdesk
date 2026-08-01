"""웹푸시 알림.

왜 직접 구현하나: 무료로 돌리기 위해서다. 푸시 서비스(FCM/APNs 게이트웨이)는
브라우저가 알아서 붙고, 서버는 VAPID 키로 서명한 요청만 보내면 된다.

iOS 주의: 사파리는 **홈 화면에 추가한 PWA에서만** 푸시를 받는다.
브라우저 탭 상태로는 구독 자체가 안 만들어지므로, 프론트에서 그 상황을
감지해 안내해야 한다(web/src/push.js).

키 생성 (최초 1회):
    python -m alerts.push --gen-keys
    → 출력된 값을 .env 의 VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY 에 넣는다.
"""
from __future__ import annotations

import json
import os
import sys


def keys_present() -> bool:
    return bool(os.environ.get("VAPID_PUBLIC_KEY") and os.environ.get("VAPID_PRIVATE_KEY"))


def public_key() -> str | None:
    return os.environ.get("VAPID_PUBLIC_KEY")


def generate_keys() -> tuple[str, str]:
    """VAPID 키쌍 생성. py_vapid 가 있어야 한다."""
    from py_vapid import Vapid01
    import base64

    vapid = Vapid01()
    vapid.generate_keys()
    priv = base64.urlsafe_b64encode(
        vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    ).decode().rstrip("=")
    pub = base64.urlsafe_b64encode(
        vapid.public_key.public_bytes(
            encoding=__import__("cryptography.hazmat.primitives.serialization",
                                fromlist=["Encoding"]).Encoding.X962,
            format=__import__("cryptography.hazmat.primitives.serialization",
                              fromlist=["PublicFormat"]).PublicFormat.UncompressedPoint,
        )
    ).decode().rstrip("=")
    return pub, priv


def send(subscription: dict, title: str, body: str,
         url: str = "/", tag: str | None = None) -> tuple[bool, str]:
    """구독 하나에 알림을 보낸다. (성공여부, 사유) 를 돌려준다.

    실패를 예외로 던지지 않는 이유: 구독은 사용자가 앱을 지우면 조용히 죽는다.
    한 구독이 죽었다고 배치 전체가 멈추면 안 된다. 410/404 면 만료된 구독이므로
    호출한 쪽에서 지우면 된다.
    """
    if not keys_present():
        return False, "VAPID 키가 설정되지 않았습니다"
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return False, "pywebpush 가 설치되지 않았습니다"

    payload = json.dumps({"title": title, "body": body, "url": url,
                          "tag": tag or "divdesk"}, ensure_ascii=False)
    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")},
            timeout=10,
        )
        return True, "ok"
    except WebPushException as exc:                           # noqa: BLE001
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return False, "expired"
        return False, f"push_failed:{status}"
    except Exception as exc:                                  # noqa: BLE001
        return False, f"{type(exc).__name__}"


def main() -> int:
    if "--gen-keys" in sys.argv:
        try:
            pub, priv = generate_keys()
        except ImportError:
            print("py_vapid 가 필요합니다: pip install py-vapid pywebpush")
            return 1
        print("아래 두 줄을 .env 에 넣으세요 (권한 600 유지):\n")
        print(f"VAPID_PUBLIC_KEY={pub}")
        print(f"VAPID_PRIVATE_KEY={priv}")
        print("VAPID_SUBJECT=mailto:본인메일주소")
        return 0
    print(f"VAPID 키 설정됨: {keys_present()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
