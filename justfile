python := "packages/server/.venv/bin/python"

default:
    @just --list

# One-time setup: backend venv + frontend packages.
install:
    cd packages/server && uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
    cd packages/web && npm install

# Backend API on :8787 against the real stores on this machine.
serve:
    {{python}} -m agent_chat_viewer.cli --port 8787

# Backend API on :8787 against synthetic data (no coding agent required).
demo:
    {{python}} -m agent_chat_viewer.cli --demo --port 8787

# Vite dev server on :5173, proxying /api to the backend. Run `just demo` too.
web:
    cd packages/web && npm run dev

# Regenerate openapi.json and the TypeScript types derived from it.
types:
    {{python}} scripts/dump_openapi.py packages/web/openapi.json
    cd packages/web && npm run gen:types

# Build the frontend into the Python package so one process serves everything.
build: types
    cd packages/web && npm run build

test:
    {{python}} -m pytest tests -q
    cd packages/web && npm test

lint:
    cd packages/server && ./.venv/bin/ruff check src ../../scripts ../../tests
    cd packages/server && ./.venv/bin/ruff format --check src ../../scripts ../../tests
    cd packages/web && npx tsc -b --noEmit && npx oxlint src

fmt:
    cd packages/server && ./.venv/bin/ruff format src ../../scripts ../../tests
    cd packages/server && ./.venv/bin/ruff check --fix src ../../scripts ../../tests

# Everything CI runs.
check: lint test
    @just types
    git diff --exit-code packages/web/src/api/schema.d.ts

# Inspect the real stores on this machine and verify docs/storage-formats.md.
probe *ARGS:
    {{python}} scripts/probe_stores.py {{ARGS}}

# Write the synthetic stores to fixtures/home for manual poking.
fixtures:
    {{python}} scripts/make_fixtures.py
