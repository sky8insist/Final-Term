"""Bounded private retention operations; public requests cannot run a sweep."""
from fastapi import HTTPException
from app.services import owner_io_service
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client


def prune(*, dry_run: bool = True, user_id: str | None = None) -> dict:
    return get_supabase_client().rpc('prune_retained_data', {
        'p_audit_days': settings.retention_audit_days,
        'p_metric_days': settings.retention_metric_days,
        'p_event_days': settings.retention_event_days,
        'p_limit': settings.retention_batch_size,
        'p_dry_run': dry_run, 'p_user': user_id,
    }).execute().data


def cleanup_assets(*, user_id: str | None = None) -> dict:
    client = get_supabase_client()
    rows = client.rpc('claim_expired_assets', {
        'p_limit': settings.retention_asset_batch_size, 'p_user': user_id,
    }).execute().data
    removed = failed = skipped = 0
    for row in rows:
        try:
            with owner_io_service.hold_owner_io(row['user_id']):
                outcome = _cleanup_one(client, row)
        except HTTPException as exc:
            if exc.status_code != 409: raise
            outcome = 'skipped'
        removed += outcome == 'removed'
        failed += outcome == 'failed'
        skipped += outcome == 'skipped'
    return {'claimed': len(rows), 'removed': removed, 'failed': failed, 'skipped': skipped}


def _cleanup_one(client, row):
    args = {'p_asset': row['id'], 'p_token': row['cleanup_token']}
    if (row['bucket'] != settings.material_storage_bucket
            or not row['object_path'].startswith(str(row['user_id']) + '/')
            or any(part in ('.', '..', '') for part in row['object_path'].split('/'))):
        client.rpc('finish_asset_cleanup', {**args, 'p_error': 'UnsafeAssetPath'}).execute()
        return 'failed'
    if not client.rpc('check_asset_cleanup', args).execute().data:
        return 'skipped'
    try:
        client.storage.from_(row['bucket']).remove([row['object_path']])
    except Exception as exc:
        # Store class only, never URLs, object names, tokens or provider text.
        client.rpc('finish_asset_cleanup', {**args, 'p_error': type(exc).__name__}).execute()
        return 'failed'
    # If this acknowledgement fails, the expired lease can be reclaimed.
    # Storage.remove of a missing object is idempotent; manifest stays durable.
    if client.rpc('finish_asset_cleanup', args).execute().data:
        return 'removed'
    else:
        return 'skipped'


def sweep(*, user_id: str | None = None) -> dict:
    if not settings.data_retention_enabled:
        return {'status': 'disabled'}
    return {'status': 'completed', 'relational': prune(dry_run=False, user_id=user_id),
            'assets': cleanup_assets(user_id=user_id)}
