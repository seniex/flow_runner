class FlowRunnerError(Exception):
    """Base exception for predictable Flow Runner failures."""


class ConditionError(FlowRunnerError):
    """A condition provider could not evaluate its condition."""


class ActionError(FlowRunnerError):
    """An action provider could not complete its action."""


class BindingError(FlowRunnerError):
    """A runtime result or variable binding could not be resolved."""


class RoutingError(FlowRunnerError):
    """A route target or workflow control operation is invalid."""


class ResourceConflict(FlowRunnerError):
    """A required desktop resource could not be acquired safely."""


class ConfigurationError(FlowRunnerError):
    """A project or capability configuration is invalid."""


class Cancelled(FlowRunnerError):
    """Execution was cancelled cooperatively by the caller."""
