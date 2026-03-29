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

    def test_ui_returns_html(self):
        url = f'http://127.0.0.1:{self.port}/'
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            content_type = resp.headers.get('Content-Type', '')
            self.assertIn('text/html', content_type)
            body = resp.read().decode()
            self.assertIn('portbroker', body)
            self.assertIn('assignments', body)


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
