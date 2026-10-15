"""Local image-provider extensions. Discovery reads data; execution is explicit.

Extensions are trusted local Python code, not a sandbox. Nothing in this module
downloads or publishes extension source. See docs/plugins.md for the contract.
"""
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

from .catalog import CATALOG


def catalog_for(store):
    return getattr(store, 'catalog', CATALOG)


def inside(root, relative):
    root = Path(root)
    if root.is_symlink() or getattr(root, 'is_junction', lambda: False)():
        raise ValueError('Plugin paths cannot contain directory links')
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Plugin paths must be relative paths with forward slashes')
    path = root / relative
    if Path(relative).is_absolute() or ':' in relative or '..' in Path(relative).parts:
        raise ValueError('Plugin path escapes its folder')
    current = path
    while current != root:
        if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
            raise ValueError('Plugin paths cannot contain directory links')
        current = current.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Plugin path escapes its folder')
    return path


def validate_options(model, values):
    if values is None:
        values = {}
    if not isinstance(values, dict) or set(values) - {'guidance', 'strength', 'negative_prompt'}:
        raise ValueError('Unsupported model options')
    schema = model.get('image_options', {})
    if set(values) - schema.keys():
        raise ValueError('This model does not support the selected options')
    result = {}
    for key, spec in schema.items():
        value = values.get(key, spec['default'])
        if key == 'negative_prompt':
            if not isinstance(value, str) or len(value) > 4000:
                raise ValueError('Negative prompt must contain 0–4,000 characters')
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not spec['min'] <= value <= spec['max']:
            raise ValueError(f'{key} is outside the supported range')
        result[key] = value
    return result


class PluginRegistry:
    def __init__(self, project_root):
        self.root = Path(project_root).resolve() / 'addons'
        self.catalog = dict(CATALOG)
        self.entries = {}
        self.errors = []
        self.modules = {}
        if self.root.is_symlink() or getattr(self.root, 'is_junction', lambda: False)():
            self.errors.append({'id': 'addons', 'error': 'The addons folder cannot be a directory link'})
            return
        if not self.root.exists():
            return
        for folder in sorted(self.root.iterdir()):
            if folder.name.startswith('.') or not folder.is_dir():
                continue
            try:
                self._read(folder)
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.errors.append({'id': folder.name, 'error': str(error)})

    def _read(self, folder):
        folder = inside(self.root, folder.name)
        manifest = inside(folder, 'plugin.json')
        if not manifest.is_file():
            return
        if manifest.stat().st_size > 256 * 1024:
            raise ValueError('Plugin manifest is too large')
        raw = manifest.read_bytes()
        data = json.loads(raw)
        plugin_id = data['id']
        if not isinstance(plugin_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', plugin_id) or plugin_id != folder.name:
            raise ValueError('Plugin ID must match its folder name')
        if data.get('api_version') != 1:
            raise ValueError('Unsupported plugin API version')
        adapter = inside(folder, data['adapter'])
        if not adapter.is_file() or adapter.suffix != '.py':
            raise ValueError('Plugin adapter must be a local Python file')
        models = data.get('models')
        if not isinstance(models, list) or not 1 <= len(models) <= 20:
            raise ValueError('A plugin must declare 1–20 image models')
        additions = {}
        for item in models:
            local_id = item['id']
            if not isinstance(local_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', local_id):
                raise ValueError('Invalid plugin model ID')
            model_id = f'addon.{plugin_id}.{local_id}'
            if model_id in additions:
                raise ValueError('Duplicate plugin model ID')
            modes = item.get('modes', ['t2i', 'edit'])
            if not isinstance(modes, list) or not modes or set(modes) - {'t2i', 'edit', 'reference'}:
                raise ValueError('Invalid image modes')
            required = item.get('required_files', [])
            if not isinstance(required, list) or len(required) > 100:
                raise ValueError('Invalid required files')
            for name in required:
                inside(folder, name)
            model = {
                'id': model_id, 'plugin_id': plugin_id, 'local_id': local_id,
                'name': item['name'], 'family': item.get('family', 'Local plugin'),
                'service': 'images', 'description': item.get('description', ''),
                'precision': item.get('precision', ''), 'download_gb': item.get('download_gb', 0),
                'vram_gb': item.get('vram_gb', 16), 'license': item.get('license', 'See model source'),
                'license_url': item.get('license_url', ''), 'source_url': item.get('source_url', ''),
                'hub_repo': '', 'weight_dir': 'weights', 'port': None, 'files': required,
                'steps': item.get('steps', 25), 'max_steps': item.get('max_steps', 100),
                'max_references': item.get('max_references', 1), 'max_size': item.get('max_size', 1536),
                'transparent': False, 'modes': modes, 'edit_kind': item.get('edit_kind', 'img2img'),
                'image_options': item.get('image_options', {}),
                'setup_hint': item.get('setup_hint', ''),
                '_plugin_root': str(folder), '_adapter': str(adapter),
                '_config': item.get('config', {}),
                '_fingerprint': hashlib.sha256(raw + adapter.read_bytes()).hexdigest(),
            }
            for key in ('name', 'family', 'description', 'precision', 'license', 'license_url', 'source_url', 'setup_hint'):
                if not isinstance(model[key], str) or len(model[key]) > 4000:
                    raise ValueError('Invalid model display metadata')
            for key in ('license_url', 'source_url'):
                if model[key] and not model[key].startswith('https://'):
                    raise ValueError('Model links must use HTTPS')
            for key, low, high in [('steps', 1, 150), ('max_steps', 1, 150), ('max_references', 0, 10), ('max_size', 512, 2048)]:
                if type(model[key]) is not int or not low <= model[key] <= high:
                    raise ValueError(f'Invalid {key}')
            if model['steps'] > model['max_steps']:
                raise ValueError('Default steps exceed maximum')
            for key in ('download_gb', 'vram_gb'):
                if isinstance(model[key], bool) or not isinstance(model[key], (int, float)) or not math.isfinite(model[key]) or model[key] < 0:
                    raise ValueError(f'Invalid {key}')
            schema = model['image_options']
            if not isinstance(schema, dict) or set(schema) - {'guidance', 'strength', 'negative_prompt'}:
                raise ValueError('Invalid image option schema')
            for key, spec in schema.items():
                if not isinstance(spec, dict) or 'default' not in spec:
                    raise ValueError('Image options need defaults')
                if key != 'negative_prompt':
                    ceiling = 1 if key == 'strength' else 30
                    if any(type(spec.get(k)) not in (int, float) or not math.isfinite(spec[k]) for k in ('min', 'max')) or not 0 <= spec['min'] <= spec['max'] <= ceiling:
                        raise ValueError('Invalid image option limits')
            validate_options(model, {})
            additions[model_id] = model
        self.catalog.update(additions)
        self.entries[plugin_id] = {'id': plugin_id, 'name': str(data.get('name', plugin_id))[:120],
                                   'version': str(data.get('version', '1'))[:40], 'models': list(additions)}

    def status(self):
        return {'plugins': list(self.entries.values()), 'errors': self.errors}

    def bundle(self, model):
        folder = inside(self.root, model['plugin_id'])
        return inside(folder, '.models/' + model['local_id'])

    def adapter(self, model):
        key = model['plugin_id']
        if key not in self.modules:
            path = inside(inside(self.root, key), str(Path(model['_adapter']).relative_to(self.root / key)).replace('\\', '/'))
            module_name = 'atelier_addon_' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
            spec = importlib.util.spec_from_file_location(module_name, path, submodule_search_locations=[str(path.parent)])
            module = importlib.util.module_from_spec(spec)
            # Register before execution so dataclasses and relative imports work.
            for name in list(sys.modules):
                if name == module_name or name.startswith(module_name + '.'):
                    del sys.modules[name]
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                for name in ('install', 'verify', 'generate'):
                    if not callable(getattr(module, name, None)):
                        raise ValueError(f'Plugin adapter needs {name}()')
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            self.modules[key] = module
        return self.modules[key]


def complete(model, root):
    root = Path(root)
    ready = root / '.runtime-ready'
    try:
        return (bool(model['files']) and ready.is_file()
                and ready.read_text(encoding='utf-8') == model['_fingerprint']
                and all(inside(root, file).is_file() for file in model['files']))
    except (OSError, ValueError):
        return False
