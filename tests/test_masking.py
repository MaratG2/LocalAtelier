import io
import unittest

import numpy as np
from PIL import Image, ImageDraw

from atelier.generation import save_image
from atelier.masking import composite_edit, inference_mask
from atelier.providers.workflow import add_mask_nodes
import test_studio as studio_fixture


class MaskingTests(unittest.TestCase):
    setUp = studio_fixture.StudioTests.setUp
    tearDown = studio_fixture.StudioTests.tearDown
    register_model = studio_fixture.StudioTests.register_model
    request = studio_fixture.StudioTests.request

    def fixture(self):
        original = Image.new('RGBA', (128, 96), (70, 100, 140, 255))
        original.putpixel((0, 0), (20, 40, 70, 61))
        source = save_image(self.store, original, 'inbox', kind='reference', name='Synthetic fixture')
        mask = Image.new('L', original.size)
        ImageDraw.Draw(mask).rectangle((32, 20, 95, 75), fill=255)
        buffer = io.BytesIO(); mask.save(buffer, 'PNG'); buffer.seek(0)
        response = self.client.post('/api/edit-masks', data={'source_id': source['id'], 'mask': (buffer, 'mask.png')})
        self.assertEqual(response.status_code, 201, response.json)
        return original, source, mask, response.json

    def test_masked_job_preserves_pixels_and_source_dimensions(self):
        self.register_model()
        original, source, mask, saved_mask = self.fixture()
        result = self.client.post('/api/jobs', json=self.request(mode='edit', reference_ids=[source['id']], edit_mask_id=saved_mask['id'], mask_feather=16, width=512, height=512))
        self.assertEqual(result.status_code, 202, result.json)
        self.app.extensions['jobs'].queue.join()
        job = self.client.get('/api/jobs').json[0]
        self.assertEqual(job['status'], 'complete', job)
        result = self.store.asset(job['result_ids'][0])
        with Image.open(self.store.open_media(result['filename'])) as image:
            pixels = np.asarray(image)
        outside = np.asarray(mask) == 0
        self.assertTrue(np.array_equal(pixels[outside], np.asarray(original)[outside]))
        self.assertFalse(np.array_equal(pixels[48, 64], np.asarray(original)[48, 64]))
        self.assertEqual((result['width'], result['height']), original.size)
        self.assertEqual(len(self.client.get('/api/assets').json), 1)

    def test_mask_rejects_different_source_and_empty_selection(self):
        self.register_model()
        _, source, _, saved_mask = self.fixture()
        other = save_image(self.store, Image.new('RGB', (128, 96)), 'inbox', kind='reference', name='Other fixture')
        result = self.client.post('/api/jobs', json=self.request(mode='edit', reference_ids=[other['id']], edit_mask_id=saved_mask['id']))
        self.assertEqual(result.status_code, 400)
        empty = io.BytesIO(); Image.new('L', (128, 96)).save(empty, 'PNG'); empty.seek(0)
        self.assertEqual(self.client.post('/api/edit-masks', data={'source_id': source['id'], 'mask': (empty, 'empty.png')}).status_code, 400)

    def test_soft_edges_transition_and_inference_context(self):
        original, source, mask, saved_mask = self.fixture()
        request = {'edit_mask_id': saved_mask['id'], 'reference_ids': [source['id']], 'mask_feather': 32}
        generated = Image.new('RGBA', original.size, (180, 190, 200, 255))
        result, _ = composite_edit(self.store, request, generated)
        values = np.asarray(result)[48, 31:40, 0]
        self.assertEqual(values[0], 70)
        self.assertTrue(np.all(np.diff(values.astype(int)) >= 0))
        self.assertLess(values[1] - values[0], 20)
        self.assertEqual(result.getpixel((64, 48)), generated.getpixel((64, 48)))
        context = inference_mask(self.store, request, original.size)
        self.assertGreater(context.getpixel((30, 48)), 0)
        self.assertEqual(result.getpixel((30, 48)), original.getpixel((30, 48)))

    def test_masked_diffusion_uses_source_latents_and_white_channel(self):
        graph = {'7': {'inputs': {'latent_image': ['old', 0]}}}
        add_mask_nodes(graph, 'mask.png', 'source.png', ['vae', 0])
        self.assertEqual(graph['7']['inputs']['latent_image'], ['mask-noise', 0])
        self.assertEqual(graph['mask-latent']['inputs']['vae'], ['vae', 0])
        self.assertEqual(graph['mask-image']['inputs']['channel'], 'red')

    def test_personal_masks_are_encrypted_and_unavailable_outside_session(self):
        self.client.post('/api/personal/setup', json={'password': 'synthetic mask test password'})
        key = self.client.get_cookie('atelier_personal').value
        with self.store.use(key):
            _, _, _, saved_mask = self.fixture()
            self.assertEqual(list(self.store.assets.iterdir()), [])
            self.assertTrue(self.store.read_file(saved_mask['filename']).startswith(b'\x89PNG'))
        other = self.app.test_client()
        self.assertEqual(other.get(saved_mask['url']).status_code, 404)
        self.client.post('/api/personal/lock')
