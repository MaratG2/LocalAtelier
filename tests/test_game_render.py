import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from atelier.game_render import frame_plan, seamless_tile
from atelier.gamedev import validate_tool, atlas_image
from test_studio import StudioTests as StudioFixture


class GameRenderTests(unittest.TestCase):
    setUp = StudioFixture.setUp
    tearDown = StudioFixture.tearDown
    register_model = StudioFixture.register_model
    request = StudioFixture.request
    upload = StudioFixture.upload

    def game(self, **values):
        return {'kind': 'spritesheet', 'generation': 'individual', 'count': 4, 'action': 'walk', 'direction': 'right', **values}

    def render(self, request, refs, callback):
        self.render_calls.append((request, [Path(p) for p in refs]))
        for ref in refs:
            self.assertTrue(Path(ref).exists())
        image = Image.new('RGBA', (request['width'], request['height']))
        ImageDraw.Draw(image).rectangle((180, 140, 310, 450), fill=(40 + len(self.render_calls), 90, 180, 255))
        return image, {'elapsed_seconds': 0.1}

    def submit(self, **values):
        self.register_model()
        self.render_calls = []
        with patch.object(self.runtime, 'generate', side_effect=self.render):
            response = self.client.post('/api/jobs', json=self.request(**{'width': 512, 'height': 512, 'game_asset': self.game(), **values}))
            self.assertEqual(response.status_code, 202, response.json)
            self.app.extensions['jobs'].queue.join()
        return self.store.job(response.json['id'])

    def test_individual_frames_anchor_alignment_seed_and_exact_atlas(self):
        job = self.submit(prompt='Blue mage', pixelation={'block_size': 8, 'colors': 16})
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(len(self.render_calls), 4)
        self.assertEqual([c[0]['seed'] for c in self.render_calls], [42, 43, 44, 45])
        self.assertEqual(self.render_calls[0][0]['mode'], 't2i')
        self.assertEqual([c[0]['mode'] for c in self.render_calls[1:]], ['reference'] * 3)
        self.assertTrue(all(c[0]['transparent_background'] for c in self.render_calls))
        self.assertIn('left foot forward', self.render_calls[0][0]['prompt'])
        self.assertIn('RIGHT boot far forward', self.render_calls[2][0]['prompt'])
        self.assertEqual(self.render_calls[1][1], self.render_calls[3][1])
        self.assertFalse(self.render_calls[1][1][0].exists())
        asset = self.store.asset(job['result_ids'][0])
        self.assertEqual((asset['width'], asset['height']), (2048, 512))
        self.assertEqual(asset['prompt'], 'Blue mage')
        self.assertEqual(asset['metadata']['game_pipeline'], 'individual-frames-v1')
        self.assertNotIn('pixel_art', asset['metadata']['game_asset'])
        with Image.open(self.store.assets / asset['filename']) as atlas:
            bottoms = [atlas.crop((i * 512, 0, (i + 1) * 512, 512)).getbbox()[3] for i in range(4)]
            self.assertEqual(len(set(bottoms)), 1)
            self.assertLessEqual(len(atlas.convert('RGB').getcolors()), 16)

    def test_custom_plan_and_views_are_explicit_and_bounded(self):
        tool = validate_tool(self.game(action='custom', custom_frames=['Draw weapon', 'Swing', 'Recover']))
        self.assertEqual(frame_plan(tool), ['Draw weapon', 'Swing', 'Recover'])
        self.assertEqual((tool['columns'], tool['rows'], tool['count']), (3, 1, 3))
        views = frame_plan(validate_tool(self.game(action='views', count=8)))
        self.assertEqual(len(views), 4)
        self.assertIn('back', views[2])
        for change in ({'count': 9}, {'action': 'custom', 'custom_frames': []}, {'action': 'custom', 'custom_frames': [' ']}, {'direction': 'invalid'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_tool(self.game(**change))

    def test_new_pipeline_rejects_unsupported_model_and_seed_overflow_before_queue(self):
        for values in ({'model_id': 'hidream-o1'}, {'seed': 4294967294}):
            response = self.client.post('/api/jobs', json=self.request(game_asset=self.game(), **values))
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/jobs').json, [])

    def test_opaque_frame_is_reported_instead_of_saving_a_broken_sheet(self):
        self.register_model()
        with patch.object(self.runtime, 'generate', return_value=(Image.new('RGB', (512, 512)), {})):
            response = self.client.post('/api/jobs', json=self.request(game_asset=self.game()))
            self.app.extensions['jobs'].queue.join()
        job = self.store.job(response.json['id'])
        self.assertEqual(job['status'], 'error')
        self.assertIn('transparent silhouette', job['error'])
        self.assertEqual(job['result_ids'], [])
        self.assertEqual(list((self.store.root / 'runtime/game-assets').iterdir()), [])

    def test_cancellation_stops_between_frames_without_partial_asset(self):
        self.register_model()
        def cancel(request, refs, progress):
            job = self.store.one("SELECT id FROM jobs WHERE status='running'")
            self.app.extensions['jobs'].cancel(job['id'])
            return Image.new('RGBA', (512, 512)), {}
        with patch.object(self.runtime, 'generate', side_effect=cancel):
            response = self.client.post('/api/jobs', json=self.request(game_asset=self.game()))
            self.app.extensions['jobs'].queue.join()
        job = self.store.job(response.json['id'])
        self.assertEqual(job['status'], 'cancelled')
        self.assertEqual(job['result_ids'], [])

    def test_export_overrides_change_pack_not_original(self):
        job = self.submit()
        asset_id = job['result_ids'][0]
        before = self.store.asset(asset_id)
        response = self.client.post(f'/api/assets/{asset_id}/game-export', json={'options': {
            'cell_size': 96, 'fps': 12, 'offsets': [[1, 0], [0, 0], [0, 0], [0, 0]]}})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as pack:
            with Image.open(io.BytesIO(pack.read('atlas.png'))) as image:
                self.assertEqual(image.size, (384, 96))
            data = json.loads(pack.read('atlas.json'))
            self.assertEqual(len(data['frames']), 4)
            self.assertEqual(data['frames']['frame-000.png']['duration'], 83)
            self.assertEqual(data['meta']['frameTags'][0]['name'], 'walk')
        self.assertEqual(self.store.asset(asset_id), before)
        bad = self.client.post(f'/api/assets/{asset_id}/game-export', json={'options': {'offsets': [[0, 0]]}})
        self.assertEqual(bad.status_code, 400)

    def test_batch_seeds_and_custom_frame_count_do_not_repeat_or_export_empty_cells(self):
        job = self.submit(batch_size=2, game_asset=self.game(action='custom', custom_frames=['Stand', 'Crouch', 'Jump', 'Land', 'Recover']))
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual([c[0]['seed'] for c in self.render_calls], list(range(42, 52)))
        self.assertEqual(len(job['result_ids']), 2)
        response = self.client.get(f"/api/assets/{job['result_ids'][0]}/game-export")
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.startswith('frames/')]), 5)

    def test_selected_character_cell_becomes_full_resolution_reference(self):
        job = self.submit()
        asset_id = job['result_ids'][0]
        before = self.store.asset(asset_id)
        response = self.client.post(f'/api/assets/{asset_id}/game-frame', json={'index': 2})
        self.assertEqual(response.status_code, 201, response.json)
        reference = self.store.asset(response.json['id'])
        self.assertEqual(reference['kind'], 'reference')
        self.assertEqual((reference['width'], reference['height']), (512, 512))
        self.assertEqual(reference['metadata']['source_frame'], 2)
        self.assertNotIn('game_asset', reference['metadata'])
        self.assertEqual(self.store.asset(asset_id), before)
        self.assertEqual(self.client.post(f'/api/assets/{asset_id}/game-frame', json={'index': 4}).status_code, 400)
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        private = self.client.post(f'/api/assets/{asset_id}/game-frame', json={'index': 0})
        self.assertEqual(private.status_code, 201, private.json)
        self.assertTrue(private.json['temporary'])
        self.assertIsNone(self.store.durable.asset(private.json['id']))
        self.client.delete('/api/temporary')
        self.assertFalse(folder.exists())

    def test_temporary_game_anchor_export_and_cleanup_stay_in_session(self):
        self.register_model()
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        self.render_calls = []
        with patch.object(self.runtime, 'generate', side_effect=self.render):
            response = self.client.post('/api/jobs', json=self.request(game_asset=self.game()))
            self.app.extensions['jobs'].queue.join()
        job = self.client.get('/api/jobs').json[0]
        self.assertEqual(job['status'], 'complete', job)
        self.assertTrue(self.render_calls[1][1][0].is_relative_to(folder))
        self.assertEqual(list((folder / 'runtime/game-assets').iterdir()), [])
        asset = self.client.get('/api/assets/' + job['result_ids'][0]).json
        self.assertTrue(asset['temporary'])
        export = self.client.post(f"/api/assets/{asset['id']}/game-export", json={'options': {'cell_size': 64}})
        self.assertEqual(export.status_code, 200)
        self.assertEqual(self.store.durable.all('SELECT * FROM assets'), [])
        self.assertEqual(self.store.durable.all('SELECT * FROM jobs'), [])
        self.client.delete('/api/temporary')
        self.assertFalse(folder.exists())

    def test_repeat_texture_has_matching_opposite_edges(self):
        rng = np.random.default_rng(4)
        source = Image.fromarray(rng.integers(0, 256, (64, 64, 3), dtype=np.uint8))
        result = np.asarray(seamless_tile(source))
        np.testing.assert_array_equal(result[0], result[-1])
        np.testing.assert_array_equal(result[:, 0], result[:, -1])

    def test_tile_export_keeps_edges_matching_after_pixel_resize(self):
        rng = np.random.default_rng(4)
        source = Image.fromarray(rng.integers(0, 256, (64, 128, 3), dtype=np.uint8))
        tool = validate_tool({'kind': 'tileset', 'generation': 'individual', 'action': 'variations', 'count': 2, 'cell_size': 48})
        for pixel in (False, True):
            atlas = np.asarray(atlas_image(source, tool, pixelated=pixel))
            for i in range(2):
                tile = atlas[:, i * 48:(i + 1) * 48]
                np.testing.assert_array_equal(tile[0], tile[-1])
                np.testing.assert_array_equal(tile[:, 0], tile[:, -1])


del StudioFixture
