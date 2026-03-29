import os
import subprocess
import sys
import tempfile
import unittest

GENDOCS = os.path.join(os.path.dirname(__file__), '..', 'portbroker', 'gendocs.py')


class TestGendocs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.out = os.path.join(self.tmpdir, 'openapi.yaml')

    def _run(self):
        subprocess.run([sys.executable, GENDOCS, '--out', self.out], check=True)

    def test_creates_file(self):
        self._run()
        self.assertTrue(os.path.exists(self.out))

    def test_output_starts_with_openapi(self):
        self._run()
        with open(self.out) as f:
            content = f.read()
        self.assertTrue(content.startswith('openapi:'))

    def test_output_contains_all_paths(self):
        self._run()
        with open(self.out) as f:
            content = f.read()
        for path in ['/health', '/register', '/deregister', '/assignments', '/cleanup']:
            self.assertIn(path, content, f'Missing path: {path}')

    def test_output_contains_schemas(self):
        self._run()
        with open(self.out) as f:
            content = f.read()
        for schema in ['Assignment', 'RegisterRequest', 'DeregisterRequest', 'Error']:
            self.assertIn(schema, content, f'Missing schema: {schema}')


if __name__ == '__main__':
    unittest.main()
