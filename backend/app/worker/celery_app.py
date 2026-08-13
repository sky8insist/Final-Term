from celery import Celery

from app.config.settings import settings

celery_app = Celery("exam_ai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.celery_task_always_eager,
    timezone="Asia/Shanghai",
    beat_schedule={
        "cleanup-expired-material-assets": {
            "task": "app.worker.tasks.cleanup_expired_assets",
            "schedule": 86400.0,
        },
    },
)
celery_app.autodiscover_tasks(["app.worker"])
