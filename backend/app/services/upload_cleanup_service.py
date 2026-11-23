"""Recover only recorded, abandoned destinations; never scan unrelated files."""
from fastapi import HTTPException
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import owner_io_service


def cleanup(*, user_id=None, dry_run=True):
    client = get_supabase_client()
    rows = client.rpc('ready_upload_cleanup', {
        'p_limit': 50, 'p_grace': settings.upload_cleanup_grace_seconds, 'p_user': user_id,
    }).execute().data
    counts = {'candidates': len(rows), 'removed': 0, 'failed': 0, 'skipped': 0, 'dryRun': dry_run}
    if dry_run:
        return counts
    for row in rows:
        try:
            with owner_io_service.hold_owner_io(row['user_id']):
                item = client.rpc('claim_upload_cleanup', {
                    'p_intent': row['id'], 'p_grace': settings.upload_cleanup_grace_seconds,
                }).execute().data
                if not item:
                    counts['skipped'] += 1
                    continue
                args = {'p_intent': item['id'], 'p_token': item['claim_token']}
                try:
                    if (item['bucket'] != settings.material_storage_bucket
                            or not item['object_path'].startswith(str(item['user_id']) + '/')
                            or any(part in ('', '.', '..') for part in item['object_path'].split('/'))):
                        raise ValueError('Unsafe upload destination')
                    client.storage.from_(item['bucket']).remove([item['object_path']])
                except Exception as exc:
                    client.rpc('finish_upload_cleanup', {**args, 'p_error': type(exc).__name__}).execute()
                    counts['failed'] += 1
                else:
                    accepted = client.rpc('finish_upload_cleanup', args).execute().data
                    counts['removed' if accepted else 'skipped'] += 1
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            counts['skipped'] += 1
    return counts


def sweep():
    return cleanup(dry_run=False) if settings.upload_cleanup_enabled else {'status': 'disabled'}
