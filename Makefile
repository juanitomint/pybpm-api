IMAGE_REPOSITORY  ?= juanitomint/pybpm-api
CURRENT_DIR = $(shell pwd)
GIT_LAST_TAG=$(shell git tag --sort=committerdate|tail -n 1)
GIT_COMMIT=$(shell git rev-parse --short HEAD)
help:
	@grep -E '^[\/a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
.PHONY: deps
deps:  ## Install dependencies using uv
	uv sync --dev

.PHONY: run
run: ## Run the FastAPI development server locally
	.venv/bin/python -m uvicorn main:app --reload --port 5000

.PHONY: migrate
migrate: ## Run database migrations
	.venv/bin/python -m alembic upgrade head

.PHONY: test
test: ## Run all tests
	.venv/bin/python -m pytest

.PHONY: lint
lint: ## Show code lints using ruff
	uv run --with ruff -- ruff check .

.PHONY: fix
fix: ## Fix code lints using ruff
	uv run --with ruff ruff check --fix .
	uv run --with ruff ruff format ./

.PHONY: openapi
openapi: ## update openapi definitions to doc/api/openapi/openapi.yaml
	mkdir -p doc/api/openapi
	uv run fast-api-cli openapi update

.PHONY: cover
cover: ## Run tests with coverage
	uv run pytest --cov=. --cov-report=html:htmlcov --cov-report=json:.coverage.json --no-header -v tests/

.PHONY: clean
clean: ## Clean up local environment and caches
	rm -rf ./.venv
	rm -rf ./.pytest_cache
	rm -rf ./**/__pycache__
	rm -rf tests/__pycache__
	rm -rf app/__pycache__
	rm -f .coverage
	rm -rf htmlcov

.PHONY: compose-up
compose-up: ## Start Postgres + app (detached, removes orphaned containers from prior runs)
	docker compose --env-file .env up -d --remove-orphans

.PHONY: compose-down
compose-down: ## Stop and remove containers, networks, and orphaned resources
	docker compose down --remove-orphans

.PHONY: compose-run
compose-run: ## Run app interactively via docker-compose (foreground, for development)
	docker compose run --rm --service-ports app

.PHONY: compose-stop
compose-stop: ## Stop running containers but keep them for restart
	docker compose stop

.PHONY: docker-build
docker-build: ## Build docker image using latest as cache
	echo "building: ${IMAGE_REPOSITORY}:${IMAGE_TAG}"
	DOCKER_BUILDKIT=1 docker build -t ${IMAGE_REPOSITORY}:latest . --build-arg IMAGE_TAG=${IMAGE_TAG}
	docker tag ${IMAGE_REPOSITORY}:latest ${IMAGE_REPOSITORY}:${IMAGE_TAG}

.PHONY: docker-push
docker-push: ## Push docker image to remote ${IMAGE_REPOSITORY}
	docker push ${IMAGE_REPOSITORY}:${IMAGE_TAG}
	docker push ${IMAGE_REPOSITORY}:latest

.PHONY: docker-test
docker-test: ## Test using docker image with .env variables
	docker run -it --rm -v ${CURRENT_DIR}:/workspace --env-file .env --net=host ${IMAGE_REPOSITORY}:latest bash

## Run engine test on a model (.venv/bin/python scripts/test_model.py <idwf>)
.PHONY: test-model
test-model: ## Run engine test on a model (MODEL=<idwf> [--post-all-tasks])
	@.venv/bin/python scripts/test_model.py $(MODEL) --no-import
.PHONY: printvars
printvars: ## Prints make variables
	$(foreach V, $(sort $(.VARIABLES)), \
	$(if $(filter-out environment% default automatic, $(origin $V)),$(warning $V=$($V) ($(value $V)))) \
	)
