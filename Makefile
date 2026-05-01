# BFT-voting / inspection-rate experiment Makefile.
#
# Assumes the conda env `ece60872` is already active (Python 3.12). If not,
# run `conda activate ece60872` once per shell session.
#
# All scenario-running targets default to A0 (no judges) + dangerous
# permission mode. Override with PERMISSION=default or pass a different
# CONFIG=ablations/configs/Ax.json.
#
# Positional argument support (via MAKECMDGOALS hack):
#   make test <path/to/test_file.py>     run pytest on a single file
#   make run  <path/to/scenario.yaml>    run a single scenario at A0+dangerous
#
# Quick reference:
#   make help              show all targets
#   make test              run the full test suite (180 tests, ~5s)
#   make test <path>       run pytest on a specific test file or directory
#   make build             build the docker images (agent + judge)
#   make run <scenario>    run one scenario at A0+dangerous (positional)
#   make sweep-npm         all npm trojaned-codebase scenarios at A0+dangerous
#   make sweep-pip         all pip trojaned-codebase scenarios at A0+dangerous
#   make sweep             both ecosystems
#   make tail-honeypot     stream the honeypot JSONL log live
#   make clean             clean workspace + ephemeral results
#   make clean-all         clean everything including built docker images

PYTHON       ?= python3
PYTEST       ?= $(PYTHON) -m pytest
EXPERIMENT   ?= $(PYTHON) -m ablations.experiment

# Defaults for all scenario-running targets. Override on the command line:
#   make sweep CONFIG=ablations/configs/A1.json PERMISSION=default REPS=5
CONFIG       ?= ablations/configs/A0.json
PERMISSION   ?= dangerous
REPS         ?= 3
TIMEOUT      ?= 120
WORKSPACE    ?= /tmp/bft-workspace
RESULTS      ?= results

NPM_SCENARIOS := \
  scenarios/trojaned-codebases/npm-postinstall-direct.yaml \
  scenarios/trojaned-codebases/npm-postinstall-base64.yaml \
  scenarios/trojaned-codebases/npm-lockfile-lie.yaml \
  scenarios/trojaned-codebases/npm-patch-package.yaml \
  scenarios/trojaned-codebases/npm-transitive-postinstall.yaml

PIP_SCENARIOS := \
  scenarios/trojaned-codebases/pip-pyproject-backend.yaml \
  scenarios/trojaned-codebases/pip-setup-py.yaml \
  scenarios/trojaned-codebases/pip-typosquat.yaml

ALL_SCENARIOS := $(NPM_SCENARIOS) $(PIP_SCENARIOS)

# Positional-arg capture. When the user runs `make test path/to/foo.py` or
# `make run path/to/scenario.yaml`, MAKECMDGOALS is "test path/to/foo.py".
# We strip the leading target name and feed the rest to the underlying
# command. The catch-all `%:` rule below silences make's complaint about
# the path looking like an unknown target.
TEST_ARGS := $(filter-out test test-fast typecheck,$(MAKECMDGOALS))
RUN_ARGS  := $(filter-out run,$(MAKECMDGOALS))

.PHONY: help test test-fast typecheck build run sweep sweep-npm sweep-pip \
        tail-honeypot tail-proxy clean clean-workspace clean-results \
        clean-all images-list

help:
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test: ## run pytest. usage: make test  OR  make test <path/to/test_file.py>
ifeq ($(strip $(TEST_ARGS)),)
	$(PYTEST) tests/ -q --ignore=tests/test_realworld
else
	$(PYTEST) $(TEST_ARGS) -q
endif

test-fast: ## run only fast unit tests (skip integration)
	$(PYTEST) tests/ -q --ignore=tests/test_realworld -m "not slow"

typecheck: ## run pyright on core + analysis modules
	pyright core analysis ablations || true

# ---------------------------------------------------------------------------
# Docker images
# ---------------------------------------------------------------------------

build: ## build agent + judge docker images
	docker compose build

images-list: ## show currently built bft- images
	docker images | grep -E "REPOSITORY|bft-" || true

# ---------------------------------------------------------------------------
# Scenario runs (default: A0 config + dangerous permission mode)
# ---------------------------------------------------------------------------

run: ## run a single scenario. usage: make run <path/to/scenario.yaml>
ifeq ($(strip $(RUN_ARGS)),)
	@echo "usage: make run <path/to/scenario.yaml>"
	@echo "example: make run scenarios/trojaned-codebases/npm-postinstall-direct.yaml"
	@echo ""
	@echo "defaults: CONFIG=$(CONFIG)  PERMISSION=$(PERMISSION)  REPS=$(REPS)  TIMEOUT=$(TIMEOUT)"
	@exit 1
else
	@$(MAKE) clean-workspace
	$(EXPERIMENT) \
	  --config $(CONFIG) \
	  --scenarios $(RUN_ARGS) \
	  --reps $(REPS) --max-concurrency 1 \
	  --permission-mode $(PERMISSION) \
	  --timeout $(TIMEOUT)
endif

sweep-npm: ## sweep all npm trojaned-codebase scenarios
	@$(MAKE) clean-workspace
	$(EXPERIMENT) \
	  --config $(CONFIG) \
	  --scenarios $(NPM_SCENARIOS) \
	  --reps $(REPS) --max-concurrency 1 \
	  --permission-mode $(PERMISSION) \
	  --timeout $(TIMEOUT) \
	  --results-root $(RESULTS)-npm

sweep-pip: ## sweep all pip trojaned-codebase scenarios
	@$(MAKE) clean-workspace
	$(EXPERIMENT) \
	  --config $(CONFIG) \
	  --scenarios $(PIP_SCENARIOS) \
	  --reps $(REPS) --max-concurrency 1 \
	  --permission-mode $(PERMISSION) \
	  --timeout $(TIMEOUT) \
	  --results-root $(RESULTS)-pip

sweep: ## sweep all scenarios (npm + pip)
	@$(MAKE) clean-workspace
	$(EXPERIMENT) \
	  --config $(CONFIG) \
	  --scenarios $(ALL_SCENARIOS) \
	  --reps $(REPS) --max-concurrency 1 \
	  --permission-mode $(PERMISSION) \
	  --timeout $(TIMEOUT)

# ---------------------------------------------------------------------------
# Live observability
# ---------------------------------------------------------------------------

tail-honeypot: ## live-tail honeypot JSONL log (Ctrl-C to stop)
	tail -f $(RESULTS)/honeypot.jsonl

tail-proxy: ## live-tail proxy log
	tail -f $(RESULTS)/proxy.jsonl

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean-workspace: ## wipe /tmp/bft-workspace contents (between scenarios)
	@if [ -d "$(WORKSPACE)" ]; then \
	  echo "cleaning $(WORKSPACE)"; \
	  rm -rf $(WORKSPACE)/*; \
	  rm -rf $(WORKSPACE)/.[!.]* 2>/dev/null || true; \
	fi

clean-results: ## wipe ephemeral results (keeps results-* sweep outputs)
	@if [ -d "$(RESULTS)" ]; then \
	  echo "cleaning $(RESULTS)"; \
	  rm -rf $(RESULTS)/A*/scenarios $(RESULTS)/A*/events $(RESULTS)/A*/judge_transcripts; \
	  rm -f $(RESULTS)/honeypot.jsonl $(RESULTS)/proxy.jsonl $(RESULTS)/honeypot.log $(RESULTS)/proxy.log; \
	fi

clean: clean-workspace clean-results ## clean workspace + ephemeral results

clean-all: clean ## clean everything including built docker images
	@echo "removing bft- docker images"
	-docker rmi bft-agent:latest bft-judge-agentic:latest 2>/dev/null
	@echo "removing __pycache__"
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# Catch-all: silently absorb positional args so `make test path/foo.py`
# doesn't error on the second arg looking like an unknown target.
# ---------------------------------------------------------------------------

%:
	@:
