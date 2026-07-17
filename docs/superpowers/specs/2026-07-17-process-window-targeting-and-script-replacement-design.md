# Process Window Targeting and Script Replacement Design

Date: 2026-07-17

## Goal

Make window conditions and window actions target stable executable process names instead of relying
on changing window titles, while preserving existing title-based project data. Replace the current
standalone window-control scripts in the active project with equivalent built-in window actions and
conditions without changing the separate long-running automation scripts.

## Scope

The built-in `system.window` condition and `system.window_action` action gain process-based window
selection. The active `data/project.json` is migrated only where a `system.launch` action invokes one
of these window-control scripts:

- `min_lanren.py`
- `RESTORE_lanren.py`
- `min.py`
- `RESTORE.py`
- `restore_platform.py`

`pet_explore.pyw` and `auto_war3.py` remain program-launch actions because they contain independent
image recognition, input, looping, and lifecycle behavior beyond window management. Recording
playback files such as `基本卡片.json`, `亮屏.json`, and `退出游戏.json` also remain recording actions.

## Window Selector Model

New guided configurations use a primary executable name and optional ordered fallbacks:

```json
{
  "process_name": "chrome.exe",
  "fallback_process_names": ["PotPlayerMini64.exe", "potplayer.exe"]
}
```

Process names are matched case-insensitively against the executable basename associated with each
top-level Win32 window. Empty names are rejected and duplicate fallback names are ignored after
case normalization.

Existing configurations containing only `title` remain valid and keep their current visible-title
substring behavior. A configuration must use either process matching or title matching, not both.
The normal editor exposes process matching. The legacy `title` field remains available through
loaded existing data and advanced JSON instead of occupying the common form.

## Win32 Matching and Selection

The Win32 backend enumerates visible top-level windows with non-empty titles. For every candidate it
records the handle, title, process ID, executable basename, foreground state, and minimized state.
Process lookup failures caused by short-lived windows are skipped without aborting the complete
enumeration.

Primary and fallback process names are evaluated in order. All windows belonging to the first name
that has matches form the selected match set; fallbacks are not mixed with primary matches.

Operation behavior is deterministic:

- `activate`: choose the foreground match first, otherwise a non-minimized match, otherwise the
  first enumerated match; restore it and place it in the foreground.
- `minimize`: minimize every window in the selected match set.
- `restore`: restore every window in the selected match set without changing which window is in the
  foreground.
- `move_resize`: apply geometry to the same single-window selection rule as `activate`, without
  activating it.

Title-based matching retains its existing first-match behavior for backward compatibility.

## Window Conditions

`system.window` uses the same selector and match ordering as window actions. A process condition
matches when at least one selected window exists. With `require_foreground=true`, it matches only
when the current foreground window belongs to the selected match set.

The condition result reports the selected executable name, all matched handles and titles, the
chosen primary handle, and foreground/minimized state. This makes diagnostics useful when one
process owns multiple top-level windows.

## Window Action Resources

Window actions continue to acquire one stable runtime resource key. Process targets use a key based
on the normalized ordered process list; legacy title targets retain the existing title-based key.
This prevents conflicting input/window actions against the same process target from running in
parallel.

## Standalone Script Replacement

Known script launches in all three active workflow groups are replaced as follows:

| Script | Built-in replacement |
|---|---|
| `min_lanren.py` | Minimize all `lanren2.exe` windows |
| `RESTORE_lanren.py` | Activate `lanren2.exe` |
| `min.py` | Minimize `war3.exe` with fallback `warcraft iii.exe`, wait 0.3 seconds, then activate `chrome.exe` with PotPlayer fallbacks |
| `RESTORE.py` | Activate `war3.exe` with fallback `warcraft iii.exe` |
| `restore_platform.py` | Activate `platform.exe` |

The explicit 0.3-second wait preserves the only intentional delay inside `min.py`. Process startup,
module imports, and COM initialization disappear because no child Python process is launched.

Every matching launch occurrence is migrated across groups A, B, and C, including `开始游戏`,
`还原lanren`, `最小化war3`, `最小化`, `还原war3`, `转职3全流程`, `100`, and other numbered flows
that use the same scripts. Routes, workflow IDs, step IDs, unrelated actions, and user-edited timing
remain unchanged.

When one script maps to multiple built-in actions, the replacement actions occupy the same step and
execute in the script's original order. Existing legacy `wait_seconds` semantics already converted
into explicit wait actions remain in place; the migration does not add duplicate waits.

## Recorded Script Compatibility

Recording playback remains unchanged. Window-control replacement must complete synchronously before
the next action or routed workflow begins, unlike launching an external helper and racing its child
process. A workflow can additionally use a process-based `system.window` condition with
`require_foreground=true` before a coordinate click when it needs a positive readiness check.

The migration does not rewrite the current user-edited `点击屏幕1` action or any recording JSON.
Those files and actions are treated as user-owned data unless a later request explicitly changes
their timing or coordinates.

## Error Handling

If none of the configured process names has a visible top-level window, a window action fails with a
message listing the attempted executable names. Conditions return `no_match` with the same attempted
names in provider data. Transient PID/process lookup errors are included in debug provider data but
do not prevent other windows from matching.

Legacy title actions preserve their current `window not found` failure behavior.

## Testing

Automated tests cover:

- case-insensitive executable basename matching;
- ordered fallback process selection;
- foreground, non-minimized, and enumeration-order single-window selection;
- multi-window minimize and restore;
- process condition existence and foreground requirements;
- legacy title configuration validation and execution;
- rejection of ambiguous process-plus-title configurations;
- localized labels, summaries, common fields, advanced JSON round trips, and compact layouts;
- migration of every known window-control script occurrence while preserving routes, IDs, waits,
  recordings, `pet_explore.pyw`, and `auto_war3.py` launches;
- project validation and the complete automated suite.

Real Windows acceptance verifies the five script-equivalent behaviors against running LanRen2,
War3, Chrome/PotPlayer, and Platform windows, followed by the affected workflow sequences and their
recorded clicks.
