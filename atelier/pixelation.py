"""Deterministic image finishing, independent of the GPU model."""

import numpy as np
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


def _edge_cells(padded, columns, rows, block):
    """Choose a color group per cell, keeping supported contrasting details.

    Two local clusters separate an outline/highlight from its background. A
    smaller cluster can win when it is a strong outlier in the surrounding cells
    and has enough connected pixels. Broad boundaries follow cell coverage;
    gentle shading keeps its average. Isolated noise cannot claim a whole cell.
    Process strips so large reference images do not create huge pixel tensors.
    """
    averaged = np.asarray(padded.resize((columns, rows), Image.Resampling.BOX)).astype(np.float32)
    coverage = averaged[..., 3:4] / 255 if padded.mode == 'RGBA' else np.ones((rows, columns, 1), np.float32)
    weighted = np.pad(averaged[..., :3] * coverage, ((1, 1), (1, 1), (0, 0)), mode='edge')
    coverage = np.pad(coverage, ((1, 1), (1, 1), (0, 0)), mode='edge')
    context = sum(weighted[y:y + rows, x:x + columns] for y in range(3) for x in range(3))
    context /= np.maximum(sum(coverage[y:y + rows, x:x + columns] for y in range(3) for x in range(3)), 1e-6)

    source = np.asarray(padded)
    result = np.empty((rows, columns, 3), dtype=np.uint8)
    strip_rows = max(1, 262144 // (columns * block * block))
    for start in range(0, rows, strip_rows):
        stop = min(start + strip_rows, rows)
        cells = source[start * block:stop * block].reshape(stop - start, block, columns, block, -1)
        cells = cells.transpose(0, 2, 1, 3, 4).reshape(-1, block * block, source.shape[2]).astype(np.float32)
        pixels = cells[..., :3]
        weights = cells[..., 3] / 255 if padded.mode == 'RGBA' else np.ones(cells.shape[:2], np.float32)
        total = weights.sum(axis=1)
        mean = (pixels * weights[..., None]).sum(axis=1) / np.maximum(total[:, None], 1e-6)
        indices = np.arange(len(cells))
        # Deterministic seeds; invisible colors never participate in clustering.
        first = pixels[indices, (((pixels - mean[:, None]) ** 2).sum(axis=2) * weights).argmax(axis=1)]
        second = pixels[indices, (((pixels - first[:, None]) ** 2).sum(axis=2) * weights).argmax(axis=1)]
        for _ in range(5):
            mask = ((pixels - first[:, None]) ** 2).sum(axis=2) <= ((pixels - second[:, None]) ** 2).sum(axis=2)
            mass = (weights * mask).sum(axis=1)
            first = (pixels * (weights * mask)[..., None]).sum(axis=1) / np.maximum(mass[:, None], 1e-6)
            second = (pixels * (weights * ~mask)[..., None]).sum(axis=1) / np.maximum((total - mass)[:, None], 1e-6)
            first = np.where((mass > 0)[:, None], first, mean)
            second = np.where((total > mass)[:, None], second, mean)

        def coherent(group):
            grid = (group & (weights >= 0.5)).reshape(-1, block, block)
            pairs = (grid[:, :, 1:] & grid[:, :, :-1]).sum(axis=(1, 2))
            pairs += (grid[:, 1:, :] & grid[:, :-1, :]).sum(axis=(1, 2))
            count = grid.sum(axis=(1, 2))
            return (count > 0) & (pairs >= count * 0.5)

        first_coherent, second_coherent = coherent(mask), coherent(~mask)
        local = context[start:stop].reshape(-1, 3)
        distance_first = ((first - local) ** 2).sum(axis=1)
        distance_second = ((second - local) ** 2).sum(axis=1)
        contrast = ((first - second) ** 2).sum(axis=1) > 70 ** 2
        # Reserve minority rescue for thin features. A loose context ratio also
        # expands/retracts broad shadow boundaries, producing one-cell teeth.
        keep_first = contrast & first_coherent & (mass >= total * 0.18) & (distance_first > distance_second * 8)
        keep_second = contrast & second_coherent & (total - mass >= total * 0.18) & (distance_second > distance_first * 8)
        choice = np.where(keep_first, True, np.where(keep_second, False, mass >= total / 2))
        rgb = np.where(choice[:, None], first, second)
        # Low-contrast ramps have no edge to snap: picking one half of their
        # colors biases the shading. Preserve their average, as with noise.
        rgb = np.where(((first_coherent | second_coherent) & contrast)[:, None], rgb, mean)
        result[start:stop] = np.rint(rgb).clip(0, 255).astype(np.uint8).reshape(stop - start, columns, 3)
    return result, averaged[..., 3] >= 128 if padded.mode == 'RGBA' else None


def _limit_palette(rgb, opaque, colors):
    """Build the palette, then match exact colors instead of octree bin labels.

    Exact matching avoids bright specks where nearly identical background
    colors straddle an octree boundary. Transparent cells do not bias training.
    """
    flat = rgb.reshape(-1, 3)
    visible = np.ones(len(flat), dtype=bool) if opaque is None else opaque.ravel()
    result = np.zeros_like(flat)
    if visible.any():
        samples = flat[visible]
        budget = colors - int(not visible.all())  # Reserve one transparent color.
        quantized = Image.fromarray(samples.reshape(-1, 1, 3)).quantize(
            colors=budget, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        palette = np.asarray(quantized.getpalette(), dtype=np.int32).reshape(-1, 3)
        palette = palette[[index for _, index in quantized.getcolors()]]
        reduced = np.empty_like(samples)
        for start in range(0, len(samples), 2048):
            chunk = samples[start:start + 2048].astype(np.int32)
            nearest = ((chunk[:, None] - palette) ** 2).sum(axis=2).argmin(axis=1)
            reduced[start:start + len(chunk)] = palette[nearest]
        result[visible] = reduced
    return Image.fromarray(result.reshape(rgb.shape))


def pixelate(image, settings):
    """Preserve contrasting features on a square grid without smoothing edges.

    Edge padding keeps cells square even for an odd-sized reference output.
    Color clusters are alpha-weighted; alpha coverage becomes a hard silhouette.
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
    rgb, opaque = _edge_cells(padded, columns, rows, block)
    reduced = _limit_palette(rgb, opaque, colors)
    if opaque is not None:
        reduced.putalpha(Image.fromarray(opaque.astype(np.uint8) * 255))
    result = reduced.resize(padded.size, Image.Resampling.NEAREST).crop((0, 0, width, height))
    return result, {**settings, 'grid_width': columns, 'grid_height': rows,
                    'algorithm': 'coverage-cluster-nearest-v3', 'hard_alpha': has_alpha}
