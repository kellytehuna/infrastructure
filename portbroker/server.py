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
OPENAPI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'openapi.yaml')
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
        with self.lock:
            if key == 'portbroker:system':
                return False, 'protected'
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


def _build_docs_html():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>portbroker API</title>
  <style>
    body { margin: 0; padding: 0; background: #1e1e1e; }
  </style>
</head>
<body>
  <div id="redoc-container"></div>
  <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
  <script>
    Redoc.init('/openapi.yaml', {
      theme: {
        colors: { primary: { main: '#569cd6' } },
        typography: { fontFamily: 'monospace, monospace' },
        sidebar: { backgroundColor: '#1e1e1e', textColor: '#d4d4d4' },
        rightPanel: { backgroundColor: '#252525' }
      }
    }, document.getElementById('redoc-container'))
  </script>
</body>
</html>'''


def _make_handler(registry, openapi_path=OPENAPI_PATH):
    class PortBrokerHandler(BaseHTTPRequestHandler):
        _registry = registry
        _openapi_path = openapi_path

        def log_message(self, fmt, *args):
            pass  # suppress per-request console noise

        def do_GET(self):
            if self.path == '/':
                self._serve_ui()
            elif self.path == '/health':
                self._json({'status': 'ok', 'port': DAEMON_PORT})
            elif self.path == '/docs':
                self._serve_docs()
            elif self.path == '/openapi.yaml':
                self._serve_openapi()
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
            html = _build_ui_html()
            body = html.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_docs(self):
            html = _build_docs_html()
            body = html.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_openapi(self):
            if not os.path.exists(self._openapi_path):
                body = b'openapi.yaml not found. Run: portctl gendocs'
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            with open(self._openapi_path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/yaml')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return PortBrokerHandler


def run_server(host=DAEMON_HOST, port=DAEMON_PORT, registry_path=REGISTRY_PATH,
               openapi_path=OPENAPI_PATH, block=True):
    registry = Registry(registry_path)
    registry.bootstrap()
    server = HTTPServer((host, port), _make_handler(registry, openapi_path))
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
