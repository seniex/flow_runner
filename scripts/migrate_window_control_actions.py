from __future__ import annotations

import argparse
import sys
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))


def main(argv: list[str] | None = None) -> int:
    from flow_runner.infrastructure.persistence.project_store import ProjectStore
    from flow_runner.migration.window_controls import (
        count_window_control_scripts,
        migrate_project_window_control_actions,
    )

    parser = argparse.ArgumentParser(description="Replace standalone window-control launches")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    store = ProjectStore(args.project, backup_directory=args.project.parent / "backups")
    project = store.load()
    counts = count_window_control_scripts(project)
    if not counts:
        print("No known window-control script launches found")
        return 0
    for script_name, count in sorted(counts.items()):
        print(f"{script_name}: {count}")
    if not args.apply:
        print("DRY RUN: no files changed")
        return 0

    migrated = migrate_project_window_control_actions(project)
    store.save(migrated)
    print(f"MIGRATED: {args.project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
