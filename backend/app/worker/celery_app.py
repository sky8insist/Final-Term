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
        'cleanup-abandoned-uploads': {'task':'app.worker.tasks.cleanup_abandoned_uploads','schedule':600.0},
        'dispatch-material-ingestions': {'task':'app.worker.tasks.sweep_material_ingestions','schedule':60.0},
        'dispatch-learning-jobs': {'task':'app.worker.tasks.sweep_learning_jobs','schedule':60.0},
        'enqueue-upload-notes': {'task': 'app.worker.tasks.sweep_upload_notes', 'schedule': 60.0},
        'dispatch-learning-conversions': {'task': 'app.worker.tasks.sweep_conversions', 'schedule': 60.0},
        "refresh-changed-study-plans": {"task": "app.worker.tasks.refresh_study_plans", "schedule": 300.0},
        "cleanup-expired-material-assets": {
            "task": "app.worker.tasks.cleanup_expired_assets",
            "schedule": 3600.0,
        },
    },
)
celery_app.autodiscover_tasks(["app.worker"])
