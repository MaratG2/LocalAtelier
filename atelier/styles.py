"""Project art direction and explicit per-generation overrides."""


def project_style(data, store):
    result = {}
    if 'style_prompt' in data:
        value = data['style_prompt']
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError('Style prompt must contain 0–4,000 characters')
        result['style_prompt'] = value.strip()
    if 'inherit_style' in data:
        if not isinstance(data['inherit_style'], bool):
            raise ValueError('Style inheritance must be true or false')
        result['inherit_style'] = int(data['inherit_style'])
    if 'style_reference_id' in data:
        ref = data['style_reference_id']
        asset = store.asset(ref) if isinstance(ref, str) else None
        if ref is not None and (not asset or asset['deleted'] or asset['kind'] not in {'generated', 'reference'}):
            raise ValueError('Choose an available style reference image')
        result['style_reference_id'] = ref
    return result


def apply_style(data, store):
    data = dict(data)
    use_style = data.pop('use_style', True)
    use_reference = data.pop('use_style_reference', True)
    if not isinstance(use_style, bool) or not isinstance(use_reference, bool):
        raise ValueError('Style options must be true or false')
    project = store.project(data.get('project_id', 'inbox')) if isinstance(data.get('project_id', 'inbox'), str) else None
    original = data.get('prompt', '')
    style = ''
    reference = None
    if project and use_style:
        style = project['style_prompt'] or (store.setting('style_prompt', '') if project['inherit_style'] else '')
        if style and isinstance(original, str):
            data['prompt'] = original + '\n\nArt direction: ' + style
    # Text editing is an explicit override: never inject a second image into Edit.
    if project and use_reference and data.get('mode', 't2i') != 'edit':
        reference = project['style_reference_id']
        if reference:
            asset = store.asset(reference)
            if not asset or asset['deleted']:
                raise ValueError('Project style reference is unavailable. Replace it or turn off the style reference.')
            refs = data.get('reference_ids', [])
            if isinstance(refs, list):
                data['reference_ids'] = list(dict.fromkeys([*refs, reference]))
                data['mode'] = 'reference'
                if isinstance(data.get('prompt'), str):
                    index = data['reference_ids'].index(reference) + 1
                    data['prompt'] += f'\n\nUse image {index} as the visual style reference: preserve its palette, rendering technique, lighting and level of detail. Follow the requested subject and composition rather than copying the reference subject.'
    return data, {'user_prompt': original, 'style_prompt': style, 'style_reference_id': reference,
                  'use_style': use_style, 'use_style_reference': use_reference}
