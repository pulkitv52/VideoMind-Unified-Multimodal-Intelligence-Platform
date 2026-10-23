.PHONY: help setup start up stop down restart restart-frontend status ps logs verify test-frontend build-frontend

COMPOSE_FILE := infra/compose/compose.yaml
ENV_FILE := .env

help:
	@echo "VideoMind Service Management"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  start             Start all services (builds and runs background containers)"
	@echo "  stop              Stop all running services (preserves data volumes)"
	@echo "  restart           Restart all services"
	@echo "  restart-frontend  Rebuild and restart the frontend service"
	@echo "  status            Show status of all running containers"
	@echo "  logs              Tail logs across all containers"
	@echo "  setup             Generate .env and local tokens if not present"
	@echo "  verify            Run stack verification suite"
	@echo "  build-frontend    Build production frontend bundle"
	@echo "  test-frontend     Run Playwright frontend end-to-end test suite"

setup:
	python3 scripts/dev.py setup

start:
	python3 scripts/dev.py up

up: start

stop:
	python3 scripts/dev.py down

down: stop

restart:
	python3 scripts/dev.py down
	python3 scripts/dev.py up

restart-frontend:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) up -d --build frontend

status:
	python3 scripts/dev.py status

ps: status

logs:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) logs -f

verify:
	python3 scripts/dev.py verify

build-frontend:
	pnpm --dir frontend build

test-frontend:
	pnpm --dir frontend test:ui
