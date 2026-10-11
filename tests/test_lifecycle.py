import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from atelier.lifecycle import InstanceLock, ManagedLifecycle, RESTART_EXIT, read_json, source_stamp, write_json
from test_studio import StudioTests as StudioFixture
import launcher


class LifecycleTests(unittest.TestCase):
    setUp = StudioFixture.setUp
    tearDown = StudioFixture.tearDown
    register_model = StudioFixture.register_model
    request = StudioFixture.request

    def lifecycle(self):
        folder = self.root / 'control'
        identity = {'session_id': 'test-session', 'instance_id': 'test-instance', 'port': 7879}
        return ManagedLifecycle(self.app, self.root, folder, identity), folder

    def command(self, folder, action='restart', session='test-session'):
        write_json(folder / 'command.json', {'id': 'request', 'session_id': session, 'action': action})

    def test_restart_drains_admission_before_shutdown(self):
        self.register_model()
        lifecycle, folder = self.lifecycle()
        self.command(folder)
        server = Mock()
        self.assertTrue(lifecycle.poll(server))
        server.shutdown.assert_called_once()
        self.assertEqual(lifecycle.exit_code, RESTART_EXIT)
        self.assertEqual(read_json(folder / 'state.json')['state'], 'restarting')
        self.assertEqual(self.client.post('/api/jobs', json=self.request()).status_code, 503)
        with self.assertRaisesRegex(ValueError, 'updating'):
            self.app.extensions['jobs'].submit(self.request())
        with self.assertRaisesRegex(ValueError, 'updating'):
            self.models.start('qwen-image-2.1', 'verify')

    def test_running_generation_finishes_before_restart(self):
        self.register_model()
        self.runtime.gate.clear()
        self.client.post('/api/jobs', json=self.request())
        lifecycle, folder = self.lifecycle()
        self.command(folder)
        server = Mock()
        self.assertFalse(lifecycle.poll(server))
        self.assertEqual(read_json(folder / 'state.json')['reason'], 'Waiting for generation to finish')
        server.shutdown.assert_not_called()
        self.runtime.gate.set()
        self.app.extensions['jobs'].queue.join()
        self.assertTrue(lifecycle.poll(server))
        self.assertEqual(self.client.get('/api/jobs').json[0]['status'], 'complete')

    def test_model_operations_and_private_results_defer_stop(self):
        lifecycle, folder = self.lifecycle()
        self.command(folder, 'stop')
        server = Mock()
        self.models.operations['install'] = {'status': 'running'}
        self.assertFalse(lifecycle.poll(server))
        self.models.operations.clear()
        self.client.post('/api/temporary')
        self.assertFalse(lifecycle.poll(server))
        self.assertIn('incognito', read_json(folder / 'state.json')['reason'])
        self.client.delete('/api/temporary')
        self.assertTrue(lifecycle.poll(server))
        self.assertEqual(lifecycle.exit_code, 0)

    def test_source_changes_reload_only_after_debounce(self):
        (self.root / 'run.py').write_text('# old')
        lifecycle, folder = self.lifecycle()
        server = Mock()
        with patch('atelier.lifecycle.time.monotonic', return_value=10):
            (self.root / 'run.py').write_text('# changed')
            self.assertFalse(lifecycle.poll(server))
        with patch('atelier.lifecycle.time.monotonic', return_value=12):
            self.assertFalse(lifecycle.poll(server))
        with patch('atelier.lifecycle.time.monotonic', return_value=14):
            self.assertTrue(lifecycle.poll(server))
        self.assertEqual(lifecycle.exit_code, RESTART_EXIT)

    def test_stale_or_partial_command_does_not_stop_server(self):
        lifecycle, folder = self.lifecycle()
        self.command(folder, session='an-old-launcher')
        server = Mock()
        self.assertFalse(lifecycle.poll(server))
        (folder / 'command.json').write_text('{unfinished')
        self.assertFalse(lifecycle.poll(server))
        server.shutdown.assert_not_called()


class LauncherSafetyTests(unittest.TestCase):
    def test_single_instance_lock_recovers_after_close(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lock'
            with InstanceLock(path):
                with self.assertRaises(RuntimeError):
                    with InstanceLock(path):
                        self.fail('A second instance acquired the same lock')
            with InstanceLock(path):
                pass

    def test_source_monitor_ignores_private_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'atelier').mkdir()
            (root / 'atelier' / 'app.py').write_text('# code')
            before = source_stamp(root)
            (root / 'private.png').write_bytes(b'private')
            self.assertEqual(source_stamp(root), before)
            (root / 'atelier' / 'new.py').write_text('# new code')
            self.assertNotEqual(source_stamp(root), before)

    def test_legacy_takeover_refuses_a_different_workspace(self):
        with patch('launcher.status', return_value={'name': 'Local Atelier', 'data_path': '/other/data'}), patch('launcher.psutil.Process') as process:
            with self.assertRaisesRegex(RuntimeError, 'left running'):
                launcher.migrate_legacy(7870, launcher.ROOT / 'data')
            process.assert_not_called()

    def test_legacy_identity_requires_script_and_working_directory(self):
        process = Mock()
        process.cwd.return_value = str(launcher.ROOT)
        process.cmdline.return_value = ['python.exe', '-u', str(launcher.ROOT / 'run.py'), '--port', '7870']
        self.assertTrue(launcher.owned_process(process))
        process.cwd.return_value = str(launcher.ROOT.parent)
        self.assertFalse(launcher.owned_process(process))
        process.cwd.return_value = str(launcher.ROOT)
        process.cmdline.return_value = ['python.exe', '-u', 'other.py']
        self.assertFalse(launcher.owned_process(process))


del StudioFixture
