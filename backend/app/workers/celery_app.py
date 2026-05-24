from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "whv_workers",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60 * 30,  # hard kill after 30 min
    task_soft_time_limit=60 * 25,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    # Nightly full sync from Impower at 02:00 UTC.
    # One hour before the postgres backup (03:00 UTC) so fresh data lands in
    # the backup. Real-time updates flow via the webhook receiver in between.
    "sync-all-impower-nightly": {
        "task": "app.workers.tasks.sync_all_impower",
        "schedule": crontab(hour=2, minute=0),
    },
}
