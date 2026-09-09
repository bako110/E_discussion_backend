# ── E-discussion backend ─────────────────────────────────────────────────────
.PHONY: help install dev up down migrate revision test lint fmt

help:
	@echo "install   installer les dependances"
	@echo "up        lancer db + redis + api (docker compose)"
	@echo "down      arreter la stack"
	@echo "dev       lancer l'api en local (uvicorn --reload)"
	@echo "migrate   appliquer les migrations"
	@echo "revision  m='msg' : autogenerer une migration"
	@echo "test      lancer pytest"
	@echo "lint      ruff check"
	@echo "fmt       ruff format + fix"

install:
	pip install -r requirements.txt

up:
	docker compose up --build

down:
	docker compose down

dev:
	uvicorn app.main:app --reload --port 8000

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

test:
	pytest -q

lint:
	ruff check .

fmt:
	ruff check --fix . && ruff format .
