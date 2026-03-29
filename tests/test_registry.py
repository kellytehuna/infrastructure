import json
import os
import tempfile
import unittest
from unittest.mock import patch

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
        self.patcher = patch.object(Registry, '_system_ports', return_value=set())
        self.patcher.start()
        self.reg = Registry(self.path)
        self.reg.bootstrap()

    def tearDown(self):
        self.patcher.stop()

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
        self.patcher = patch.object(Registry, '_system_ports', return_value=set())
        self.patcher.start()
        self.reg = Registry(self.path)
        self.reg.bootstrap()

    def tearDown(self):
        self.patcher.stop()

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
