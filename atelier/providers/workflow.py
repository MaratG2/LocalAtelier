"""ComfyUI schema validation shared by local providers."""


def add_mask_nodes(graph, mask_name, source_name, vae):
    """White pixels select editable latents; the source supplies the surroundings."""
    graph['mask-source'] = {'class_type': 'LoadImage', 'inputs': {'image': source_name}}
    graph['mask-image'] = {'class_type': 'LoadImageMask', 'inputs': {'image': mask_name, 'channel': 'red'}}
    graph['mask-latent'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['mask-source', 0], 'vae': vae}}
    graph['mask-noise'] = {'class_type': 'SetLatentNoiseMask', 'inputs': {'samples': ['mask-latent', 0], 'mask': ['mask-image', 0]}}
    graph['7']['inputs']['latent_image'] = ['mask-noise', 0]

def validate_workflow(graph, node_info):
    """Fail before submission if an engine upgrade changes an input contract.

    ComfyUI can silently ignore misspelled autogrow image inputs. Check expanded
    reference keys against the engine's actual schema, as well as required keys.
    """
    for node in graph.values():
        name = node["class_type"]
        schema = node_info[name]["input"]
        inputs = node["inputs"]
        allowed = set(schema.get("required", {})) | set(schema.get("optional", {}))
        for field, definition in schema.get("required", {}).items():
            if definition[0] == "COMFY_AUTOGROW_V3":
                allowed.update(f"{field}.{slot}" for slot in definition[1]["template"]["names"])
            elif field not in inputs:
                raise RuntimeError(f"{name} is missing required input {field}; update the workflow for this ComfyUI version")
        if set(inputs) - allowed:
            raise RuntimeError(f"{name} contains unsupported inputs: {sorted(set(inputs) - allowed)}")
