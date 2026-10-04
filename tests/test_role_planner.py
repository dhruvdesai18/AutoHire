from unittest.mock import patch

from app.role_planner import generate_team_job_descriptions

ONE_ROLE_TEAM_PLAN = {
    "roles": [{"title": "Backend Engineer", "count": 1, "rationale": "Needs an API."}]
}
REQUIREMENTS = {
    "what_they_will_build": "The API.",
    "responsibilities": ["Build the API"],
    "required_skills": ["Python"],
    "preferred_skills": ["Postgres"],
}
DRAFT_JD = {
    "title": "Backend Engineer",
    "about_the_role": "You will build the API.",
    "responsibilities": ["Build the API"],
    "required_skills": ["Python"],
    "preferred_skills": ["Postgres"],
}


def _responder(by_instruction_keyword):
    """Build a _generate_json side_effect that dispatches on a keyword found in
    the system_instruction, so tests don't depend on call ordering."""

    def respond(system_instruction, _user_text):
        for keyword, value_or_fn in by_instruction_keyword.items():
            if keyword in system_instruction:
                return value_or_fn() if callable(value_or_fn) else value_or_fn
        raise AssertionError(f"Unexpected system_instruction: {system_instruction[:60]}")

    return respond


def test_generate_team_job_descriptions_happy_path():
    responder = _responder(
        {
            "Team Planning Agent": ONE_ROLE_TEAM_PLAN,
            "Role Requirements Agent": REQUIREMENTS,
            "Job Description Writer Agent": DRAFT_JD,
            "Review Agent": {"approved": True, "issues": [], "revision_instructions": None},
        }
    )
    with patch("app.role_planner._generate_json", side_effect=responder) as mock_gen:
        events = list(generate_team_job_descriptions("Build a thing", max_revisions=2))

    types = [e["type"] for e in events]
    assert types == [
        "team_planned",
        "role_start",
        "requirements_ready",
        "draft_ready",
        "review_ready",
        "role_finalized",
        "done",
    ]
    assert events[-1]["results"] == [{"role": ONE_ROLE_TEAM_PLAN["roles"][0], "jd": DRAFT_JD}]
    # plan_team + requirements + one write + one review = 4 calls, no revision loop
    assert mock_gen.call_count == 4


def test_generate_team_job_descriptions_revises_until_approved():
    review_calls = {"n": 0}

    def review_response():
        review_calls["n"] += 1
        if review_calls["n"] == 1:
            return {"approved": False, "issues": ["too vague"], "revision_instructions": "be specific"}
        return {"approved": True, "issues": [], "revision_instructions": None}

    responder = _responder(
        {
            "Team Planning Agent": ONE_ROLE_TEAM_PLAN,
            "Role Requirements Agent": REQUIREMENTS,
            "Job Description Writer Agent": DRAFT_JD,
            "Review Agent": review_response,
        }
    )
    with patch("app.role_planner._generate_json", side_effect=responder):
        events = list(generate_team_job_descriptions("Build a thing", max_revisions=2))

    draft_events = [e for e in events if e["type"] == "draft_ready"]
    review_events = [e for e in events if e["type"] == "review_ready"]
    assert len(draft_events) == 2
    assert len(review_events) == 2
    assert review_events[0]["approved"] is False
    assert review_events[1]["approved"] is True
    assert events[-1]["type"] == "done"


def test_generate_team_job_descriptions_stops_at_max_revisions():
    responder = _responder(
        {
            "Team Planning Agent": ONE_ROLE_TEAM_PLAN,
            "Role Requirements Agent": REQUIREMENTS,
            "Job Description Writer Agent": DRAFT_JD,
            "Review Agent": {"approved": False, "issues": ["still bad"], "revision_instructions": "fix it"},
        }
    )
    with patch("app.role_planner._generate_json", side_effect=responder):
        events = list(generate_team_job_descriptions("Build a thing", max_revisions=1))

    draft_events = [e for e in events if e["type"] == "draft_ready"]
    # initial draft + 1 allowed revision = 2 drafts, then it gives up and finalizes anyway
    assert len(draft_events) == 2
    assert events[-1]["type"] == "done"
    assert events[-1]["results"][0]["jd"] == DRAFT_JD


def test_generate_team_job_descriptions_emits_error_event_on_failure():
    def boom(_system_instruction, _user_text):
        raise RuntimeError("Gemini exploded")

    with patch("app.role_planner._generate_json", side_effect=boom):
        events = list(generate_team_job_descriptions("Build a thing", max_revisions=2))

    assert len(events) == 1
    assert events[0] == {"type": "error", "message": "Gemini exploded"}
