"""Deterministic image finishing, independent of the GPU model."""

from PIL import Image


def validate_pixelation(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'block_size', 'colors'}:
        raise ValueError('Pixel settings must contain only pixel size and colors')
    block = value.get('block_size', 8)
    colors = value.get('colors', 32)
    if type(block) is not int or block not in (2, 4, 8, 16, 32):
        raise ValueError('Pixel size must be 2, 4, 8, 16 or 32')
    if type(colors) is not int or not 2 <= colors <= 256:
        raise ValueError('Pixel colors must be a whole number between 2 and 256')
    return {'block_size': block, 'colors': colors}


def pixelate(image, settings):
    """Average aligned square cells, limit colors, then enlarge without smoothing.

    Edge padding keeps cells square even for an odd-sized reference output.
    Alpha is averaged with premultiplied color, then snapped to a hard silhouette.
    The returned image keeps the source dimensions; the source is never mutated.
    """
    settings = validate_pixelation(settings)
    block, colors = settings['block_size'], settings['colors']
    width, height = image.size
    columns, rows = (width + block - 1) // block, (height + block - 1) // block
    has_alpha = 'A' in image.getbands() or 'transparency' in image.info
    source = image.convert('RGBA' if has_alpha else 'RGB')
    padded = Image.new(source.mode, (columns * block, rows * block))
    padded.paste(source, (0, 0))
    if padded.width > width:
        edge = source.crop((width - 1, 0, width, height))
        padded.paste(edge.resize((padded.width - width, height), Image.Resampling.NEAREST), (width, 0))
    if padded.height > height:
        edge = padded.crop((0, height - 1, padded.width, height))
        padded.paste(edge.resize((padded.width, padded.height - height), Image.Resampling.NEAREST), (0, height))
    small = padded.resize((columns, rows), Image.Resampling.BOX)
    rgb = small.convert('RGB')
    alpha = None
    if has_alpha:
        alpha = small.getchannel('A').point(lambda value: 255 if value >= 128 else 0)
        # Collapse hidden colors so they cannot fill the palette or bleed into edges.
        rgb.paste((0, 0, 0), mask=alpha.point(lambda value: 255 - value))
    reduced = rgb.quantize(colors=colors, method=Image.Quantize.FASTOCTREE,
                           dither=Image.Dither.NONE).convert('RGB')
    if alpha is not None:
        reduced.putalpha(alpha)
    result = reduced.resize(padded.size, Image.Resampling.NEAREST).crop((0, 0, width, height))
    return result, {**settings, 'grid_width': columns, 'grid_height': rows,
                    'algorithm': 'area-octree-nearest-v1', 'hard_alpha': has_alpha}
