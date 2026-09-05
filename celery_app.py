import os
from celery import Celery
from dotenv import load_dotenv

# Load .env so REDIS_URL is always available
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

redis_url = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/5')

celery = Celery(
    'proofdeck',
    broker=redis_url,
    backend=redis_url,
    include=['pkg.tasks.bulk_tasks']
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

_flask_app = None

def get_flask_app():
    global _flask_app
    if _flask_app is None:
        from pkg import create_app
        _flask_app = create_app()
    return _flask_app

class FlaskContextTask(celery.Task):
    """Ensure every Celery task runs within the Flask application context."""
    def __call__(self, *args, **kwargs):
        app = get_flask_app()
        with app.app_context():
            return self.run(*args, **kwargs)

celery.Task = FlaskContextTask

def make_celery(app=None):
    return celery
