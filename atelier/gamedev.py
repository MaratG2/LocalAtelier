"""Grid-aware image requests and deterministic, engine-friendly exports."""
import io
import json
import zipfile

from PIL import Image


def validate_tool(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'kind', 'columns', 'rows', 'cell_size', 'fps', 'pixel_art', 'palette', 'generation', 'count', 'action', 'direction', 'custom_frames', 'seamless'}:
        raise ValueError('Unsupported game asset settings')
    if value.get('kind') not in {'tileset', 'spritesheet'}:
        raise ValueError('Choose tileset or sprite sheet')
    from .generation import integer
    result = {'kind': value['kind']}
    for name, default, low, high in [('columns', 4, 1, 8), ('rows', 4, 1, 8), ('cell_size', 32, 16, 256), ('fps', 8, 1, 30), ('palette', 32, 2, 256)]:
        result[name] = integer(value.get(name, default), name, low, high)
    result['pixel_art'] = value.get('pixel_art', True)
    if not isinstance(result['pixel_art'], bool):
        raise ValueError('Pixel art must be true or false')
    generation = value.get('generation', 'sheet')
    if generation not in ('sheet', 'individual'):
        raise ValueError('Unknown game generation method')
    result['generation'] = generation
    if generation == 'individual':
        action = value.get('action', 'idle' if result['kind'] == 'spritesheet' else 'variations')
        actions = {'idle', 'walk', 'attack', 'views', 'custom'} if result['kind'] == 'spritesheet' else {'variations', 'custom'}
        if not isinstance(action, str) or action not in actions:
            raise ValueError('Choose an available game asset preset')
        direction = value.get('direction', 'right')
        if direction not in ('front', 'right', 'back', 'left'):
            raise ValueError('Choose a character direction')
        custom = value.get('custom_frames', [])
        if not isinstance(custom, list) or len(custom) > 8 or any(not isinstance(v, str) or not v.strip() or len(v) > 800 for v in custom):
            raise ValueError('Describe up to 8 frames, one per line, using 1–800 characters each')
        count = len(custom) if action == 'custom' else 4 if action == 'views' else integer(value.get('count', 4), 'Frame count', 2, 8)
        if not count:
            raise ValueError('Describe at least one custom frame')
        seamless = value.get('seamless', True)
        if not isinstance(seamless, bool):
            raise ValueError('Seamless must be true or false')
        result.update(action=action, direction=direction, count=count, custom_frames=[v.strip() for v in custom],
                      seamless=seamless, columns=min(4, count), rows=(count + 3) // 4)
        # New tools use the shared Pixel finish exclusively; retain old fields
        # only to read and export legacy sheets without changing their appearance.
        result.pop('pixel_art')
        result.pop('palette')
    return result


def tool_prompt(tool):
    grid = f"Exactly {tool['columns']} columns and {tool['rows']} rows in an evenly spaced grid. No margins, gutters, borders, labels or text. Each cell is the same size."
    art = 'Crisp pixel art, consistent pixel scale, limited color palette, no antialiasing.' if tool['pixel_art'] else 'Consistent rendering style and palette.'
    if tool['kind'] == 'spritesheet':
        return f"Game character sprite sheet. {grid} Read animation frames from left to right, then top to bottom. Same character, proportions, camera, lighting, ground line and pivot in every cell; fully visible poses, no overlapping cells. {art}"
    return f"Top-down game terrain tileset. {grid} Each cell is one complete square tile. Consistent camera, scale and lighting. Matching edge colors and features for seamless repeating tiles; include terrain and transition variations. {art}"


def atlas_image(source, tool, pixelated=False, offsets=None):
    cols, rows, cell = tool['columns'], tool['rows'], tool['cell_size']
    atlas = Image.new('RGBA', (cols * cell, rows * cell))
    for y in range(rows):
        for x in range(cols):
            box = (round(x * source.width / cols), round(y * source.height / rows), round((x+1)*source.width/cols), round((y+1)*source.height/rows))
            frame = source.crop(box).convert('RGBA').resize((cell, cell), Image.Resampling.NEAREST if pixelated or tool.get('pixel_art') else Image.Resampling.LANCZOS)
            if tool.get('generation') == 'individual' and tool['kind'] == 'tileset' and tool.get('seamless'):
                # Resampling and Pixel finishing can separate previously matched
                # borders. Copy existing colors so the export stays in its palette.
                frame.paste(frame.crop((0, 0, 1, cell)), (cell - 1, 0))
                frame.paste(frame.crop((0, 0, cell, 1)), (0, cell - 1))
            if offsets:
                shifted = Image.new('RGBA', (cell, cell))
                dx, dy = offsets[y * cols + x] if y * cols + x < len(offsets) else (0, 0)
                shifted.paste(frame, (dx, dy))
                frame = shifted
            atlas.paste(frame, (x * cell, y * cell))
    if tool.get('pixel_art'):
        alpha = atlas.getchannel('A')
        atlas = atlas.convert('RGB').quantize(colors=tool['palette'], dither=Image.Dither.NONE).convert('RGBA')
        atlas.putalpha(alpha)
    return atlas


def export_bundle(store, asset, layout=None, options=None, preview=False):
    tool = validate_tool(asset['metadata'].get('game_asset'))
    if not tool:
        raise ValueError('This image has no game asset grid')
    from .generation import integer
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options) - {'cell_size', 'fps', 'offsets'}:
        raise ValueError('Unsupported game export settings')
    for name, low, high in [('cell_size', 16, 256), ('fps', 1, 30)]:
        if name in options:
            tool[name] = integer(options[name], name, low, high)
    count = tool.get('count', tool['columns'] * tool['rows'])
    offsets = options.get('offsets')
    if offsets is not None and (not isinstance(offsets, list) or len(offsets) != count or any(
            not isinstance(pair, list) or len(pair) != 2 or any(type(v) is not int or abs(v) > tool['cell_size'] for v in pair) for pair in offsets)):
        raise ValueError('Frame offsets must stay within one export cell')
    with Image.open(store.assets / asset['filename']) as source:
        atlas = atlas_image(source, tool, bool(asset['metadata'].get('pixelation')), offsets)
    if preview:
        return b'', atlas
    cols, rows, cell = tool['columns'], tool['rows'], tool['cell_size']
    buffer = io.BytesIO()
    def png(image):
        data = io.BytesIO(); image.save(data, 'PNG'); return data.getvalue()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('atlas.png', png(atlas))
        frames = {}
        for i in range(count):
            x, y = (i % cols) * cell, (i // cols) * cell
            name = f"{'tile' if tool['kind'] == 'tileset' else 'frame'}-{i:03}.png"
            archive.writestr('frames/' + name, png(atlas.crop((x, y, x+cell, y+cell))))
            frames[name] = {'frame': {'x': x, 'y': y, 'w': cell, 'h': cell}, 'rotated': False, 'trimmed': False,
                            'spriteSourceSize': {'x': 0, 'y': 0, 'w': cell, 'h': cell}, 'sourceSize': {'w': cell, 'h': cell}, 'duration': round(1000/tool['fps'])}
        archive.writestr('atlas.json', json.dumps({'frames': frames, 'meta': {'app': 'Local Atelier', 'image': 'atlas.png', 'size': {'w': atlas.width, 'h': atlas.height}, 'scale': '1', 'pivot': {'x': 0.5, 'y': 0.875}, 'frameTags': [{'name': tool.get('action', 'default'), 'from': 0, 'to': count-1, 'direction': 'forward'}]}}, indent=2))
        if tool['kind'] == 'tileset':
            tileset = {'type': 'tileset', 'version': '1.10', 'name': 'atelier', 'tilewidth': cell, 'tileheight': cell, 'tilecount': count, 'columns': cols, 'image': 'atlas.png', 'imagewidth': atlas.width, 'imageheight': atlas.height, 'margin': 0, 'spacing': 0}
            archive.writestr('tileset.tsj', json.dumps(tileset, indent=2))
            if layout is not None:
                if not isinstance(layout, list) or len(layout) != 144 or any(type(n) is not int or not 0 <= n <= count for n in layout):
                    raise ValueError('Tile map must contain 144 valid tile IDs')
                tilemap = {'type': 'map', 'version': '1.10', 'orientation': 'orthogonal', 'renderorder': 'right-down', 'width': 12, 'height': 12, 'tilewidth': cell, 'tileheight': cell, 'infinite': False, 'tilesets': [{'firstgid': 1, 'source': 'tileset.tsj'}], 'layers': [{'id': 1, 'type': 'tilelayer', 'name': 'Terrain', 'width': 12, 'height': 12, 'data': layout, 'opacity': 1, 'visible': True, 'x': 0, 'y': 0}]}
                archive.writestr('map.tmj', json.dumps(tilemap, indent=2))
        archive.writestr('README.txt', 'Local Atelier game asset export\nSource image is preserved in the studio. Frames are ordered left to right, then top to bottom. atlas.json uses Aseprite-style frame metadata with durations, an action tag and a normalized ground pivot at (0.5, 0.875). Configure your engine pivot as needed; JSON alone does not configure Unity or Godot imports. Tiles use Tiled JSON.\nReview motion, silhouette alignment and terrain transitions before production use. Matching opposite texture edges does not create automatic terrain adjacency.\n')
    return buffer.getvalue(), atlas
