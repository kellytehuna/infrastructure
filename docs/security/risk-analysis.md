# Security Risk Analysis
**Project:** portbroker + local Docker development infrastructure
**Date:** 2026-03-29
**Environment:** WSL2 (Ubuntu), Windows host browsers, local network

---

## Summary Table

| Risk | Severity | Status | Mitigation |
|---|---|---|---|
| DB ports exposed on network with weak credentials | High | Existing — pre-dates this project | Bind to `127.0.0.1` or remove host port mappings |
| portbroker daemon binds to `0.0.0.0` | Medium | Must prevent at build time | Explicitly bind to `127.0.0.1` in implementation |
| Unauthenticated portbroker API | Low | Acceptable | localhost-only personal tool; document assumption |
| Docker socket access in Traefik | Low–Medium | Future concern | Use static Caddy config to avoid socket mount |
| Traefik/Caddy admin UIs exposed on network | Low | Future concern | Bind admin interfaces to `127.0.0.1` explicitly |

---

## 1. portbroker Daemon

### Unauthenticated API — Low Risk
The daemon exposes no authentication. Any process that can reach port 9876 can register, deregister, or read the full port assignment list. For a personal dev tool on localhost this is an accepted tradeoff.

**Critical implementation requirement:** the daemon **must** bind to `127.0.0.1:9876`, not `0.0.0.0:9876`. Binding to `0.0.0.0` would make the API reachable from the local network, allowing anyone on the same WiFi to manipulate the registry or enumerate project names.

### Information Disclosure — Low Risk
`GET /assignments` reveals project names, worktree names, and port assignments. Acceptable on strict localhost. Reinforces the `127.0.0.1` binding requirement.

### Web UI / CSRF — Low Risk (accepted)
The management UI's Remove buttons issue DELETE requests with no CSRF protection. This is acceptable under the localhost-only assumption: CSRF attacks require a malicious page to make cross-origin requests, and `localhost` is not a meaningful attack origin from outside the machine. This assumption must hold — if the daemon ever needs to be exposed beyond localhost, authentication and CSRF protection must be added before doing so.

---

## 2. Existing Docker Projects — High Risk (pre-existing)

Several projects already expose database ports to the host with weak or guessable credentials:

| Project | Service | Host Binding | Credential Risk |
|---|---|---|---|
| volleyball-scorebook | MySQL 8.0 | `3306:3306` | `MYSQL_ROOT_PASSWORD: root_password` |
| gymscheduler | Postgres 16 | `5432:5432` | password: `gymscheduler` |
| colwellstanning | Postgres 16 | internal only | no exposure — correctly configured |

In WSL2, ports bound inside the WSL2 VM are forwarded to the Windows host's `localhost`. Depending on Windows Firewall configuration and network profile (public vs. private), **these ports may be reachable from other machines on the local network** with guessable credentials.

**Recommended fix (independent of portbroker work):**
- Either remove host port mappings entirely for database services (access via container name within the Docker network is sufficient for application use)
- Or if host access is needed for tooling, bind explicitly to loopback: `"127.0.0.1:5432:5432"`

colwellstanning's pattern (no host port binding on the DB service) is the correct model.

---

## 3. Future Traefik / Caddy Integration

### Docker Socket Access — Low–Medium Risk
Traefik's auto-discovery feature requires mounting `/var/run/docker.sock` into the Traefik container. This grants the container full Docker control over the host — a compromised Traefik instance could start, stop, or inspect any container. This is a widely-accepted tradeoff in local dev environments, but should be a conscious decision.

**Mitigation:** Caddy with a static config file avoids the socket mount entirely. If Traefik is chosen, consider using a Docker socket proxy (e.g., `tecnativa/docker-socket-proxy`) to limit what Traefik can access.

### Admin Dashboards — Low Risk
Both Traefik and Caddy expose admin/API interfaces. Default binding behavior varies by version and may expose these on `0.0.0.0`. Explicitly bind admin interfaces to `127.0.0.1` in all configurations.

### Port 80 Binding — Low Risk
Running a reverse proxy on port 80 inside a Docker container is fine — Docker handles the privilege internally. The host port mapping (`80:80`) means the Windows host's port 80 is consumed. Ensure Windows is not running IIS or any other service on port 80 before deploying.

### Windows Hosts File — Operational Note
Hostname-based routing requires entries in `C:\Windows\System32\drivers\etc\hosts` on the Windows host. This file requires administrator access to edit and is outside version control and WSL2. Any automation that modifies it requires a Windows-side privileged script. This is acceptable as a one-time manual step per project but should not be assumed automatable by WSL2-based agents.

---

## Assumptions That Must Hold

For the low-risk assessments above to remain valid:

1. `portbroker` binds exclusively to `127.0.0.1` — never `0.0.0.0`
2. The portbroker port (9876) is not exposed through any port forwarding rule to the external network
3. This infrastructure is for single-developer local use only — no shared or team access
4. Windows Firewall remains active and is not configured to allow inbound traffic to WSL2 ports from external sources

If any of these assumptions change, the risk profile must be re-evaluated.
