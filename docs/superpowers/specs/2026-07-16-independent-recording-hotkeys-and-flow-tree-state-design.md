# Independent Recording Controls, Hotkey Filtering, and Flow-Tree State Design

## Goal

Give independent input recording its own pause/resume control and configurable hotkey, prevent all
configured application-control hotkeys from entering recordings, apply hotkey changes immediately,
and remember each project's flow-group expansion state locally without dirtying project JSON.

## Confirmed Requirements

- Workflow pause/resume and recording pause/resume are completely independent.
- Add a dedicated `暂停录制` / `继续录制` button.
- Add a dedicated configurable `record_pause` hotkey; its default is empty.
- The start, stop, workflow-pause, recording-toggle, and recording-pause hotkeys are all excluded
  from recorded keyboard events.
- Saving changed hotkeys applies both control behavior and recording filtering immediately.
- Explicit workflow stop still stops and saves an active or paused independent recording.
- Natural workflow completion still leaves independent recording active.
- Flow-group expanded/collapsed state is stored locally, separated by project, and never written to
  `data/project.json`.
- The parallel-monitor root remains expanded by default and is outside this persistence scope.

## Observed Behavior and Root Causes

The latest runtime log contains accepted workflow pause/resume transitions, so workflow pause works
when a runtime loop is active. The existing pause button is deliberately disabled while no workflow
is running, which leaves an independent recording with no usable pause entry point. The application
also connects accepted workflow pause directly to `RecordingRecorder.pause()` and workflow resume
to `RecordingRecorder.resume()`, coupling two states that now need to be independent.

The latest `data/recordings/latest.json` contains F10 and F6 events. The project currently maps F10
to workflow pause and F6 to recording toggle. `HotkeyService` and `RecordingRecorder` use separate
pynput listeners, so both listeners receive the same physical key. The recorder currently accepts
every keyboard callback and has no configured-key filter. This also explains the release event from
the key that starts recording and the press event from the key that stops recording.

`HotkeyService` builds its bindings once during application composition. Updating project settings
changes the project model but does not restart the listener, so saved shortcut changes do not take
effect until restart. `FlowTreePanel.set_project()` rebuilds every group and calls
`group_item.setExpanded(True)`, discarding the user's collapsed state after any project refresh.

## Recording State and User Interface

The left runtime controls gain a `pause_recording_action` beside the existing recording action.
Its object name is `pauseRecordingAction`, allowing the central icon map and UI tests to address it.

The UI state is:

| Recorder state | Recording action | Recording-pause action |
| --- | --- | --- |
| Stopped | `录制` | `暂停录制`, disabled |
| Recording | `停止录制` | `暂停录制`, enabled, pause icon |
| Paused | `停止录制` | `继续录制`, enabled, resume icon |

Starting a recording always enters the recording state. Pausing ignores new mouse and keyboard
callbacks and freezes the recording's active-time clock. Resuming continues from that active-time
position. Stopping from either recording or paused state saves the accepted events and resets both
actions. Invoking recording pause while stopped is a no-op.

Workflow pause no longer calls the recorder. Recording pause never calls the runner. Existing
workflow pause signals may remain for compatibility, but application composition will not use them
to mutate recording state. Explicit workflow stop continues using the accepted-stop signal to stop
and save the recorder. This preserves the previously approved safety boundary without coupling the
two pause states.

## Hotkey Model and Immediate Reconfiguration

`HotkeyConfig` gains:

```python
record_pause: str = ""
```

The existing normalization and uniqueness validation includes the new field. `SettingsDialog`
adds the Chinese row `暂停/继续录制热键`. Empty disables the shortcut. This work does not add chord
support; it preserves the current single-key hotkey model.

`HotkeyService` gains an explicit active-service state and `reconfigure(config)`. Reconfiguration
updates its binding map even before services start. While services are active it replaces the
listener immediately. If the new listener cannot start, it attempts to restore the previous
bindings/listener and raises an error for the UI status bar. A service with no enabled bindings
remains active logically so that adding bindings later can create a listener without restarting the
application.

After settings are accepted, `MainWindow` emits the validated `HotkeyConfig`. Application
composition applies it through one coordination method:

1. reconfigure `HotkeyService`;
2. after success, update the recorder's ignored-key set from the service's effective bindings;
3. update the status bar;
4. on failure, keep the recorder filter aligned with the restored effective bindings and report
   `快捷键更新失败：...`.

This makes control behavior and filtering switch together. The project setting can still be saved
if a real listener restart fails; restarting the application will retry that saved configuration.

## Recorder-Level Control-Key Filtering

`RecordingRecorder` owns a thread-safe `frozenset[str]` of ignored normalized key names. It exposes
`set_ignored_keys(keys)`. Both `_on_press` and `_on_release` normalize the pynput key using the same
uppercase naming convention as `HotkeyService` and return before `_append` when the key is ignored.
Mouse callbacks are unchanged.

The ignored set always comes from the effective bindings for:

- workflow start;
- workflow stop;
- workflow pause/resume;
- recording start/stop;
- recording pause/resume.

Filtering before event creation avoids incomplete press/release pairs and avoids ambiguous
post-save cleanup. When settings change during recording, the ignored set changes atomically. New
control keys are excluded immediately. Keys removed from the configuration become ordinary
recordable keys for subsequent events.

## Application Coordination

`MainWindow` adds `recordPauseRequested` and a hotkey-settings-applied signal carrying the validated
configuration. `ApplicationComposition` adds:

- `toggle_recording_pause()` to pause/resume only the recorder and update UI/status text;
- `apply_hotkey_config()` to reconfigure the listener and recorder filter as one operation.

The hotkey action map gains `record_pause: window.recordPauseRequested.emit`. Application creation
sets the recorder's ignored keys before services start, including injected test configurations.
The existing recording-toggle and accepted-runtime-stop error handling remains in force.

## Local Flow-Group Expansion Preferences

A focused `FlowTreePreferences` class wraps `QSettings`. Its key space is partitioned by stable
project UUID. It stores only collapsed group UUID strings, for example:

```text
flow_tree/<project-id>/collapsed_groups
```

Storing collapsed groups preserves current behavior naturally:

- no local value means all groups expanded;
- newly added groups default to expanded;
- expanding removes the UUID from the stored collapsed set;
- collapsing adds it;
- stale UUIDs for deleted groups are removed when the current state is persisted.

`FlowTreePanel` exposes a `groupExpansionChanged(group_id, expanded)` signal and a restoration method
that applies a set of collapsed group IDs while suppressing persistence callbacks caused by the
restoration itself. `MainWindow` injects or constructs `FlowTreePreferences`, restores state after
every tree rebuild, and persists user expansion changes immediately. These operations do not touch
`ProjectViewModel`, undo history, dirty state, or project saving.

## Error Handling and Compatibility

- Existing projects without `record_pause` load with the empty default, avoiding conflicts with
  customized F-keys.
- Duplicate validation covers all five configured controls and continues to reject ambiguous
  bindings before settings are accepted.
- A recording listener or save failure retains the current Chinese status reporting and never
  blocks accepted workflow stop or input release.
- Hotkey-listener replacement failure is reported and rolls back runtime bindings when possible.
- Malformed local collapsed-group values are ignored; groups default to expanded.
- Moving a project file does not lose local tree state because the project UUID, not the path, is
  used as the preference identity.
- The user's existing `data/project.json` modifications are outside implementation scope and must
  not be staged or rewritten.

## Test Strategy

Focused automated tests will cover:

1. `HotkeyConfig.record_pause` default, normalization, uniqueness, and settings round-trip.
2. `HotkeyService.reconfigure()` before start, while active, with empty bindings, and rollback after
   listener-start failure.
3. Recorder filtering of control-key presses and releases, including F6/F10-style start/stop edges.
4. Updating ignored keys during recording: new keys filtered immediately and removed keys recorded
   afterward.
5. Dedicated recording-pause button and shortcut states without an active workflow.
6. Workflow pause leaving recorder state unchanged and recording pause leaving runner state
   unchanged.
7. Explicit workflow stop saving a manually paused recording; natural completion retaining it.
8. Flow-tree preferences round-trip, per-project isolation, malformed-value handling, refresh
   restoration, new-group default expansion, and unchanged project dirty state.
9. Existing runtime, recording, hotkey, icon, main-window, and application smoke suites.
10. Full global-Python pytest, Ruff, formatting, mypy, compileall, and pip-check gates.

## Manual Acceptance

1. Start recording with no workflow; pause and resume using both button and the configured shortcut.
2. Confirm the recording-pause button switches Chinese text and pause/resume icon correctly.
3. Run and pause a workflow while recording; confirm the recording continues unless separately
   paused.
4. Pause recording while a workflow runs; confirm the workflow continues.
5. Change every hotkey in Settings without restarting; confirm new keys work immediately and old
   keys no longer control the application.
6. Save a recording and verify none of the five current control keys appear in
   `data/recordings/latest.json`.
7. Change a hotkey during an active recording; confirm the newly configured control key is filtered
   immediately.
8. Collapse different groups in two projects, restart or refresh each project, and confirm their
   local states remain independent without creating an unsaved-project indicator.
