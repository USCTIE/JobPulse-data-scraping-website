import os

from celery import Celery


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
    )

    return celery


celery = make_celery()

