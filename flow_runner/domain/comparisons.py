import re
from typing import Any

from flow_runner.domain.routing import ComparisonOperator


def compare_values(actual: Any, operator: ComparisonOperator, expected: Any) -> bool:
    if operator is ComparisonOperator.EQ:
        return bool(actual == expected)
    if operator is ComparisonOperator.NE:
        return bool(actual != expected)
    if operator is ComparisonOperator.LT:
        return bool(actual < expected)
    if operator is ComparisonOperator.LE:
        return bool(actual <= expected)
    if operator is ComparisonOperator.GT:
        return bool(actual > expected)
    if operator is ComparisonOperator.GE:
        return bool(actual >= expected)
    if operator is ComparisonOperator.CONTAINS:
        return bool(expected in actual)
    return re.search(str(expected), str(actual)) is not None
