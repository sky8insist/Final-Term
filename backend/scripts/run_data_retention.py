"""Private operator entry: preview by default, --execute explicitly deletes."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import retention_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--user-id', type=UUID, help='Optional exact owner scope')
    args = parser.parse_args()
    user_id = str(args.user_id) if args.user_id else None
    if args.execute:
        report = {'relational': retention_service.prune(dry_run=False, user_id=user_id),
                  'assets': retention_service.cleanup_assets(user_id=user_id)}
    else:
        count = get_supabase_client().rpc('preview_expired_assets', {
            'p_limit': settings.retention_asset_batch_size, 'p_user': user_id,
        }).execute().data
        report = {'relational': retention_service.prune(user_id=user_id),
                  'assets': {'eligibleInBatch': count, 'batchLimit': settings.retention_asset_batch_size}}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
