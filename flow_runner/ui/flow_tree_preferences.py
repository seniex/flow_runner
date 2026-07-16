from collections.abc import Iterable
from uuid import UUID

from PySide6.QtCore import QSettings


class FlowTreePreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    def collapsed_groups(self, project_id: UUID) -> frozenset[UUID]:
        raw = self._settings.value(self._key(project_id), [])
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        collapsed = set()
        for value in values:
            try:
                collapsed.add(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return frozenset(collapsed)

    def set_collapsed_groups(
        self,
        project_id: UUID,
        group_ids: Iterable[UUID],
    ) -> None:
        self._settings.setValue(
            self._key(project_id),
            sorted(str(group_id) for group_id in group_ids),
        )

    @staticmethod
    def _key(project_id: UUID) -> str:
        return f"flow_tree/{project_id}/collapsed_groups"
