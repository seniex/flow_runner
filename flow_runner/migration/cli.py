from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from flow_runner.infrastructure.input.recording import RecordingStore
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.migration.legacy import (
    LegacyConversionPaths,
    convert_legacy_config,
    convert_legacy_recording,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a legacy Flow Runner project")
    parser.add_argument("--source", type=Path, default=Path("config/flow_runner.json"))
    parser.add_argument("--output", type=Path, default=Path("project.json"))
    parser.add_argument("--paddle-executable", type=Path, required=True)
    parser.add_argument("--recording-source-dir", type=Path, default=Path("scripts"))
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument(
        "--pythonw-executable",
        type=Path,
        default=Path(sys.executable).with_name("pythonw.exe"),
    )
    args = parser.parse_args(argv)

    source = json.loads(args.source.read_text(encoding="utf-8"))
    output = args.output.resolve()
    recording_directory = output.parent / "recordings" / "legacy"
    paths = LegacyConversionPaths(
        project_directory=output.parent,
        python_executable=args.python_executable.resolve(),
        pythonw_executable=args.pythonw_executable.resolve(),
        paddle_executable=args.paddle_executable.resolve(),
        recording_directory=recording_directory,
    )
    project = convert_legacy_config(source, paths)
    converted_recordings = _convert_recordings(
        source,
        args.recording_source_dir,
        recording_directory,
    )
    ProjectStore(output).save(project)
    report = {
        "output": str(output),
        "groups": len(project.groups),
        "workflows": sum(len(group.workflows) for group in project.groups),
        "steps": sum(
            len(workflow.steps) for group in project.groups for workflow in group.workflows
        ),
        "recordings": converted_recordings,
        "reference_errors": project.validate_references(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _convert_recordings(
    source: dict[str, Any],
    fallback_directory: Path,
    output_directory: Path,
) -> list[dict[str, Any]]:
    references = {
        str(step.get("script_path", ""))
        for group in source.get("flow_groups", [])
        for flow in group.get("flows", [])
        for step in flow.get("steps", [])
        if step.get("type") == "run_script"
    }
    report: list[dict[str, Any]] = []
    for reference in sorted(references):
        original = Path(reference)
        source_path = original if original.is_file() else fallback_directory / original.name
        if not source_path.is_file():
            raise FileNotFoundError(f"legacy recording does not exist: {reference}")
        raw_events = json.loads(source_path.read_text(encoding="utf-8"))
        events = convert_legacy_recording(raw_events)
        target = output_directory / original.name
        RecordingStore.save(target, events)
        report.append(
            {
                "source": str(source_path.resolve()),
                "output": str(target.resolve()),
                "legacy_events": len(raw_events),
                "converted_events": len(events),
            }
        )
    return report


if __name__ == "__main__":
    raise SystemExit(main())
