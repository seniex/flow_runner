# Recording History and Controls Design

Date: 2026-07-17

## Goal

Preserve every completed input recording under a timestamped filename while retaining
`latest.json` compatibility, add an icon-only control that opens the recordings directory, and
adjust the workflow movement controls to the requested order and label.

## Recording Persistence

Stopping an active recording saves one in-memory event snapshot to two physical JSON files in the
active project's recordings directory:

- `recording_YYYYMMDD_HHMMSS.json` preserves that recording as history.
- `latest.json` is overwritten with the same events for existing playback actions and external
  workflows that already reference the stable filename.

The timestamp represents save time in local time. If a timestamped filename already exists, the
application appends `_2`, `_3`, and so on instead of overwriting an earlier recording. The same
dual-save behavior applies whether recording stops from the recording toggle, an accepted runtime
stop, or application shutdown.

Timestamp path generation belongs with application runtime paths. Recording serialization remains
in the input recording infrastructure. Both destinations are written from the same validated event
list so their content is identical.

If saving fails, the existing recording error handling remains responsible for reporting the
failure. A recording is reported as successfully saved only after both destinations have been
written.

## Open Recordings Directory Control

The runtime control group gains an action immediately after `暂停录制` / `继续录制`. Its visible
button is icon-only and uses a packaged open-folder icon. The action keeps the accessible text and
tooltip `打开录制目录`.

Triggering the action creates the active project's recordings directory when it does not yet exist,
then asks Qt to open that local directory with the operating system file manager. Failure to create
or open the directory is shown in the main-window status bar. Opening the directory is independent
of recording and runtime state, so the control remains enabled at all times.

The main window emits the user intent while application composition supplies the active recordings
directory and performs the desktop-service call. This keeps the reusable window testable without
hard-coding a global project path.

## Workflow Control Layout

The `组与流程` control order changes from:

1. `流程上移`
2. `流程下移`
3. `移动到组`

to:

1. `流程上移`
2. `移动组`
3. `流程下移`

Only presentation order and action text change. Moving a workflow between groups continues to use
the existing selection dialog and `move_workflow_to_group` behavior.

## Testing

Focused automated tests will verify:

- one stop writes identical timestamped and `latest.json` recordings;
- an existing timestamped name receives a numeric suffix and is not overwritten;
- every application stop path uses the same dual-save behavior;
- the directory action is placed after the recording-pause action, is icon-only, and exposes its
  tooltip;
- triggering the directory action invokes the configured directory opener and reports failure;
- workflow controls appear in `流程上移`, `移动组`, `流程下移` order;
- existing recording pause, playback, and workflow movement behavior remains intact.

The README recording section will document timestamped history, `latest.json` compatibility, and
the open-directory control.
