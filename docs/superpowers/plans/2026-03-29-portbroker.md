# portbroker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python 3 HTTP daemon that assigns unique host ports to Docker Compose projects and worktrees on demand, persists assignments to disk, and serves a management web UI.

**Architecture:** A single `server.py` file contains a `Registry` class (port assignment logic + JSON persistence) and an HTTP handler class (REST API + web UI). A `portctl` shell script wraps the API for terminal and agent use. Auto-start is handled by systemd (preferred) or a `.zshrc` guard (fallback).

**Tech Stack:** Python 3 stdlib only (`http.server`, `json`, `threading`, `subprocess`, `socket`), bash for `portctl`, systemd for auto-start.

---

## File Map

| File | Purpose |
|---|---|
| `portbroker/server.py` | Registry class + HTTP handler + main entry point |
| `portbroker/portctl` | Shell script CLI wrapping the HTTP API |
| `portbroker/portbroker.service` | Systemd user service unit |
| `portbroker/start.sh` | One-time install script: installs systemd service or adds .zshrc guard |
| `tests/__init__.py` | Empty — makes tests/ a package for discovery |
| `tests/test_registry.py` | Unit tests for Registry class |
| `tests/test_api.py` | Integration tests for HTTP API endpoints |
| `docs/AGENTS.md` | Instructions for project agents |

---

## Task 1: Scaffold

**Files:**
- Create: `portbroker/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Verify Python 3 is available**

```bash
python3 --version
```

Expected: `Python 3.x.x` (any 3.6+). If not found: `sudo apt install python3`

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p portbroker tests
touch portbroker/__init__.py tests/__init__.py
```

- [ ] **Step 3: Verify structure**

```bash
ls portbroker/ tests/
```

Expected: `portbroker/` contains `__init__.py`, `tests/` contains `__init__.py`.

- [ ] **Step 4: Commit**

```bash
git add portbroker/__init__.py tests/__init__.py
git commit -m "chore: scaffold portbroker package and tests directory"
```

---

## Task 2: Registry Class

**Files:**
- Create: `portbroker/server.py`
- Create: `tests/test_registry.py`

The Registry class owns all data — it loads and saves `ports.json`, knows which ports are preferred for which service types, assigns the next available port (checking both the registry and active system ports), and enforces the `portbroker:system` protection.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_registry.py`:

```python
import json
import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from portbroker.server import Registry


class TestRegistryBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'ports.json')
        self.reg = Registry(self.path)
        self.reg.bootstrap()

    def test_bootstrap_creates_system_entry(self):
        data = self.reg.get_all()
        self.assertIn('portbroker:system', data)

    def test_bootstrap_reserves_port_9876(self):
        data = self.reg.get_all()
        self.assertEqual(data['portbroker:system']['ports']['portbroker'], 9876)

    def test_bootstrap_is_permanent(self):
        data = self.reg.get_all()
        self.assertFalse(data['portbroker:system']['ephemeral'])

    def test_bootstrap_is_idempotent(self):
        self.reg.bootstrap()  # calling twice should not raise or duplicate
        data = self.reg.get_all()
        count = sum(1 for k in data if k == 'portbroker:system')
        self.assertEqual(count, 1)


class TestRegistryPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'ports.json')

    def test_persists_to_disk(self):
        reg = Registry(self.path)
        reg.bootstrap()
        reg.register('myproject', 'main', ['nginx'], False)
        reg2 = Registry(self.path)
        self.assertIsNotNone(reg2.get_one('myproject', 'main'))

    def test_creates_file_if_missing(self):
        Registry(self.path)
        self.assertTrue(os.path.exists(self.path))


class TestRegistryRegister(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'ports.json')
        self.reg = Registry(self.path)
        self.reg.bootstrap()

    def test_assigns_preferred_port_for_nginx(self):
        entry, err = self.reg.register('proj', 'main', ['nginx'], False)
        self.assertIsNone(err)
        self.assertEqual(entry['ports']['nginx'], 8080)

    def test_assigns_preferred_port_for_postgres(self):
        entry, err = self.reg.register('proj', 'main', ['postgres'], False)
        self.assertIsNone(err)
        self.assertEqual(entry['ports']['postgres'], 5432)

    def test_increments_on_collision(self):
        self.reg.register('proj1', 'main', ['postgres'], False)
        entry, err = self.reg.register('proj2', 'main', ['postgres'], False)
        self.assertIsNone(err)
        self.assertEqual(entry['ports']['postgres'], 5433)

    def test_multiple_services_no_collision(self):
        entry, err = self.reg.register('proj', 'main', ['nginx', 'postgres'], False)
        self.assertIsNone(err)
        ports = list(entry['ports'].values())
        self.assertEqual(len(ports), len(set(ports)))  # all unique

    def test_duplicate_registration_returns_error(self):
        self.reg.register('proj', 'main', ['nginx'], False)
        _, err = self.reg.register('proj', 'main', ['nginx'], False)
        self.assertEqual(err, 'already_registered')

    def test_ephemeral_flag_stored(self):
        entry, _ = self.reg.register('proj', 'wt1', ['nginx'], True)
        self.assertTrue(entry['ephemeral'])

    def test_unknown_service_gets_fallback_port(self):
        entry, err = self.reg.register('proj', 'main', ['myservice'], False)
        self.assertIsNone(err)
        self.assertIn('myservice', entry['ports'])
        self.assertGreater(entry['ports']['myservice'], 0)


class TestRegistryDeregister(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'ports.json')
        self.reg = Registry(self.path)
        self.reg.bootstrap()

    def test_deregister_removes_entry(self):
        self.reg.register('proj', 'main', ['nginx'], False)
        ok, err = self.reg.deregister('proj', 'main')
        self.assertTrue(ok)
        self.assertIsNone(self.reg.get_one('proj', 'main'))

    def test_deregister_frees_port_for_reuse(self):
        self.reg.register('proj1', 'main', ['nginx'], False)
        self.reg.deregister('proj1', 'main')
        entry, _ = self.reg.register('proj2', 'main', ['nginx'], False)
        self.assertEqual(entry['ports']['nginx'], 8080)

    def test_deregister_not_found_returns_error(self):
        ok, err = self.reg.deregister('nonexistent', 'main')
        self.assertFalse(ok)
        self.assertEqual(err, 'not_found')

    def test_deregister_portbroker_system_is_protected(self):
        ok, err = self.reg.deregister('portbroker', 'system')
        self.assertFalse(ok)
        self.assertEqual(err, 'protected')


class TestRegistryCleanup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'ports.json')
        self.reg = Registry(self.path)
        self.reg.bootstrap()

    def test_cleanup_removes_ephemeral_entries(self):
        self.reg.register('proj', 'wt1', ['nginx'], True)
        removed = self.reg.cleanup_ephemeral()
        self.assertIn('proj:wt1', removed)
        self.assertIsNone(self.reg.get_one('proj', 'wt1'))

    def test_cleanup_preserves_permanent_entries(self):
        self.reg.register('proj', 'main', ['nginx'], False)
        self.reg.cleanup_ephemeral()
        self.assertIsNotNone(self.reg.get_one('proj', 'main'))

    def test_cleanup_preserves_system_entry(self):
        self.reg.cleanup_ephemeral()
        self.assertIsNotNone(self.reg.get_one('portbroker', 'system'))

    def test_cleanup_returns_list_of_removed_keys(self):
        self.reg.register('proj', 'wt1', ['nginx'], True)
        self.reg.register('proj', 'wt2', ['postgres'], True)
        removed = self.reg.cleanup_ephemeral()
        self.assertEqual(len(removed), 2)


class TestRegistryQuery(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'ports.json')
        self.reg = Registry(self.path)
        self.reg.bootstrap()
        self.reg.register('proj', 'main', ['nginx'], False)
        self.reg.register('proj', 'wt1', ['postgres'], True)

    def test_get_all_returns_all_entries(self):
        data = self.reg.get_all()
        self.assertIn('proj:main', data)
        self.assertIn('proj:wt1', data)
        self.assertIn('portbroker:system', data)

    def test_get_project_filters_by_project(self):
        data = self.reg.get_project('proj')
        self.assertIn('proj:main', data)
        self.assertNotIn('portbroker:system', data)

    def test_get_one_returns_specific_entry(self):
        entry = self.reg.get_one('proj', 'main')
        self.assertIsNotNone(entry)
        self.assertEqual(entry['project'], 'proj')
        self.assertEqual(entry['worktree'], 'main')

    def test_get_one_missing_returns_none(self):
        self.assertIsNone(self.reg.get_one('proj', 'nonexistent'))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m unittest tests/test_registry.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError` — `portbroker.server` does not exist yet.

- [ ] **Step 3: Create portbroker/server.py with the Registry class**

```python
#!/usr/bin/env python3
"""portbroker — local port assignment daemon."""

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

DAEMON_HOST = '127.0.0.1'
DAEMON_PORT = 9876
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ports.json')
FALLBACK_PORT = 9000

SERVICE_DEFAULTS = {
    'nginx':        8080,
    'web':          8080,
    'http':         8080,
    'postgres':     5432,
    'postgresql':   5432,
    'mysql':        3306,
    'mariadb':      3306,
    'redis':        6379,
    'vite':         5173,
    'frontend':     5173,
    'mailhog-smtp': 1025,
    'mailhog-ui':   8025,
    'adminer':      8090,
    'portbroker':   9876,
}


class Registry:
    def __init__(self, path=REGISTRY_PATH):
        self.path = path
        self.lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        data = {'assignments': {}}
        self._write(data)
        return data

    def _write(self, data=None):
        if data is None:
            data = self._data
        with open(self.path, 'w') as f:
            json.dump(data, f, indent=2)

    def _assigned_ports(self):
        return {
            port
            for entry in self._data['assignments'].values()
            for port in entry['ports'].values()
        }

    def _system_ports(self):
        try:
            result = subprocess.run(
                ['ss', '-tlnp'], capture_output=True, text=True, timeout=2
            )
            ports = set()
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    addr = parts[3]
                    try:
                        ports.add(int(addr.rsplit(':', 1)[-1]))
                    except ValueError:
                        pass
            return ports
        except Exception:
            return set()

    def _next_available(self, service, taken):
        preferred = SERVICE_DEFAULTS.get(service.lower(), FALLBACK_PORT)
        port = preferred
        while port in taken:
            port += 1
        return port

    def bootstrap(self):
        key = 'portbroker:system'
        with self.lock:
            if key not in self._data['assignments']:
                self._data['assignments'][key] = {
                    'project':       'portbroker',
                    'worktree':      'system',
                    'ephemeral':     False,
                    'registered_at': datetime.now(timezone.utc).isoformat(),
                    'ports':         {'portbroker': DAEMON_PORT},
                }
                self._write()

    def register(self, project, worktree, services, ephemeral):
        key = f'{project}:{worktree}'
        with self.lock:
            if key in self._data['assignments']:
                return None, 'already_registered'
            taken = self._assigned_ports() | self._system_ports()
            ports = {}
            for service in services:
                port = self._next_available(service, taken)
                ports[service] = port
                taken.add(port)
            entry = {
                'project':       project,
                'worktree':      worktree,
                'ephemeral':     ephemeral,
                'registered_at': datetime.now(timezone.utc).isoformat(),
                'ports':         ports,
            }
            self._data['assignments'][key] = entry
            self._write()
            return entry, None

    def deregister(self, project, worktree):
        key = f'{project}:{worktree}'
        if key == 'portbroker:system':
            return False, 'protected'
        with self.lock:
            if key not in self._data['assignments']:
                return False, 'not_found'
            del self._data['assignments'][key]
            self._write()
            return True, None

    def cleanup_ephemeral(self):
        with self.lock:
            removed = [
                k for k, v in self._data['assignments'].items()
                if v.get('ephemeral')
            ]
            for k in removed:
                del self._data['assignments'][k]
            if removed:
                self._write()
            return removed

    def get_all(self):
        with self.lock:
            return dict(self._data['assignments'])

    def get_project(self, project):
        with self.lock:
            return {k: v for k, v in self._data['assignments'].items()
                    if v['project'] == project}

    def get_one(self, project, worktree):
        with self.lock:
            return self._data['assignments'].get(f'{project}:{worktree}')


if __name__ == '__main__':
    pass  # HTTP server added in next task
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m unittest tests/test_registry.py -v
```

Expected: all tests pass. No failures.

- [ ] **Step 5: Commit**

```bash
git add portbroker/server.py tests/test_registry.py
git commit -m "feat: add Registry class with port assignment and persistence"
```

---

## Task 3: HTTP Server and API

**Files:**
- Modify: `portbroker/server.py` (add handler class and `run_server`, replace `if __name__` block)
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_api.py`:

```python
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from portbroker.server import run_server


def _request(method, port, path, body=None):
    url = f'http://127.0.0.1:{port}{path}'
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestAPIHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.registry_path = os.path.join(cls.tmpdir, 'ports.json')
        cls.port = 19876
        cls.server = run_server('127.0.0.1', cls.port, cls.registry_path, block=False)
        time.sleep(0.1)  # allow server thread to start

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_health_returns_200(self):
        status, data = _request('GET', self.port, '/health')
        self.assertEqual(status, 200)
        self.assertEqual(data['status'], 'ok')


class TestAPIRegister(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.registry_path = os.path.join(cls.tmpdir, 'ports.json')
        cls.port = 19877
        cls.server = run_server('127.0.0.1', cls.port, cls.registry_path, block=False)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_register_returns_port_assignments(self):
        status, data = _request('POST', self.port, '/register', {
            'project': 'testproj', 'services': ['nginx', 'postgres']
        })
        self.assertEqual(status, 200)
        self.assertIn('nginx', data['ports'])
        self.assertIn('postgres', data['ports'])

    def test_register_defaults_worktree_to_main(self):
        status, data = _request('POST', self.port, '/register', {
            'project': 'defaultwt', 'services': ['redis']
        })
        self.assertEqual(status, 200)
        self.assertEqual(data['worktree'], 'main')

    def test_register_conflict_returns_409(self):
        _request('POST', self.port, '/register', {
            'project': 'dupproj', 'services': ['nginx']
        })
        status, _ = _request('POST', self.port, '/register', {
            'project': 'dupproj', 'services': ['nginx']
        })
        self.assertEqual(status, 409)

    def test_register_missing_project_returns_400(self):
        status, _ = _request('POST', self.port, '/register', {
            'services': ['nginx']
        })
        self.assertEqual(status, 400)

    def test_register_missing_services_returns_400(self):
        status, _ = _request('POST', self.port, '/register', {
            'project': 'noop'
        })
        self.assertEqual(status, 400)


class TestAPIDeregister(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.registry_path = os.path.join(cls.tmpdir, 'ports.json')
        cls.port = 19878
        cls.server = run_server('127.0.0.1', cls.port, cls.registry_path, block=False)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_deregister_returns_200(self):
        _request('POST', self.port, '/register', {
            'project': 'todel', 'services': ['nginx']
        })
        status, _ = _request('DELETE', self.port, '/deregister', {
            'project': 'todel', 'worktree': 'main'
        })
        self.assertEqual(status, 200)

    def test_deregister_missing_returns_404(self):
        status, _ = _request('DELETE', self.port, '/deregister', {
            'project': 'ghost', 'worktree': 'main'
        })
        self.assertEqual(status, 404)

    def test_deregister_system_returns_403(self):
        status, _ = _request('DELETE', self.port, '/deregister', {
            'project': 'portbroker', 'worktree': 'system'
        })
        self.assertEqual(status, 403)


class TestAPIAssignments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.registry_path = os.path.join(cls.tmpdir, 'ports.json')
        cls.port = 19879
        cls.server = run_server('127.0.0.1', cls.port, cls.registry_path, block=False)
        time.sleep(0.1)
        _request('POST', cls.port, '/register', {
            'project': 'myapp', 'services': ['nginx', 'postgres']
        })
        _request('POST', cls.port, '/register', {
            'project': 'myapp', 'worktree': 'feature-x',
            'services': ['nginx'], 'ephemeral': True
        })

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_get_all_includes_all_entries(self):
        status, data = _request('GET', self.port, '/assignments')
        self.assertEqual(status, 200)
        self.assertIn('myapp:main', data['assignments'])
        self.assertIn('myapp:feature-x', data['assignments'])

    def test_get_project_filters_correctly(self):
        status, data = _request('GET', self.port, '/assignments/myapp')
        self.assertEqual(status, 200)
        self.assertIn('myapp:main', data)
        self.assertNotIn('portbroker:system', data)

    def test_get_one_returns_entry(self):
        status, data = _request('GET', self.port, '/assignments/myapp/main')
        self.assertEqual(status, 200)
        self.assertEqual(data['project'], 'myapp')

    def test_get_one_missing_returns_404(self):
        status, _ = _request('GET', self.port, '/assignments/myapp/nonexistent')
        self.assertEqual(status, 404)


class TestAPICleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.registry_path = os.path.join(cls.tmpdir, 'ports.json')
        cls.port = 19880
        cls.server = run_server('127.0.0.1', cls.port, cls.registry_path, block=False)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_cleanup_removes_ephemeral_and_returns_list(self):
        _request('POST', self.port, '/register', {
            'project': 'wt', 'worktree': 'ephwt',
            'services': ['nginx'], 'ephemeral': True
        })
        status, data = _request('POST', self.port, '/cleanup')
        self.assertEqual(status, 200)
        self.assertIn('wt:ephwt', data['removed'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m unittest tests/test_api.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'run_server'` — function not yet defined.

- [ ] **Step 3: Add HTTP handler and run_server to portbroker/server.py**

Replace the `if __name__ == '__main__': pass` block at the bottom of `portbroker/server.py` with everything below. Also add `import argparse` at the top imports block.

The complete new bottom section of `server.py` (append after the Registry class, replacing the `if __name__` stub):

```python
def _make_handler(registry):
    class PortBrokerHandler(BaseHTTPRequestHandler):
        _registry = registry

        def log_message(self, fmt, *args):
            pass  # suppress per-request console noise

        def do_GET(self):
            if self.path == '/':
                self._serve_ui()
            elif self.path == '/health':
                self._json({'status': 'ok', 'port': DAEMON_PORT})
            elif self.path == '/assignments':
                self._json({'assignments': self._registry.get_all()})
            elif self.path.startswith('/assignments/'):
                parts = self.path[len('/assignments/'):].strip('/').split('/')
                if len(parts) == 1:
                    self._json(self._registry.get_project(parts[0]))
                elif len(parts) == 2:
                    entry = self._registry.get_one(parts[0], parts[1])
                    if entry:
                        self._json(entry)
                    else:
                        self._error(404, 'not_found')
                else:
                    self._error(404, 'not_found')
            else:
                self._error(404, 'not_found')

        def do_POST(self):
            body = self._body()
            if self.path == '/register':
                project = body.get('project')
                services = body.get('services')
                if not project or not services:
                    return self._error(400, 'project and services are required')
                worktree = body.get('worktree', 'main')
                ephemeral = body.get('ephemeral', False)
                entry, err = self._registry.register(project, worktree, services, ephemeral)
                if err == 'already_registered':
                    return self._error(409, 'already_registered')
                self._json(entry)
            elif self.path == '/cleanup':
                removed = self._registry.cleanup_ephemeral()
                self._json({'removed': removed})
            else:
                self._error(404, 'not_found')

        def do_DELETE(self):
            body = self._body()
            if self.path == '/deregister':
                project = body.get('project')
                if not project:
                    return self._error(400, 'project is required')
                worktree = body.get('worktree', 'main')
                ok, err = self._registry.deregister(project, worktree)
                if err == 'protected':
                    return self._error(403, 'cannot deregister portbroker:system')
                if err == 'not_found':
                    return self._error(404, 'not_found')
                self._json({'message': f'deregistered {project}:{worktree}'})
            else:
                self._error(404, 'not_found')

        def _body(self):
            length = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(length)) if length else {}

        def _json(self, data, status=200):
            body = json.dumps(data, indent=2).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message):
            self._json({'error': message}, status)

        def _serve_ui(self):
            # Web UI added in Task 4 — placeholder until then
            body = b'<html><body>portbroker running</body></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return PortBrokerHandler


def run_server(host=DAEMON_HOST, port=DAEMON_PORT, registry_path=REGISTRY_PATH, block=True):
    registry = Registry(registry_path)
    registry.bootstrap()
    server = HTTPServer((host, port), _make_handler(registry))
    if block:
        print(f'portbroker listening on {host}:{port}')
        server.serve_forever()
    else:
        t = threading.Thread(target=server.serve_forever)
        t.daemon = True
        t.start()
    return server


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='portbroker daemon')
    parser.add_argument('--host', default=DAEMON_HOST)
    parser.add_argument('--port', type=int, default=DAEMON_PORT)
    parser.add_argument('--registry', default=REGISTRY_PATH)
    args = parser.parse_args()
    run_server(args.host, args.port, args.registry, block=True)
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
python3 -m unittest discover tests/ -v
```

Expected: all tests pass across both test files.

- [ ] **Step 5: Manually smoke-test the daemon**

```bash
python3 portbroker/server.py &
sleep 0.5
curl -s http://localhost:9876/health
curl -s -X POST http://localhost:9876/register \
  -H "Content-Type: application/json" \
  -d '{"project":"smoke","services":["nginx","postgres"]}'
curl -s http://localhost:9876/assignments
kill %1
```

Expected: health returns `{"status": "ok", ...}`, register returns port assignments, assignments lists both `portbroker:system` and `smoke:main`.

- [ ] **Step 6: Commit**

```bash
git add portbroker/server.py tests/test_api.py
git commit -m "feat: add HTTP server with full REST API"
```

---

## Task 4: Web UI

**Files:**
- Modify: `portbroker/server.py` (replace `_serve_ui` placeholder with full implementation)

The UI is a self-contained HTML page generated in Python and served at `GET /`. It uses `fetch()` to call the API and renders a table of all assignments. The `portbroker:system` row's Remove button is disabled.

- [ ] **Step 1: Write the failing test**

Add this to `tests/test_api.py`, inside the `TestAPIHealth` class (the server for this class is already running):

```python
def test_ui_returns_html(self):
    url = f'http://127.0.0.1:{self.port}/'
    with urllib.request.urlopen(url) as resp:
        self.assertEqual(resp.status, 200)
        content_type = resp.headers.get('Content-Type', '')
        self.assertIn('text/html', content_type)
        body = resp.read().decode()
        self.assertIn('portbroker', body)
        self.assertIn('assignments', body)
```

- [ ] **Step 2: Run the new test to verify it fails**

```bash
python3 -m unittest tests.test_api.TestAPIHealth.test_ui_returns_html -v
```

Expected: FAIL — the placeholder does not include `assignments` in the body.

- [ ] **Step 3: Replace the `_serve_ui` method in server.py**

Find the `_serve_ui` method in `portbroker/server.py` and replace it with:

```python
def _serve_ui(self):
    html = _build_ui_html()
    body = html.encode()
    self.send_response(200)
    self.send_header('Content-Type', 'text/html; charset=utf-8')
    self.send_header('Content-Length', str(len(body)))
    self.end_headers()
    self.wfile.write(body)
```

Then add this module-level function to `portbroker/server.py` (place it just before `_make_handler`):

```python
def _build_ui_html():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>portbroker</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { font-family: monospace; padding: 2rem; background: #1e1e1e; color: #d4d4d4; margin: 0; }
    h1 { color: #569cd6; margin-top: 0; }
    #status { font-size: 0.85rem; color: #608b4e; margin-bottom: 1rem; }
    table { border-collapse: collapse; width: 100%; }
    th { text-align: left; padding: 0.5rem 1rem; color: #9cdcfe; border-bottom: 2px solid #444; }
    td { padding: 0.5rem 1rem; border-bottom: 1px solid #2d2d2d; vertical-align: top; }
    tr:hover td { background: #252525; }
    .tag-system  { color: #4ec9b0; }
    .tag-perm    { color: #d4d4d4; }
    .tag-eph     { color: #9e9e9e; font-style: italic; }
    .ports       { color: #ce9178; }
    .date        { color: #608b4e; font-size: 0.85rem; }
    button       { background: #c0392b; color: #fff; border: none;
                   padding: 0.2rem 0.6rem; cursor: pointer; font-family: monospace; font-size: 0.85rem; }
    button:hover { background: #e74c3c; }
    button:disabled { background: #444; color: #777; cursor: default; }
    .actions     { display: flex; gap: 0.5rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
    .btn-cleanup { background: #d35400; }
    .btn-cleanup:hover { background: #e67e22; }
    .btn-refresh { background: #2980b9; }
    .btn-refresh:hover { background: #3498db; }
    #message     { margin-top: 0.5rem; font-size: 0.85rem; min-height: 1.2em; }
    .msg-ok  { color: #608b4e; }
    .msg-err { color: #c0392b; }
  </style>
</head>
<body>
  <h1>portbroker</h1>
  <div id="status">loading...</div>
  <div class="actions">
    <button class="btn-refresh" onclick="load()">Refresh</button>
    <button class="btn-cleanup" onclick="cleanup()">Clean up ephemeral</button>
  </div>
  <div id="message"></div>
  <table>
    <thead>
      <tr>
        <th>Project : Worktree</th>
        <th>Type</th>
        <th>Ports</th>
        <th>Registered</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <script>
    function msg(text, ok) {
      const el = document.getElementById('message');
      el.textContent = text;
      el.className = ok ? 'msg-ok' : 'msg-err';
    }

    async function load() {
      try {
        const resp = await fetch('/assignments');
        const data = await resp.json();
        const entries = Object.entries(data.assignments)
          .sort(([a], [b]) => a.localeCompare(b));
        const tbody = document.getElementById('tbody');
        tbody.innerHTML = '';
        document.getElementById('status').textContent =
          entries.length + ' assignment(s)';
        for (const [key, e] of entries) {
          const isSystem = key === 'portbroker:system';
          const cls = isSystem ? 'tag-system' : e.ephemeral ? 'tag-eph' : 'tag-perm';
          const typeLabel = isSystem ? 'system' : e.ephemeral ? 'ephemeral' : 'permanent';
          const ports = Object.entries(e.ports)
            .map(([s, p]) => s + '=' + p).join('<br>');
          const date = e.registered_at.split('T')[0];
          tbody.innerHTML += '<tr>' +
            '<td class="' + cls + '">' + key + '</td>' +
            '<td class="' + cls + '">' + typeLabel + '</td>' +
            '<td class="ports">' + ports + '</td>' +
            '<td class="date">' + date + '</td>' +
            '<td><button onclick="remove(' + JSON.stringify(e.project) + ',' +
              JSON.stringify(e.worktree) + ')" ' +
              (isSystem ? 'disabled' : '') + '>Remove</button></td>' +
            '</tr>';
        }
      } catch (err) {
        document.getElementById('status').textContent = 'error loading assignments';
        msg('Failed to load: ' + err.message, false);
      }
    }

    async function remove(project, worktree) {
      if (!confirm('Remove ' + project + ':' + worktree + '?')) return;
      try {
        const resp = await fetch('/deregister', {
          method: 'DELETE',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({project, worktree})
        });
        if (resp.ok) {
          msg('Removed ' + project + ':' + worktree, true);
          load();
        } else {
          const d = await resp.json();
          msg('Error: ' + d.error, false);
        }
      } catch (err) {
        msg('Request failed: ' + err.message, false);
      }
    }

    async function cleanup() {
      if (!confirm('Remove all ephemeral entries?')) return;
      try {
        const resp = await fetch('/cleanup', {method: 'POST'});
        const data = await resp.json();
        const n = data.removed.length;
        msg('Removed ' + n + ' ephemeral entr' + (n === 1 ? 'y' : 'ies'), true);
        load();
      } catch (err) {
        msg('Request failed: ' + err.message, false);
      }
    }

    load();
  </script>
</body>
</html>'''
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
python3 -m unittest discover tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Manually verify the UI in a Windows browser**

```bash
python3 portbroker/server.py &
sleep 0.5
curl -s -X POST http://localhost:9876/register \
  -H "Content-Type: application/json" \
  -d '{"project":"gymscheduler","services":["nginx","postgres"]}'
curl -s -X POST http://localhost:9876/register \
  -H "Content-Type: application/json" \
  -d '{"project":"gymscheduler","worktree":"feature-x","services":["nginx"],"ephemeral":true}'
```

Open `http://localhost:9876` in a Windows browser. Verify: table shows three rows (portbroker:system, gymscheduler:main, gymscheduler:feature-x), Remove buttons work, cleanup removes ephemeral entry, refresh reloads data.

```bash
kill %1
```

- [ ] **Step 6: Commit**

```bash
git add portbroker/server.py tests/test_api.py
git commit -m "feat: add web UI served at GET /"
```

---

## Task 5: portctl CLI

**Files:**
- Create: `portbroker/portctl`

`portctl` is a bash script. It wraps `curl` calls to the API and formats output using inline Python for JSON rendering. Register command syntax: `portctl register <project> [--worktree <name>] [--ephemeral] <service...>`

- [ ] **Step 1: Create portbroker/portctl**

```bash
#!/usr/bin/env bash
set -euo pipefail

BROKER="http://localhost:9876"

usage() {
  cat <<'EOF'
portctl — portbroker CLI

Usage:
  portctl status
  portctl list
  portctl get <project> [<worktree>]
  portctl register <project> [--worktree <name>] [--ephemeral] <service> [<service>...]
  portctl deregister <project> [<worktree>]
  portctl cleanup
EOF
}

die() { echo "Error: $*" >&2; exit 1; }

require_daemon() {
  curl -sf "$BROKER/health" >/dev/null 2>&1 \
    || die "portbroker is not running. Start it: python3 ~/projects/infrastructure/portbroker/server.py &"
}

cmd_status() {
  if curl -sf "$BROKER/health" >/dev/null 2>&1; then
    echo "portbroker is running on port 9876"
  else
    echo "portbroker is NOT running"
    exit 1
  fi
}

cmd_list() {
  require_daemon
  curl -s "$BROKER/assignments" | python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)
entries = sorted(data['assignments'].items())
if not entries:
    print("No assignments.")
    sys.exit(0)
col1 = max(len(k) for k, _ in entries)
print(f"{'PROJECT:WORKTREE':<{col1}}  {'TYPE':<10}  PORTS")
print("-" * (col1 + 40))
for key, e in entries:
    t = "system" if key == "portbroker:system" else ("ephemeral" if e["ephemeral"] else "permanent")
    ports = ", ".join(f"{s}={p}" for s, p in e["ports"].items())
    print(f"{key:<{col1}}  {t:<10}  {ports}")
PYEOF
}

cmd_get() {
  require_daemon
  local project="${1:?Usage: portctl get <project> [<worktree>]}"
  local worktree="${2:-main}"
  curl -s "$BROKER/assignments/$project/$worktree" | python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)
if "error" in data:
    print(f"Error: {data['error']}", file=sys.stderr)
    sys.exit(1)
print(f"{data['project']}:{data['worktree']}  ({'ephemeral' if data['ephemeral'] else 'permanent'})")
for s, p in data["ports"].items():
    print(f"  {s}: {p}")
PYEOF
}

cmd_register() {
  require_daemon
  local project="${1:?Usage: portctl register <project> [--worktree <name>] [--ephemeral] <service...>}"
  shift
  local worktree="main"
  local ephemeral="false"
  local services=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --worktree) worktree="$2"; shift 2 ;;
      --ephemeral) ephemeral="true"; shift ;;
      *) services+=("$1"); shift ;;
    esac
  done

  [[ ${#services[@]} -gt 0 ]] || die "At least one service name is required"

  local svc_json
  svc_json=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1:]))" -- "${services[@]}")

  curl -s -X POST "$BROKER/register" \
    -H "Content-Type: application/json" \
    -d "{\"project\":\"$project\",\"worktree\":\"$worktree\",\"ephemeral\":$ephemeral,\"services\":$svc_json}" \
  | python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)
if "error" in data:
    print(f"Error: {data['error']}", file=sys.stderr)
    sys.exit(1)
print(f"Registered {data['project']}:{data['worktree']}  ({'ephemeral' if data['ephemeral'] else 'permanent'})")
for s, p in data["ports"].items():
    print(f"  {s}: {p}")
PYEOF
}

cmd_deregister() {
  require_daemon
  local project="${1:?Usage: portctl deregister <project> [<worktree>]}"
  local worktree="${2:-main}"
  curl -s -X DELETE "$BROKER/deregister" \
    -H "Content-Type: application/json" \
    -d "{\"project\":\"$project\",\"worktree\":\"$worktree\"}" \
  | python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)
if "error" in data:
    print(f"Error: {data['error']}", file=sys.stderr)
    sys.exit(1)
print(data.get("message", "Done"))
PYEOF
}

cmd_cleanup() {
  require_daemon
  curl -s -X POST "$BROKER/cleanup" | python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)
removed = data.get("removed", [])
if removed:
    print(f"Removed {len(removed)} ephemeral entr{'y' if len(removed)==1 else 'ies'}:")
    for k in removed:
        print(f"  {k}")
else:
    print("No ephemeral entries to remove.")
PYEOF
}

case "${1:-}" in
  status)     cmd_status ;;
  list)       cmd_list ;;
  get)        shift; cmd_get "$@" ;;
  register)   shift; cmd_register "$@" ;;
  deregister) shift; cmd_deregister "$@" ;;
  cleanup)    cmd_cleanup ;;
  -h|--help)  usage ;;
  *)          usage; exit 1 ;;
esac
```

- [ ] **Step 2: Make executable**

```bash
chmod +x portbroker/portctl
```

- [ ] **Step 3: Manually verify portctl**

Start the daemon, then test each command:

```bash
python3 portbroker/server.py &
sleep 0.5

./portbroker/portctl status
# Expected: portbroker is running on port 9876

./portbroker/portctl register gymscheduler --worktree main nginx postgres
# Expected: Registered gymscheduler:main (permanent) / nginx: 8080 / postgres: 5432

./portbroker/portctl register gymscheduler --worktree feature-x --ephemeral nginx
# Expected: Registered gymscheduler:feature-x (ephemeral) / nginx: 8081

./portbroker/portctl list
# Expected: table with portbroker:system, gymscheduler:main, gymscheduler:feature-x

./portbroker/portctl get gymscheduler main
# Expected: gymscheduler:main (permanent) / nginx: 8080 / postgres: 5432

./portbroker/portctl deregister gymscheduler feature-x
# Expected: deregistered gymscheduler:feature-x

./portbroker/portctl cleanup
# Expected: No ephemeral entries to remove.

kill %1
```

- [ ] **Step 4: Add portctl to PATH via symlink**

```bash
mkdir -p ~/.local/bin
ln -sf "$(pwd)/portbroker/portctl" ~/.local/bin/portctl
```

Verify `~/.local/bin` is in your PATH:
```bash
echo $PATH | grep -q '.local/bin' && echo "in PATH" || echo "NOT in PATH — add: export PATH=\"\$HOME/.local/bin:\$PATH\" to ~/.zshrc"
```

If not in PATH, add it to `~/.zshrc`:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

- [ ] **Step 5: Commit**

```bash
git add portbroker/portctl
git commit -m "feat: add portctl CLI script"
```

---

## Task 6: Auto-start

**Files:**
- Create: `portbroker/portbroker.service`
- Create: `portbroker/start.sh`

`start.sh` is a one-time install script. It detects systemd availability and installs the appropriate auto-start mechanism. Run it once after cloning the repo.

- [ ] **Step 1: Create portbroker/portbroker.service**

```ini
[Unit]
Description=portbroker — local port assignment daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/projects/infrastructure/portbroker/server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Create portbroker/start.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="portbroker"
SERVER="$SCRIPT_DIR/server.py"
LOG="$SCRIPT_DIR/portbroker.log"

has_systemd() {
  systemctl --user status >/dev/null 2>&1
}

install_systemd() {
  local service_dir="$HOME/.config/systemd/user"
  mkdir -p "$service_dir"
  cp "$SCRIPT_DIR/portbroker.service" "$service_dir/$SERVICE_NAME.service"
  systemctl --user daemon-reload
  systemctl --user enable "$SERVICE_NAME"
  systemctl --user start "$SERVICE_NAME"
  echo "portbroker installed as systemd user service."
  echo "It will start automatically on login."
  echo "Manage with: systemctl --user {status,stop,restart} portbroker"
}

install_zshrc() {
  local zshrc="$HOME/.zshrc"
  local marker="# portbroker auto-start"
  if grep -q "$marker" "$zshrc" 2>/dev/null; then
    echo "portbroker .zshrc guard already present."
    return
  fi
  cat >> "$zshrc" <<ZSHEOF

$marker
if ! curl -sf http://localhost:9876/health >/dev/null 2>&1; then
  nohup python3 $SERVER > $LOG 2>&1 &
fi
ZSHEOF
  echo "portbroker .zshrc guard added."
  echo "It will start automatically with each new shell session."
  echo "Start now with: python3 $SERVER &"
}

echo "Installing portbroker auto-start..."
if has_systemd; then
  install_systemd
else
  echo "systemd not available — using .zshrc fallback."
  install_zshrc
fi
```

- [ ] **Step 3: Make start.sh executable**

```bash
chmod +x portbroker/start.sh
```

- [ ] **Step 4: Run the install script**

```bash
./portbroker/start.sh
```

Expected: either "portbroker installed as systemd user service" or "portbroker .zshrc guard added".

- [ ] **Step 5: Verify auto-start is working**

If systemd was installed:
```bash
systemctl --user status portbroker
```
Expected: `Active: active (running)`

If .zshrc fallback was installed: open a new terminal and run:
```bash
curl -s http://localhost:9876/health
```
Expected: `{"status": "ok", ...}`

- [ ] **Step 6: Commit**

```bash
git add portbroker/portbroker.service portbroker/start.sh
git commit -m "feat: add auto-start via systemd or .zshrc fallback"
```

---

## Task 7: AGENTS.md

**Files:**
- Create: `docs/AGENTS.md`

This file is the canonical handoff document for any agent working in a project that needs to integrate with portbroker. It should be self-contained — an agent receiving this file as context should need nothing else to work with the port broker.

- [ ] **Step 1: Create docs/AGENTS.md**

```markdown
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
```

- [ ] **Step 2: Verify the file reads clearly**

```bash
cat docs/AGENTS.md
```

Read through it as if you were an agent with no prior context. Confirm every curl example is correct and complete.

- [ ] **Step 3: Commit**

```bash
git add docs/AGENTS.md
git commit -m "docs: add AGENTS.md agent integration guide"
```

---

## Task 8: Final Verification

No new files. Confirm everything works end-to-end before declaring done.

- [ ] **Step 1: Run the full test suite**

```bash
python3 -m unittest discover tests/ -v
```

Expected: all tests pass, no errors.

- [ ] **Step 2: Full end-to-end manual test**

```bash
# Confirm daemon is running (auto-started or start manually)
curl -s http://localhost:9876/health

# Register two projects
portctl register gymscheduler nginx postgres
portctl register colwellstanning nginx postgres vite

# Both nginx ports should differ
portctl list

# Register a worktree
portctl register gymscheduler --worktree feature-auth --ephemeral nginx postgres

# Verify three gymscheduler entries
curl -s http://localhost:9876/assignments/gymscheduler | python3 -m json.tool

# Deregister the worktree
portctl deregister gymscheduler feature-auth

# Open web UI in Windows browser: http://localhost:9876
# Verify: two projects visible, portbroker:system present, Remove works

# Cleanup (should be a no-op now)
portctl cleanup
```

- [ ] **Step 3: Confirm no port collisions in the output of portctl list**

```bash
portctl list | awk '{print $NF}' | tr ',' '\n' | grep -oP '=\K[0-9]+' | sort | uniq -d
```

Expected: no output (no duplicate ports).

- [ ] **Step 4: Final commit**

```bash
git add -A
git status  # should be clean already
git log --oneline
```

Expected: clean working tree. 7 commits visible.
