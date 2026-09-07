PYTHON_SOURCES := dfharness tests tools dfctl dfhack-run

.PHONY: build check dead-code format format-check lint lint-fix lua-check shell-check sync test type-check

sync:
	uv sync --locked

lint:
	uv run --locked ruff check $(PYTHON_SOURCES)

lint-fix:
	uv run --locked ruff check --fix $(PYTHON_SOURCES)

format:
	uv run --locked ruff format $(PYTHON_SOURCES)

format-check:
	uv run --locked ruff format --check $(PYTHON_SOURCES)

dead-code:
	uv run --locked vulture

type-check:
	uv run --locked ty check

lua-check:
	luacheck dfharness tests

shell-check:
	shellcheck df-ascii

test:
	uv run --locked python -m tests.run

build:
	uv build

check: lint format-check type-check dead-code lua-check shell-check test build
