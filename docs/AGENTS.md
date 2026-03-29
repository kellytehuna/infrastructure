# portbroker — Agent Integration Guide

portbroker is a daemon running locally at `http://localhost:9876`. It assigns unique host
ports to Docker Compose projects and worktrees so that multiple projects can run
simultaneously without port collisions.

## Before You Start

Always verify the daemon is running before making any port requests:

    curl -s http://localhost:9876/health

Expected response: `{"status": "ok", "port": 9876}`

If the daemon is unreachable, **do not proceed**. Tell the user:
> portbroker is not running. Please start it with:
> `python3 ~/projects/infrastructure/portbroker/server.py &`
> Or if auto-start was configured: open a new terminal (it starts with each shell session).

## Setting Up a New Project

Call this **once** when writing the project's Docker configuration for the first time.
Use `"ephemeral": false` — this is a permanent registration.

    curl -s -X POST http://localhost:9876/register \
      -H "Content-Type: application/json" \
      -d '{
        "project": "<project-name>",
        "worktree": "main",
        "ephemeral": false,
        "services": ["<service1>", "<service2>"]
      }'

**Known service names and their preferred ports:**

| Service name | Default port |
|---|---|
| `nginx` / `web` / `http` | 8080 |
| `postgres` / `postgresql` | 5432 |
| `mysql` / `mariadb` | 3306 |
| `redis` | 6379 |
| `vite` / `frontend` | 5173 |
| `mailhog-smtp` | 1025 |
| `mailhog-ui` | 8025 |
| `adminer` | 8090 |

Any other string is accepted — it receives a port starting at 9000.

**Response:**

    {
      "project": "myproject",
      "worktree": "main",
      "ephemeral": false,
      "ports": {
        "nginx": 8082,
        "postgres": 5434
      }
    }

**Use the returned port numbers as static values in `docker-compose.yml`:**

    ports:
      - "8082:80"   # nginx — assigned by portbroker

If the response is `409 Conflict`, this project:worktree is already registered.
Retrieve the existing assignment instead:

    curl -s http://localhost:9876/assignments/myproject/main

## Worktrees and Test Containers

When spinning up a worktree or temporary test environment, register with `"ephemeral": true`.
Use a descriptive worktree name (e.g., the branch name).

    curl -s -X POST http://localhost:9876/register \
      -H "Content-Type: application/json" \
      -d '{
        "project": "<project-name>",
        "worktree": "<branch-or-worktree-name>",
        "ephemeral": true,
        "services": ["nginx", "postgres"]
      }'

**When tearing down**, deregister explicitly:

    curl -s -X DELETE http://localhost:9876/deregister \
      -H "Content-Type: application/json" \
      -d '{"project": "<project-name>", "worktree": "<worktree-name>"}'

If teardown fails or the process crashes, stale entries can be cleaned manually:
- Web UI: `http://localhost:9876` → Remove button
- CLI: `portctl cleanup` (removes all ephemeral entries)
- API: `curl -s -X POST http://localhost:9876/cleanup`

## Checking Existing Assignments

    # All assignments
    curl -s http://localhost:9876/assignments

    # All worktrees for one project
    curl -s http://localhost:9876/assignments/<project>

    # One specific assignment
    curl -s http://localhost:9876/assignments/<project>/<worktree>

## Security Note

portbroker binds to `127.0.0.1` only. Do not change this. See
`docs/security/risk-analysis.md` for full security context.
