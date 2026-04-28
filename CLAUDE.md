# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repository hosts **portbroker**, a single-developer, localhost-only Python 3 HTTP daemon that assigns unique host ports to Docker Compose projects and worktrees. The daemon, its CLI (`portctl`), and the OpenAPI doc generator (`gendocs.py`) are the entire product surface — there is no application framework, no build step, and no third-party runtime dependencies (Python 3 stdlib only).

`docs/AGENTS.md` is **not** instructions for working on this repo. It is the integration guide for *consumers* — agents working in **other** project repos that need to call portbroker. When editing this repo, treat `docs/AGENTS.md` as a contract: any change to request/response shapes, status codes, or endpoint paths must be reflected in `docs/AGENTS.md` and `portbroker/gendocs.py` together.

## Critical invariants

These are load-bearing assumptions in `docs/security/risk-analysis.md`. Do not change without re-reading that doc:

- **The daemon binds to `127.0.0.1` only.** Never `0.0.0.0`. The unauthenticated API and lack of CSRF protection on the web UI are only acceptable under strict localhost binding.
- **Port 9876 is reserved for portbroker itself** via `Registry.bootstrap()`, which writes a `portbroker:system` entry on first start. That entry is protected from deregistration (returns 403). Don't add code that bypasses the protection.
- **`ports.json` is never hand-edited.** It is written exclusively by `Registry._write()` under `self.lock`. Tests use `tempfile.mkdtemp()` registries — do not point tests at the real registry.

## Architecture

`portbroker/server.py` is the whole daemon in one file:

- **`Registry`** owns `ports.json` and is the only thing that mutates it. All public methods take `self.lock`. Port allocation in `_next_available()` walks upward from the service's preferred port (from `SERVICE_DEFAULTS`) skipping anything already in the registry *or* currently bound on the host (probed via `ss -tlnp` in `_system_ports()`). Unknown service names fall back to port 9000.
- **`_make_handler(registry, openapi_path)`** is a closure factory that returns a `BaseHTTPRequestHandler` subclass with the registry baked in. This is how tests inject a temp registry without globals.
- **`run_server(..., block=False)`** runs the server on a daemon thread and returns the `HTTPServer` so tests can call `.shutdown()` in `tearDownClass`. Tests use `block=False` and a unique high port per test class (19876–19882) to allow parallel-ish setup.
- **HTML is inlined.** `_build_ui_html()` (admin UI at `/`) and `_build_docs_html()` (Redoc viewer at `/docs`) return string literals. Redoc loads from a CDN and reads `/openapi.yaml` from the daemon, which serves the file from disk.

### OpenAPI is code, not a hand-edited file

`portbroker/openapi.yaml` is **generated** from a string literal in `portbroker/gendocs.py` (run via `portctl gendocs`). When you change an endpoint's contract:

1. Update the handler in `server.py`.
2. Update the `OPENAPI_YAML` string in `gendocs.py`.
3. Re-run `portctl gendocs` to regenerate `openapi.yaml`.
4. Update `docs/AGENTS.md` if the change is consumer-visible.
5. `tests/test_gendocs.py` asserts that all current endpoint paths and schema names appear in the generated YAML — extend it when adding paths/schemas.

### Ephemeral vs permanent assignments

The `ephemeral` flag does **not** cause automatic cleanup. It is a label that:
- Distinguishes worktree/test registrations from permanent project registrations in the UI and `portctl list`.
- Determines what `POST /cleanup` (and `portctl cleanup`) sweeps.

Callers are responsible for `DELETE /deregister`. The cleanup endpoint exists for crash recovery, not normal teardown.

## Running and testing

```bash
# Run the daemon (foreground)
python3 portbroker/server.py

# Run the daemon (background, with auto-start install on shell login or systemd)
bash portbroker/start.sh

# Run all tests
python3 -m unittest discover -s tests -v

# Run a single test file / class / method
python3 -m unittest tests.test_registry -v
python3 -m unittest tests.test_api.TestAPIRegister -v
python3 -m unittest tests.test_api.TestAPIRegister.test_register_conflict_returns_409 -v

# Regenerate openapi.yaml after editing gendocs.py
portbroker/portctl gendocs
# or
python3 portbroker/gendocs.py

# CLI shortcuts (require daemon running)
portbroker/portctl status
portbroker/portctl list
portbroker/portctl register myproj --worktree feat-x --ephemeral nginx postgres
portbroker/portctl deregister myproj feat-x
portbroker/portctl cleanup
```

Tests are stdlib `unittest` only — no pytest, no test runner config. They start real `HTTPServer` instances on `127.0.0.1` and talk to them via `urllib.request`. `TestRegistryRegister` and `TestRegistryDeregister` patch `Registry._system_ports` to return an empty set so port assertions are deterministic; do the same in any new test that asserts on specific port numbers.
