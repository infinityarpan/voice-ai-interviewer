from app.schemas.interview import ExpectedConcept, FollowUpTrigger, InterviewPlan, InterviewQuestion, InterviewSkillPlan, RubricItem


def sample_plan(skills: list[str]) -> InterviewPlan:
    return InterviewPlan(
        role_title="Backend Engineer",
        role_level="senior",
        skills=[
            InterviewSkillPlan(
                skill_id=f"skill-{index}",
                skill_name=skill,
                target_depth="senior",
                questions=[
                    InterviewQuestion(
                        question_id=f"q-{index}",
                        skill_id=f"skill-{index}",
                        question_text=f"Tell me about {skill}.",
                    )
                ],
                expected_concepts=[
                    ExpectedConcept(name=f"{skill} fundamentals", description="Core knowledge."),
                    ExpectedConcept(name=f"{skill} tradeoffs", description="Tradeoff reasoning."),
                ],
                rubric=[RubricItem(score=80, description="Strong answer.")],
                follow_up_triggers=[FollowUpTrigger(trigger_type="missing_concept", description="Missing concept.")],
            )
            for index, skill in enumerate(skills, start=1)
        ],
    )
