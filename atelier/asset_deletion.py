"""Deletion stays in the current workspace and preserves other batch results."""
import json


def ensure_unused(router, asset_ids):
    for job in router.all("SELECT request,result_ids FROM jobs WHERE status IN ('queued','running')"):
        # UUIDs are stored as complete JSON strings, including nested settings.
        if any(json.dumps(asset_id) in job['request'] or json.dumps(asset_id) in job['result_ids']
               for asset_id in asset_ids):
            raise ValueError('Wait for the generation using this asset to finish')


def delete_asset(router, asset_id):
    store = router.current
    asset = store.one('SELECT id,deleted FROM assets WHERE id=?', (asset_id,))
    if not asset:
        raise ValueError('This asset does not belong to the current workspace')
    if not asset['deleted']:
        raise ValueError('Move this generation to Trash before deleting it permanently')
    masks = [row['id'] for row in store.all("SELECT id,metadata FROM assets WHERE kind='mask'")
             if json.loads(row['metadata']).get('source_id') == asset_id]
    owned = [asset_id, *masks]
    ensure_unused(router, owned)
    for item in owned:
        store.remove_asset_files(item)
    with store.connect() as db:
        for row in db.execute('SELECT id,result_ids FROM jobs').fetchall():
            original = json.loads(row['result_ids'])
            remaining = [item for item in original if item not in owned]
            if original == remaining:
                continue
            if remaining:
                db.execute('UPDATE jobs SET result_ids=? WHERE id=?', (json.dumps(remaining), row['id']))
            else:
                db.execute('DELETE FROM jobs WHERE id=?', (row['id'],))
        for item in owned:
            db.execute('UPDATE projects SET style_reference_id=NULL WHERE style_reference_id=?', (item,))
            db.execute('DELETE FROM assets WHERE id=?', (item,))
