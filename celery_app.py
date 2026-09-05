import os
from celery import Celery

def make_celery(app=None):
    """
    Create and configure a Celery instance.
    If a Flask app is provided, configure Celery to work within the Flask app context.
    """
    celery = Celery(
        'proofdeck',
        broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    )

    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )

    if app:
        celery.conf.update(app.config)

        class ContextTask(celery.Task):
            """Ensure each Celery task runs inside the Flask application context."""
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    return celery


# Module-level celery instance for the worker CLI: celery -A celery_app.celery worker
# This gets properly configured with Flask context when create_app() runs.
celery = make_celery()
