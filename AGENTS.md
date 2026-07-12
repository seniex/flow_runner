# Project Agent Instructions

## Before Starting Any Task

1. Read this file and any more specific `AGENTS.md` files that apply to the files being changed.
2. Read the project `README.md` and relevant design, architecture, or status documents when they exist.
3. Check the current `git status` and `git diff`.
4. Continue from the current code state and do not repeat completed work.

## Core Principles

- Preserve existing behavior unless the requested change explicitly requires otherwise.
- Keep changes focused on the requested task; do not modify unrelated modules.
- Prefer small, reviewable changes over broad rewrites.
- Reuse existing interfaces and abstractions where practical.
- Keep business logic separate from presentation, transport, and framework-specific code.
- Add focused tests for bug fixes and behavior changes when practical.

## Task Flow

For each task:

1. Analyze the current code state and relevant existing behavior.
2. List the proposed plan.
3. Wait for the user to confirm the plan or adjust the requirement before modifying files.
4. Modify code, documentation, or configuration only after that confirmation.
5. Run relevant tests and checks in proportion to the risk of the change.
6. Update relevant project documentation or status records when the change affects them.
7. Clearly report completed work, verification results, and any remaining manual checks.

Do not begin file modifications before the user confirms the listed plan unless the user explicitly
asks to skip confirmation. If a requirement is ambiguous or risky to infer, ask the user to clarify.

## File Editing

- Preserve user changes and work carefully in a dirty worktree.
- Do not overwrite or revert unrelated changes.
- Keep the existing encoding and line-ending conventions.
- Use UTF-8 for text files unless the project explicitly requires another encoding.
- Avoid broad mechanical rewrites when a focused edit is sufficient.
- Do not edit generated files unless the project workflow explicitly requires it.

## Testing

- Discover and use the project's existing test, lint, format, type-check, build, and smoke commands.
- Start with focused checks for the changed area, then run broader validation when warranted.
- Prefer tests that are deterministic and do not depend on a real display, network, or external service.
- Do not claim a check passed unless it was actually run successfully.
- If a required real-environment check cannot be automated, explicitly hand it off to the user.

## Sandbox and Tooling

On Windows, sandboxed commands can fail before execution with setup or access errors. When this
happens:

- Do not repeatedly retry the same sandboxed command after the same failure.
- If the command is required, retry once with narrowly scoped elevated permission and a concise
  justification.
- Prefer an already approved narrow command prefix when one exists.
- Do not work around sandbox failures with destructive commands or unrelated file operations.
- Report the command as blocked only after the approved fallback fails or permission is denied.

## Design and UI Work

If design files exist, use them as guidance rather than assuming they are a complete implementation
specification. Prefer this flow:

1. Inspect the current implementation and design guidance.
2. Create an isolated preview or focused proposal when the visual change is substantial.
3. Confirm the direction before integrating it into the application.
4. Reuse the project's theme, token, component, or styling system instead of scattering hard-coded
   visual values.

Do not change business flow or delete functionality solely for visual polish.

## Git

- Check `git status` before editing and again before handoff.
- Review the final diff for accidental or unrelated changes.
- Do not use destructive commands such as `git reset --hard` or discard user changes unless the user
  explicitly requests it.
- Prefer non-interactive Git commands.
- Commit or push only when requested or when the project instructions explicitly require it.

## Project-Specific Additions

Add project-specific architecture, test commands, packaging rules, release checks, and current
priorities below this section. Keep those rules separate from the reusable guidance above so this
file remains easy to adapt for another repository.
