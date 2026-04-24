.PHONY: dev test migrate fresh fmt lint typecheck

dev:
	uvicorn derivation_web.api.app:app --reload --port 8080

test:
	pytest -q

migrate:
	alembic upgrade head

fresh:
	docker compose down -v && docker compose up -d db && \
	until docker compose exec -T db pg_isready -U dw >/dev/null 2>&1; do sleep 1; done && \
	alembic upgrade head

fmt:
	ruff check --fix . && ruff format .

lint:
	ruff check .

typecheck:
	mypy derivation_web
