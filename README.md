# portbroker

A tiny, single-developer, localhost-only HTTP daemon that hands out unique host
ports to Docker Compose projects and worktrees so multiple projects can run at
the same time without colliding on `5432`, `8080`, `6379`, and friends.

- **Runtime:** Python 3, standard library only — no dependencies.
- **Storage:** a single `ports.json` file next to the daemon.
- **Surface:** REST API on `http://localhost:9876`, a `portctl` shell client, and a Redoc-rendered API browser at `/docs`.

> portbroker is a personal-use tool. It binds to `127.0.0.1` only and has no
> authentication. See [`docs/security/risk-analysis.md`](docs/security/risk-analysis.md)
> before changing any of that.

## Install / run

```bash
# Run in the foreground
python3 portbroker/server.py

# Or install auto-start (systemd user unit if available, otherwise a .zshrc guard)
bash portbroker/start.sh

# Confirm it's up
curl -s http://localhost:9876/health
# {"status": "ok", "port": 9876}
```

The first run creates `portbroker/ports.json` and writes a permanent
`portbroker:system` entry that reserves port 9876 for the daemon itself.

## Using it

### CLI (`portctl`)

```bash
portbroker/portctl status
portbroker/portctl list
portbroker/portctl register myproj nginx postgres
portbroker/portctl register myproj --worktree feat-x --ephemeral nginx postgres
portbroker/portctl get myproj feat-x
portbroker/portctl deregister myproj feat-x
portbroker/portctl cleanup        # remove all ephemeral entries
portbroker/portctl gendocs        # regenerate openapi.yaml
```

### REST

```bash
# Register a project (permanent, defaults to worktree=main)
curl -s -X POST http://localhost:9876/register \
  -H 'Content-Type: application/json' \
  -d '{"project": "myproj", "services": ["nginx", "postgres"]}'

# Register an ephemeral worktree
curl -s -X POST http://localhost:9876/register \
  -H 'Content-Type: application/json' \
  -d '{"project": "myproj", "worktree": "feat-x", "ephemeral": true, "services": ["nginx"]}'

# Look up assignments
curl -s http://localhost:9876/assignments
curl -s http://localhost:9876/assignments/myproj
curl -s http://localhost:9876/assignments/myproj/feat-x

# Release a worktree
curl -s -X DELETE http://localhost:9876/deregister \
  -H 'Content-Type: application/json' \
  -d '{"project": "myproj", "worktree": "feat-x"}'

# Sweep all ephemeral entries (e.g. after a crash)
curl -s -X POST http://localhost:9876/cleanup
```

A 409 from `/register` means `project:worktree` is already registered — fetch
the existing assignment with `GET /assignments/{project}/{worktree}` instead of
re-registering.

### Browser

- `http://localhost:9876/` — admin UI (list, deregister, cleanup).
- `http://localhost:9876/docs` — full API reference (Redoc on `/openapi.yaml`).

## Service ports

The daemon knows a small set of well-known services and starts allocation from
their conventional ports. Anything in use (in the registry or live on the host
per `ss -tlnp`) is skipped by incrementing.

| Service                       | Preferred port |
|-------------------------------|---------------:|
| `nginx` / `web` / `http`      | 8080           |
| `postgres` / `postgresql`     | 5432           |
| `mysql` / `mariadb`           | 3306           |
| `redis`                       | 6379           |
| `vite` / `frontend`           | 5173           |
| `mailhog-smtp`                | 1025           |
| `mailhog-ui`                  | 8025           |
| `adminer`                     | 8090           |

Unknown service names fall back to port 9000 and walk upward.

Use the returned port numbers as static values in `docker-compose.yml`:

```yaml
services:
  nginx:
    ports:
      - "8082:80"   # nginx — assigned by portbroker
```

## Ephemeral vs permanent

The `ephemeral` flag is a label, not an expiry. Nothing is auto-removed.

- `ephemeral: false` (default) — long-lived project registration.
- `ephemeral: true` — worktrees and test containers; included in `POST /cleanup`.

Callers are responsible for `DELETE /deregister`. `cleanup` exists for crash
recovery, not normal teardown.

## Tests

Standard library `unittest`, no extra tooling:

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_api.TestAPIRegister -v
python3 -m unittest tests.test_api.TestAPIRegister.test_register_conflict_returns_409 -v
```

## Repo layout

```
portbroker/
  server.py           # daemon (Registry + HTTP handler + admin UI)
  portctl             # bash CLI
  gendocs.py          # generates openapi.yaml from an inline string
  openapi.yaml        # generated — do not hand-edit
  portbroker.service  # systemd user unit
  start.sh            # installs systemd unit or .zshrc auto-start guard
docs/
  AGENTS.md           # integration guide for OTHER projects' agents
  security/
    risk-analysis.md  # security model and invariants
tests/
  test_registry.py    # Registry unit tests
  test_api.py         # HTTP API integration tests (real HTTPServer)
  test_gendocs.py     # asserts gendocs output stays in sync
```

## Further reading

- [`docs/AGENTS.md`](docs/AGENTS.md) — how an agent in another project should
  call portbroker (what to register, when, and how to handle 409).
- [`docs/security/risk-analysis.md`](docs/security/risk-analysis.md) — full
  security context, including the assumptions that justify the unauthenticated,
  no-CSRF design.
- [`CLAUDE.md`](CLAUDE.md) — guidance for Claude Code when modifying this repo.
