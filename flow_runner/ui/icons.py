from pathlib import Path

from PySide6.QtGui import QIcon

ICON_DIRECTORY = Path(__file__).resolve().parents[1] / "resources" / "icons"

ACTION_ICON_NAMES = {
    "saveProjectAction": "save",
    "undoProjectAction": "undo",
    "addStepAction": "add",
    "addTemplateStepAction": "template",
    "removeStepAction": "delete",
    "moveStepUpAction": "move-up",
    "moveStepDownAction": "move-down",
    "addGroupAction": "add",
    "copyGroupAction": "copy",
    "addWorkflowAction": "add",
    "copyWorkflowAction": "copy",
    "renameFlowAction": "edit",
    "moveWorkflowUpAction": "move-up",
    "moveWorkflowDownAction": "move-down",
    "moveWorkflowGroupAction": "move-group",
    "deleteFlowAction": "delete",
    "projectSettingsAction": "settings",
    "addParallelBlockAction": "add",
    "editParallelBlockAction": "edit",
    "deleteParallelBlockAction": "delete",
    "copyStepAction": "copy",
    "startWorkflowAction": "start",
    "pauseWorkflowAction": "pause",
    "stopWorkflowAction": "stop",
    "recordAction": "record",
    "diagnosticsAction": "diagnostics",
    "runSelectedStepAction": "start",
    "previewConditionAction": "preview",
}


def icon(name: str) -> QIcon:
    path = ICON_DIRECTORY / f"{name}.svg"
    return QIcon(str(path)) if path.is_file() else QIcon()


def application_icon() -> QIcon:
    return icon("app")
