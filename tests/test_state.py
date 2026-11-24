import pytest


def test_state_persists_and_cannot_skip_gate(tmp_path):
    from auditflow.core.state import Tracker

    path = tmp_path / "tracker.sqlite"
    tracker = Tracker(path)
    tracker.add_target("sample")
    with pytest.raises(ValueError):
        tracker.transition_target("sample", "CLONED")
    tracker.transition_target("sample", "GATE1_PENDING")
    assert Tracker(path).target_status("sample") == "GATE1_PENDING"


def test_environment_resume_requires_state_transition(tmp_path):
    from auditflow.core.state import Tracker

    tracker = Tracker(tmp_path / "tracker.sqlite")
    tracker.add_target("sample")
    tracker.add_candidate("sample", "CAND-01")
    for state in ["GATE2_PENDING", "VERIFY_APPROVED", "DEPLOYING", "NEEDS_HUMAN_ENV"]:
        tracker.transition_candidate("sample", "CAND-01", state)
    with pytest.raises(ValueError):
        tracker.transition_candidate("sample", "CAND-01", "VERIFIED")
    tracker.transition_candidate("sample", "CAND-01", "DEPLOYING")
    assert tracker.candidate_status("sample", "CAND-01") == "DEPLOYING"
