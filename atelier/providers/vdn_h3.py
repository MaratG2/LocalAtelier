"""One owned FreeVideo process tree per job, sharing the studio's GPU queue."""
import json
import shutil
import time
from pathlib import Path

from ..models import python_at
from ..storage import identifier
from ..video_install import complete, environment, manifest
from ..videos import QUALITIES, inspect_media, media_kind, register_video


def remove_job_files(folder):
    # Windows can retain child-process log handles briefly after taskkill returns.
    for attempt in range(10):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(.2 * min(attempt + 1, 4))


def progress_event(row):
    event = row.get('event', '')
    labels = {'encoding_start': 'Encoding prompt and references', 'conditioning_reused': 'Reusing preview conditioning',
              'conditioning_cache_hit': 'Reusing prompt conditioning', 'video_start': 'Rendering video and sound',
              'latent_upscaler_prepare': 'Preparing full-resolution refinement', 'decode_resume': 'Decoding video and sound',
              'resource_retry': 'Adjusting memory placement and retrying', 'compute_device': 'Planning GPU memory',
              'encoder_load_start': 'Loading text encoder', 'encoder_compute_start': 'Encoding text and images',
              'encoder_complete': 'Prompt and references ready', 'first_pass_reused': 'Continuing from the saved preview',
              'latent_upscale': 'Upscaling for the final pass', 'preview_mismatch': 'Preview differs from this runtime · rendering first pass again'}
    if event in labels:
        return labels[event], 0
    if event in {'sampling_start', 'sampling_progress', 'sampling_step'}:
        done, total = row.get('completed_steps', 0), row.get('total', 8)
        if isinstance(done, int) and isinstance(total, int) and total > 0:
            step = min(total, done + 1)
            return f'Rendering video and sound · step {step} of {total}', min(99, round(done / total * 100))
    if event in {'decode_phase', 'model_load_phase'}:
        return str(row.get('phase', 'Loading model')), 0
    phase = row.get('label') or row.get('stage') or row.get('phase') or event
    done, total = row.get('step', row.get('done')), row.get('steps', row.get('total'))
    if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0:
        return f'{str(phase).replace("_", " ").capitalize()} · {done:g} / {total:g}', min(99, round(done / total * 100))
    return None


def generate(runtime, request, callback, cancelled):
    store = runtime.store
    record = store.one("SELECT * FROM models WHERE id='vdn-h3'")
    if not record or not record['verified'] or not complete(record['runtime_path']):
        raise RuntimeError('Install and verify VDN-H3 first')
    bundle = Path(record['runtime_path']); weights = bundle / 'weights'
    asset_id = identifier(); folder = store.assets / asset_id; folder.mkdir()
    output = folder / 'video.mp4'; succeeded = False
    start = time.monotonic()
    try:
        prompt = folder / 'prompt.txt'; prompt.write_text(request['prompt'], encoding='utf-8')
        paths = bundle / '.runtime/encoder-paths.yaml'
        paths.write_text('local_atelier:\n  base_path: ' + json.dumps(str(weights)) + '\n  text_encoders: text_encoders\n', encoding='utf-8')
        args = [python_at(bundle), '-u', '-m', 'freevideo_engine', 'generate', '--prompt-file', prompt,
                '--cache', weights / manifest()['cache'], '--base', weights / 'h3-base', '--checkpoint', weights / 'stage-dmd-step-250',
                '--encoder-python', python_at(bundle), '--encoder-root', bundle / '.runtime/ComfyUI', '--model-paths', paths,
                '--out', output, '--width', request['width'], '--height', request['height'], '--frames', request['frames'],
                '--seed', request['seed'], '--base-steps', QUALITIES[request['quality']], '--attention', 'auto',
                '--two-pass' if request['quality'] == 'light' else '--no-two-pass']
        if request['preview']:
            args += ['--preview']
        if request.get('source_video_id'):
            source = store.asset(request['source_video_id'])
            args += ['--refine-from', store.assets / source['filename']]
        media = {'version': 1}
        for key in ('first', 'last'):
            if request.get(key + '_id'):
                media[key] = str(store.assets / store.asset(request[key + '_id'])['filename'])
        if request['reference_ids']:
            media['references'] = [dict(kind=media_kind(store.asset(ref)), path=str(store.assets / store.asset(ref)['filename'])) for ref in request['reference_ids']]
        if len(media) > 1:
            media_path = folder / 'inputs.json'; media_path.write_text(json.dumps(media), encoding='utf-8')
            args += ['--media', media_path]
        env = environment(bundle)
        if getattr(store, 'temporary', False):
            args += ['--no-tuning']
            scratch = runtime.root / 'h3-private'
            scratch.mkdir(parents=True, exist_ok=True)
            env.update(FREEVIDEO_HOME=str(scratch), TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch))
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        with runtime.lock:
            callback('Switching model · freeing GPU memory', 0)
            runtime.release()
            if cancelled():
                raise RuntimeError('Cancelled')
            runtime.active_model = 'vdn-h3'; runtime.phase = 'Starting MiniMax H3'
            process = runtime._start(args, bundle / '.runtime/FreeVideo', env, 'vdn-h3')
        log_path = runtime.root / 'vdn-h3.log'; offsets = {}; pending = {}; tail = ''
        while True:
            if cancelled():
                raise RuntimeError('Cancelled')
            if time.monotonic() - start > 7200:
                raise RuntimeError('H3 exceeded the two-hour generation limit; see runtime logs')
            # Child workers write their own event logs; the coordinator only reports transitions.
            logs = [log_path, *sorted(folder.glob('*.log'))]
            for path in logs:
                with path.open(encoding='utf-8', errors='replace') as log:
                    log.seek(offsets.get(path, 0)); text = log.read(128 * 1024); offsets[path] = log.tell()
                tail = (tail + text)[-5000:]
                lines = (pending.get(path, '') + text).split('\n'); pending[path] = lines.pop()[-65536:]
                for line in lines:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    update = progress_event(row) if isinstance(row, dict) else None
                    if update:
                        runtime.phase = update[0]; callback(*update)
            if process.poll() is not None:
                break
            time.sleep(.4)
        receipt = output.with_suffix('.request.json')
        report = json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() else {}
        if process.returncode or not output.is_file() or not report.get('success'):
            raise RuntimeError('MiniMax H3 failed: ' + (report.get('error_message') or tail[-1800:]))
        callback('Saving clip and thumbnails', 99)
        info = inspect_media(output)
        if info['media_kind'] != 'video' or not info['has_audio']:
            raise RuntimeError('H3 did not produce the expected video and audio streams')
        metadata = dict(settings=request, preview=request['preview'], elapsed_seconds=round(time.monotonic()-start, 2),
                        runtime='FreeVideo', runtime_revision=manifest()['freevideo_revision'], precision='INT8 ConvRot',
                        source_video_id=request.get('source_video_id'), mock_mode=False)
        asset = register_video(store, asset_id, request['project_id'], info, metadata, name=request['prompt'][:80],
                               prompt=request['prompt'], model_id='vdn-h3', seed=request['seed'])
        succeeded = True
        # Only previews need retained first-pass tensors. Source previews remain untouched.
        if not request['preview']:
            remove_job_files(output.with_suffix('.artifacts'))
        return asset
    finally:
        runtime.release('vdn-h3')
        if not succeeded:
            remove_job_files(folder)
