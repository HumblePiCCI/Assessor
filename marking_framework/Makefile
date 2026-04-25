# Makefile for Hero Path Grading Platform
# Quick commands for common development tasks

.PHONY: test coverage lint clean help install verify report stats

# Default target
help:
	@echo "Hero Path Grading Platform - Development Commands"
	@echo ""
	@echo "Available targets:"
	@echo "  make test         - Run full test suite (quick)"
	@echo "  make coverage     - Run tests with detailed coverage report (report-only)"
	@echo "  make lint         - Run code quality checks"
	@echo "  make clean        - Remove cache and temp files"
	@echo "  make install      - Install dependencies"
	@echo "  make verify       - Run tests and coverage report"
	@echo "  make report       - Generate compliance report"
	@echo ""

# Run tests quickly
test:
	@echo "Running test suite..."
	@python3 -m pytest -q

# Run tests with coverage report
coverage:
	@echo "Running tests with coverage..."
	@python3 -m pytest --cov=scripts --cov=server --cov-branch --cov-report=term-missing --no-cov-on-fail

# Verify current project gates without overstating legacy compliance policy
verify:
	@echo "Verifying compliance requirements..."
	@echo ""
	@echo "1. Reporting legacy LOC metric (non-gating):"
	@wc -l scripts/aggregate_assessments.py | awk '{print "   aggregate_assessments.py LOC:", $$1}'
	@echo ""
	@echo "2. Running full test suite:"
	@python3 -m pytest -q
	@echo ""
	@echo "3. Generating coverage report:"
	@python3 -m pytest --cov=scripts --cov=server --cov-branch --cov-report=term-missing --no-cov-on-fail
	@echo ""
	@echo "4. Compliance status:"
	@echo "   PASS: current explicit gates completed"

# Generate compliance report
report:
	@echo "Compliance Report: docs/COMPLIANCE_REPORT.md"
	@echo "Last updated: $$(date +"%Y-%m-%d %H:%M:%S")"

# Lint code
lint:
	@echo "Running linters..."
	@. ../.venv/bin/activate && python -m flake8 scripts/ server/ tests/ --max-line-length=120 --extend-ignore=E203,W503 || true
	@echo "Note: Install flake8 for full linting (pip install flake8)"

# Clean cache files
clean:
	@echo "Cleaning cache files..."
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cache cleaned"

# Install dependencies
install:
	@echo "Installing dependencies..."
	@. ../.venv/bin/activate && pip install -r server/requirements.txt
	@. ../.venv/bin/activate && pip install pytest pytest-cov
	@echo "Dependencies installed"

# Quick stats
stats:
	@echo "Codebase Statistics:"
	@echo "  Script files:  $$(find scripts -name '*.py' ! -name '__*' | wc -l | tr -d ' ')"
	@echo "  Test files:    $$(find tests -name 'test_*.py' | wc -l | tr -d ' ')"
	@echo "  Total LOC:     $$(find scripts -name '*.py' ! -name '__*' -exec cat {} + | wc -l | tr -d ' ')"
	@echo "  Test LOC:      $$(find tests -name 'test_*.py' -exec cat {} + | wc -l | tr -d ' ')"
