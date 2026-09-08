import os
from dotenv import load_dotenv

# Load .env so REDIS_URL is always available
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

redis_url = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/5')

try:
    from celery import Celery
    HAS_CELERY = True
except ImportError:
    Celery = None
    HAS_CELERY = False

_flask_app = None

def get_flask_app():
    global _flask_app
    if _flask_app is None:
        from pkg import create_app
        _flask_app = create_app()
    return _flask_app
if HAS_CELERY:
    from celery.schedules import crontab

    celery = Celery(
        'proofdeck',
        broker=redis_url,
        backend=redis_url,
        include=[
            'pkg.tasks.bulk_tasks',
            'pkg.tasks.email_tasks'
        ]
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
        beat_schedule={
            # Surface 1: Weekly Digest every Monday at 8:00 AM UTC
            'weekly-digest-monday-8am': {
                'task': 'pkg.tasks.email_tasks.scan_and_enqueue_weekly_digests',
                'schedule': crontab(minute=0, hour=8, day_of_week=1),
            },
            # Surface 3: Win-back scan daily at 10:00 AM UTC
            'winback-inactivity-scan-daily': {
                'task': 'pkg.tasks.email_tasks.scan_and_enqueue_winbacks',
                'schedule': crontab(minute=0, hour=10),
            },
        }
    )

    class FlaskContextTask(celery.Task):
        """Ensure every Celery task runs within the Flask application context."""
        def __call__(self, *args, **kwargs):
            app = get_flask_app()
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = FlaskContextTask
else:
    # Safe stub for local environments without celery installed
    class DummyCelery:
        class conf:
            @staticmethod
            def update(*args, **kwargs):
                pass
        @staticmethod
        def task(*args, **kwargs):
            def decorator(f):
                f.delay = f
                return f
            return decorator
    celery = DummyCelery()

def make_celery(app=None):
    return celery
