.PHONY: install dev lint typecheck test check run docker deploy clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

format:
	ruff format src tests scripts
	ruff check --fix src tests scripts

typecheck:
	mypy

test:
	pytest

check: lint typecheck test

run:
	uvicorn ticket_router.main:app --reload --port 8000

docker:
	docker build -t ticket-router:local .

deploy:
	gcloud run deploy ticket-router --source . --region us-central1

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache **/__pycache__ *.egg-info build dist
