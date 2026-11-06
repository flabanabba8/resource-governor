import json
from .core import Governor
from .transcode import transcode

TOOLS = {
    'resource_watch_start': ('Begin watching a same-user Linux process against explicit RSS and average CPU budgets; monitoring only, no enforcement.', {'pid': {'type': 'integer', 'minimum': 1}, 'max_rss_mb': {'type': 'number', 'exclusiveMinimum': 0}, 'max_cpu_percent': {'type': 'number', 'exclusiveMinimum': 0}}, ['pid', 'max_rss_mb', 'max_cpu_percent']),
    'resource_transcode_video': ('Run one plugin-owned CPU-only local video conversion with explicit Linux address-space, CPU-time and wall-time limits; output is separate.', {'source_path': {'type': 'string'}, 'max_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 60}, 'address_space_mb': {'type': 'integer', 'minimum': 512, 'maximum': 16384}, 'cpu_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 60}, 'wall_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 60}, 'allow_profile_media': {'type': 'boolean', 'description': 'Explicitly allow a selected media file under the active profile plugin-data directory.'}}, ['source_path', 'max_seconds', 'address_space_mb', 'cpu_seconds', 'wall_seconds']),
    'resource_watch_check': ('Measure the same process identity since watch start and report budget exceedances; never kills, pauses or throttles processes.', {'watch_id': {'type': 'string'}}, ['watch_id']),
}

def invoke(name, args):
    from plugins.plugin_storage import plugin_data_dir
    try:
        root = plugin_data_dir('resource-governor')
        if name == 'resource_transcode_video': return json.dumps(transcode(root, **args), allow_nan=False)
        return json.dumps(getattr(Governor(root), name.removeprefix('resource_watch_'))(**args), allow_nan=False)
    except (ValueError, TypeError, OSError, KeyError, RuntimeError) as exc:
        return json.dumps({'error': str(exc)})

def register(ctx):
    for name, (description, properties, required) in TOOLS.items():
        ctx.register_tool(name=name, toolset='resource_governor', schema={'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}},
            handler=lambda args, _name=name, **kwargs: invoke(_name, args))
