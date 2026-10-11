import io
import json
import unittest
from unittest.mock import patch

from PIL import Image

from atelier.pixelation import pixelate
from test_studio import StudioTests as StudioFixture


class PixelationTests(unittest.TestCase):
    def test_square_blocks_palette_dimensions_and_determinism(self):
        source = Image.new('RGB', (67, 49))
        source.putdata([((x * 13) % 256, (y * 19) % 256, (x * y) % 256)
                        for y in range(49) for x in range(67)])
        original = source.tobytes()
        result, metadata = pixelate(source, {'block_size': 8, 'colors': 16})
        self.assertEqual(result.size, source.size)
        self.assertEqual((metadata['grid_width'], metadata['grid_height']), (9, 7))
        self.assertEqual(metadata['algorithm'], 'edge-cluster-nearest-v2')
        self.assertLessEqual(len(result.getcolors()), 16)
        for y in range(0, 49, 8):
            for x in range(0, 67, 8):
                cell = result.crop((x, y, min(x + 8, 67), min(y + 8, 49)))
                self.assertEqual(len(cell.getcolors()), 1)
        again, _ = pixelate(source, {'block_size': 8, 'colors': 16})
        self.assertEqual(result.tobytes(), again.tobytes())
        self.assertEqual(source.tobytes(), original)

    def test_incoherent_noise_is_averaged_instead_of_becoming_false_edges(self):
        source = Image.new('RGB', (8, 8))
        source.putdata([(255, 255, 255) if (x + y) % 2 else (0, 0, 0)
                        for y in range(8) for x in range(8)])
        result, _ = pixelate(source, {'block_size': 4, 'colors': 8})
        self.assertEqual(result.getcolors(), [(64, (128, 128, 128))])

    def test_thin_dark_outlines_and_bright_highlights_keep_their_contrast(self):
        for detail, background in (((15, 15, 15), (240, 240, 240)),
                                   ((240, 240, 240), (15, 15, 15))):
            with self.subTest(detail=detail):
                source = Image.new('RGB', (24, 24), background)
                # The line covers only a quarter of each cell, away from its center.
                source.paste(detail, (2, 0, 4, 24))
                result, _ = pixelate(source, {'block_size': 8, 'colors': 8})
                self.assertEqual(result.crop((0, 0, 8, 24)).getcolors(), [(192, detail)])
                self.assertEqual(result.crop((8, 0, 24, 24)).getcolors(), [(384, background)])

    def test_small_color_accents_survive_even_with_similar_brightness(self):
        detail, background = (210, 60, 40), (40, 110, 60)
        source = Image.new('RGB', (24, 24), background)
        source.paste(detail, (2, 0, 4, 24))
        result, _ = pixelate(source, {'block_size': 8, 'colors': 8})
        self.assertEqual(result.getpixel((0, 0)), detail)
        self.assertEqual(result.getpixel((8, 0)), background)

    def test_isolated_specks_do_not_turn_into_large_outline_blocks(self):
        source = Image.new('RGB', (24, 24), (240, 240, 240))
        source.putpixel((3, 3), (0, 0, 0))
        result, _ = pixelate(source, {'block_size': 8, 'colors': 8})
        self.assertEqual(result.getcolors(), [(576, (240, 240, 240))])

    def test_nearby_background_colors_do_not_pick_a_distant_palette_color(self):
        source = Image.new('RGB', (64, 8))
        colors = [(191, 191, 191), (192, 192, 192), (193, 193, 193),
                  (245, 245, 245), (15, 15, 15), (220, 160, 30), (90, 110, 25), (100, 70, 55)]
        for index, color in enumerate(colors):
            source.paste(color, (index * 8, 0, index * 8 + 8, 8))
        result, _ = pixelate(source, {'block_size': 8, 'colors': 4})
        palette = [color for _, color in result.getcolors()]
        for index, color in enumerate(colors):
            distance = lambda candidate: sum((a - b) ** 2 for a, b in zip(candidate, color))
            self.assertEqual(distance(result.getpixel((index * 8, 0))), min(map(distance, palette)))

    def test_alpha_is_hard_without_hidden_color_halos(self):
        source = Image.new('RGBA', (24, 8), (0, 0, 255, 0))
        source.paste((255, 0, 0, 255), (0, 0, 12, 8))
        result, info = pixelate(source, {'block_size': 8, 'colors': 8})
        self.assertTrue(info['hard_alpha'])
        self.assertEqual(result.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(result.getpixel((8, 0)), (255, 0, 0, 255))
        self.assertEqual(result.getpixel((16, 0))[3], 0)
        self.assertEqual(set(result.getchannel('A').tobytes()), {0, 255})

    def test_transparent_palette_input_and_subpixel_image(self):
        source = Image.new('P', (1, 1))
        source.info['transparency'] = 0
        result, _ = pixelate(source, {'block_size': 32, 'colors': 2})
        self.assertEqual(result.size, (1, 1))
        self.assertEqual(result.mode, 'RGBA')
        self.assertEqual(result.getpixel((0, 0))[3], 0)


class PixelationQueueTests(unittest.TestCase):
    setUp = StudioFixture.setUp
    tearDown = StudioFixture.tearDown
    register_model = StudioFixture.register_model
    request = StudioFixture.request
    upload = StudioFixture.upload

    def test_invalid_settings_rejected_before_queueing(self):
        for value in (False, [], 'yes', {'block_size': True}, {'block_size': 3},
                      {'colors': True}, {'colors': 1}, {'colors': 257},
                      {'colors': 32.5}, {'unknown': 8}):
            with self.subTest(value=value):
                response = self.client.post('/api/jobs', json=self.request(pixelation=value))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/jobs').json, [])

    def test_saved_batch_png_metadata_thumbnail_and_default_unchanged(self):
        self.register_model()
        source = Image.new('RGBA', (512, 512), (240, 80, 30, 128))
        with patch.object(self.runtime, 'generate', side_effect=lambda *args: (source, {})):
            for enabled in (True, False):
                values = {'pixelation': {'block_size': 8, 'colors': 32}} if enabled else {}
                response = self.client.post('/api/jobs', json=self.request(width=512, height=512, batch_size=2, **values))
                self.assertEqual(response.status_code, 202, response.json)
                self.app.extensions['jobs'].queue.join()
                job = self.store.job(response.json['id'])
                self.assertEqual(job['status'], 'complete', job)
                self.assertEqual(len(job['result_ids']), 2)
                for asset_id in job['result_ids']:
                    asset = self.store.asset(asset_id)
                    with Image.open(self.store.assets / asset['filename']) as image:
                        self.assertEqual(image.getpixel((0, 0))[3], 255 if enabled else 128)
                        embedded = json.loads(image.info['local_atelier'])
                        self.assertEqual('pixelation' in embedded, enabled)
                        if enabled:
                            self.assertEqual(embedded['settings']['pixelation'], values['pixelation'])
                            self.assertEqual(embedded['pixelation']['algorithm'], 'edge-cluster-nearest-v2')
                    sidecar = json.loads((self.store.assets / (asset_id + '.json')).read_text())
                    self.assertEqual(sidecar, embedded)
                    with Image.open(self.store.assets / asset['thumbnail']) as thumb:
                        self.assertEqual(thumb.getpixel((0, 0))[3], 255 if enabled else 128)
        self.assertEqual(source.getpixel((0, 0))[3], 128)

    def test_pixel_finish_works_with_hidream_references_and_game_grid(self):
        self.register_model('hidream-o1')
        reference = self.upload()
        data = self.request(model_id='hidream-o1', mode='reference', reference_ids=[reference['id']],
                            pixelation={}, game_asset={'kind': 'spritesheet', 'columns': 2, 'rows': 2})
        response = self.client.post('/api/jobs', json=data)
        self.assertEqual(response.status_code, 202, response.json)
        self.app.extensions['jobs'].queue.join()
        job = self.store.job(response.json['id'])
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(job['request']['pixelation'], {'block_size': 8, 'colors': 32})
        self.assertEqual(job['request']['reference_ids'], [reference['id']])

    def test_incognito_processed_output_is_scoped_and_cleaned(self):
        self.register_model()
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        response = self.client.post('/api/jobs', json=self.request(pixelation={'block_size': 16, 'colors': 16}))
        self.assertEqual(response.status_code, 202, response.json)
        self.app.extensions['jobs'].queue.join()
        asset = self.client.get('/api/assets').json[0]
        self.assertTrue(asset['temporary'])
        download = self.client.get(asset['url'])
        with Image.open(io.BytesIO(download.data)) as result:
            self.assertEqual(json.loads(result.info['local_atelier'])['pixelation']['block_size'], 16)
        download.close()
        self.assertEqual(self.store.durable.all('SELECT * FROM assets'), [])
        self.assertEqual(self.client.delete('/api/temporary').status_code, 200)
        self.assertFalse(folder.exists())


del StudioFixture
