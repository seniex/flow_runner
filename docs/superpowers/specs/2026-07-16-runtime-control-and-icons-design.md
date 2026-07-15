# Runtime Control, Startup Minimization, and Icons Design

## Goal

Add an optional minimize-on-workflow-start setting, provide a complete high-contrast icon system,
and make pause and stop consistently control workflow execution, detection, recording playback,
and the independent input recorder.

## Confirmed User Experience

- `启动流程后最小化` is a project setting shown in the settings dialog.
- The setting defaults to off and is stored as `settings.minimize_on_workflow_start`.
- A successfully submitted workflow or parallel-block run minimizes the main window. Toolbar and
  global-hotkey starts behave identically.
- The window stays minimized when the run stops, fails, or completes. The user restores it
  manually.
- Pause uses strict cooperative semantics: no new detection or input is issued while paused;
  built-in waits, segmented input, and recording playback freeze at checkpoints and resume from
  the same point.
- The independent input recorder ignores input while paused, resumes into the same recording, and
  excludes paused time from event timestamps.
- Explicit stop cancels the runtime, stops and saves an active independent recording, and releases
  held mouse and keyboard inputs. Natural runtime completion leaves the independently controlled
  recorder unchanged.
- An atomic system call already in progress may finish. On pause, its result is held without
  starting follow-up work until resume. On stop, its result is discarded and cannot trigger a
  later action.
- Already delivered clicks and keys, completed window operations, and launched external processes
  are not reversed.

## Runtime Control Architecture

The existing `Runner`, `RunnerBridge`, action registry, and input abstractions remain in place.
`CancellationToken` becomes the shared lifecycle primitive for a run instead of cancellation and
pause being split between the token and a private runner event. It owns cancellation and pause
state and exposes idempotent `cancel`, `pause`, `resume`, `wait_until_active`, and pause-aware
`sleep` operations.

`Runner` creates one lifecycle token per normal, parallel, selected-step, or preview run. The same
token reaches `StepRuntime` and the execution registry. This keeps the existing dependency
direction: the engine owns lifecycle state, while capabilities receive only the callbacks they
need.

The pause-aware sleep measures active elapsed time. Waiting, retry delays, segmented mouse and
keyboard actions, and recording playback already use the injected sleep path, so they freeze at
their existing segment or event boundaries without restarting completed work. Condition and
action boundaries call `wait_until_active` before issuing new work.

Condition evaluation gains the same cancellation race already used for actions. Cancellation
returns a cancelled step without waiting for a provider coroutine to produce a usable result.
Native or thread-backed calls that cannot be forcibly terminated may finish in the background,
but their result is ignored and their resource lease is released by normal cleanup.

Main-window buttons and global hotkeys use the same intent path. Accepted pause, resume, and stop
transitions are exposed to the application composition, which applies the matching operation to
the independent recorder and releases held input on termination. This removes the current gap in
which `Runner.stop()` cancels a workflow but leaves an active recording listener running.

## Independent Recorder Semantics

`RecordingRecorder` gains explicit pause and resume operations. The listener remains installed
while paused, but callbacks do not append events. The recorder tracks accumulated paused time and
subtracts it from subsequent timestamps. Repeated pause or resume calls do nothing.

Stopping while paused closes the listener and saves events captured before the pause. A save error
is reported in Chinese but does not prevent the listener from closing, the runtime from stopping,
or held inputs from being released. F9 continues to start and stop independent recording directly.

Pause applies to the recorder only when a workflow runtime accepts the pause transition. If no
runtime is active, the runtime pause action remains unavailable and does not change a standalone
recording session.

## Startup Minimization

The settings dialog reads and writes the boolean `minimize_on_workflow_start` key while preserving
unknown project settings. Missing or non-boolean values behave as `false`; accepting the dialog
writes a valid boolean.

`RunnerBridge` reports whether a requested workflow or parallel run was accepted. `MainWindow`
calls `showMinimized()` only after an accepted submission and only when the setting is enabled.
Invalid selections, an unavailable runner service, and duplicate starts leave the window visible.
Selected-step execution and condition preview do not minimize the application.

Minimizing does not alter saved main-window dimensions. Manual restoration returns to the prior
normal or maximized state, and runtime completion does not raise or activate the window.

## Icon System

The approved visual direction is the solid high-contrast option:

- The application mark combines workflow nodes with a play triangle and remains legible at small
  title-bar and taskbar sizes.
- Start uses a green semantic accent, while stop and destructive commands use red. Other command
  icons use a light neutral foreground and let Qt derive disabled appearance.
- Buttons retain their Chinese text; icons improve scanning without replacing labels.
- Flow-tree branches use filled light-blue triangles that remain visible in normal, hovered,
  selected, expanded, and collapsed states.

Icon assets live below `flow_runner/resources/icons/` and are loaded through one UI icon helper.
The helper maps familiar commands such as start, pause, resume, stop, record, save, undo, settings,
diagnostics, add, copy, rename, delete, selected-step run, and condition preview to packaged assets.
The branch-open and branch-closed assets are referenced by the application stylesheet so their
color remains part of the central theme.

The application icon is set on `QApplication` and `MainWindow`. On Windows, the process also sets a
stable explicit application user model identifier before the first top-level window is created so
the configured mark is used by the taskbar and Alt+Tab instead of the generic Python icon.

Missing optional command assets return an empty `QIcon` so the application can still start. Tests
and packaging checks require all declared production assets, including the application and branch
icons, to exist in the built package.

## Error Handling and Safety

- Stop has priority over pause and wakes paused waiters before cancellation propagates.
- Pause, resume, stop, and input release are idempotent.
- Cancellation cleanup releases acquired interaction and observation resources.
- Recording-save failures are visible but cannot keep an input listener alive.
- Icon loading failure never blocks startup.
- Minimize-on-start is applied only after the runtime accepts the request.
- Runtime termination always releases tracked held inputs, including recording-playback keys.

## Automated Verification

Focused tests cover:

- lifecycle-token pause, resume, cancellation, pause-aware elapsed time, and stop while paused;
- condition cancellation and prevention of post-cancellation actions;
- wait, segmented mouse and keyboard input, and recording playback freezing at pause checkpoints;
- recording callbacks being ignored during pause, corrected timestamps after resume, stopping
  while paused, and save-failure cleanup;
- toolbar and hotkey pause/stop paths producing the same recorder and runtime behavior;
- setting default, dialog round-trip, accepted workflow/parallel starts, rejected starts, and no
  automatic restore;
- non-empty application and command icons, declared asset existence, and high-contrast branch
  stylesheet selectors.

After focused tests, use global Python to run the complete project quality gate: the full pytest
suite, Ruff lint and formatting checks, mypy, compileall, and pip dependency checks.

## Manual Windows Acceptance

1. Confirm the custom mark appears in the title bar, taskbar, and Alt+Tab at normal Windows display
   scaling.
2. Confirm every common command button remains readable and the tree branch triangles are obvious
   without hovering, including selected rows.
3. Enable `启动流程后最小化`; start by button and F6, and confirm accepted workflow and parallel
   runs minimize while invalid or duplicate starts do not.
4. Confirm stopping or natural completion does not automatically restore the main window.
5. During detection, wait, segmented input, recording playback, and independent recording, use F8
   to pause and resume and verify that no new automation input is emitted while paused.
6. Use F7 during playback and independent recording; confirm all future events stop, held inputs
   release, the recording is saved, and the window stays minimized.

## Out of Scope

- Reversing an input event or system operation that completed before pause or stop.
- Terminating programs launched earlier by a workflow.
- Automatically restoring, activating, or raising the main window after a run.
- Changing the three-column workspace layout or the workflow execution model.
