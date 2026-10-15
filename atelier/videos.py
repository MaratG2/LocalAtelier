"""Owned video assets, bounded media inspection and H3 request validation."""
import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from .generation import integer
from .storage import identifier, now

QUALITIES = {'light': 8, 'medium': 12, 'high': 16, 'max': 20}
SIZES = {(896, 512), (512, 896), (512, 512), (1344, 768), (768, 1344), (768, 768)}
FORMATS = {'.mp4': 'mov', '.mov': 'mov', '.m4a': 'mov', '.webm': 'matroska', '.wav': 'wav', '.mp3': 'mp3', '.ogg': 'ogg', '.flac': 'flac'}


def validate_video(data, store):
    allowed = {'project_id', 'model_id', 'mode', 'prompt', 'width', 'height', 'seconds', 'seed', 'quality',
               'preview', 'first_id', 'last_id', 'reference_ids', 'source_video_id'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError('Unsupported video settings')
    project_id = data.get('project_id', 'inbox')
    project = store.project(project_id) if isinstance(project_id, str) else None
    if not project or project['archived']:
        raise ValueError('Select an active project')
    if data.get('model_id', 'vdn-h3') != 'vdn-h3':
        raise ValueError('Select VDN-H3')
    if data.get('mode') == 'finish':
        if set(data) - {'project_id', 'model_id', 'mode', 'source_video_id'}:
            raise ValueError('Finishing a preview preserves its original settings')
        source_id = data.get('source_video_id')
        source = store.asset(source_id) if isinstance(source_id, str) else None
        if not source or source['deleted'] or source['kind'] != 'video' or not source['metadata'].get('preview') or source['model_id'] != 'vdn-h3':
            raise ValueError('Choose a generated H3 preview to finish')
        folder = Path(source['filename']).with_suffix('.artifacts')
        if not all(store.file_exists(folder / name) for name in ('first-pass.pt', 'first-pass.engine.json', 'video.json', 'conditioning.pt')):
            raise ValueError('This preview no longer has its saved first pass; generate a new preview')
        result = dict(source['metadata']['settings'], project_id=project_id, mode='finish', preview=False, source_video_id=source_id)
        return result
    mode = data.get('mode', 'text')
    if not isinstance(mode, str) or mode not in {'text', 'frames', 'references'}:
        raise ValueError('Choose Text, Frames or References')
    prompt = data.get('prompt', '')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise ValueError('Describe your video using 1–12,000 characters')
    quality = data.get('quality', 'light')
    if not isinstance(quality, str) or quality not in QUALITIES:
        raise ValueError('Unknown quality preset')
    preview = data.get('preview', quality == 'light')
    if not isinstance(preview, bool) or (preview and quality != 'light'):
        raise ValueError('Preview first is available with Light quality')
    width = integer(data.get('width', 896), 'Width', 512, 1344)
    height = integer(data.get('height', 512), 'Height', 512, 1344)
    if (width, height) not in SIZES:
        raise ValueError('Choose a supported video size')
    seconds = integer(data.get('seconds', 5), 'Duration', 2, 10)
    seed = integer(data.get('seed', 42), 'Seed', 0, 4294967295)
    refs = data.get('reference_ids', [])
    if not isinstance(refs, list) or len(refs) > 12 or any(not isinstance(r, str) for r in refs) or len(set(refs)) != len(refs):
        raise ValueError('Use up to 12 distinct references')
    first, last = data.get('first_id'), data.get('last_id')
    if any(v is not None and not isinstance(v, str) for v in (first, last)):
        raise ValueError('Invalid frame reference')
    if (mode == 'text' and (refs or first or last)) or (mode == 'frames' and (refs or not (first or last))) or (mode == 'references' and (first or last or not refs)):
        raise ValueError('Text uses a prompt, Frames needs a first or last image, and References needs at least one input')
    counts = {'image': 0, 'video': 0, 'audio': 0}; lengths = {'video': 0., 'audio': 0.}
    for ref in refs + [v for v in (first, last) if v]:
        asset = store.asset(ref)
        if not asset or asset['deleted']:
            raise ValueError('A reference is unavailable')
        kind = media_kind(asset)
        if kind not in counts or (mode == 'frames' and kind != 'image'):
            raise ValueError('Keyframes require images; references accept images, video or audio')
        if asset['width'] * asset['height'] > 24_000_000:
            raise ValueError('Reference resolution is too large')
        counts[kind] += 1
        if kind in lengths:
            duration = asset['metadata'].get('duration', 0)
            if not 2 <= duration <= 15.1:
                raise ValueError('Video and audio references must be 2–15 seconds long')
            lengths[kind] += duration
            if kind == 'video' and asset['metadata'].get('has_audio'):
                lengths['audio'] += duration
    if counts['image'] > 9 or counts['video'] > 3 or counts['audio'] > 3 or any(t > 15.1 for t in lengths.values()):
        raise ValueError('Use up to 9 images, 3 videos and 3 audio clips, with at most 15 seconds of video and audio each')
    frames = math.ceil(seconds * 24); frames += (5 - frames) % 17
    return dict(project_id=project_id, model_id='vdn-h3', mode=mode, prompt=prompt.strip(), quality=quality,
                width=width, height=height, seconds=seconds, frames=frames, seed=seed, preview=preview,
                first_id=first, last_id=last, reference_ids=refs, batch_size=1)


def media_kind(asset):
    return 'image' if asset['kind'] in {'generated', 'reference'} else asset['metadata'].get('media_kind', asset['kind'])


def inspect_media(path, *, reference=False):
    import av
    try:
        with av.open(str(path), format=FORMATS[Path(path).suffix.lower()], options={'protocol_whitelist': 'file,pipe'}) as container:
            video = next(iter(container.streams.video), None)
            audio = next(iter(container.streams.audio), None)
            if not video and not audio:
                raise ValueError('No video or audio stream was found')
            duration = (container.duration or 0) / av.time_base
            if not math.isfinite(duration) or not 0 < duration <= (15.1 if reference else 12):
                raise ValueError('Use a clip up to 15 seconds long' if reference else 'Invalid generated video duration')
            if reference and duration < 2:
                raise ValueError('Reference clips must be at least 2 seconds long')
            width, height = (video.width, video.height) if video else (0, 0)
            if width * height > 3840 * 2160 or (video and (width < 16 or height < 16)):
                raise ValueError('Use reference video up to 4K')
            return dict(media_kind='video' if video else 'audio', duration=duration, width=width, height=height,
                        fps=float(video.average_rate or 24) if video else 0, frames=video.frames if video else 0,
                        has_audio=bool(audio), channels=audio.codec_context.channels if audio else 0,
                        sample_rate=audio.codec_context.sample_rate if audio else 0)
    except (av.error.FFmpegError, OSError) as error:
        raise ValueError('The media file could not be read; use MP4, WebM, MOV, WAV, MP3 or M4A') from error


def thumbnails(path, folder, info):
    import av
    if info['media_kind'] == 'audio':
        image = Image.new('RGB', (512, 288), '#e9eee7')
        draw = ImageDraw.Draw(image)
        for i in range(24):
            h = 20 + (i * 29 % 75)
            draw.rounded_rectangle((72+i*15, 144-h//2, 77+i*15, 144+h//2), 2, fill='#44634f')
        image.save(folder / 'poster.png'); return
    frames = []
    with av.open(str(path), format=FORMATS[Path(path).suffix.lower()], options={'protocol_whitelist': 'file,pipe'}) as container:
        stream = container.streams.video[0]
        for fraction in (0, .2, .4, .6, .8):
            target = info['duration'] * fraction
            container.seek(int(target * av.time_base))
            frame = None
            for candidate in container.decode(stream):
                frame = candidate
                if candidate.time is None or candidate.time >= target:
                    break
            if frame is None:
                continue
            image = frame.to_image(); image.thumbnail((512, 512))
            frames.append(image)
    if not frames:
        raise ValueError('The video contains no decodable frames')
    frames[0].save(folder / 'poster.png')
    filmstrip = Image.new('RGB', (160*len(frames), 90), '#17251d')
    from PIL import ImageOps
    for i, image in enumerate(frames):
        filmstrip.paste(ImageOps.fit(image, (160, 90)), (i*160, 0))
    filmstrip.save(folder / 'filmstrip.jpg', quality=85)


def register_video(store, asset_id, project_id, info, metadata, *, name, prompt='', model_id=None, seed=None, kind='video', filename='video.mp4'):
    folder = store.assets / asset_id
    thumbnails(folder / filename, folder, info)
    metadata = {**metadata, **info}
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    store.seal_folder(asset_id)
    store.execute('INSERT INTO assets(id,project_id,kind,filename,thumbnail,name,prompt,model_id,width,height,seed,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (asset_id, project_id, kind, f'{asset_id}/{filename}', f'{asset_id}/poster.png', name, prompt, model_id,
                   info['width'], info['height'], seed, json.dumps(metadata), now()))
    store.execute('UPDATE projects SET updated=? WHERE id=?', (now(), project_id))
    return store.asset(asset_id)


def upload_media(store, source, project_id):
    suffix = Path(source.filename or '').suffix.lower()
    if suffix not in {'.mp4', '.webm', '.mov', '.wav', '.mp3', '.m4a', '.ogg', '.flac'}:
        raise ValueError('Use MP4, WebM, MOV, WAV, MP3, M4A, OGG or FLAC')
    asset_id = identifier(); folder = store.output_folder(asset_id)
    filename = 'reference' + suffix; path = folder / filename
    try:
        total = 0
        with path.open('wb') as handle:
            while chunk := source.stream.read(1024 * 1024):
                total += len(chunk)
                if total > 64 * 1024 * 1024:
                    raise ValueError('Reference media must be at most 64 MB')
                handle.write(chunk)
        info = inspect_media(path, reference=True)
        return register_video(store, asset_id, project_id, info, {'imported': True}, name=Path(source.filename).stem[:120], kind='media-reference', filename=filename)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
