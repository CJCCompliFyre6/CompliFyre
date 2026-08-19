import os
from dotenv import load_dotenv
import redis

load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ['SECRET_KEY']
    STATIC_FOLDER = 'static'
    TEMPLATES_FOLDER = 'templates'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 300 * 1024 * 1024
    UPLOAD_FOLDER = 'uploads'
    TEMPLATES_AUTO_RELOAD = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'max_overflow': 20,
        'pool_timeout': 30,
        "pool_pre_ping": True,
        "pool_recycle": 1800,   # Increased from 280 — Azure PG idle timeout is ~30 min
        "connect_args": {
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "connect_timeout": 30,
        },
    }

    # --- OpenAI Configuration ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')

    # --- Flask-Mail Configuration ---
    MAIL_SERVER = "mail.crackerjacktech.com"
    MAIL_PORT = 587
    # ADDED: Handle both SSL and TLS connection types
    MAIL_USE_SSL = False
    MAIL_USE_TLS = True
    MAIL_USERNAME = "complifyre2fa@crackerjacktech.com"
    MAIL_PASSWORD = "Complifyre@2025"
    MAIL_DEFAULT_SENDER = ('Complifyre Verification', "complifyre2fa@crackerjacktech.com")

    # --- Notification Email Configuration ---
    MAIL_NOTIFICATIONS_SERVER = os.environ.get('MAIL_NOTIFICATIONS_SERVER')
    MAIL_NOTIFICATIONS_PORT = int(os.environ.get('MAIL_NOTIFICATIONS_PORT', 587))
    MAIL_NOTIFICATIONS_USE_SSL = os.environ.get('MAIL_NOTIFICATIONS_USE_SSL', 'false').lower() in ['true', 'on', '1']
    MAIL_NOTIFICATIONS_USE_TLS = os.environ.get('MAIL_NOTIFICATIONS_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_NOTIFICATIONS_USERNAME = os.environ.get('MAIL_NOTIFICATIONS_USERNAME')
    MAIL_NOTIFICATIONS_PASSWORD = os.environ.get('MAIL_NOTIFICATIONS_PASSWORD')
    MAIL_NOTIFICATIONS_DEFAULT_SENDER = ('Complifyre Notifications', os.environ.get('MAIL_NOTIFICATIONS_USERNAME'))

    # --- Redis, Celery, and Session settings remain the same ---
    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    # ... (rest of the file is unchanged) ...
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    
    CELERY_REDIS_DB = int(os.getenv("CELERY_REDIS_DB", "0"))
    CELERY = {
    "broker_url": f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{CELERY_REDIS_DB}' if REDIS_PASSWORD else f'redis://{REDIS_HOST}:{REDIS_PORT}/{CELERY_REDIS_DB}',
    "result_backend": f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{CELERY_REDIS_DB}' if REDIS_PASSWORD else f'redis://{REDIS_HOST}:{REDIS_PORT}/{CELERY_REDIS_DB}',
    "task_routes": {
        'app.services.automate_task.process_all_activities': {'queue': 'extract_activities'},
        'app.services.manual_task.extract_guidelines': {'queue': 'extract_guidelines'},
        'app.services.manual_task.extract_clauses': {'queue': 'extract_clauses'},
        'app.services.manual_task.extract_activities': {'queue': 'extract_activities'},
        'app.services.manual_task.extract_test_procedures': {'queue': 'extract_test_procedures'},
        'app.services.manual_task.extract_all_activities_and_tests': {'queue': 'extract_all_activities_and_tests'},
        # EVE v2 tasks
        'app.services.eve_tasks.generate_guideline_eve_context': {'queue': 'eve_context'},
        'app.services.eve_tasks.generate_control_checklist': {'queue': 'eve_checklist'},
        'app.services.eve_tasks.copy_checklist_to_project': {'queue': 'eve_checklist'},
    },
    "imports": (
        "app.services.automate_task",
        "app.services.manual_task",
        "app.services.eve_tasks",
    ),
    "task_track_started": True,
    "task_time_limit": 30 * 60,  # 30 minutes
    "task_acks_late": True,
    "worker_prefetch_multiplier": 1,
    }

    SESSION_REDIS_DB = int(os.getenv("SESSION_REDIS_DB", "1"))
    SESSION_TYPE = 'redis'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'session:'
    SESSION_REDIS = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=SESSION_REDIS_DB,
        password=REDIS_PASSWORD
    )

    # --- S-18: session cookie security flags ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 1800

    # --- S-19: CSRF, opt-in mode. CSRFProtect() is initialized in __init__.py
    # but WTF_CSRF_CHECK_DEFAULT=False means NO route is protected until it
    # explicitly opts in via @csrf.protect. Nothing breaks by enabling this --
    # it only unblocks incremental per-route hardening going forward.
    WTF_CSRF_CHECK_DEFAULT = False


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    db_user = os.environ.get('DB_USER')
    db_password = os.environ.get('DB_PASSWORD')
    db_host = os.environ.get('DB_HOST')
    db_port = os.environ.get('DB_PORT')
    db_name = os.environ.get('DB_NAME')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI", f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    )


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    db_user = os.environ.get('DB_USER')
    db_password = os.environ.get('DB_PASSWORD')
    db_host = os.environ.get('DB_HOST')
    db_port = os.environ.get('DB_PORT')
    db_name = os.environ.get('DB_NAME')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI", f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    )


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

# Create a settings object for easy access
settings = config_by_name[os.getenv("FLASK_ENV", "default")]()