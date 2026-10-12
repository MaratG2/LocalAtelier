"""Generate isolated game frames, then assemble exact cells on the CPU."""
import math
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image


def frame_plan(tool):
    count, action = tool['count'], tool['action']
    if action == 'custom':
        return tool['custom_frames']
    if tool['kind'] == 'tileset':
        return [f'Texture variation {i + 1}: a distinct arrangement of the same terrain material, palette and scale.' for i in range(count)]
    if action == 'views':
        return [f'Neutral standing pose, {view} view.' for view in ('front', 'right side', 'back', 'left side')]
    if action == 'walk':
        phases = [
            'Contact pose: left foot forward on the ground, right foot behind; right arm forward.',
            'Down pose: weight moves onto left leg, knees bent slightly, right heel lifting.',
            'Passing pose: stand on ONE straight supporting left leg. Lift the RIGHT knee high in front; right boot is off the ground, directly under the bent knee. Feet are close together horizontally, NOT a wide stride. Raise the robe hem with the knee so the bent leg is visible.',
            'Up pose: right knee moving forward, left heel rising, body slightly raised.',
            'Opposite contact: long stride with RIGHT boot far forward and LEFT boot far behind, both on the ground. Left arm swings forward and right arm back. Reverse the limbs compared with the first contact pose.',
            'Opposite down: weight moves onto right leg, knees bent slightly, left heel lifting.',
            'Opposite passing: stand on ONE straight supporting right leg. Lift the LEFT knee high in front; left boot is off the ground, directly under the bent knee. Feet are close together horizontally, NOT a wide stride. Lift the left side of the robe to reveal the bent knee.',
            'Opposite up: left knee moving forward, right heel rising; prepare to return to first pose.',
        ]
        return [phases[min(7, math.floor(i * 8 / count))] for i in range(count)]
    if action == 'attack':
        phases = ['Ready stance, weapon held close.', 'Anticipation, draw the weapon back.',
                  'Strike, weapon extended toward the facing direction.', 'Recovery, return toward the ready stance.']
        return [phases[min(3, math.floor(i * 4 / count))] for i in range(count)]
    return [f'Idle breathing cycle, phase {i + 1} of {count}: '
            + ('relaxed neutral stance.' if i == 0 else 'subtle inhale, chest slightly raised.' if i < count / 2
               else 'gentle exhale, settle back toward the original stance.') for i in range(count)]


def seamless_tile(image):
    """Blend opposing border bands; their outermost pixel rows/columns match."""
    data = np.asarray(image.convert('RGB')).astype(np.float32)
    for axis in (1, 0):
        values = np.swapaxes(data, axis, 0)
        band = max(2, len(values) // 12)
        weight = (0.5 * (1 + np.cos(np.linspace(0, math.pi, band))) / 2)[:, None, None]
        first, last = values[:band].copy(), values[-band:][::-1].copy()
        values[:band] = first * (1 - weight) + last * weight
        values[-band:] = (last * (1 - weight) + first * weight)[::-1]
    return Image.fromarray(np.rint(data).clip(0, 255).astype(np.uint8)).convert('RGBA')


def align_frames(frames, cell):
    boxes = []
    for image in frames:
        alpha = image.getchannel('A')
        box = alpha.point(lambda value: 255 if value >= 32 else 0).getbbox()
        if box is None or alpha.getextrema()[0] >= 250:
            raise ValueError('A character frame has no usable transparent silhouette. Try a simpler character prompt or another seed.')
        boxes.append(box)
    # One shared scale preserves relative pose sizes. Every cell has the same
    # ground line; no independent stretching or rescaling of individual limbs.
    scale = min(cell * 0.78 / max(b[2] - b[0] for b in boxes), cell * 0.78 / max(b[3] - b[1] for b in boxes))
    result = []
    for image, box in zip(frames, boxes):
        sprite = image.crop(box)
        size = (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale)))
        sprite = sprite.resize(size, Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (cell, cell))
        canvas.paste(sprite, ((cell - sprite.width) // 2, round(cell * 0.875) - sprite.height))
        result.append(canvas)
    return result


def render_game(runtime, store, request, references, progress, cancelled):
    tool = request['game_asset']
    plan = frame_plan(tool)
    root = store.root / 'runtime' / 'game-assets'
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    frames, details = [], []
    character = tool['kind'] == 'spritesheet'
    cell = request['width']
    with tempfile.TemporaryDirectory(dir=root) as scratch:
        anchor = Path(scratch) / 'character.png'
        for i, pose in enumerate(plan):
            if cancelled():
                raise RuntimeError('Game generation cancelled')
            refs = [*references, anchor] if character and i else list(references)
            description = (
                'Render exactly ONE full-body game character, completely visible including feet and held items. '
                'One pose only. No sprite sheet, grid, multiple characters, labels, text, ground plane or cast shadow. '
                'Transparent background. Orthographic game camera, consistent scale and lighting. '
                + (f'Facing {tool["direction"]}. ' if tool['action'] != 'views' else '')
                + (f'Image {len(refs)} provides ONLY character appearance: same face, costume, colors and equipment. Its limb positions MUST change to the new pose. Redraw the legs, arms and clothing folds. ' if i else '')
                if character else
                'Render ONE square top-down game terrain texture filling the entire canvas edge to edge. '
                'No grid, individual tile borders, text, props or perspective. Same scale and lighting for the whole material. '
            )
            prompt = (f'Edit the character from image {len(refs)} into this NEW animation pose: {pose}\n\n' if character and i else f'Required pose: {pose}\n\n') + request['prompt'] + '\n\n' + description + '\nThe resulting pose must clearly show: ' + pose
            item = {**request, 'prompt': prompt, 'height': cell, 'seed': request['seed'] + i,
                    'mode': 'reference' if refs else 't2i', 'keep_original_aspect': False,
                    'transparent_background': character}
            image, metadata = runtime.generate(item, refs, lambda phase, value: progress(
                f'Generating frame {i + 1} of {len(plan)}', round((i * 96 + value * 0.96) / len(plan))))
            if cancelled():
                raise RuntimeError('Game generation cancelled')
            image = image.convert('RGBA')
            if i == 0 and character:
                image.save(anchor)
            frames.append(image)
            details.append({'index': i, 'seed': item['seed'], 'instruction': pose, 'elapsed_seconds': metadata.get('elapsed_seconds')})
        progress('Aligning and assembling frames', 97)
        if character:
            frames = align_frames(frames, cell)
        else:
            frames = [image.resize((cell, cell), Image.Resampling.LANCZOS) for image in frames]
            if tool['seamless']:
                frames = [seamless_tile(image) for image in frames]
        atlas = Image.new('RGBA', (tool['columns'] * cell, tool['rows'] * cell))
        for i, image in enumerate(frames):
            atlas.paste(image, ((i % tool['columns']) * cell, (i // tool['columns']) * cell))
        return atlas, {'elapsed_seconds': round(time.monotonic() - started, 2), 'mock_mode': False,
                       'game_pipeline': 'individual-frames-v1', 'frame_details': details,
                       'pivot': {'x': 0.5, 'y': 0.875}, 'width': atlas.width, 'height': atlas.height}
