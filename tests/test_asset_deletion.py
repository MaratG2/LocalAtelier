import json
import time
import unittest

from PIL import Image

from atelier.generation import save_image, validate
from atelier.storage import identifier
import test_studio as fixtures


class AssetDeletionTests(unittest.TestCase):
    setUp = fixtures.StudioTests.setUp
    tearDown = fixtures.StudioTests.tearDown
    register_model = fixtures.StudioTests.register_model
    request = fixtures.StudioTests.request
    upload = fixtures.StudioTests.upload

    def image(self, **kwargs):
        return save_image(self.store, Image.new('RGB', (64, 64)), 'inbox',
                          kind='generated', name='Disposable deletion fixture', **kwargs)

    def trash(self, asset):
        result = self.client.patch('/api/assets/' + asset['id'], json={'deleted': True})
        self.assertEqual(result.status_code, 200, result.json)

    def delete(self, asset):
        return self.client.delete('/api/assets/' + asset['id'])

    def job(self, assets, **values):
        job_id = identifier()
        self.store.execute("INSERT INTO jobs(id,project_id,model_id,status,phase,total,request,result_ids,created,updated) VALUES(?,'inbox','qwen-image-2.1',?,'Complete',?,'{}',?,?,?)",
                           (job_id, values.get('status', 'complete'), len(assets), json.dumps([a['id'] for a in assets]), time.time(), time.time()))
        return job_id

    def test_requires_trash_and_restore_preserves_files(self):
        image = self.image()
        self.assertEqual(self.delete(image).status_code, 400)
        self.trash(image)
        self.assertEqual(self.client.get('/api/assets').json, [])
        self.assertEqual(self.client.get('/api/assets?trash=true').json[0]['id'], image['id'])
        self.client.patch('/api/assets/' + image['id'], json={'deleted': False})
        with self.client.get(image['url']) as response:
            self.assertEqual(response.status_code, 200)
        self.trash(image)
        self.assertEqual(self.delete(image).status_code, 200)
        self.assertIsNone(self.store.asset(image['id']))
        self.assertEqual(list(self.store.assets.iterdir()), [])
        self.assertEqual(self.delete(image).status_code, 404)

    def test_removes_only_owned_files_and_last_batch_history(self):
        reference = self.upload()
        first, second = self.image(), self.image()
        mask = save_image(self.store, Image.new('L', (64, 64)), 'inbox', kind='mask', name='Selection', metadata={'source_id': first['id']})
        job_id = self.job([first, second])
        self.store.execute("UPDATE projects SET style_reference_id=? WHERE id='inbox'", (first['id'],))
        self.trash(first)
        self.assertEqual(self.delete(first).status_code, 200)
        self.assertEqual(self.store.job(job_id)['result_ids'], [second['id']])
        self.assertIsNone(self.store.asset(mask['id']))
        self.assertIsNone(self.store.project('inbox')['style_reference_id'])
        self.assertTrue(self.store.file_exists(reference['filename']))
        self.assertTrue(self.store.file_exists(second['filename']))
        self.trash(second)
        self.assertEqual(self.delete(second).status_code, 200)
        self.assertIsNone(self.store.job(job_id))

    def test_video_mesh_owned_directories_and_unrelated_files(self):
        for kind in ['video', 'mesh']:
            asset = self.image()
            self.store.execute('UPDATE assets SET kind=? WHERE id=?', (kind, asset['id']))
            self.store.write_file(asset['id'] + '/output.artifacts/latents.bin', b'fixture')
            self.store.write_file(asset['id'] + '/preview.png', b'fixture')
            self.trash(asset)
            self.assertEqual(self.delete(asset).status_code, 200)
            self.assertFalse((self.store.assets / asset['id']).exists())
        self.assertEqual(list(self.store.assets.iterdir()), [])

    def test_active_batch_output_and_reference_protected(self):
        image = self.image()
        job_id = self.job([image], status='running')
        self.assertEqual(self.client.patch('/api/assets/' + image['id'], json={'deleted': True}).status_code, 400)
        self.store.execute('UPDATE assets SET deleted=1 WHERE id=?', (image['id'],))
        self.assertEqual(self.delete(image).status_code, 400)
        self.store.execute("UPDATE jobs SET result_ids='[]',request=? WHERE id=?", (json.dumps({'reference_ids': [image['id']]}), job_id))
        self.assertEqual(self.delete(image).status_code, 400)
        self.assertTrue(self.store.file_exists(image['filename']))
        self.store.execute("UPDATE jobs SET status='complete' WHERE id=?", (job_id,))

    def test_private_deletion_removes_encrypted_blobs_and_survives_lock(self):
        public = self.image()
        password = 'disposable test passphrase'
        self.assertEqual(self.client.post('/api/personal/setup', json={'password': password}).status_code, 200)
        key = self.client.get_cookie('atelier_personal').value
        session = self.store.sessions[key]
        with self.store.use(key):
            image = self.image()
            job_id = self.job([image])
            self.store.write_file(image['id'] + '/output.artifacts/latents.bin', b'private fixture')
        names = [r['name'] for r in session.all('SELECT name FROM vault_files')]
        self.assertTrue(names)
        self.assertEqual(self.delete(public).status_code, 404)
        self.trash(image)
        self.assertEqual(self.delete(image).status_code, 200)
        self.assertTrue(all(not session.blob(name).exists() for name in names))
        self.assertEqual(session.all('SELECT name FROM vault_files'), [])
        self.client.post('/api/personal/lock')
        self.assertEqual(self.client.post('/api/personal/unlock', json={'password': password}).status_code, 200)
        self.assertEqual(self.client.get('/api/assets?trash=true').json, [])
        self.assertEqual(self.client.get('/api/assets/' + image['id']).status_code, 404)
        self.assertEqual(self.client.get('/api/jobs').json, [])
        self.client.post('/api/personal/lock')
        self.assertIsNotNone(self.store.asset(public['id']))

    def test_temporary_session_cannot_delete_borrowed_saved_asset(self):
        image = self.image()
        self.trash(image)
        self.assertEqual(self.client.post('/api/temporary').status_code, 200)
        self.assertEqual(self.delete(image).status_code, 404)
        self.assertTrue(self.store.durable.file_exists(image['filename']))
        self.client.delete('/api/temporary')

    def test_storage_rejects_path_escape(self):
        outside = self.root / 'keep.txt'
        outside.write_text('keep')
        with self.assertRaises(ValueError):
            self.store.remove_asset_files('../keep.txt')
        self.assertEqual(outside.read_text(), 'keep')

    def test_reused_style_and_references_reproduce_prompt_without_duplication(self):
        reference = self.upload()
        self.store.execute("UPDATE projects SET style_prompt='Original style',style_reference_id=? WHERE id='inbox'", (reference['id'],))
        original = validate(self.request(prompt='A vase'), self.store)
        self.store.execute("UPDATE projects SET style_prompt='Changed style',style_reference_id=NULL WHERE id='inbox'")
        reused = validate(self.request(prompt=original['user_prompt'], mode=original['mode'],
            reference_ids=original['reference_ids'], use_style=True, use_style_reference=False,
            style_prompt_override=original['style_prompt'], style_reference_override=original['style_reference_id']), self.store)
        self.assertEqual(reused['prompt'], original['prompt'])
        self.assertEqual(reused['reference_ids'], [reference['id']])
        disabled = validate(self.request(use_style=False, use_style_reference=False, style_prompt_override='Unused'), self.store)
        self.assertEqual(disabled['prompt'], self.request()['prompt'])
