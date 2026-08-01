"""국내 소스 실측 스크립트 — EC2에서 실행.

쓰는 이유: 비공식 엔드포인트라 '문서'가 없다. 지금 살아있는지, 응답 키 이름이 뭔지는
직접 때려봐야만 안다. 결과를 보고 naver_kr.py 의 파서 필드명을 확정한다.

실행:  cd ~/divdesk && python -m collector.probe_kr
출력:  각 후보의 상태코드 / 응답 앞부분 / 최상위 키 목록
"""
from __future__ import annotations

import json
import time

import requests

from .sources.naver_kr import CANDIDATES, HDR
from .sources.base import UA

SAMPLE = "458730"      # TIGER 미국배당다우존스
TODAY = time.strftime("%Y%m%d")
START = time.strftime("%Y%m%d", time.localtime(time.time() - 60 * 86400))


def show(label: str, url: str) -> None:
    try:
        resp = requests.get(url, headers={"User-Agent": UA, **HDR}, timeout=12)
    except Exception as exc:                      # noqa: BLE001
        print(f"[ERR ] {label:12} {type(exc).__name__}: {exc}")
        return

    head = resp.text[:220].replace("\n", " ")
    print(f"[{resp.status_code:>4}] {label:12} {head}")

    if resp.status_code == 200:
        try:
            body = resp.json()
        except json.JSONDecodeError:
            print(f"        └ JSON 아님 (HTML/JSONP 가능) len={len(resp.text)}")
            return
        if isinstance(body, dict):
            print(f"        └ keys: {list(body.keys())[:20]}")
        elif isinstance(body, list) and body:
            first = body[0]
            keys = list(first.keys())[:20] if isinstance(first, dict) else type(first).__name__
            print(f"        └ list[{len(body)}] first keys: {keys}")
    time.sleep(1.5)                                # 예절: 요청 간 간격


def main() -> None:
    print(f"=== 국내 소스 실측 {time.strftime('%Y-%m-%d %H:%M')} / 샘플 {SAMPLE} ===")
    for label, template in CANDIDATES.items():
        show(label, template.format(code=SAMPLE, start=START, end=TODAY))
    print("\n다음 할 일: 200 나온 후보의 keys 를 보고 naver_kr.py 파서 필드명 확정 → verified=True")


if __name__ == "__main__":
    main()
