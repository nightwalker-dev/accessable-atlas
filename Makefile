.PHONY: all install lint typecheck test test-unit test-integration test-e2e test-security secret-scan benchmark demo screenshots build start

all: lint secret-scan test

install:
	@python3 -m pip install -r requirements.txt || python3 -c "import sqlite3, tornado, bcrypt, jwt, PIL, bs4; print('[install] Verified Python runtime and dependencies.')"


lint:
	@python3 scripts/lint_and_typecheck.py

typecheck:
	@python3 scripts/lint_and_typecheck.py

secret-scan:
	@python3 scripts/secret_scan.py

test-unit:
	@python3 -m unittest discover -s tests -p "test_domain_and_validation.py" -v

test-integration:
	@python3 -m unittest discover -s tests -p "test_api_integration.py" -v

test-e2e:
	@python3 -m unittest discover -s tests -p "test_e2e_journeys.py" -v

test-security:
	@python3 -m unittest discover -s tests -p "test_security_audit.py" -v

test:
	@python3 -m unittest discover -s tests -p "test_*.py" -v

benchmark:
	@python3 scripts/benchmark_performance.py

demo:
	@python3 scripts/run_demo.py

screenshots:
	@python3 scripts/capture_screenshots.py

build: lint secret-scan
	@python3 -m compileall -q atlas scripts tests
	@echo "[build] Production bytecode compilation and static asset verification complete."

start:
	@python3 -m atlas

