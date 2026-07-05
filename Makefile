# CANOPY — no dependencies required for the core. Python 3.9+ stdlib only.

PY ?= python3

.PHONY: help demo serve test report json db-up db-down clean

help:
	@echo "CANOPY targets:"
	@echo "  make demo    end-to-end run, print the after-action report"
	@echo "  make serve   run the demo and start the live UI at :8787"
	@echo "  make report  same as demo"
	@echo "  make json    dump the full after-action report as JSON"
	@echo "  make test    run the kill-criteria + parity test suite"
	@echo "  make db-up   start Postgres+PostGIS+TimescaleDB (docker compose)"
	@echo "  make db-down stop the database"

demo report:
	$(PY) scripts/demo.py

serve:
	$(PY) scripts/demo.py --serve

json:
	$(PY) scripts/demo.py --json

test:
	$(PY) -m unittest discover -s tests -p "test_*.py" -v

db-up:
	docker compose up -d

db-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
