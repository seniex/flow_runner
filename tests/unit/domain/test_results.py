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


def test_not_group_never_exposes_primary():
    group = ConditionResult.not_group(
        "not_login",
        ConditionResult(node_id="ocr_login", outcome=ConditionOutcome.NO_MATCH),
    )

    assert group.outcome is ConditionOutcome.MATCH
    assert group.primary is None
