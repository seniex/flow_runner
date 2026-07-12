import re

PRIMARY_PATTERN = re.compile(
    r"^\$result\.primary\.(?P<field>outcome|text|position|bounds|confidence|provider_data)$"
)
CHILD_PATTERN = re.compile(
    r'^\$result\.children\["(?P<alias>[^"\\]+)"\]\.'
    r"(?P<field>outcome|text|position|bounds|confidence|provider_data)$"
)
VARIABLE_PATTERN = re.compile(
    r"^\$variables\.(?P<scope>task|workflow|persistent)\.(?P<name>[A-Za-z_][\w-]*)$"
)


def is_binding_expression(value: str) -> bool:
    return any(
        pattern.fullmatch(value) is not None
        for pattern in (PRIMARY_PATTERN, CHILD_PATTERN, VARIABLE_PATTERN)
    )
