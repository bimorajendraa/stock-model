.PHONY: install up down migrate migrate-new test test-integration lint fmt

install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

up:
	docker compose up -d db

down:
	docker compose down

migrate:
	.venv/bin/alembic upgrade head

migrate-new:
	.venv/bin/alembic revision --autogenerate -m "$(m)"

test:
	.venv/bin/pytest -v

test-integration:
	.venv/bin/pytest -v -m integration

lint:
	.venv/bin/ruff check src apps

fmt:
	.venv/bin/ruff format src apps
