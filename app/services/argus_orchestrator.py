"""
ARGUS orchestrator (app/services/argus_orchestrator.py)

The periodic task that drives ArgusQueueItems through its stages by
watching the REAL, EXISTING extraction pipeline from the outside --
it never modifies extract_guidelines / extract_clauses / activity
extraction themselves, only reacts to state they already produce.

Design reference: 'ARGUS Pipeline Spec' in the Build Sequence tracker
(v125), refined during the 2026-08-12 morning session which discovered:
- The human-approval gate for structure maps already exists inside
  extract_clauses() itself (it generates the map, sets
  AWAITING_CONFIRMATION, and returns -- no changes needed).
- confirm_structure_map() (app/routes/main.py) already sets
  structure_map['confirmed']=True and re-dispatches extract_clauses()
  itself on approval -- also needs no changes.
- Activity extraction is manually triggered from the UI today, with
  built-in resume-where-it-left-off behavior on retrigger -- also
  needs no changes.
So this orchestrator's real job is much narrower than originally
scoped: watch for state changes at each stage and advance ArgusQueueItems
accordingly, firing notifications and enforcing one-guideline-at-a-time,
without ever touching the underlying, already-proven extraction code.

Detection method differs by stage, deliberately:
- Where WE dispatch the task (ingestion, and the first extract_clauses
  call that triggers map generation), we track task_id and check
  celery.result.AsyncResult -- the durable source of truth for whether
  a task actually finished and what it returned. The 5-minute Redis
  progress keys (update_progress / update_guideline_progress) are for
  live UI progress display only, not completion detection.
- Where an EXISTING route dispatches the next step outside our control
  (confirm_structure_map's re-dispatch, the manual activity-extraction
  trigger), we can't track a task_id at all -- we check real database
  state instead (has structure_map.confirmed become true? do clauses
  rows exist yet? do activities exist yet?).
"""
import logging
from datetime import datetime, timezone, timedelta

from celery import shared_task
from celery.result import AsyncResult

from app import db
from app.models.argus import ArgusQueueItems, ArgusNotifications
from app.models.ai import Guidelines, Clauses, ComplianceActivities
from app.services.manual_task import extract_guidelines, extract_clauses
from app.utils.email_service import send_via_azure_email

logger = logging.getLogger(__name__)

ACTIVE_STAGES = [
    "QUEUED", "STRUCTURE_MAP_PENDING", "AWAITING_MAP_REVIEW",
    "CLAUSE_EXTRACTING", "AWAITING_ACTIVITY_START", "ACTIVITY_EXTRACTING",
]

STALENESS_GRACE_MINUTES = {
    "QUEUED": 10,
    "STRUCTURE_MAP_PENDING": 10,
    "CLAUSE_EXTRACTING": 20,
    "ACTIVITY_EXTRACTING": 60,
}

ARGUS_EMAIL_ADDRESS = "complifyre@gmail.com"
IDLE_EMAIL_MIN_INTERVAL_HOURS = 24


def _create_notification(notification_type, message, queue_item_id=None):
    n = ArgusNotifications(
        notification_type=notification_type,
        queue_item_id=queue_item_id,
        message=message,
    )
    db.session.add(n)
    db.session.commit()
    logger.info(f"[ARGUS] Notification: {notification_type} -- {message}")
    return n


def _send_argus_email(subject, html_body):
    try:
        send_via_azure_email(
            recipient_email=ARGUS_EMAIL_ADDRESS,
            subject=subject,
            html_body=html_body,
        )
    except Exception as e:
        logger.error(f"[ARGUS] Failed to send notification email: {e}")


def _check_empty_sections(structure_map):
    if not structure_map:
        return True
    return len(structure_map.get("sections", [])) == 0


def _mark_failed(item, reason):
    item.stage = "FAILED"
    item.error_message = reason
    db.session.commit()
    _create_notification(
        "failure",
        f"'{item.source_filename}' has stopped and needs attention: {reason}",
        queue_item_id=item.id,
    )
    _send_argus_email(
        f"ARGUS: '{item.source_filename}' needs attention",
        f"<p>ARGUS has stopped processing <b>{item.source_filename}</b>.</p>"
        f"<p>{reason}</p><p>The queue is paused until this is resolved.</p>",
    )
    logger.error(f"[ARGUS] queue_item_id={item.id} marked FAILED: {reason}")


def _is_stale(item):
    grace = STALENESS_GRACE_MINUTES.get(item.stage)
    if grace is None or not item.started_at:
        return False
    started = item.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - started
    return elapsed >= timedelta(minutes=grace)


def _start_ingestion(item):
    with open(item.queued_file_path, "rb") as f:
        content = f.read()
    task = extract_guidelines.delay(item.source_filename, content)
    item.current_task_id = task.id
    item.started_at = datetime.now(timezone.utc)
    db.session.commit()
    logger.info(f"[ARGUS] Started ingestion for queue_item_id={item.id}, task_id={task.id}")


def _process_queued_ingesting(item):
    result = AsyncResult(item.current_task_id)
    if result.state == "FAILURE":
        _mark_failed(item, f"Ingestion failed: {result.result}")
        return
    if result.state != "SUCCESS":
        if _is_stale(item):
            _mark_failed(item, f"Ingestion has been running for over "
                                f"{STALENESS_GRACE_MINUTES['QUEUED']} minutes with no result -- may be stuck.")
        return
    guideline_id = (result.result or {}).get("guideline_id")
    if not guideline_id:
        _mark_failed(item, "Ingestion completed but returned no guideline_id.")
        return
    item.guideline_id = guideline_id
    item.stage = "STRUCTURE_MAP_PENDING"
    item.started_at = datetime.now(timezone.utc)
    task = extract_clauses.delay(guideline_id)
    item.current_task_id = task.id
    db.session.commit()
    logger.info(f"[ARGUS] queue_item_id={item.id} -> STRUCTURE_MAP_PENDING, "
                f"guideline_id={guideline_id}, task_id={task.id}")


def _process_structure_map_pending(item):
    result = AsyncResult(item.current_task_id)
    if result.state == "FAILURE":
        _mark_failed(item, f"Structure map generation failed: {result.result}")
        return
    if result.state != "SUCCESS":
        if _is_stale(item):
            _mark_failed(item, f"Structure map generation has been running for over "
                                f"{STALENESS_GRACE_MINUTES['STRUCTURE_MAP_PENDING']} minutes -- may be stuck.")
        return
    if (result.result or {}).get("status") != "awaiting_confirmation":
        _mark_failed(item, f"Unexpected result from structure map generation: {result.result}")
        return
    guideline = Guidelines.query.get(item.guideline_id)
    item.map_flagged = _check_empty_sections(guideline.structure_map if guideline else None)
    item.stage = "AWAITING_MAP_REVIEW"
    item.current_task_id = None
    db.session.commit()
    flag_text = " (flagged: no sections detected -- please check carefully)" if item.map_flagged else ""
    _create_notification(
        "map_ready",
        f"Structure map ready for review: '{item.source_filename}'{flag_text}",
        queue_item_id=item.id,
    )
    logger.info(f"[ARGUS] queue_item_id={item.id} -> AWAITING_MAP_REVIEW")


def _process_awaiting_map_review(item):
    guideline = Guidelines.query.get(item.guideline_id)
    if not guideline or not guideline.structure_map:
        return
    if not guideline.structure_map.get("confirmed"):
        return
    item.stage = "CLAUSE_EXTRACTING"
    item.started_at = datetime.now(timezone.utc)
    db.session.commit()
    logger.info(f"[ARGUS] queue_item_id={item.id} -> CLAUSE_EXTRACTING (confirmed by a COMPLIFYRE user)")


def _process_clause_extracting(item):
    clause_count = Clauses.query.filter_by(guideline_id=item.guideline_id).count()
    if clause_count == 0:
        if _is_stale(item):
            _mark_failed(item, f"Clause extraction has been running for over "
                                f"{STALENESS_GRACE_MINUTES['CLAUSE_EXTRACTING']} minutes with no clauses saved -- may be stuck.")
        return
    item.stage = "AWAITING_ACTIVITY_START"
    db.session.commit()
    _create_notification(
        "clauses_ready",
        f"Clauses extracted ({clause_count}) -- ready to start activity extraction: '{item.source_filename}'",
        queue_item_id=item.id,
    )
    logger.info(f"[ARGUS] queue_item_id={item.id} -> AWAITING_ACTIVITY_START, {clause_count} clauses")


def _process_awaiting_activity_start(item):
    started = db.session.query(ComplianceActivities.id).join(
        Clauses, ComplianceActivities.clause_id == Clauses.id
    ).filter(Clauses.guideline_id == item.guideline_id).first()
    if not started:
        return
    item.stage = "ACTIVITY_EXTRACTING"
    item.started_at = datetime.now(timezone.utc)
    db.session.commit()
    logger.info(f"[ARGUS] queue_item_id={item.id} -> ACTIVITY_EXTRACTING")


def _process_activity_extracting(item):
    total_clauses = Clauses.query.filter_by(guideline_id=item.guideline_id).count()
    clauses_with_activities = db.session.query(
        db.func.count(db.func.distinct(ComplianceActivities.clause_id))
    ).join(Clauses, ComplianceActivities.clause_id == Clauses.id).filter(
        Clauses.guideline_id == item.guideline_id
    ).scalar() or 0

    if clauses_with_activities < total_clauses:
        if _is_stale(item):
            _mark_failed(
                item,
                f"Activity extraction has been running for over "
                f"{STALENESS_GRACE_MINUTES['ACTIVITY_EXTRACTING']} minutes with no new progress "
                f"({clauses_with_activities}/{total_clauses} clauses done) -- may be stuck."
            )
        return

    item.stage = "COMPLETE"
    item.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    _create_notification(
        "guideline_complete",
        f"'{item.source_filename}' is complete and added to the library.",
        queue_item_id=item.id,
    )
    logger.info(f"[ARGUS] queue_item_id={item.id} -> COMPLETE")


STAGE_HANDLERS = {
    "STRUCTURE_MAP_PENDING": _process_structure_map_pending,
    "AWAITING_MAP_REVIEW": _process_awaiting_map_review,
    "CLAUSE_EXTRACTING": _process_clause_extracting,
    "AWAITING_ACTIVITY_START": _process_awaiting_activity_start,
    "ACTIVITY_EXTRACTING": _process_activity_extracting,
}


def _check_idle_and_notify():
    recent = ArgusNotifications.query.filter_by(notification_type="queue_idle").order_by(
        ArgusNotifications.created_at.desc()
    ).first()
    if recent and recent.created_at:
        created = recent.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created < timedelta(hours=IDLE_EMAIL_MIN_INTERVAL_HOURS):
            return
    _create_notification(
        "queue_idle",
        "The ARGUS queue is empty -- nothing is being processed. Add more circulars to keep building the library.",
    )
    _send_argus_email(
        "ARGUS: queue is empty",
        "<p>The ARGUS ingestion queue is currently empty -- nothing is being processed.</p>"
        "<p>Add more circulars to <code>watch_intake/</code> to keep the library growing.</p>",
    )
    logger.info("[ARGUS] Queue idle -- notification created")


@shared_task(bind=True)
def argus_orchestrator(self):
    active_item = ArgusQueueItems.query.filter(
        ArgusQueueItems.stage.in_(ACTIVE_STAGES),
    ).filter(
        db.or_(
            ArgusQueueItems.stage != "QUEUED",
            ArgusQueueItems.current_task_id.isnot(None),
        )
    ).order_by(ArgusQueueItems.queue_position.asc()).first()

    if active_item:
        if active_item.stage == "QUEUED":
            _process_queued_ingesting(active_item)
        else:
            handler = STAGE_HANDLERS.get(active_item.stage)
            if handler:
                handler(active_item)
        return {"action": "processed", "queue_item_id": active_item.id, "stage": active_item.stage}

    next_item = ArgusQueueItems.query.filter_by(stage="QUEUED", current_task_id=None).order_by(
        ArgusQueueItems.queue_position.asc()
    ).first()

    if next_item:
        _start_ingestion(next_item)
        return {"action": "started_ingestion", "queue_item_id": next_item.id}

    _check_idle_and_notify()
    return {"action": "idle"}
