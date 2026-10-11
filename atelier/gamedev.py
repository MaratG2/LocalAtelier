"""Grid-aware image requests and deterministic, engine-friendly exports."""
import io
import json
import zipfile

from PIL import Image


def validate_tool(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'kind', 'columns', 'rows', 'cell_size', 'fps', 'pixel_art', 'palette'}:
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
    return result


def tool_prompt(tool):
    grid = f"Exactly {tool['columns']} columns and {tool['rows']} rows in an evenly spaced grid. No margins, gutters, borders, labels or text. Each cell is the same size."
    art = 'Crisp pixel art, consistent pixel scale, limited color palette, no antialiasing.' if tool['pixel_art'] else 'Consistent rendering style and palette.'
    if tool['kind'] == 'spritesheet':
        return f"Game character sprite sheet. {grid} Read animation frames from left to right, then top to bottom. Same character, proportions, camera, lighting, ground line and pivot in every cell; fully visible poses, no overlapping cells. {art}"
    return f"Top-down game terrain tileset. {grid} Each cell is one complete square tile. Consistent camera, scale and lighting. Matching edge colors and features for seamless repeating tiles; include terrain and transition variations. {art}"


def atlas_image(source, tool):
    cols, rows, cell = tool['columns'], tool['rows'], tool['cell_size']
    atlas = Image.new('RGBA', (cols * cell, rows * cell))
    for y in range(rows):
        for x in range(cols):
            box = (round(x * source.width / cols), round(y * source.height / rows), round((x+1)*source.width/cols), round((y+1)*source.height/rows))
            frame = source.crop(box).convert('RGBA').resize((cell, cell), Image.Resampling.NEAREST if tool['pixel_art'] else Image.Resampling.LANCZOS)
            atlas.paste(frame, (x * cell, y * cell))
    if tool['pixel_art']:
        alpha = atlas.getchannel('A')
        atlas = atlas.convert('RGB').quantize(colors=tool['palette'], dither=Image.Dither.NONE).convert('RGBA')
        atlas.putalpha(alpha)
    return atlas


def export_bundle(store, asset, layout=None):
    tool = validate_tool(asset['metadata'].get('game_asset'))
    if not tool:
        raise ValueError('This image has no game asset grid')
    with Image.open(store.assets / asset['filename']) as source:
        atlas = atlas_image(source, tool)
    cols, rows, cell = tool['columns'], tool['rows'], tool['cell_size']
    buffer = io.BytesIO()
    def png(image):
        data = io.BytesIO(); image.save(data, 'PNG'); return data.getvalue()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('atlas.png', png(atlas))
        frames = {}
        for i in range(cols * rows):
            x, y = (i % cols) * cell, (i // cols) * cell
            name = f"{'tile' if tool['kind'] == 'tileset' else 'frame'}-{i:03}.png"
            archive.writestr('frames/' + name, png(atlas.crop((x, y, x+cell, y+cell))))
            frames[name] = {'frame': {'x': x, 'y': y, 'w': cell, 'h': cell}, 'rotated': False, 'trimmed': False,
                            'spriteSourceSize': {'x': 0, 'y': 0, 'w': cell, 'h': cell}, 'sourceSize': {'w': cell, 'h': cell}, 'duration': round(1000/tool['fps'])}
        archive.writestr('atlas.json', json.dumps({'frames': frames, 'meta': {'app': 'Local Atelier', 'image': 'atlas.png', 'size': {'w': atlas.width, 'h': atlas.height}, 'scale': '1', 'frameTags': [{'name': 'default', 'from': 0, 'to': cols*rows-1, 'direction': 'forward'}]}}, indent=2))
        if tool['kind'] == 'tileset':
            tileset = {'type': 'tileset', 'version': '1.10', 'name': 'atelier', 'tilewidth': cell, 'tileheight': cell, 'tilecount': cols*rows, 'columns': cols, 'image': 'atlas.png', 'imagewidth': atlas.width, 'imageheight': atlas.height, 'margin': 0, 'spacing': 0}
            archive.writestr('tileset.tsj', json.dumps(tileset, indent=2))
            if layout is not None:
                if not isinstance(layout, list) or len(layout) != 144 or any(type(n) is not int or not 0 <= n <= cols*rows for n in layout):
                    raise ValueError('Tile map must contain 144 valid tile IDs')
                tilemap = {'type': 'map', 'version': '1.10', 'orientation': 'orthogonal', 'renderorder': 'right-down', 'width': 12, 'height': 12, 'tilewidth': cell, 'tileheight': cell, 'infinite': False, 'tilesets': [{'firstgid': 1, 'source': 'tileset.tsj'}], 'layers': [{'id': 1, 'type': 'tilelayer', 'name': 'Terrain', 'width': 12, 'height': 12, 'data': layout, 'opacity': 1, 'visible': True, 'x': 0, 'y': 0}]}
                archive.writestr('map.tmj', json.dumps(tilemap, indent=2))
        archive.writestr('README.txt', 'Local Atelier game asset export\nSource image is preserved in the studio. Atlas cells are sampled from an even grid. Review alignment, animation poses and tile seams before production use.\nSprite frames: left to right, then top to bottom. atlas.json uses Aseprite-style frame metadata. Tiles use Tiled JSON. No AI seam or pose guarantee.\n')
    return buffer.getvalue(), atlas
