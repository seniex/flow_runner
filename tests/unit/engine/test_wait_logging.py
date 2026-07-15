import asyncio

from flow_runner.capabilities.actions.wait import WaitAction
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.context import StepContext
from flow_runner.engine.runner import Runner
from flow_runner.engine.step_executor import StepExecutor, StepRuntime
from flow_runner.infrastructure.logging.sinks import MemoryEventSink


def test_runner_emits_wait_action_start_and_finish_with_identity():
    async def run():
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        registry = CapabilityRegistry()
        registry.register_action(WaitAction(fake_sleep))
        step = AutomationStep(
            name="等待加载",
            actions=[ActionSpec(capability="system.wait", config={"seconds": 3})],
        )
        workflow = Workflow(name="流程", steps=[step])
        project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
        sink = MemoryEventSink()
        executor = StepExecutor(
            StepRuntime(
                registry=registry,
                context=StepContext(),
                cancellation=CancellationToken(),
                sleep=fake_sleep,
            )
        )
        runner = Runner(executor, event_sink=sink)

        await runner.start(project, workflow.id)

        waits = [event for event in sink.events if event.kind.startswith("action.wait.")]
        assert [event.kind for event in waits] == ["action.wait.started", "action.wait.finished"]
        assert waits[0].workflow_id == workflow.id
        assert waits[0].step_id == step.id
        assert waits[0].details["seconds"] == 3
        assert waits[0].details["wait_id"] == waits[1].details["wait_id"]
        assert slept == [3.0]

    asyncio.run(run())


def test_run_step_emits_wait_identity_too():
    async def run():
        async def fake_sleep(_seconds):
            return None

        registry = CapabilityRegistry()
        registry.register_action(WaitAction(fake_sleep))
        step = AutomationStep(
            name="等待加载",
            actions=[ActionSpec(capability="system.wait", config={"seconds": 0})],
        )
        workflow = Workflow(name="流程", steps=[step])
        project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
        sink = MemoryEventSink()
        runner = Runner(
            StepExecutor(
                StepRuntime(
                    registry=registry,
                    context=StepContext(),
                    cancellation=CancellationToken(),
                    sleep=fake_sleep,
                )
            ),
            event_sink=sink,
        )

        await runner.run_step(project, workflow.id, step.id)

        waits = [event for event in sink.events if event.kind.startswith("action.wait.")]
        assert waits[0].workflow_id == workflow.id
        assert waits[0].step_id == step.id

    asyncio.run(run())
