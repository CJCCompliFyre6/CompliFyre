import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''    FORWARD_GRACE_DAYS = 7
    most_recent_forward = (
        UserJourneyEvents.query
        .filter_by(organization_id=org.organization_id, event_type="forwarded")
        .order_by(UserJourneyEvents.occurred_at.desc())
        .first()
    )
    if most_recent_forward:
        occurred_at = most_recent_forward.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - occurred_at).days < FORWARD_GRACE_DAYS:
            return "NONE"'''

new = '''    FORWARD_GRACE_DAYS = 7
    most_recent_forward = (
        UserJourneyEvents.query
        .filter_by(organization_id=org.organization_id, event_type="forwarded")
        .order_by(UserJourneyEvents.occurred_at.desc())
        .first()
    )
    # Fix 2026-08-09: this was checking org-wide, not per-user -- meaning
    # it correctly silenced the gate for A (the person who forwarded)
    # but ALSO accidentally silenced it for B (the colleague forwarded
    # TO), who has never actually seen the LOI even once. Now only
    # applies if the current viewer is the SAME user_id that did the
    # forwarding, matching this function's own (previously unused)
    # user= parameter.
    if most_recent_forward and user is not None and most_recent_forward.user_id == user.id:
        occurred_at = most_recent_forward.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - occurred_at).days < FORWARD_GRACE_DAYS:
            return "NONE"'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_loi_gate_per_user_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_loi_gate_per_user_fix)")
