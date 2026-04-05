# routes/notifications.py
from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_login import current_user, login_required
import json
import time
from app.models.task_status import TaskStatus

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/task-status/<task_id>')
@login_required
def task_status(task_id):
    task_status_model = TaskStatus()
    
    def generate():
        last_data = None
        # Check for status updates every second for 5 minutes
        for _ in range(300):
            data = task_status_model.get_status(task_id)
            if data and data != last_data:
                yield f"data: {json.dumps(data)}\n\n"
                last_data = data
                if data['status'] in ['completed', 'failed']:
                    break
            time.sleep(1)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@notifications_bp.route('/recent-tasks')
@login_required
def recent_tasks():
    task_status_model = TaskStatus()
    tasks = task_status_model.get_user_tasks(current_user.id)
    return jsonify(tasks)