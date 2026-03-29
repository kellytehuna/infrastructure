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
