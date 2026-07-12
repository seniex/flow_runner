# Flow Runner PySide6 Refactor Implementation Plan

> 当前实施与验证状态见 `REFACTOR_STATUS.md`。本文件中的逐步复选框保留为原始 TDD 实施清单；最终真实环境验收仍以 `REAL_ENVIRONMENT_CHECKLIST.md` 的逐项证据为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standardized PySide6 game-automation workflow editor and runtime using composable conditions, actions, policies, and conditional routing, while keeping the existing three scripts unchanged as migration references.

**Architecture:** Implement a Qt-independent domain and runtime core first, then adapt screenshot/OCR/input capabilities behind registries, and finally connect them to a three-pane PySide6 editor through ViewModels. Stable UUID references, typed result contexts, shared perception snapshots, and resource coordination replace index-based routing and duplicated OCR/image step families.

**Tech Stack:** Python 3.11+, PySide6, Pydantic v2, pytest, pytest-qt, Pillow, OpenCV, pywin32, pynput, pyautogui, PaddleOCR-json/Tesseract adapters, JSON configuration, QSS.

---

## 1. Execution Rules

- Read `FLOW_RUNNER_QT_REFACTOR_DESIGN.md` before starting each phase.
- Preserve `flow_runner_p1.py`, `flow_runner_p2.py`, `flow_runner_p3.py`, `config/`, and `scripts/` until the new runtime passes real-environment acceptance.
- Start every behavior change with a focused failing test.
- Run the focused test after implementation, then the phase test set.
- The current directory is not a Git repository. Do not run commit commands unless the user separately initializes or authorizes Git. Use the verification checkpoints in this plan as change boundaries.
- Do not implement the old-to-new configuration converter in this plan. It is a separate task after the new schema and runtime are stable.
- Do not implement final visual styling in this plan. Create the QSS contract and neutral base stylesheet; apply the future `DESIGN.md` in a separate design pass.

## 2. Target File Map

```text
pyproject.toml                         Project metadata, dependencies, tools
README.md                              Setup, architecture, run/test commands
flow_runner/__init__.py                Package version
flow_runner/app.py                     PySide6 entry point
flow_runner/domain/enums.py            Stable runtime enums
flow_runner/domain/results.py          Condition/action/step result models
flow_runner/domain/conditions.py       Leaf/group condition configuration
flow_runner/domain/actions.py          Action configuration and bindings
flow_runner/domain/policies.py         Condition/action retry policies
flow_runner/domain/routing.py          Route rules and UUID targets
flow_runner/domain/project.py          Project/group/workflow/step models
flow_runner/domain/references.py       Typed workflow/step UUID references
flow_runner/domain/errors.py           Domain exception hierarchy
flow_runner/engine/context.py          Variables, result scope, call stack
flow_runner/engine/bindings.py         $result/$variables expression resolver
flow_runner/engine/cancellation.py     Cooperative cancellation token
flow_runner/engine/step_executor.py    Deterministic step state machine
flow_runner/engine/workflow_executor.py Workflow routing and calls
flow_runner/engine/runner.py           Task lifecycle and public API
flow_runner/engine/perception.py       Frame broker and detector cache
flow_runner/engine/resources.py        Read sharing and exclusive actions
flow_runner/capabilities/base.py        Condition/action protocols
flow_runner/capabilities/registry.py    Capability registration and lookup
flow_runner/capabilities/conditions/    OCR/image/time/count/variable providers
flow_runner/capabilities/actions/       Input/process/wait/script/variable providers
flow_runner/infrastructure/capture/     Desktop/window capture adapters
flow_runner/infrastructure/ocr/         Paddle/Tesseract adapters
flow_runner/infrastructure/input/       Mouse/keyboard adapters
flow_runner/infrastructure/persistence/ JSON validation and atomic save
flow_runner/infrastructure/logging/     Structured runtime event models/sink
flow_runner/ui/main_window.py           Three-pane window assembly
flow_runner/ui/view_models/             Project/selection/run-state binding
flow_runner/ui/panels/                  Tree, step list, property panel
flow_runner/ui/editors/                 Condition/action/policy/route editors
flow_runner/ui/dialogs/                 Guided add/settings/diagnostics
flow_runner/ui/theme_manager.py         QSS loading and refresh
flow_runner/resources/styles/base.qss   Neutral semantic stylesheet
tests/unit/                             Pure domain/runtime tests
tests/integration/                      Adapter/cache/concurrency tests
tests/ui/                               pytest-qt UI tests
```

## Phase 1: Project Foundation and Typed Domain

### Task 1: Create the installable package and test toolchain

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `flow_runner/__init__.py`
- Create: `tests/unit/test_package.py`

- [ ] **Step 1: Write the package smoke test**

```python
# tests/unit/test_package.py
def test_package_exposes_version():
    import flow_runner

    assert flow_runner.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the test and verify the package is absent**

Run: `python -m pytest tests/unit/test_package.py -q`

Expected: FAIL because `flow_runner` does not exist.

- [ ] **Step 3: Add package metadata and tool configuration**

Create `pyproject.toml` with these sections and values:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "flow-runner-qt"
version = "0.1.0"
description = "Composable desktop automation workflow editor and runtime"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "PySide6>=6.8,<7",
  "pydantic>=2.10,<3",
  "Pillow>=11,<13",
  "opencv-python>=4.10,<5",
  "numpy>=2,<3",
  "pyautogui>=0.9.54,<1",
  "pynput>=1.7.7,<2",
  "pywin32>=308; platform_system == 'Windows'",
]

[project.optional-dependencies]
test = [
  "pytest>=8,<10",
  "pytest-asyncio>=0.25,<2",
  "pytest-cov>=6,<8",
  "pytest-qt>=4.4,<5",
  "ruff>=0.11,<1",
  "mypy>=1.15,<2",
]

[project.scripts]
flow-runner = "flow_runner.app:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["flow_runner"]
```

Create `flow_runner/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `README.md` with these concrete sections: project purpose, Python 3.11 requirement, `python -m pip install -e ".[test]"`, `python -m pytest`, `python -m flow_runner.app`, package-layer overview, and a warning that the legacy scripts remain reference-only.

- [ ] **Step 4: Install the editable test environment**

Run: `python -m pip install -e ".[test]"`

Expected: installation completes and reports `flow-runner-qt` installed.

- [ ] **Step 5: Run the smoke test**

Run: `python -m pytest tests/unit/test_package.py -q`

Expected: `1 passed`.

- [ ] **Step 6: Run the foundation quality checks**

Run: `python -m ruff check flow_runner tests`

Expected: no lint errors.

### Task 2: Define runtime enums, exceptions, and result models

**Files:**
- Create: `flow_runner/domain/enums.py`
- Create: `flow_runner/domain/errors.py`
- Create: `flow_runner/domain/results.py`
- Create: `tests/unit/domain/test_results.py`

- [ ] **Step 1: Write result-semantic tests**

```python
# tests/unit/domain/test_results.py
from flow_runner.domain.enums import ConditionOutcome, StepOutcome
from flow_runner.domain.results import ConditionResult


def test_leaf_match_becomes_primary():
    leaf = ConditionResult(
        node_id="ocr_a",
        outcome=ConditionOutcome.MATCH,
        text="开始",
        position=(120, 80),
    )
    assert leaf.primary is leaf


def test_and_group_never_exposes_primary():
    group = ConditionResult.and_group(
        "all",
        [
            ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH),
            ConditionResult(node_id="image_b", outcome=ConditionOutcome.MATCH),
        ],
    )
    assert group.primary is None


def test_or_group_exposes_primary_only_for_one_match():
    one = ConditionResult.or_group(
        "either",
        [
            ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH),
            ConditionResult(node_id="image_b", outcome=ConditionOutcome.NO_MATCH),
        ],
    )
    many = ConditionResult.or_group(
        "either",
        [
            ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH),
            ConditionResult(node_id="image_b", outcome=ConditionOutcome.MATCH),
        ],
    )
    assert one.primary is one.children["ocr_a"]
    assert many.primary is None
    assert StepOutcome.TIMEOUT.value == "timeout"
```

- [ ] **Step 2: Run the result tests and verify failure**

Run: `python -m pytest tests/unit/domain/test_results.py -q`

Expected: FAIL because the domain modules do not exist.

- [ ] **Step 3: Implement the exact enum and exception contracts**

Define string enums in `enums.py`:

```python
from enum import StrEnum


class ConditionOutcome(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    ERROR = "error"


class StepOutcome(StrEnum):
    SUCCESS = "success"
    NOT_MATCHED = "not_matched"
    TIMEOUT = "timeout"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class ConditionMode(StrEnum):
    ONCE = "once"
    UNTIL = "until"
```

Define `FlowRunnerError` and the concrete subclasses `ConditionError`, `ActionError`, `BindingError`, `RoutingError`, `ResourceConflict`, `ConfigurationError`, and `Cancelled` in `errors.py`.

- [ ] **Step 4: Implement immutable result models**

Use frozen Pydantic models in `results.py`. `ConditionResult` must contain `node_id`, `outcome`, optional `text`, optional `position`, optional `bounds`, optional `confidence`, `provider_data`, and aliased `children`. Implement `and_group()`, `or_group()`, and `not_group()` constructors and a computed `primary` property with the exact rules from the design. Add `ActionResult` and `StepResult` models keyed by `StepOutcome`.

- [ ] **Step 5: Run result tests**

Run: `python -m pytest tests/unit/domain/test_results.py -q`

Expected: `3 passed`.

### Task 3: Define typed conditions, actions, policies, routes, and project models

**Files:**
- Create: `flow_runner/domain/conditions.py`
- Create: `flow_runner/domain/actions.py`
- Create: `flow_runner/domain/policies.py`
- Create: `flow_runner/domain/routing.py`
- Create: `flow_runner/domain/references.py`
- Create: `flow_runner/domain/project.py`
- Create: `tests/unit/domain/test_project_model.py`

- [ ] **Step 1: Write model validation tests**

```python
# tests/unit/domain/test_project_model.py
from uuid import uuid4

import pytest
from pydantic import ValidationError

from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.project import AutomationStep, Project, Workflow, FlowGroup
from flow_runner.domain.routing import RouteRule, RouteTarget


def test_project_uses_stable_ids_and_cross_group_routes():
    target_workflow_id = uuid4()
    step = AutomationStep(
        name="进入 B",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(target_workflow_id),
            )
        ],
    )
    project = Project(
        name="挂机",
        groups=[FlowGroup(name="A", workflows=[Workflow(name="A1", steps=[step])])],
    )
    assert project.groups[0].workflows[0].steps[0].id == step.id
    assert step.routes[0].target.workflow_id == target_workflow_id


def test_once_policy_rejects_multiple_attempts():
    with pytest.raises(ValidationError):
        AutomationStep.model_validate(
            {
                "name": "invalid",
                "condition_policy": {"mode": ConditionMode.ONCE, "max_attempts": 3},
            }
        )
```

- [ ] **Step 2: Run model tests and verify failure**

Run: `python -m pytest tests/unit/domain/test_project_model.py -q`

Expected: FAIL because project models do not exist.

- [ ] **Step 3: Implement discriminated configuration models**

Implement:

```python
# Required public shapes
class LeafCondition(BaseModel):
    id: str
    capability: str
    config: dict[str, object]


class ConditionGroup(BaseModel):
    id: str
    operator: Literal["and", "or", "not"]
    children: list[ConditionNode]


class ActionSpec(BaseModel):
    capability: str
    config: dict[str, object]


class ConditionPolicy(BaseModel):
    mode: ConditionMode = ConditionMode.ONCE
    interval_seconds: float = 1.0
    max_attempts: int = 1
    timeout_seconds: float | None = None
    before_attempt_actions: list[ActionSpec] = []
    after_no_match_actions: list[ActionSpec] = []


class ActionPolicy(BaseModel):
    max_attempts: int = 1
    retry_interval_seconds: float = 0.0
```

The policy validator must require `max_attempts == 1` for `ONCE`, positive intervals, and either a finite `max_attempts` or finite timeout for `UNTIL`.

- [ ] **Step 4: Implement stable route and project references**

Define typed `WorkflowRef` and `StepRef` models in `references.py`. `RouteTarget` must support `next_step`, `jump_workflow`, `call_workflow`, `return`, and `end`. `AutomationStep`, `Workflow`, and `FlowGroup` receive UUIDs from `default_factory=uuid4`. `Project` contains `schema_version=1`, name, groups, and global settings. Add `Project.validate_references()` to return concrete broken-reference messages rather than mutating data.

- [ ] **Step 5: Run model tests**

Run: `python -m pytest tests/unit/domain/test_project_model.py -q`

Expected: `2 passed`.

- [ ] **Step 6: Run the Phase 1 suite**

Run: `python -m pytest tests/unit/domain tests/unit/test_package.py -q`

Expected: all tests pass.

## Phase 2: Capability Registry, Bindings, and Step State Machine

### Task 4: Build capability protocols and registry

**Files:**
- Create: `flow_runner/capabilities/base.py`
- Create: `flow_runner/capabilities/registry.py`
- Create: `tests/unit/capabilities/test_registry.py`

- [ ] **Step 1: Write registry contract tests**

```python
# tests/unit/capabilities/test_registry.py
import pytest

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.errors import ConfigurationError


class FakeCondition:
    name = "fake.condition"


def test_registry_rejects_duplicate_names():
    registry = CapabilityRegistry()
    registry.register_condition(FakeCondition())
    with pytest.raises(ConfigurationError, match="fake.condition"):
        registry.register_condition(FakeCondition())
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m pytest tests/unit/capabilities/test_registry.py -q`

Expected: FAIL because the registry does not exist.

- [ ] **Step 3: Implement async capability protocols**

Define `ConditionCapability.evaluate(config, evaluation_context) -> ConditionResult` and `ActionCapability.execute(config, action_context) -> ActionResult` as async protocols. Each capability exposes `name`, `config_model`, and `required_resources(config)`.

- [ ] **Step 4: Implement explicit registry lookup**

`CapabilityRegistry` stores condition and action providers separately, rejects duplicates, raises `ConfigurationError` for unknown names, and exposes sorted metadata for the Qt editors. Do not add filesystem plugin discovery.

- [ ] **Step 5: Run registry tests**

Run: `python -m pytest tests/unit/capabilities/test_registry.py -q`

Expected: PASS.

### Task 5: Implement scoped runtime context and expression bindings

**Files:**
- Create: `flow_runner/engine/context.py`
- Create: `flow_runner/engine/bindings.py`
- Create: `tests/unit/engine/test_bindings.py`

- [ ] **Step 1: Write binding behavior tests**

```python
# tests/unit/engine/test_bindings.py
import pytest

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.errors import BindingError
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.bindings import resolve_binding
from flow_runner.engine.context import StepContext


def test_binding_reads_named_child_and_variable():
    result = ConditionResult.and_group(
        "all",
        [ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH, text="42")],
    )
    context = StepContext(result=result, task_variables={"limit": 10})
    assert resolve_binding('$result.children["ocr_a"].text', context) == "42"
    assert resolve_binding("$variables.task.limit", context) == 10


def test_missing_primary_is_a_binding_error():
    result = ConditionResult.and_group(
        "all",
        [ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH)],
    )
    with pytest.raises(BindingError, match="primary"):
        resolve_binding("$result.primary.position", StepContext(result=result))
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest tests/unit/engine/test_bindings.py -q`

Expected: FAIL because bindings are not implemented.

- [ ] **Step 3: Implement explicit runtime scopes**

`TaskContext` owns task variables, persistent-variable access, call stack, cancellation token, and event sink. `WorkflowContext` owns workflow-local variables and execution counters. `StepContext` owns only the current `ConditionResult` and references to parent scopes. Clear `StepContext.result` when the step completes.

- [ ] **Step 4: Implement a restricted binding parser**

Support only `$result.primary.<field>`, `$result.children["alias"].<field>`, `$variables.task.<name>`, `$variables.workflow.<name>`, and `$variables.persistent.<name>`. Do not use Python `eval`. Parse tokens explicitly, return scalar/tuple values, and raise `BindingError` with the failing segment.

- [ ] **Step 5: Run binding tests**

Run: `python -m pytest tests/unit/engine/test_bindings.py -q`

Expected: `2 passed`.

### Task 6: Implement cancellation and the deterministic step executor

**Files:**
- Create: `flow_runner/engine/cancellation.py`
- Create: `flow_runner/engine/step_executor.py`
- Create: `tests/unit/engine/test_step_executor.py`

- [ ] **Step 1: Write ONCE and UNTIL state-machine tests using fakes**

```python
# tests/unit/engine/test_step_executor.py
import pytest

from flow_runner.domain.enums import ConditionMode, ConditionOutcome, StepOutcome
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.step_executor import StepExecutor


@pytest.mark.asyncio
async def test_once_no_match_returns_not_matched_without_retry(fake_runtime):
    fake_runtime.conditions.queue(
        ConditionResult(node_id="ocr", outcome=ConditionOutcome.NO_MATCH)
    )
    step = AutomationStep(
        name="once",
        condition={"id": "ocr", "capability": "fake", "config": {}},
    )
    result = await StepExecutor(fake_runtime).execute(step)
    assert result.outcome is StepOutcome.NOT_MATCHED
    assert fake_runtime.conditions.call_count == 1


@pytest.mark.asyncio
async def test_until_runs_hooks_and_times_out(fake_runtime):
    fake_runtime.conditions.repeat_no_match(count=3)
    step = AutomationStep.model_validate(
        {
            "name": "wait",
            "condition": {"id": "ocr", "capability": "fake", "config": {}},
            "condition_policy": {
                "mode": ConditionMode.UNTIL,
                "max_attempts": 3,
                "interval_seconds": 0,
                "after_no_match_actions": [
                    {"capability": "fake.recover", "config": {}}
                ],
            },
        }
    )
    result = await StepExecutor(fake_runtime).execute(step)
    assert result.outcome is StepOutcome.TIMEOUT
    assert fake_runtime.actions.calls("fake.recover") == 3
```

- [ ] **Step 2: Add shared fake-runtime fixtures**

Create `tests/conftest.py` with deterministic fake condition/action registries, a fake monotonic clock, and an immediately completing async sleep. Expose `fake_runtime` with call counters and queued results.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/unit/engine/test_step_executor.py -q`

Expected: FAIL because `StepExecutor` is absent.

- [ ] **Step 4: Implement cooperative cancellation**

`CancellationToken.cancel()` sets an `asyncio.Event`; `raise_if_cancelled()` raises `Cancelled`; `sleep(seconds)` waits for either cancellation or timeout without blocking the event loop.

- [ ] **Step 5: Implement the state machine in the confirmed order**

`StepExecutor.execute()` must run before-attempt actions, create/evaluate a fresh condition tick, run main actions only on MATCH, run after-no-match actions on NO_MATCH, apply condition and action retry policies independently, and convert terminal states to `StepResult`. It must never select routes; routing belongs to `WorkflowExecutor`.

- [ ] **Step 6: Run step tests**

Run: `python -m pytest tests/unit/engine/test_step_executor.py -q`

Expected: all tests pass.

- [ ] **Step 7: Run the Phase 2 suite**

Run: `python -m pytest tests/unit/capabilities tests/unit/engine -q`

Expected: all tests pass.

## Phase 3: Routing, Workflow Calls, and Task Lifecycle

### Task 7: Implement workflow routing with cross-group jumps and calls

**Files:**
- Create: `flow_runner/engine/workflow_executor.py`
- Create: `tests/unit/engine/test_workflow_executor.py`

- [ ] **Step 1: Write the A→B→C scenario test**

Build a project fixture with stable IDs for A1, A2, A3, B1, B2, B3, and C1. Configure A3 so `a1_runs < n` jumps to A1 and otherwise jumps to B1; configure B3 to jump to C1.

```python
@pytest.mark.asyncio
async def test_dynamic_cross_group_route_reaches_c1(project_abc, fake_step_executor):
    fake_step_executor.set_task_variable("n", 3)
    executor = WorkflowExecutor(project_abc.project, fake_step_executor)
    trace = await executor.run(entry_workflow_id=project_abc.ids["A1"])
    assert trace.workflow_names == [
        "A1", "A2", "A3",
        "A1", "A2", "A3",
        "A1", "A2", "A3",
        "B1", "B2", "B3", "C1",
    ]
```

- [ ] **Step 2: Write call/return and runaway-route tests**

Verify that `call_workflow` pushes a return address, `return` resumes the caller, an empty stack raises `RoutingError`, and more than 10,000 transitions without a cancellable wait raises `RoutingError("transition limit")`.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/unit/engine/test_workflow_executor.py -q`

Expected: FAIL because workflow routing is absent.

- [ ] **Step 4: Implement indexed project lookup and route selection**

Build immutable maps from UUID to workflow and step at task start. Evaluate route rules in stored order against `StepResult` and current variables. Require exactly one default route per reachable terminal result or use the explicit end target.

- [ ] **Step 5: Implement jump, call, return, and end semantics**

Flow groups must not appear in execution lookup rules. Calls push `(workflow_id, next_step_id)`; jumps do not push. Returning with no frame is a routing error. Increment workflow and step counters in `WorkflowContext` before executing them.

- [ ] **Step 6: Run workflow tests**

Run: `python -m pytest tests/unit/engine/test_workflow_executor.py -q`

Expected: all tests pass.

### Task 8: Add public runner lifecycle, pause, stop, and structured events

**Files:**
- Create: `flow_runner/engine/runner.py`
- Create: `flow_runner/infrastructure/logging/events.py`
- Create: `flow_runner/infrastructure/logging/sinks.py`
- Create: `tests/unit/engine/test_runner.py`

- [ ] **Step 1: Write lifecycle tests**

Test `IDLE → RUNNING → PAUSED → RUNNING → COMPLETED`, stop during a cancellable wait, and prevention of a second start while running. Assert emitted events contain task ID, workflow ID, step ID, outcome, monotonic timestamp, and optional frame ID.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/unit/engine/test_runner.py -q`

Expected: FAIL because `Runner` does not exist.

- [ ] **Step 3: Implement task lifecycle without Qt dependencies**

Expose async `start(project, entry_workflow_id)`, `pause()`, `resume()`, and `stop()`. Use an async pause gate and cancellation token. Accept an `EventSink` protocol so the UI and file logger can subscribe without importing PySide6.

- [ ] **Step 4: Implement JSON-lines and memory sinks**

The file sink writes one UTF-8 JSON object per event and flushes after ERROR/terminal events. The memory sink stores immutable events for tests and diagnostics.

- [ ] **Step 5: Run lifecycle tests and Phase 3 suite**

Run: `python -m pytest tests/unit/engine -q`

Expected: all tests pass.

## Phase 4: Shared Perception and Resource Coordination

### Task 9: Implement global frame sharing and detector caches

**Files:**
- Create: `flow_runner/engine/perception.py`
- Create: `flow_runner/infrastructure/capture/base.py`
- Create: `tests/unit/engine/test_perception.py`

- [ ] **Step 1: Write cache and invalidation tests**

```python
@pytest.mark.asyncio
async def test_concurrent_reads_share_one_frame(fake_capture):
    service = PerceptionService(fake_capture, coalesce_window_ms=10)
    first, second = await asyncio.gather(
        service.snapshot("window:game"),
        service.snapshot("window:game"),
    )
    assert first.frame_id == second.frame_id
    assert fake_capture.calls == 1


@pytest.mark.asyncio
async def test_scene_change_invalidates_frame_and_ocr_cache(fake_capture, fake_ocr):
    service = PerceptionService(fake_capture)
    old = await service.snapshot("desktop")
    await service.ocr(old, region=(0, 0, 100, 100), provider=fake_ocr)
    service.mark_scene_changed("desktop")
    new = await service.snapshot("desktop")
    await service.ocr(new, region=(0, 0, 100, 100), provider=fake_ocr)
    assert new.frame_id != old.frame_id
    assert fake_ocr.calls == 2
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/unit/engine/test_perception.py -q`

Expected: FAIL because perception service is absent.

- [ ] **Step 3: Implement immutable snapshots**

`PerceptionSnapshot` contains target ID, frame ID, scene generation, monotonic capture time, image, and dimensions. Cropping returns views/copies from the same image and never captures again.

- [ ] **Step 4: Implement request coalescing and keyed caches**

Coalesce simultaneous capture requests per target within the configured window. Key OCR cache by `(frame_id, region, provider, language, preprocessing)` and image cache by `(frame_id, region, template_digest, threshold)`. Bound both caches with LRU limits.

- [ ] **Step 5: Run perception tests**

Run: `python -m pytest tests/unit/engine/test_perception.py -q`

Expected: all tests pass.

### Task 10: Implement resource leases and stale-coordinate revalidation

**Files:**
- Create: `flow_runner/engine/resources.py`
- Create: `tests/unit/engine/test_resources.py`

- [ ] **Step 1: Write concurrency tests**

Test that two observation leases for the same target overlap, two interaction leases serialize, mouse and keyboard are global exclusive resources, and a result tied to an old scene generation invokes the supplied revalidation callback before action execution.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/unit/engine/test_resources.py -q`

Expected: FAIL because resource coordination is absent.

- [ ] **Step 3: Implement ordered leases**

Acquire resource names in sorted order to prevent deadlocks. Use shared observation counters and exclusive async locks per target. A desktop interaction lease conflicts with every window interaction lease. Always release leases in `async with` cleanup.

- [ ] **Step 4: Implement observe-decide-act validation**

`execute_with_fresh_result(target, result, action, revalidate)` acquires the interaction resources, compares the result frame generation with `PerceptionService.current_generation(target)`, revalidates if stale, runs the action, then marks the scene changed.

- [ ] **Step 5: Run resource and Phase 4 tests**

Run: `python -m pytest tests/unit/engine/test_perception.py tests/unit/engine/test_resources.py -q`

Expected: all tests pass.

## Phase 5: Real Capabilities and Persistence

### Task 11: Port screenshot, OCR, and image conditions behind adapters

**Files:**
- Create: `flow_runner/infrastructure/capture/desktop.py`
- Create: `flow_runner/infrastructure/ocr/base.py`
- Create: `flow_runner/infrastructure/ocr/paddle_json.py`
- Create: `flow_runner/infrastructure/ocr/tesseract.py`
- Create: `flow_runner/capabilities/conditions/ocr.py`
- Create: `flow_runner/capabilities/conditions/image.py`
- Create: `tests/integration/test_visual_conditions.py`

- [ ] **Step 1: Create deterministic visual fixtures**

Add small generated PNG fixtures under `tests/fixtures/visual/`: one frame containing a known template rectangle and one template image. Store a fixed fake OCR response containing text, bounds, confidence, and engine metadata.

- [ ] **Step 2: Write adapter contract tests**

Verify region coordinates use `(left, top, right, bottom)`, template match returns center/bounds/confidence, OCR keyword grammar preserves existing `|` OR and `,` AND semantics, and adapter errors become `ConditionError`.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/integration/test_visual_conditions.py -q`

Expected: FAIL because adapters are absent.

- [ ] **Step 4: Extract focused implementations from the legacy reference**

Port BitBlt/ImageGrab capture, PaddleOCR-json process communication, Tesseract invocation, keyword matching, and OpenCV template matching without importing `flow_runner_p1.py`. Constructors receive dependencies explicitly; module import must not create log directories or start processes.

- [ ] **Step 5: Register OCR and image condition providers**

Both providers request frames through `PerceptionService` and return `ConditionResult`. They must not implement polling, clicking, or routing.

- [ ] **Step 6: Run adapter tests**

Run: `python -m pytest tests/integration/test_visual_conditions.py -q`

Expected: all deterministic tests pass.

### Task 12: Port input, wait, process, script, and variable actions

**Files:**
- Create: `flow_runner/infrastructure/input/mouse.py`
- Create: `flow_runner/infrastructure/input/keyboard.py`
- Create: `flow_runner/capabilities/actions/mouse.py`
- Create: `flow_runner/capabilities/actions/keyboard.py`
- Create: `flow_runner/capabilities/actions/wait.py`
- Create: `flow_runner/capabilities/actions/process.py`
- Create: `flow_runner/capabilities/actions/script.py`
- Create: `flow_runner/capabilities/actions/variables.py`
- Create: `flow_runner/infrastructure/input/recording.py`
- Create: `tests/integration/test_actions.py`

- [ ] **Step 1: Write fake-device action tests**

Verify `$result.primary.position` binding, absolute/offset coordinates, click sequences, keyboard press/release/hotkey actions, cancellable waits, normalized process paths, script speed/max-gap behavior, and explicit task/workflow/persistent variable assignment.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/integration/test_actions.py -q`

Expected: FAIL because action providers are absent.

- [ ] **Step 3: Port input and recording logic behind interfaces**

Move the behavior of `RecorderEngine` and `PlaybackEngine` into focused infrastructure modules. Device adapters expose methods but do not own retry or route logic. Every delay uses the cancellation token.

- [ ] **Step 4: Implement registered action providers**

Providers validate config through Pydantic models, resolve bindings through `engine.bindings`, declare required resources, and return `ActionResult`. Mouse/keyboard providers run through `ResourceCoordinator`.

- [ ] **Step 5: Run action tests**

Run: `python -m pytest tests/integration/test_actions.py -q`

Expected: all tests pass.

### Task 13: Add time, count, and variable conditions

**Files:**
- Create: `flow_runner/capabilities/conditions/time.py`
- Create: `flow_runner/capabilities/conditions/count.py`
- Create: `flow_runner/capabilities/conditions/variables.py`
- Create: `tests/unit/capabilities/test_scalar_conditions.py`

- [ ] **Step 1: Write scalar-condition tests**

Test elapsed duration, local time range including midnight rollover, workflow execution count, step count, numeric/text/boolean comparisons, missing-variable errors, and AND/OR composition with visual results.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/unit/capabilities/test_scalar_conditions.py -q`

Expected: FAIL because scalar conditions are absent.

- [ ] **Step 3: Implement deterministic providers**

Inject clock and context access. Support comparison operators `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `contains`, and `matches`. Compile regular expressions during config validation and report invalid patterns as `ConfigurationError`.

- [ ] **Step 4: Run scalar-condition tests**

Run: `python -m pytest tests/unit/capabilities/test_scalar_conditions.py -q`

Expected: all tests pass.

### Task 14: Implement versioned JSON loading, validation, backup, and atomic save

**Files:**
- Create: `flow_runner/infrastructure/persistence/project_store.py`
- Create: `tests/integration/test_project_store.py`

- [ ] **Step 1: Write persistence failure tests**

Use `tmp_path` to verify valid round-trip, invalid JSON rejection, broken UUID reference rejection, temporary-file cleanup, atomic replacement, and retention of the five newest backups.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/integration/test_project_store.py -q`

Expected: FAIL because `ProjectStore` is absent.

- [ ] **Step 3: Implement load and validation**

Decode UTF-8 JSON, validate with `Project.model_validate_json()`, run `validate_references()`, and raise `ConfigurationError` containing the JSON path and all broken references.

- [ ] **Step 4: Implement safe save**

Serialize to a sibling temporary file, flush and `os.fsync`, read it back through the same validator, rotate timestamped backups, then use `os.replace`. Never mutate the caller's project during save.

- [ ] **Step 5: Run persistence tests and Phase 5 suite**

Run: `python -m pytest tests/unit/capabilities tests/integration -q`

Expected: all tests pass; tests requiring a real desktop remain marked `manual` and are not part of this command.

## Phase 6: PySide6 Editor Skeleton and QSS Contract

### Task 15: Build ViewModels and three-pane selection synchronization

**Files:**
- Create: `flow_runner/ui/view_models/project_view_model.py`
- Create: `flow_runner/ui/view_models/run_view_model.py`
- Create: `flow_runner/ui/panels/flow_tree_panel.py`
- Create: `flow_runner/ui/panels/step_list_panel.py`
- Create: `flow_runner/ui/panels/property_panel.py`
- Create: `flow_runner/ui/main_window.py`
- Create: `tests/ui/test_main_window.py`

- [ ] **Step 1: Write the Qt selection test**

```python
def test_selecting_step_updates_property_panel(qtbot, sample_project):
    window = MainWindow(project=sample_project, registry=fake_registry())
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(sample_project.first_workflow.id)
    window.step_list.select_step(sample_project.first_step.id)
    assert window.property_panel.step_id == sample_project.first_step.id
```

Also test that renaming/moving a flow does not change UUID routes and that closing a dirty project prompts through an injected dialog service.

- [ ] **Step 2: Run UI tests offscreen and verify failure**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_main_window.py -q`

Expected: FAIL because the UI modules are absent.

- [ ] **Step 3: Implement Qt-independent edit commands in the ViewModel**

Expose add/remove/move/rename commands and selection signals. Commands replace validated Pydantic models rather than mutating nested JSON dictionaries. Maintain an undo stack boundary per user command.

- [ ] **Step 4: Assemble the three panes**

Use `QMainWindow` and nested `QSplitter` widgets: flow tree left, step list center, property panel right. Set semantic `objectName` values only; do not set colors, fonts, borders, or per-widget styles in Python.

- [ ] **Step 5: Run UI selection tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_main_window.py -q`

Expected: all tests pass.

### Task 16: Implement capability-driven property editors and guided add

**Files:**
- Create: `flow_runner/ui/editors/condition_editor.py`
- Create: `flow_runner/ui/editors/action_editor.py`
- Create: `flow_runner/ui/editors/policy_editor.py`
- Create: `flow_runner/ui/editors/route_editor.py`
- Create: `flow_runner/ui/dialogs/guided_add_dialog.py`
- Create: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Write editor behavior tests**

Test the three add choices `检测`, `执行`, `控制`; changing condition capability from OCR to image; preservation of common region/policy/routes; ONCE/UNTIL controls; named condition-child references; missing-primary validation; and route target selection across groups.

- [ ] **Step 2: Run tests and verify failure**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_step_editors.py -q`

Expected: FAIL because editors are absent.

- [ ] **Step 3: Implement registry-driven editor factories**

Read capability metadata and Pydantic field schemas from `CapabilityRegistry`. Map supported scalar, enum, path, region, coordinate, and binding fields to focused editor widgets. Capability-specific editors may override the generic form through an explicit registered editor factory.

- [ ] **Step 4: Implement safe capability switching**

When switching OCR to image, retain only shared semantic fields declared by both capabilities, then validate the new condition. Keep condition policy and routes unchanged. Show a confirmation listing discarded provider-specific fields.

- [ ] **Step 5: Implement the guided add dialog**

Page 1 selects detection/execution/control; page 2 selects a capability; page 3 configures minimal required fields and outcome behavior. The dialog returns one validated `AutomationStep` and never edits the project until accepted.

- [ ] **Step 6: Run editor tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_step_editors.py -q`

Expected: all tests pass.

### Task 17: Add QSS theme management and neutral semantic styling

**Files:**
- Create: `flow_runner/ui/theme_manager.py`
- Create: `flow_runner/resources/styles/base.qss`
- Create: `tests/ui/test_theme_manager.py`

- [ ] **Step 1: Write theme tests**

Verify one application-wide QSS load, file-not-found diagnostics, refresh after file change, and selectors for `[role="primary"]`, `[status="running"]`, `#flowTreePanel`, `#stepListPanel`, and `#propertyPanel`.

- [ ] **Step 2: Run tests and verify failure**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_theme_manager.py -q`

Expected: FAIL because theme management is absent.

- [ ] **Step 3: Implement application-wide QSS loading**

`ThemeManager.apply(app, path)` reads UTF-8 QSS and calls `app.setStyleSheet()` once. It must not rewrite widget styles. `refresh_widget(widget)` performs unpolish/polish after dynamic-property changes.

- [ ] **Step 4: Add the neutral stylesheet contract**

Define all required semantic selectors with neutral readable values. Keep every color, font size, spacing, border, hover, selected, disabled, and status treatment in `base.qss`; Python files must contain no hex/RGB color constants.

- [ ] **Step 5: Run theme tests and scan for hard-coded styles**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_theme_manager.py -q`

Run: `rg -n "setStyleSheet|#[0-9A-Fa-f]{6}|rgb\(" flow_runner/ui -g "*.py"`

Expected: tests pass; the scan returns no matches except the single application-level call in `theme_manager.py`.

## Phase 7: Application Integration and Diagnostics

### Task 18: Connect Runner to Qt without cross-thread widget access

**Files:**
- Create: `flow_runner/ui/runner_bridge.py`
- Create: `flow_runner/ui/dialogs/diagnostics_dialog.py`
- Create: `tests/ui/test_runner_bridge.py`

- [ ] **Step 1: Write signal-delivery tests**

Verify runtime events emitted from a worker thread arrive on the Qt main thread, start/pause/resume/stop button states follow runner state, and closing during execution requests cancellation before window destruction.

- [ ] **Step 2: Run tests and verify failure**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_runner_bridge.py -q`

Expected: FAIL because the bridge is absent.

- [ ] **Step 3: Implement an event bridge**

Use a `QObject` with typed Signals carrying immutable event DTOs. Run the asyncio runtime in a dedicated worker thread with its own event loop. UI slots update widgets only on the Qt thread.

- [ ] **Step 4: Add diagnostics views**

Display current task/workflow/step, result outcome, condition tree, frame ID, scene generation, retry counts, selected route, resource waits, and structured error ID. Provide screenshot preview only when the event includes a diagnostic capture.

- [ ] **Step 5: Run bridge tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_runner_bridge.py -q`

Expected: all tests pass.

### Task 19: Add settings, hotkeys, recording controls, and entry point

**Files:**
- Create: `flow_runner/ui/dialogs/settings_dialog.py`
- Create: `flow_runner/ui/hotkeys.py`
- Create: `flow_runner/app.py`
- Modify: `README.md`
- Create: `tests/ui/test_app_smoke.py`

- [ ] **Step 1: Write application smoke tests**

Test offscreen startup, config-path injection, settings validation, disabled empty hotkeys, duplicate hotkey rejection, and clean OCR/runner/hotkey shutdown.

- [ ] **Step 2: Run tests and verify failure**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_app_smoke.py -q`

Expected: FAIL because `app.py` is absent.

- [ ] **Step 3: Implement dependency composition in one place**

`app.py` creates adapters, perception service, resource coordinator, registry, project store, runner bridge, theme manager, and main window. No other module constructs global service singletons.

- [ ] **Step 4: Implement hotkey and shutdown services**

Hotkey callbacks emit Qt signals and never call widgets from the pynput thread. Shutdown cancels the runner, stops listeners, terminates owned OCR processes, waits with bounded timeouts, and reports forced cleanup.

- [ ] **Step 5: Document exact run and test commands**

Update README with editable installation, `flow-runner`, offscreen tests, real-environment prerequisites, Paddle/Tesseract paths, QSS location, and the statement that final styling follows a future `DESIGN.md`.

- [ ] **Step 6: Run app smoke tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_app_smoke.py -q`

Expected: all tests pass.

## Phase 8: Second-Stage Game Automation Capabilities

### Task 20: Add pixel, region-change, window, and process conditions

**Files:**
- Create: `flow_runner/capabilities/conditions/pixel.py`
- Create: `flow_runner/capabilities/conditions/region_change.py`
- Create: `flow_runner/capabilities/conditions/window.py`
- Create: `flow_runner/capabilities/conditions/process.py`
- Create: `flow_runner/infrastructure/windowing/win32.py`
- Create: `flow_runner/infrastructure/processes/query.py`
- Create: `tests/integration/test_system_conditions.py`

- [ ] **Step 1: Write provider contract tests**

Test RGB tolerance, percentage region change, window existence/title/foreground checks, process existence, inaccessible-process errors, and deterministic fake Win32 providers.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/integration/test_system_conditions.py -q`

Expected: FAIL because providers are absent.

- [ ] **Step 3: Implement providers through injected Win32/process adapters**

Keep native calls in infrastructure modules and return standard `ConditionResult` objects. Pixel and region-change providers use `PerceptionService`; window and process checks do not capture frames.

- [ ] **Step 4: Run provider tests**

Run: `python -m pytest tests/integration/test_system_conditions.py -q`

Expected: all tests pass.

### Task 21: Add window actions and parallel monitor orchestration

**Files:**
- Create: `flow_runner/capabilities/actions/window.py`
- Create: `flow_runner/engine/parallel.py`
- Create: `tests/integration/test_parallel_monitors.py`

- [ ] **Step 1: Write resource-aware parallel tests**

Test two read-only monitors sharing a frame, same-window actions serializing, desktop actions blocking window interactions, stale-coordinate revalidation, and cancellation of all child monitors when the parent task stops.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/integration/test_parallel_monitors.py -q`

Expected: FAIL because parallel orchestration is absent.

- [ ] **Step 3: Implement explicit parallel blocks**

Parallel execution must be configured explicitly, never inferred from separate routes. Child contexts share task variables through synchronized access, keep separate workflow variables and call stacks, and report conflicts through `ResourceCoordinator` events.

- [ ] **Step 4: Implement window actions**

Support activate, minimize, restore, move, and resize through an injected Win32 adapter. Declare target-window exclusive resources and mark scene changes after geometry/focus operations.

- [ ] **Step 5: Run parallel tests**

Run: `python -m pytest tests/integration/test_parallel_monitors.py -q`

Expected: all tests pass.

## Phase 9: Final Verification and Handoff

### Task 22: Run automated verification and real Windows acceptance

**Files:**
- Modify: `README.md`
- Create: `REAL_ENVIRONMENT_CHECKLIST.md`

- [ ] **Step 1: Run the complete deterministic test suite**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q`

Expected: all automated tests pass with no unexpected skips.

- [ ] **Step 2: Run static checks**

Run: `python -m ruff check flow_runner tests`

Run: `python -m mypy flow_runner`

Expected: both commands complete with no errors.

- [ ] **Step 3: Verify imports have no side effects**

Run: `python -c "import flow_runner; import flow_runner.engine.runner; print('ok')"`

Expected: prints `ok`; no log/config directories are created and no OCR process starts.

- [ ] **Step 4: Create the real-environment checklist**

Document exact pass/fail checks for Windows DPI scaling, multiple monitors, full-screen/window capture, PaddleOCR-json, Tesseract, template matching, global hotkeys, mouse/keyboard cancellation, recording/playback, window focus, process launch, concurrent monitors, pause/resume, shutdown, and configuration recovery.

- [ ] **Step 5: Execute user-assisted real-environment acceptance**

Run the checklist against a disposable automation project. Record environment, observed result, and evidence path for every item. Do not declare the refactor complete while any required item is untested or failing.

- [ ] **Step 6: Review the final file boundary**

Run: `rg -n "flow_runner_p[123]|from flow_runner_p|import flow_runner_p" flow_runner tests`

Expected: no matches. The new package must not import legacy scripts.

- [ ] **Step 7: Confirm deferred work explicitly**

Record that two separate user-directed tasks remain outside this implementation plan: applying the future `DESIGN.md` to final QSS/assets, and generating a new configuration from the legacy config after the new project is stable.

## 3. Phase Checkpoints

| Checkpoint | Required evidence |
|---|---|
| Domain ready | Typed models and reference validation tests pass |
| Runtime ready | ONCE/UNTIL, retry, routing, call/return and cancellation tests pass |
| Concurrency ready | Shared-frame, cache invalidation, exclusive input and revalidation tests pass |
| Capability parity | Existing OCR/image/input/process/script behavior passes adapter contracts |
| Editor ready | Offscreen three-pane, guided-add, switching and QSS tests pass |
| Integration ready | Runner bridge, hotkeys, shutdown and persistence tests pass |
| Refactor accepted | Full automated suite plus real Windows checklist pass |

## 4. Plan Completion Criteria

- Every task checkbox is complete with recorded command output.
- No new package module imports any legacy script.
- No fixed `ocr_click`/`ocr_loop`/`ocr_poll` or image equivalents exist in the new model.
- The A1→A2→A3 loop, dynamic transition to B1, and B3→C1 transition pass an automated test.
- AND/NOT/multi-match OR results cannot expose ambiguous `primary` values.
- Repeated conditions share frames and detector results by documented cache keys.
- Screen-derived actions revalidate stale results under exclusive resource leases.
- Python UI modules contain no hard-coded visual styling.
- Old configuration conversion and final `DESIGN.md` styling remain separate, explicitly requested follow-up tasks.
