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
redis_db = getattr(Config, "CELERY_REDIS_DB", 0)

def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    # Configure Celery with Redis and keep existing task_routes intact
    celery_app.config_from_object({
        "broker_url": f'redis://{redis_host}:6379/{redis_db}',
        "result_backend": f'redis://{redis_host}:6379/{redis_db}',
        "task_routes": {
            'app.services.eve_step678.run_eve_step6_and_7': {'queue': 'eve_evaluate'},
            'app.services.eve_step678.run_eve_step8_clause_rollup': {'queue': 'eve_evaluate'},
            'app.services.eve_step5.run_eve_step5_for_evidence': {'queue': 'eve_evaluate'},
            'app.services.eve_step5.run_eve_step5_for_all_evidence': {'queue': 'eve_evaluate'},
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
            'app.services.eve_tasks.generate_guideline_eve_context': {'queue': 'eve_context'},
            'app.services.eve_tasks.generate_control_checklist': {'queue': 'eve_checklist'},
            'app.services.eve_tasks.copy_checklist_to_project': {'queue': 'eve_checklist'},     
        },
        "imports": ("app.services.automate_task", "app.services.manual_task", "app.services.eve_tasks", "app.services.eve_step5"),"imports": ("app.services.automate_task", "app.services.manual_task", "app.services.eve_tasks", "app.services.eve_step5", "app.services.eve_step678"),
        "task_track_started": True,
        "task_time_limit": 24 * 60 * 60,  # 24 hours
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
        "result_extended": True,  # Enable extended result features
        "broker_transport_options": {"visibility_timeout": 21600},  # 6 hours — task_acks_late + long-running bulk tasks (e.g. activity-generation) need this longer than Redis's 1hr default, or the broker redelivers an in-progress task to another worker
        "beat_schedule": {
            "fix-pending-checklists-every-5-min": {
                "task": "app.services.eve_tasks.fix_pending_checklists",
                "schedule": 300.0,
            },
        },
    })


    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app