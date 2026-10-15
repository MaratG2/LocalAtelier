import unittest
from unittest.mock import patch

from atelier.runtime import Runtime
import test_studio as studio_fixture


class RuntimeRetentionTests(unittest.TestCase):
    setUp = studio_fixture.StudioTests.setUp
    tearDown = studio_fixture.StudioTests.tearDown
    register_model = studio_fixture.StudioTests.register_model
    request = studio_fixture.StudioTests.request

    def render(self):
        response = self.client.post('/api/jobs', json=self.request())
        self.assertEqual(response.status_code, 202, response.json)
        self.app.extensions['jobs'].queue.join()
        # Job lists are scoped to the browser's workspace.
        rows = self.client.get('/api/jobs').json
        self.assertEqual(next(row for row in rows if row['id'] == response.json['id'])['status'], 'complete')

    def check_warm(self):
        self.register_model()
        self.render()
        self.render()
        self.assertEqual(len(self.runtime.calls), 2)
        self.assertEqual(self.runtime.releases, [])
        self.assertEqual(self.runtime.active_model, 'qwen-image-2.1')

    def test_regular_images_stay_loaded_and_toggle_does_not_release(self):
        self.check_warm()
        self.assertEqual(self.client.patch('/api/settings', json={'unload_after_job': False}).status_code, 200)
        self.assertEqual(self.runtime.releases, [])

    def test_incognito_stays_loaded_until_session_ends(self):
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        self.check_warm()
        self.client.delete('/api/temporary')
        self.assertEqual(len(self.runtime.releases), 1)
        self.assertFalse(folder.exists())

    def test_personal_stays_loaded_until_lock_and_results_are_saved(self):
        password = 'synthetic retention test passphrase'
        self.client.post('/api/personal/setup', json={'password': password})
        key = self.client.get_cookie('atelier_personal').value
        session = self.store.sessions[key]
        self.check_warm()
        self.assertEqual(list(session.assets.iterdir()), [])
        self.client.post('/api/personal/lock')
        self.assertEqual(len(self.runtime.releases), 1)
        self.assertFalse(session.root.exists())
        self.client.post('/api/personal/unlock', json={'password': password})
        self.assertEqual(len(self.client.get('/api/assets').json), 2)
        self.client.post('/api/personal/lock')

    def test_explicit_unload_setting_is_honored(self):
        self.store.set_setting('unload_after_job', True)
        self.client.post('/api/temporary')
        self.register_model()
        self.render()
        self.assertEqual(len(self.runtime.releases), 1)
        self.assertIsNone(self.runtime.active_model)
        self.client.delete('/api/temporary')

    def test_closing_one_session_does_not_release_another_worker(self):
        runtime = Runtime(self.store)
        runtime.worker_root = self.store.root / 'runtime'
        runtime.active_model = 'qwen-image-2.1'
        with patch.object(runtime, 'release') as release:
            self.assertTrue(runtime.release_session(self.store.root / 'temporary' / 'different-session'))
            release.assert_not_called()
            self.assertTrue(runtime.release_session(self.store.root))
            release.assert_called_once()
        runtime.release()

    def test_private_media_cleanup_keeps_model_cache(self):
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        runtime = Runtime(self.store)
        with self.store.use(key):
            runtime.active_model = 'qwen-image-2.1'
            for name in ('qwen-input', 'qwen-output', 'qwen-temp', 'cache'):
                folder = runtime.root / name
                folder.mkdir(parents=True)
                (folder / 'fixture').write_bytes(b'synthetic test content')
            runtime._clear_private_media()
            self.assertTrue((runtime.root / 'cache/fixture').is_file())
            self.assertEqual(list((runtime.root / 'qwen-output').iterdir()), [])
            self.assertEqual(runtime.active_model, 'qwen-image-2.1')
        runtime.release()
        self.client.delete('/api/temporary')
