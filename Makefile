# Makefile untuk IDX Screener
# Jalankan `make help` untuk melihat perintah tersedia

.PHONY: help setup run dashboard test clean docker-build docker-run docker-up schedule

PYTHON := python3
VENV := .venv

help:
	@echo "Perintah tersedia:"
	@echo "  make setup       - Setup virtualenv dan install dependencies"
	@echo "  make run         - Jalankan screener sekali"
	@echo "  make run-loose   - Jalankan screener dengan preset loose"
	@echo "  make dashboard   - Jalankan dashboard web"
	@echo "  make schedule    - Install systemd timer / cron job"
	@echo "  make health      - Jalankan health check"
	@echo "  make test        - Test pengiriman Telegram"
	@echo "  make docker-up   - Jalankan semua service dengan Docker Compose"
	@echo "  make docker-down - Hentikan service Docker"
	@echo "  make clean       - Hapus virtualenv, log, dan database"

setup:
	@echo "🚀 Setup environment..."
	@bash setup.sh

run:
	$(VENV)/bin/python run.py

run-loose:
	$(VENV)/bin/python run.py

run-strict:
	$(VENV)/bin/python run.py

dashboard:
	$(VENV)/bin/python dashboard.py

schedule:
	@bash setup_cron.sh

health:
	$(VENV)/bin/python health_check.py

test:
	$(VENV)/bin/python test_telegram.py

docker-build:
	docker build -t idx-screener .

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down

clean:
	@echo "🧹 Membersihkan environment..."
	@rm -rf .venv __pycache__ *.pyc *.pyo *.egg-info dist build
	@rm -f screener.log fallback_notifications.log
	@echo "⚠️  screener_history.db tidak dihapus. Hapus manual jika perlu."
