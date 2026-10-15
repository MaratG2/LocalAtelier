import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from atelier.app import create_app
from atelier.catalog import CATALOG
from atelier.generation import save_image
from atelier.storage import Store
from atelier.runtime import Runtime


class FakeRuntime:
    def __init__(self, store):
        self.store = store
        self.worker_root = None
        self.active_model = None
        self.phase = 'Idle'
        self.calls = []
        self.releases = []
        self.gate = threading.Event()
        self.gate.set()

    def generate(self, request, refs, callback):
        self.calls.append((request, refs))
        self.worker_root = self.store.root / 'runtime'
        self.active_model = request['model_id']
        callback('Rendering', 50)
        self.gate.wait(10)
        return Image.new('RGBA', (request['width'], request['height']), (50, 100, 60, 128)), {'elapsed_seconds': 0.1}

    def release(self, model_id=None):
        self.releases.append(model_id)
        self.active_model = None
        self.worker_root = None

    def release_session(self, session_root):
        if self.worker_root == session_root / 'runtime':
            self.release()
        return True

    def logs(self):
        return {}


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(project_root=self.root, runtime_factory=FakeRuntime)
        self.app.testing = True
        self.client = self.app.test_client()
        self.store = self.app.extensions['store']
        self.models = self.app.extensions['models']
        self.runtime = self.app.extensions['runtime']

    def tearDown(self):
        self.runtime.gate.set()
        self.app.extensions['jobs'].queue.join()
        self.temp.cleanup()

    def register_model(self, model_id='qwen-image-2.1', root=None):
        bundle = root or self.root / 'models' / model_id
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / '.atelier-owned.json').write_text(json.dumps({'model_id':model_id}))
        self.store.execute('INSERT INTO models(id,source,runtime_path,linked,verified) VALUES(?,?,?,?,?)', (model_id,'managed',str(bundle),time.time(),time.time()))
        return bundle

    def request(self, **values):
        return {'project_id':'inbox','model_id':'qwen-image-2.1','prompt':'A green ceramic vase','seed':42,**values}

    def upload(self):
        buffer=io.BytesIO()
        Image.new('RGBA',(120,80),(10,80,50,128)).save(buffer,format='PNG')
        buffer.seek(0)
        response=self.client.post('/api/uploads',data={'image':(buffer,'reference.png')})
        self.assertEqual(response.status_code,201)
        return response.json

    def test_project_archive_restore_preserves_images(self):
        p=self.client.post('/api/projects',json={'name':'Study','description':'Materials'}).json
        a=save_image(self.store,Image.new('RGB',(64,64)),p['id'],kind='generated',name='Study')
        self.assertEqual(self.client.patch('/api/projects/'+p['id'],json={'archived':True}).status_code,200)
        self.assertEqual(self.client.get('/api/assets?project='+p['id']).json,[])
        self.assertEqual(self.client.get('/api/projects?archived=true').json[0]['asset_count'],1)
        self.client.patch('/api/projects/'+p['id'],json={'archived':False})
        self.assertEqual(self.client.get('/api/assets?project='+p['id']).json[0]['id'],a['id'])

    def test_default_project_cannot_be_archived(self):
        self.assertEqual(self.client.patch('/api/projects/inbox',json={'archived':True}).status_code,400)

    def test_generation_validation_rejects_bad_shapes_and_types(self):
        for values in ({'width':513},{'width':True},{'model_id':[]},{'project_id':{}},{'mode':[]}, {'batch_size':5},{'seed':4294967295,'batch_size':2},{'prompt':''},{'reference_ids':[None]}, {'mode':'edit'}, {'transparent_background':'yes'}):
            with self.subTest(values=values):
                self.assertEqual(self.client.post('/api/jobs',json=self.request(**values)).status_code,400)

    def test_hidream_does_not_claim_native_alpha(self):
        self.assertEqual(self.client.post('/api/jobs',json=self.request(model_id='hidream-o1',transparent_background=True)).status_code,400)

    def test_unknown_job_without_model_is_rejected(self):
        self.assertEqual(self.client.post('/api/jobs',json=self.request()).status_code,400)

    def test_unverified_weights_cannot_generate(self):
        self.register_model()
        self.store.execute('UPDATE models SET verified=NULL')
        self.assertEqual(self.client.post('/api/jobs',json=self.request()).status_code,400)

    def test_runtime_never_adopts_an_existing_server(self):
        runtime=Runtime(self.store)
        with patch('atelier.runtime.socket.socket') as socket_factory, patch('atelier.runtime.httpx.Client') as client, patch.object(runtime,'_start') as start:
            socket_factory.return_value.__enter__.return_value.bind.side_effect=OSError('occupied')
            with self.assertRaisesRegex(RuntimeError,'will not connect to another installation'):
                runtime.ensure('qwen-image-2.1',lambda *args:None)
            client.assert_not_called()
            start.assert_not_called()

    def test_upload_keeps_alpha_and_references_out_of_gallery(self):
        asset=self.upload()
        with Image.open(self.store.assets/asset['filename']) as im:
            self.assertEqual(im.getchannel('A').getextrema(),(128,128))
        self.assertEqual(self.client.get('/api/assets').json,[])

    def test_invalid_upload_is_useful_error(self):
        self.assertEqual(self.client.post('/api/uploads',data={'image':(io.BytesIO(b'not an image'),'x.png')}).status_code,400)

    def test_batch_seeds_metadata_and_alpha_survive_restart(self):
        self.register_model()
        job=self.client.post('/api/jobs',json=self.request(batch_size=2,transparent_background=True)).json
        self.app.extensions['jobs'].queue.join()
        saved=self.store.job(job['id'])
        self.assertEqual(saved['status'],'complete')
        self.assertEqual([c[0]['seed'] for c in self.runtime.calls],[42,43])
        restored=Store(self.store.root)
        self.assertEqual(len(restored.projects()),1)
        for asset_id in saved['result_ids']:
            asset=restored.asset(asset_id)
            self.assertTrue(asset['metadata']['settings']['transparent_background'])
            with Image.open(restored.assets/asset['filename']) as im:
                self.assertEqual(im.mode,'RGBA')
                self.assertIn('local_atelier',im.info)

    def test_active_references_cannot_be_trashed(self):
        self.register_model()
        ref=self.upload()
        self.runtime.gate.clear()
        self.client.post('/api/jobs',json=self.request(mode='edit',reference_ids=[ref['id']]))
        self.assertEqual(self.client.patch('/api/assets/'+ref['id'],json={'deleted':True}).status_code,400)

    def test_queued_model_cannot_be_removed_or_verified(self):
        self.register_model()
        self.runtime.gate.clear()
        self.client.post('/api/jobs',json=self.request())
        self.assertEqual(self.client.delete('/api/models/qwen-image-2.1',json={'confirmation':'Qwen-Image-2.1'}).status_code,400)
        self.assertEqual(self.client.post('/api/models/qwen-image-2.1/verify').status_code,400)
        self.assertEqual(self.client.post('/api/runtime/release').status_code,400)

    def test_queue_limit_and_cancellation(self):
        self.register_model()
        self.runtime.gate.clear()
        jobs=[self.client.post('/api/jobs',json=self.request(seed=i)) for i in range(4)]
        self.assertTrue(all(j.status_code==202 for j in jobs))
        self.assertEqual(self.client.post('/api/jobs',json=self.request()).status_code,400)
        last=jobs[-1].json['id']
        self.client.post('/api/jobs/'+last+'/cancel')
        self.runtime.gate.set()
        self.app.extensions['jobs'].queue.join()
        self.assertEqual(self.store.job(last)['status'],'cancelled')
        self.assertNotIn(3,[c[0]['seed'] for c in self.runtime.calls])

    def test_owned_delete_keeps_projects_and_assets(self):
        bundle=self.register_model()
        (bundle/'weight.bin').write_bytes(b'owned test model')
        ref=self.upload()
        self.assertEqual(self.client.delete('/api/models/qwen-image-2.1',json={'confirmation':'wrong'}).status_code,400)
        self.assertTrue(bundle.exists())
        self.assertEqual(self.client.delete('/api/models/qwen-image-2.1',json={'confirmation':'Qwen-Image-2.1'}).status_code,200)
        self.assertFalse(bundle.exists())
        self.assertTrue((self.store.assets/ref['filename']).exists())

    def test_delete_rejects_outside_path(self):
        outside=self.root/'unrelated'
        self.register_model(root=outside)
        self.assertEqual(self.client.delete('/api/models/qwen-image-2.1',json={'confirmation':'Qwen-Image-2.1'}).status_code,400)
        self.assertTrue(outside.exists())

    def test_delete_rejects_missing_marker(self):
        bundle=self.register_model()
        (bundle/'.atelier-owned.json').unlink()
        self.assertEqual(self.client.delete('/api/models/qwen-image-2.1',json={'confirmation':'Qwen-Image-2.1'}).status_code,400)
        self.assertTrue(bundle.exists())

    def test_verify_checks_publisher_hash_and_clears_bad_stamp(self):
        bundle=self.register_model()
        (bundle/'weights').mkdir()
        (bundle/'weights'/'test.bin').write_bytes(b'correct')
        file=SimpleNamespace(rfilename='test.bin',size=7,lfs=SimpleNamespace(sha256=hashlib.sha256(b'correct').hexdigest()))
        operation={'model_id':'qwen-image-2.1','logs':[]}
        with patch.object(self.models,'_hub_files',return_value=[file]),patch('atelier.models.installed',return_value=True):
            self.models._verify(operation)
            self.assertIsNotNone(self.models.record('qwen-image-2.1')['verified'])
            (bundle/'weights'/'test.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'Integrity mismatch'):
                self.models._verify(operation)
        self.assertIsNone(self.models.record('qwen-image-2.1')['verified'])

    def test_no_link_or_discovery_feature(self):
        self.assertEqual(self.client.post('/api/models/qwen-image-2.1/link',json={'path':'outside'}).status_code,400)
        self.assertEqual(self.client.get('/api/models/discover').status_code,404)
        self.assertFalse(any(m['source'] for m in self.client.get('/api/models').json))

    def test_cross_origin_write_and_untrusted_host_rejected(self):
        self.assertEqual(self.client.post('/api/projects',json={'name':'Unwanted'},headers={'Origin':'https://example.com'}).status_code,403)
        self.assertEqual(self.client.get('/api/projects',headers={'Host':'example.com'}).status_code,400)

    def test_bad_asset_move_is_client_error(self):
        a=self.upload()
        self.assertEqual(self.client.patch('/api/assets/'+a['id'],json={'project_id':{}}).status_code,400)

    def test_favorite_trash_restore(self):
        a=save_image(self.store,Image.new('RGB',(64,64)),'inbox',kind='generated',name='Test')
        self.client.patch('/api/assets/'+a['id'],json={'favorite':True})
        self.assertEqual(len(self.client.get('/api/assets?favorite=true').json),1)
        self.client.patch('/api/assets/'+a['id'],json={'deleted':True})
        self.assertEqual(self.client.get('/api/assets').json,[])
        self.assertEqual(len(self.client.get('/api/assets?trash=true').json),1)
        self.client.patch('/api/assets/'+a['id'],json={'deleted':False})
        self.assertEqual(len(self.client.get('/api/assets').json),1)


if __name__=='__main__':
    unittest.main()
