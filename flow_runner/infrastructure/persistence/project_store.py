import os
import shutil
import time
from pathlib import Path

from pydantic import ValidationError

from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import Project


class ProjectStore:
    def __init__(self, path: Path, backup_limit: int = 5) -> None:
        self.path = path
        self.backup_limit = backup_limit

    def load(self) -> Project:
        return self._load_path(self.path)

    def save(self, project: Project) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        data = project.model_dump_json(indent=2)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self._load_path(temporary)
        if self.path.exists():
            backup = self.path.with_name(f"{self.path.stem}.{time.time_ns()}.bak{self.path.suffix}")
            shutil.copy2(self.path, backup)
        os.replace(temporary, self.path)
        self._trim_backups()

    def _load_path(self, path: Path) -> Project:
        try:
            project = Project.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise ConfigurationError(f"invalid project JSON at {path}: {error}") from error
        errors = project.validate_references()
        if errors:
            raise ConfigurationError("invalid project references: " + "; ".join(errors))
        return project

    def _trim_backups(self) -> None:
        backups = sorted(
            self.path.parent.glob(f"{self.path.stem}.*.bak{self.path.suffix}"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for backup in backups[self.backup_limit :]:
            backup.unlink()
