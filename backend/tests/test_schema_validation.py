import pytest
from pydantic import ValidationError

from app.ai.provider import strict_json_schema
from app.schemas.interview import AnswerEvaluation, InterviewPlan
from tests.utils import sample_plan


def test_valid_interview_plan_json_is_accepted():
    payload = sample_plan(["python"]).model_dump()

    plan = InterviewPlan.model_validate(payload)

    assert plan.skills[0].skill_name == "python"


def test_malformed_evaluator_json_is_rejected():
    with pytest.raises(ValidationError):
        AnswerEvaluation.model_validate({"score": 101, "confidence": 1.2, "follow_up_needed": True})


def test_requires_evidence_items_to_be_non_blank():
    with pytest.raises(ValidationError):
        AnswerEvaluation.model_validate(
            {
                "score": 50,
                "confidence": 0.5,
                "follow_up_needed": True,
                "evidence": [" "],
            }
        )


def test_openai_strict_schema_hardening_sets_additional_properties_false():
    schema = strict_json_schema(InterviewPlan.model_json_schema())

    object_nodes = []

    def collect_objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                object_nodes.append(node)
            for value in node.values():
                collect_objects(value)
        elif isinstance(node, list):
            for item in node:
                collect_objects(item)

    collect_objects(schema)

    assert object_nodes
    assert all(node.get("additionalProperties") is False for node in object_nodes)
    assert all(set(node.get("required", [])) == set((node.get("properties") or {}).keys()) for node in object_nodes)


def test_openai_strict_schema_hardening_removes_defaults():
    schema = strict_json_schema(InterviewPlan.model_json_schema())

    def assert_no_default(node):
        if isinstance(node, dict):
            assert "default" not in node
            for value in node.values():
                assert_no_default(value)
        elif isinstance(node, list):
            for item in node:
                assert_no_default(item)

    assert_no_default(schema)
