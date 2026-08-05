.PHONY: help install db migrate seed verify probe toss toss-dry opening collect collect-us collect-kr collect-dry score serve web alerts alerts-dry vapid clean

help:
	@echo "install      의존성 설치 (python + npm)"
	@echo "db           스키마 적용 (DIVDESK_DSN 필요)"
	@echo "migrate      기존 테이블에 새 컬럼 반영 (open/low 등)"
	@echo "seed         종목 마스터 31종 시딩"
	@echo "verify       검증 4단계 - 커밋 전 필수"
	@echo "probe        국내 엔드포인트 실측 - EC2에서 먼저 실행"
	@echo "collect-dry  미국 수집기 DB 없이 실행"
	@echo "collect      미국+국내 수집 실적재"
	@echo "score        스코어 재계산 (API 기동 상태에서)"
	@echo "serve        API 서버 기동"
	@echo "web          프론트 개발서버"
	@echo "alerts-dry   알람 판정만 (발송 없음)"
	@echo "alerts       알람 발송"
	@echo "vapid        웹푸시 키 생성 (최초 1회)"
	@echo "toss-dry     토스 매수이력 동기화 (저장 안 함)"
	@echo "toss         토스 매수이력 동기화"
	@echo "opening      기초 잔고 보정 (주문이력 이전 보유분)"

install:
	pip install -r requirements.txt
	cd web && npm install

db:
	psql "$$DIVDESK_DSN" -f db/schema.sql

migrate:
	python3 -m db.migrate

seed:
	python3 scripts/seed_master.py

verify:
	@python3 scripts/verify.py

probe:
	python3 -m collector.probe_kr

collect-dry:
	python3 -m collector.run_us --dry-run

collect: collect-us collect-kr

collect-us:
	python3 -m collector.run_us

collect-kr:
	python3 -m collector.run_kr

score:
	curl -s -X POST http://127.0.0.1:8000/scores/recompute

serve:
	uvicorn api.main:app --host 127.0.0.1 --port 8000

web:
	cd web && npm run dev

alerts-dry:
	python3 -m alerts.run_alerts --dry-run

alerts:
	python3 -m alerts.run_alerts

toss-dry:
	python3 -m collector.sync_toss --dry-run

toss:
	python3 -m collector.sync_toss

opening:
	python3 -m collector.opening_balance

vapid:
	python3 -m alerts.push --gen-keys

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
