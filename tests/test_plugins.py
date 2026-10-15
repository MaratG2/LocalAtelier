import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from atelier.app import create_app
from atelier.generation import save_image, validate
from atelier.models import installed
from atelier.plugins import PluginRegistry, inside
from atelier.runtime import Runtime
from test_studio import FakeRuntime


MANIFEST = {
    'api_version': 1, 'id': 'example', 'name': 'Example', 'adapter': 'adapter.py',
    'models': [{'id': 'paint', 'name': 'Example paint', 'modes': ['t2i', 'edit'],
                'required_files': ['weights/test.bin'], 'max_references': 1,
                'image_options': {'strength': {'min': 0.1, 'max': 1, 'default': 0.4},
                                  'guidance': {'min': 1, 'max': 15, 'default': 6},
                                  'negative_prompt': {'default': ''}},
                'config': {'private_value': 'do-not-expose'}}]}

ADAPTER = '''
from PIL import Image
def install(root, model, run, progress):
    (root / 'weights').mkdir(exist_ok=True)
    (root / 'weights/test.bin').write_bytes(b'verified fixture')
def verify(root, model, progress):
    if (root / 'weights/test.bin').read_bytes() != b'verified fixture':
        raise ValueError('Bad test weights')
    return {'files': [{'name': 'weights/test.bin', 'hash': 'fixture'}]}
def generate(runtime, root, model, request, references, callback):
    callback('Fixture generation', 50)
    return Image.new('RGB', (request['width'], request['height'])), {'fixture': True}
'''


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'addons/example'
        self.folder.mkdir(parents=True)
        self.manifest = copy.deepcopy(MANIFEST)
        self.write_manifest()
        (self.folder / 'adapter.py').write_text(ADAPTER)
        self.app = create_app(project_root=self.root, runtime_factory=FakeRuntime)
        self.app.testing = True
        self.client = self.app.test_client()
        self.store = self.app.extensions['store']
        self.manager = self.app.extensions['models']
        self.model_id = 'addon.example.paint'

    def tearDown(self):
        self.app.extensions['jobs'].queue.join()
        self.temp.cleanup()

    def write_manifest(self):
        (self.folder / 'plugin.json').write_text(json.dumps(self.manifest))

    def operation(self, action):
        operation = {'model_id': self.model_id, 'action': action, 'status': 'running', 'logs': []}
        self.manager._operate(operation)
        return operation

    def request(self, **values):
        return {'model_id': self.model_id, 'prompt': 'A ceramic vase', 'project_id': 'inbox', **values}

    def test_discovery_has_no_code_execution_and_no_global_mutation(self):
        (self.folder / 'adapter.py').write_text("raise RuntimeError('must not execute during discovery')")
        registry = PluginRegistry(self.root)
        self.assertIn(self.model_id, registry.catalog)
        from atelier.catalog import CATALOG
        self.assertNotIn(self.model_id, CATALOG)
        with tempfile.TemporaryDirectory() as other:
            self.assertNotIn(self.model_id, PluginRegistry(other).catalog)

    def test_malformed_plugin_isolated_and_private_metadata_hidden(self):
        other = self.root / 'addons/broken'
        other.mkdir()
        (other / 'plugin.json').write_text('{invalid')
        response = self.client.post('/api/plugins/refresh')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['errors'][0]['id'], 'broken')
        models = self.client.get('/api/models').json
        self.assertTrue(any(m['id'] == 'qwen-image-2.1' for m in models))
        model = next(m for m in models if m['id'] == self.model_id)
        self.assertNotIn('private_value', json.dumps(model))
        self.assertFalse(any(key.startswith('_') for key in model))

    def test_adapter_supports_relative_imports_and_dataclasses(self):
        (self.folder / 'helper.py').write_text("VALUE = 'local helper'\n")
        (self.folder / 'adapter.py').write_text("from dataclasses import dataclass\nfrom .helper import VALUE\n@dataclass\nclass Config:\n    name: str = VALUE\n" + ADAPTER)
        self.client.post('/api/plugins/refresh')
        adapter = self.store.plugins.adapter(self.store.catalog[self.model_id])
        self.assertEqual(adapter.Config().name, 'local helper')

    def test_manifest_validation_and_paths(self):
        for change in ({'id': '../escape'}, {'adapter': '../outside.py'}, {'api_version': 2}):
            self.manifest = {**copy.deepcopy(MANIFEST), **change}
            self.write_manifest()
            registry = PluginRegistry(self.root)
            self.assertTrue(registry.errors)
            self.assertNotIn(self.model_id, registry.catalog)
        for path in ('../escape', 'C:/escape', 'nested/../../escape', 'nested\\escape'):
            with self.assertRaises(ValueError):
                inside(self.root, path)

    def test_validation_options_modes_and_style(self):
        request = validate(self.request(), self.store)
        self.assertEqual(request['model_options']['strength'], 0.4)
        for values in ({'strength': 2}, {'guidance': True}, {'guidance': float('nan')}, {'unknown': 2}, {'negative_prompt': []}):
            with self.assertRaises(ValueError):
                validate(self.request(model_options=values), self.store)
        with self.assertRaises(ValueError):
            validate(self.request(mode='reference'), self.store)
        asset = save_image(self.store, Image.new('RGB', (64, 64)), 'inbox', kind='reference', name='Style')
        self.store.execute('UPDATE projects SET style_reference_id=?,style_prompt=? WHERE id=?', (asset['id'], 'Warm light', 'inbox'))
        request = validate(self.request(), self.store)
        self.assertEqual(request['mode'], 't2i')
        self.assertIsNone(request['style_reference_id'])
        self.assertIn('Warm light', request['prompt'])
        request = validate(self.request(mode='edit', reference_ids=[asset['id']], model_options={'strength': 0.7}), self.store)
        self.assertEqual(request['model_options']['strength'], 0.7)

    def test_install_verify_changes_invalidate_and_delete_preserves_source(self):
        self.assertEqual(self.operation('install')['status'], 'complete')
        model = self.store.catalog[self.model_id]
        bundle = self.store.plugins.bundle(model)
        self.assertTrue(installed(model, bundle))
        self.manifest['models'][0]['steps'] = 20
        self.write_manifest()
        self.client.post('/api/plugins/refresh')
        self.assertFalse(installed(self.store.catalog[self.model_id], bundle))
        self.assertEqual(self.operation('verify')['status'], 'complete')
        self.manager.remove(self.model_id)
        self.assertFalse(bundle.exists())
        self.assertTrue((self.folder / 'adapter.py').is_file())

    def test_failed_verification_clears_verified_flag(self):
        self.operation('install')
        (self.store.plugins.bundle(self.store.catalog[self.model_id]) / 'weights/test.bin').write_bytes(b'corrupt')
        self.assertEqual(self.operation('verify')['status'], 'error')
        self.assertIsNone(self.manager.record(self.model_id)['verified'])

    def test_delete_refuses_foreign_database_path(self):
        self.operation('install')
        self.store.execute('UPDATE models SET runtime_path=? WHERE id=?', (str(self.root / 'outside'), self.model_id))
        with self.assertRaises(ValueError):
            self.manager.remove(self.model_id)
        self.assertTrue(self.store.plugins.bundle(self.store.catalog[self.model_id]).exists())

    def test_refresh_blocked_by_jobs_and_temporary_mode(self):
        self.store.execute("INSERT INTO jobs(id,project_id,model_id,status,phase,total,request,created,updated) VALUES('pending','inbox',?,'queued','Queued',1,'{}',?,?)", (self.model_id, time.time(), time.time()))
        self.assertEqual(self.client.post('/api/plugins/refresh').status_code, 400)
        with patch.object(self.app.extensions['runtime'], 'lock', create=True) as runtime_lock:
            runtime_lock.__enter__.side_effect = AssertionError('Busy scan must not wait on the GPU lock')
            self.assertEqual(self.client.post('/api/plugins/refresh').status_code, 400)
        self.store.execute('DELETE FROM jobs')
        response = self.client.post('/api/temporary')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post('/api/plugins/refresh').status_code, 400)
        self.client.delete('/api/temporary')

    def test_changed_manifest_is_rejected_before_job_is_saved(self):
        self.operation('install')
        self.manifest['models'][0]['steps'] = 20
        self.write_manifest()
        self.client.post('/api/plugins/refresh')
        response = self.client.post('/api/jobs', json=self.request())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/jobs').json, [])

    def test_runtime_switches_and_uses_session_root(self):
        self.operation('install')
        runtime = Runtime(self.store)
        runtime.active_model = 'qwen-image-2.1'
        try:
            with patch.object(runtime, 'release', wraps=runtime.release) as release:
                image, metadata = runtime.generate(validate(self.request(), self.store), [], lambda *args: None)
                release.assert_called_once()
                self.assertEqual(runtime.active_model, self.model_id)
                self.assertEqual(image.size, (1024, 1024))
                self.assertTrue(metadata['fixture'])
        finally:
            runtime.release()


if __name__ == '__main__':
    unittest.main()
