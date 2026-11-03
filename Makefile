.PHONY: install run doctor chat workflows test clean

VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip

install:
	./install.sh

run:
	$(PYTHON) -m agent_otonom serve

doctor:
	$(PYTHON) -m agent_otonom doctor

workflows:
	$(PYTHON) -m agent_otonom workflows

chat:
	@test -n "$(MSG)" || (echo 'Usage: make chat MSG="buat film sinematik tentang laut"'; exit 1)
	$(PYTHON) -m agent_otonom chat $(MSG)

clean:
	rm -rf .venv dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
