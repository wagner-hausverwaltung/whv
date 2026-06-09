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
    # Reconciliation watchdog runs 90 min after the sync (and after the
    # backup) so any drift the sync missed surfaces in Sentry. Read-only —
    # never writes. Pages every entity, so we want this off-peak.
    "reconcile-impower-daily": {
        "task": "app.workers.tasks.reconcile_impower",
        "schedule": crontab(hour=3, minute=30),
    },
    # Contacts-only refresh every 15 min. The nightly full sync + the Impower
    # contact webhook are meant to keep phone/email current, but the contact
    # webhook isn't firing reliably — so this catches edits (e.g. a new phone
    # number) within ~15 min instead of next-day. Cheap: one paged GET + upserts.
    "sync-contacts-periodic": {
        "task": "app.workers.tasks.sync_contacts_periodic",
        "schedule": crontab(minute="*/15"),
    },
    # Hourly: open ENTWURF resolutions whose opens_at has passed, and
    # finalize OFFEN resolutions whose closes_at has passed (tally → PDF →
    # email). Hourly granularity is fine for v1 — owners read the Frist as
    # a calendar deadline, not a precise stopwatch.
    "process-due-resolutions-hourly": {
        "task": "app.workers.tasks.process_due_resolutions",
        "schedule": crontab(minute=5),
    },
    # Every minute: fan out announcements whose 10-min editorial buffer
    # has elapsed (or that the admin pressed "Sofort veröffentlichen"
    # on). The partial index makes the scan O(due-rows) so a 1-minute
    # cadence is cheap. Lower granularity (e.g. 5 min) would give the
    # admin a frustrating "I clicked publish-now but it took ages"
    # experience — 1 min is the sweet spot.
    "publish-due-announcements-every-minute": {
        "task": "app.workers.tasks.publish_due_announcements",
        "schedule": crontab(minute="*"),
    },
}
