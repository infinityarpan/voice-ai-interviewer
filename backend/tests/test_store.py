from app.schemas.interview import InterviewConfig, InterviewSessionState, SkillRuntimeState
from app.services.interview_engine.store import SQLiteInterviewStore
from tests.utils import sample_plan


def test_sqlite_store_round_trips_session_state(tmp_path):
    plan = sample_plan(["python"])
    state = InterviewSessionState(
        session_id="session-1",
        plan=plan,
        config=InterviewConfig(),
        current_skill_id="skill-1",
        skill_states={"skill-1": SkillRuntimeState(skill_id="skill-1", skill_name="python")},
        asked_question_fingerprints={"tell me about python"},
    )
    db_path = tmp_path / "interviews.sqlite3"

    store = SQLiteInterviewStore(str(db_path))
    store.save(state)
    reloaded = SQLiteInterviewStore(str(db_path)).get("session-1")

    assert reloaded.session_id == "session-1"
    assert reloaded.plan.skills[0].skill_name == "python"
    assert reloaded.asked_question_fingerprints == {"tell me about python"}


def test_sqlite_store_raises_key_error_for_missing_session(tmp_path):
    store = SQLiteInterviewStore(str(tmp_path / "interviews.sqlite3"))

    try:
        store.get("missing")
    except KeyError as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("Expected KeyError for missing session")
