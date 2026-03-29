# portbroker — Design Spec
**Date:** 2026-03-29
**Environment:** WSL2 (Ubuntu), Windows host browsers, local Docker Compose projects

---

## Overview

`portbroker` is a lightweight Python 3 HTTP daemon that acts as the single source of truth for host port assignments across all local Docker Compose projects and worktrees. Agents interact with it via a REST API using `curl`. It eliminates port collisions by assigning unique ports on request, tracking all assignments persistently, and preventing its own port from being handed out.

It is designed to be extended later with hostname-based routing via Traefik or Caddy. The port assignments it manages today become the routing targets that reverse proxy integration will consume.

---

## Repository Structure

```
~/projects/infrastructure/
├── portbroker/
│   ├── server.py              # The daemon
│   ├── ports.json             # Persistent registry (never hand-edited)
│   ├── portbroker.service     # Systemd unit file
│   ├── start.sh               # Manual start fallback
│   └── portctl                # CLI client script
├── docs/
│   ├── security/
│   │   └── risk-analysis.md
│   ├── superpowers/
│   │   └── specs/
│   │       └── 2026-03-29-portbroker-design.md
│   └── AGENTS.md              # Instructions for project agents
└── README.md
```

---

## Daemon: server.py

### Binding
The daemon binds exclusively to `127.0.0.1:9876`. It must never bind to `0.0.0.0`. See `docs/security/risk-analysis.md` for rationale.

### Self-registration
On first start, before accepting any requests, the daemon writes a permanent entry for itself into `ports.json`:

```json
"portbroker:system": {
  "project": "portbroker",
  "worktree": "system",
  "ephemeral": false,
  "registered_at": "<iso timestamp>",
  "ports": { "portbroker": 9876 }
}
```

Port 9876 is therefore permanently reserved and will never be assigned to any project.

### Service Knowledge

The daemon has a built-in map of well-known services and their preferred ports. If the preferred port is already taken (in the registry or in active system use), it increments by 1 until finding a free slot. System port usage is checked via `ss -tlnp`.

| Service key(s) | Preferred port | Notes |
|---|---|---|
| `nginx`, `web`, `http` | 8080 | 80 requires root; 8080 is conventional |
| `postgres`, `postgresql` | 5432 | |
| `mysql`, `mariadb` | 3306 | |
| `redis` | 6379 | |
| `vite`, `frontend` | 5173 | Vite default |
| `mailhog-smtp` | 1025 | |
| `mailhog-ui` | 8025 | |
| `adminer` | 8090 | |
| `portbroker` | 9876 | Reserved for self |

Additional service types can be added to the `SERVICE_DEFAULTS` dict at the top of `server.py` without touching any other logic.

### Persistence

All assignments are stored in `ports.json` in the same directory as `server.py`. The file is created automatically on first start. It is never modified by hand — use the API or `portctl` instead.

Structure:
```json
{
  "assignments": {
    "portbroker:system": {
      "project": "portbroker",
      "worktree": "system",
      "ephemeral": false,
      "registered_at": "2026-03-29T10:00:00",
      "ports": { "portbroker": 9876 }
    },
    "gymscheduler:main": {
      "project": "gymscheduler",
      "worktree": "main",
      "ephemeral": false,
      "registered_at": "2026-03-29T10:01:00",
      "ports": { "nginx": 8080, "postgres": 5432 }
    },
    "gymscheduler:feature-x": {
      "project": "gymscheduler",
      "worktree": "feature-x",
      "ephemeral": true,
      "registered_at": "2026-03-29T14:00:00",
      "ports": { "nginx": 8083, "postgres": 5435 }
    }
  }
}
```

**Ephemeral flag:** Main project registrations use `"ephemeral": false`. Worktree and test container registrations use `"ephemeral": true`. The flag does not cause automatic cleanup — agents are responsible for deregistering. It exists to distinguish long-lived assignments from temporary ones in the UI and list output, and to enable manual batch cleanup via `POST /cleanup`.

---

## API Reference

Base URL: `http://localhost:9876`

### POST /register

Request a port block for a project or worktree. Returns assigned ports.

```bash
curl -s -X POST http://localhost:9876/register \
  -H "Content-Type: application/json" \
  -d '{
    "project": "gymscheduler",
    "worktree": "main",
    "ephemeral": false,
    "services": ["nginx", "postgres"]
  }'
```

- `worktree` defaults to `"main"` if omitted
- `ephemeral` defaults to `false` if omitted
- Returns `409 Conflict` if the project:worktree is already registered (use `GET /assignments/<project>/<worktree>` to retrieve existing assignment)

Response:
```json
{
  "project": "gymscheduler",
  "worktree": "main",
  "ephemeral": false,
  "ports": {
    "nginx": 8080,
    "postgres": 5432
  }
}
```

### DELETE /deregister

Release all ports for a project:worktree combination.

```bash
curl -s -X DELETE http://localhost:9876/deregister \
  -H "Content-Type: application/json" \
  -d '{"project": "gymscheduler", "worktree": "feature-x"}'
```

- Returns `404` if the project:worktree is not registered
- The `portbroker:system` entry cannot be deregistered

### GET /assignments

List all current assignments.

```bash
curl -s http://localhost:9876/assignments
```

### GET /assignments/\<project\>

List all worktree assignments for a single project.

```bash
curl -s http://localhost:9876/assignments/gymscheduler
```

### GET /assignments/\<project\>/\<worktree\>

Get the assignment for a specific project:worktree.

```bash
curl -s http://localhost:9876/assignments/gymscheduler/main
```

### POST /cleanup

Deregister all ephemeral entries. Use after a crash or failed teardown left stale registrations.

```bash
curl -s -X POST http://localhost:9876/cleanup
```

Returns a list of entries that were removed.

### GET /health

Returns `200 OK` with daemon status. Used by agents to confirm the daemon is running before making registration requests.

```bash
curl -s http://localhost:9876/health
```

---

## Web UI

The daemon serves a management UI at `http://localhost:9876/`. Since WSL2 forwards ports to the Windows host, this is accessible from any Windows browser.

The UI displays:
- A table of all assignments grouped by project
- Ephemeral entries visually distinguished (e.g., italic or badge)
- A **Remove** button per entry that calls `DELETE /deregister`
- A **Clean up ephemeral** button that calls `POST /cleanup`
- The daemon's own `portbroker:system` entry is shown but its Remove button is disabled

The UI is served as a single self-contained HTML response generated by `server.py` — no static files, no build step.

---

## CLI: portctl

A shell script at `~/projects/infrastructure/portbroker/portctl`, symlinked to `~/.local/bin/portctl` (or added to `PATH`).

```bash
portctl list                                      # table of all assignments
portctl register <project> [worktree] <services>  # register (wraps POST /register)
portctl deregister <project> [worktree]           # deregister (wraps DELETE /deregister)
portctl get <project> [worktree]                  # get specific assignment
portctl cleanup                                   # sweep ephemeral entries
portctl status                                    # check if daemon is running
```

`portctl` is for human terminal use and agent scripting. Agents may use `curl` directly or `portctl` — both are valid.

---

## Auto-start in WSL2

Two modes are provided. `start.sh` is a one-time install script — run it once during setup. It detects whether systemd is available and installs the appropriate mode automatically.

### Systemd (preferred)
For WSL2 with `systemd=true` in `/etc/wsl.conf`:

`start.sh` installs `portbroker.service` as a user systemd service and enables it:
```
systemctl --user enable portbroker
systemctl --user start portbroker
```

Starts automatically on WSL2 login. No shell config changes needed.

### Fallback (.zshrc)
If systemd is not available, `start.sh` appends a guard to `~/.zshrc`:
```bash
# portbroker — start if not running
if ! curl -s http://localhost:9876/health > /dev/null 2>&1; then
  nohup python3 ~/projects/infrastructure/portbroker/server.py \
    > ~/projects/infrastructure/portbroker/portbroker.log 2>&1 &
fi
```

Starts automatically with any new shell session.

---

## Agent Integration (AGENTS.md)

A standalone `docs/AGENTS.md` file provides copy-paste instructions for agents in any project. Key points:

1. **Check daemon is running** before any port operation: `curl -s http://localhost:9876/health`
2. **Register once** when setting up a new project's Docker config. Use `"ephemeral": false`. Hardcode the returned ports directly into `docker-compose.yml` as static values.
3. **For worktrees/test containers:** register with `"ephemeral": true`, use the returned ports, deregister explicitly when tearing down.
4. **If already registered:** a `409` response means this project:worktree already has an assignment. Use `GET /assignments/<project>/<worktree>` to retrieve it instead of re-registering.
5. **If daemon is unreachable:** do not proceed. Inform the user that portbroker is not running and provide the start command.

---

## Future: Traefik / Caddy Integration

This service is designed to be extended with hostname-based routing. When that work begins:

- portbroker continues to own port assignments
- A reverse proxy (Traefik or Caddy) is added to the infrastructure stack
- Each project's assigned ports become the upstream targets in proxy config
- Hostname routing (`gymscheduler.localhost`) is added via Windows hosts file entries (one-time manual setup per project)
- Caddy with static config is preferred over Traefik to avoid Docker socket mounting

See `docs/security/risk-analysis.md` for security considerations specific to this integration.

---

## Constraints and Assumptions

- Single-developer local use only — no multi-user or team access
- Daemon always binds to `127.0.0.1`, never `0.0.0.0`
- Python 3 is available in the WSL2 environment (install via `sudo apt install python3` if not)
- No pip packages required — stdlib only
- `jq` is not required — all JSON handling is done in Python
- `ss` (iproute2) is available for system port checking (standard in Ubuntu WSL2)
