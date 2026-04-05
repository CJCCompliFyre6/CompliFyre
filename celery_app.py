# from flask import Flask


# celery = Celery(
# broker='redis://127.0.0.1:6379/0',
# backend='redis://127.0.0.1:6379/0',
# task_routes={
#         'app.services.automate_task.process_all_activities':{'queue':'extract_activities'} # Make sure this full path is correct too
#     },
#     # --- THIS IS THE CRUCIAL PART ---
# imports=('app.services.automate_task',)
# )

from flask import Flask
from celery import Celery, Task

from config import Config

redis_host = Config.REDIS_HOST

def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    # Configure Celery with Redis and keep existing task_routes intact
    celery_app.config_from_object({
        "broker_url": f'redis://{redis_host}:6379/0',
        "result_backend": f'redis://{redis_host}:6379/0',
        "task_routes": {
            'app.services.automate_task.process_all_activities': {'queue': 'extract_activities'},
            # Add manual_task routes without disturbing existing ones
            'app.services.manual_task.extract_guidelines': {'queue': 'extract_guidelines'},
            'app.services.manual_task.extract_clauses': {'queue': 'extract_clauses'},
            'app.services.manual_task.extract_activities': {'queue': 'extract_activities'},
            'app.services.manual_task.extract_test_procedures': {'queue': 'extract_test_procedures'},
            'app.services.manual_task.extract_all_activities_and_tests': {'queue': 'extract_all_activities_and_tests'},
            'app.services.manual_task.generate_consolidated_observation_summary': {'queue': 'generate_consolidated_observation_summary'},
            'app.services.manual_task.generate_consolidated_test_procedure': {'queue': 'generate_consolidated_test_procedure'},
            'app.services.manual_task.generate_consolidated_findings_summary': {'queue': 'generate_consolidated_findings_summary'},
            'app.services.manual_task.generate_consolidated_recommendations_summary': {'queue': 'generate_consolidated_recommendations_summary'},
            'app.services.manual_task.extract_selected_activities_and_tests': {'queue': 'extract_selected_activities_and_tests'},
            'app.services.manual_task.generate_missing_activities_for_guidelines': {'queue': 'generate_missing_activities_for_guidelines'},
            'app.services.manual_task.generate_single_clause_activities': {'queue': 'generate_single_clause_activities'},
            'app.services.manual_task.consolidate_evidence_task': {'queue': 'consolidate_evidence_task'},

        },
        "imports": ("app.services.automate_task", "app.services.manual_task"),
        "task_track_started": True,
        "task_time_limit": 30 * 60,  # 30 minutes
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
        "result_extended": True,  # Enable extended result features
    })


    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app