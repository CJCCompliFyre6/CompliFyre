from app import create_app
from celery_app import celery_init_app

flask_app = create_app()
celery = celery_init_app(flask_app)

# This ensures Celery sees the `celery` variable when running `-A celery_worker`
