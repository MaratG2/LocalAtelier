"""Masked edits: guide diffusion locally and preserve the source outside the mask."""
import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import distance_transform_edt


def read_mask(store, request):
    asset = store.asset(request['edit_mask_id'])
    with Image.open(store.open_media(asset['filename'])) as image:
        return image.convert('L')


def inference_mask(store, request, size):
    mask = read_mask(store, request).resize(size, Image.Resampling.BILINEAR)
    # A little context beyond the final blend boundary avoids a hard denoising seam.
    radius = max(4, round(max(size) / 128))
    return mask.filter(ImageFilter.MaxFilter(radius * 2 + 1)).filter(ImageFilter.GaussianBlur(2))


def composite_edit(store, request, generated):
    source = store.asset(request['reference_ids'][0])
    with Image.open(store.open_media(source['filename'])) as image:
        original = image.convert('RGBA')
    mask = np.asarray(read_mask(store, request), dtype=np.float32) / 255
    distance = distance_transform_edt(np.pad(mask > 0, 1))[1:-1, 1:-1]
    feather = request.get('mask_feather', 12) * max(original.size) / 1024
    alpha = mask.copy()
    if feather:
        transition = np.clip(distance / (feather + 1), 0, 1)
        alpha *= transition * transition * (3 - 2 * transition)
    original_pixels = np.asarray(original, dtype=np.float32)
    edited = np.asarray(generated.convert('RGBA').resize(original.size, Image.Resampling.LANCZOS), dtype=np.float32).copy()
    # Match only a narrow boundary's color bias. Preserve the intended interior
    # change instead of applying whole-patch histogram or contrast matching.
    ring = (mask > .5) & (distance <= max(2, feather))
    if feather and np.count_nonzero(ring) >= 16:
        correction = np.clip(np.median(original_pixels[ring, :3] - edited[ring, :3], axis=0), -32, 32)
        edited[:, :, :3] += correction * (1 - alpha[:, :, None])
    result = np.clip(np.rint(original_pixels * (1 - alpha[:, :, None]) + edited * alpha[:, :, None]), 0, 255).astype(np.uint8)
    result[mask == 0] = np.asarray(original)[mask == 0]
    return Image.fromarray(result), {'source_id': source['id'], 'mask_id': request['edit_mask_id'],
                                    'feather': request.get('mask_feather', 12), 'preserved_outside_mask': True}
