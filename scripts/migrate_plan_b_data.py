from __future__ import annotations

import argparse
import sys
from pathlib import Path

_APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(_APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(_APPLICATION_ROOT))


def main() -> int:
    from flow_runner.migration.data_directory import build_migration_plan, execute_migration

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = build_migration_plan(args.root)
    for entry in plan.entries:
        print(f"{entry.category}: {entry.source} -> {entry.destination}")
    if not args.apply:
        print("DRY RUN: no files changed")
        return 0
    execute_migration(plan)
    print(f"MIGRATED: {plan.data_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
