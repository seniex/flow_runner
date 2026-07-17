from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    application_root: Path
    data_directory: Path
    project_file: Path
    backup_directory: Path
    template_directory: Path
    recording_directory: Path
    log_directory: Path

    @classmethod
    def default(cls, application_root: Path) -> ApplicationPaths:
        root = application_root.resolve()
        data = root / "data"
        return cls._build(root, data, data / "project.json")

    @classmethod
    def for_project(cls, project_file: Path) -> ApplicationPaths:
        project = project_file.resolve()
        data = project.parent
        return cls._build(data, data, project)

    @classmethod
    def _build(
        cls,
        application_root: Path,
        data_directory: Path,
        project_file: Path,
    ) -> ApplicationPaths:
        return cls(
            application_root=application_root,
            data_directory=data_directory,
            project_file=project_file,
            backup_directory=data_directory / "backups",
            template_directory=data_directory / "templates",
            recording_directory=data_directory / "recordings",
            log_directory=data_directory / "logs",
        )

    @property
    def latest_recording_file(self) -> Path:
        return self.recording_directory / "latest.json"

    @property
    def legacy_directory(self) -> Path:
        return self.data_directory / "legacy"

    @property
    def session_name(self) -> str:
        return self.application_root.name or "flow_runner"


def timestamped_recording_file(directory: Path, saved_at: datetime) -> Path:
    stem = f"recording_{saved_at:%Y%m%d_%H%M%S}"
    candidate = directory / f"{stem}.json"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{suffix}.json"
        suffix += 1
    return candidate
