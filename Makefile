# Why a Makefile: one memorable entrypoint instead of remembering flag
# combinations for pytest/ruff/uvicorn across however many tools get added
# over the project's life. `make test` never changes even if the underlying
# command does.

.PHONY: install test lint format run docker-up docker-down

install:
	pip install -r backend/requirements.txt -r backend/requirements-dev.txt

test:
	cd backend && python -m pytest -v

lint:
	cd backend && ruff check . && mypy app

format:
	cd backend && black . && ruff check --fix .

run:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

docker-up:
	docker compose up --build

docker-down:
	docker compose down
