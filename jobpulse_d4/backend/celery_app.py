import os

from celery import Celery
from celery.schedules import crontab


def make_celery() -> Celery:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

    celery = Celery(
        "jobpulse",
        broker=redis_url,
        backend=redis_url,
        include=["app"],
    )

    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "daily-etl-ingest": {
            "task": "etl_coordinator",
            # "schedule": 300.0,           # (for testing)
            # Run once a month: 2nd day at 19:00 UTC
            "schedule": crontab(day_of_month="2", hour=19, minute=0), # UTC Time zone
        }
        }
    )
    return celery


celery = make_celery()

