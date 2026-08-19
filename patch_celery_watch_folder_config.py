#!/usr/bin/env python3
"""
Patch: Register scan_watch_folder() in celery_app.py's task_routes (routed
to the existing "extract_guidelines" queue -- see companion manual_task.py
patch for why) and beat_schedule (every 5 minutes, matching the existing
"fix-pending-checklists-every-5-min" convention already in this file).

Uses whitespace-tolerant (.rstrip()-based) line matching throughout, since
this file has trailing whitespace on at least one anchor-adjacent line --
learned the hard way twice already this session with exact-block matching.

Usage:
    python3 patch_celery_watch_folder_config.py --dry-run
    python3 patch_celery_watch_folder_config.py --apply
    python3 patch_celery_watch_folder_config.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "celery_app.py"
BACKUP = TARGET.with_suffix(".py.bak_watch_folder_config")

ROUTE_ANCHOR = "'app.services.eve_tasks.copy_checklist_to_project': {'queue': 'eve_checklist'},"
NEW_ROUTE_LINE = "            'app.services.manual_task.scan_watch_folder': {'queue': 'extract_guidelines'},\n"

BEAT_TASK_MARKER = '"fix-pending-checklists-every-5-min"'
NEW_BEAT_ENTRY = (
    '            "scan-watch-folder-every-5-min": {\n'
    '                "task": "app.services.manual_task.scan_watch_folder",\n'
    '                "schedule": 300.0,\n'
    '            },\n'
)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        if not BACKUP.exists():
            print(f"No backup found at {BACKUP}. Nothing to roll back.")
            sys.exit(1)
        shutil.copy2(BACKUP, TARGET)
        print(f"Rolled back {TARGET} from {BACKUP}.")
        return

    if not TARGET.exists():
        print(f"ERROR: target file not found: {TARGET}")
        sys.exit(1)

    lines = TARGET.read_text().splitlines(keepends=True)
    full_text = "".join(lines)

    if "scan_watch_folder" in full_text:
        print("Patch already applied. Nothing to do.")
        return

    # --- Find route insertion point: line whose stripped content matches ROUTE_ANCHOR ---
    route_idx = None
    matches = [i for i, l in enumerate(lines) if l.strip() == ROUTE_ANCHOR]
    if len(matches) != 1:
        print(f"ERROR: route anchor matched {len(matches)} times (expected 1). Aborting.")
        sys.exit(1)
    route_idx = matches[0]

    # --- Find beat_schedule insertion point: the closing "}," of the
    # fix-pending-checklists entry, i.e. the first line whose stripped
    # content is "}," AFTER the line containing BEAT_TASK_MARKER ---
    marker_idx = None
    for i, l in enumerate(lines):
        if BEAT_TASK_MARKER in l:
            marker_idx = i
            break
    if marker_idx is None:
        print("ERROR: could not find the fix-pending-checklists-every-5-min marker. Aborting.")
        sys.exit(1)

    beat_close_idx = None
    for i in range(marker_idx, min(marker_idx + 10, len(lines))):
        if lines[i].strip() == "},":
            beat_close_idx = i
            break
    if beat_close_idx is None:
        print("ERROR: could not find the closing '},' for the fix-pending-checklists entry. Aborting.")
        sys.exit(1)

    # Apply both insertions -- route first (earlier in file), then beat (later),
    # building the output in a single pass using both indices.
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        if i == route_idx:
            out.append(NEW_ROUTE_LINE)
        if i == beat_close_idx:
            out.append(NEW_BEAT_ENTRY)

    new_content = "".join(out)

    if args.dry_run:
        print(f"Route anchor found at line {route_idx+1}.")
        print(f"Beat-schedule closing brace found at line {beat_close_idx+1} (marker at line {marker_idx+1}).")
        print("Would insert:")
        print(" ", NEW_ROUTE_LINE.strip())
        print(" ", NEW_BEAT_ENTRY.strip().replace(chr(10), " / "))
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(new_content)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
