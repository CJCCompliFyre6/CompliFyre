# app/models/task_status.py
import json
import redis
from datetime import datetime
from flask import current_app


class TaskStatus:
    def __init__(self, app=None):
        self.redis = None
        if app:
            self.init_app(app)
        else:
            # Try to get app from current_app if available
            try:
                self.init_app(current_app._get_current_object())
            except:
                pass

    def init_app(self, app):
        self.redis = redis.Redis.from_url(
            app.config.get("REDIS_URL", "redis://localhost:6379/0")
        )

    def set_status(self, task_id, user_id, task_name, status, progress=0, message=""):
        if self.redis is None:
            # Try to initialize if not already initialized
            try:
                self.init_app(current_app._get_current_object())
            except:
                print("Redis not initialized. Cannot set task status.")
                return

        data = {
            "task_id": task_id,
            "user_id": user_id,
            "task_name": task_name,
            "status": status,  # 'pending', 'progress', 'completed', 'failed'
            "progress": progress,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            self.redis.setex(
                f"task:{task_id}", 3600 * 24, json.dumps(data)
            )  # Expire in 24 hours
            # Also store user's recent tasks
            self.redis.lpush(f"user_tasks:{user_id}", json.dumps(data))
            self.redis.ltrim(f"user_tasks:{user_id}", 0, 9)  # Keep only 10 most recent
        except Exception as e:
            print(f"Error setting task status: {e}")

    def get_status(self, task_id):
        if self.redis is None:
            return None

        try:
            data = self.redis.get(f"task:{task_id}")
            if data:
                return json.loads(data)
        except:
            pass
        return None

    def get_user_tasks(self, user_id, limit=10):
        if self.redis is None:
            return []

        try:
            tasks = self.redis.lrange(f"user_tasks:{user_id}", 0, limit - 1)
            return [json.loads(task) for task in tasks]
        except:
            return []


# Create a global instance
task_status = TaskStatus()
