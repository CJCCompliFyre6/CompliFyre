"""
Models for the ARGUS continuous ingestion pipeline (design finalized
2026-08-10, see 'ARGUS Pipeline Spec' in the Build Sequence tracker).
Deliberately no per-user read/action tracking -- a single COMPLIFYRE-role
user approving a map, starting activity extraction, or restarting a
failed item is a real action on the queue item itself, not something
that needs per-viewer state. Whether a notification is still "pending"
is derived live from the queue item's own current stage, not stored
separately.
"""
from app import db
from sqlalchemy import func


class ArgusQueueItems(db.Model):
    __tablename__ = "argus_queue_items"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    source_filename = db.Column(db.String(255), nullable=False)
    queued_file_path = db.Column(db.String(500), nullable=True)
    # Where the file actually landed after scan_watch_folder moved it to
    # _processed/ -- needed since dispatch of extract_guidelines is now
    # deferred until this item's turn, not immediate on discovery.
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"), nullable=True)

    stage = db.Column(db.String(50), nullable=False, default="QUEUED")
    # QUEUED -> STRUCTURE_MAP_PENDING -> AWAITING_MAP_REVIEW ->
    # CLAUSE_EXTRACTING -> AWAITING_ACTIVITY_START -> ACTIVITY_EXTRACTING
    # -> COMPLETE / FAILED

    queue_position = db.Column(db.Float, nullable=False)
    # Governs both normal FIFO order and priority-jump -- one mechanism,
    # not two. Lower value = earlier in the queue.

    map_flagged = db.Column(db.Boolean, nullable=False, default=False)
    # The one automated check: structure_map["sections"] came back empty.
    # No LLM-based judge -- deliberately rejected, see design notes.

    current_task_id = db.Column(db.String(255), nullable=True)
    # The active Celery task_id for the current stage, when the underlying
    # task keys its Redis progress by task_id rather than guideline_id
    # (ingestion: guideline_progress:{task_id}). Used to read live progress
    # and detect staleness (task_id set but its Redis key has expired).

    error_message = db.Column(db.Text, nullable=True)
    # Populated only on genuine failure. A failure blocks the whole
    # queue until manually resolved -- does not silently skip ahead.

    last_action_by_user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"), nullable=True)
    last_action_at = db.Column(db.TIMESTAMP, nullable=True)
    # Who most recently approved a map, started activity extraction,
    # or restarted a failed item -- a real accountability record, even
    # though the action itself isn't gated to a specific person.

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    started_at = db.Column(db.TIMESTAMP, nullable=True)
    completed_at = db.Column(db.TIMESTAMP, nullable=True)


class ArgusNotifications(db.Model):
    __tablename__ = "argus_notifications"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    notification_type = db.Column(db.String(50), nullable=False)
    # map_ready / clauses_ready / guideline_complete / failure

    queue_item_id = db.Column(db.BigInteger, db.ForeignKey("argus_queue_items.id"), nullable=True)
    # Nullable: a "queue_idle" notification has no specific item to attach
    # to -- it's a queue-level condition (nothing active at all), not an
    # item-level one. Every other notification type still sets this.
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
