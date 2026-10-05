from app.gemini import _generate_json

TEAM_PLAN_SYSTEM_INSTRUCTION = """You are a Team Planning Agent inside a recruiting system.

A recruiter will describe a project in plain language. They may not know the technical
makeup of the team required. Your job is to work out which roles are actually needed to
build what is described, and how many people are needed for each role.

Rules:
- Base every role strictly on what the project actually requires. Do not add roles "just
  in case" or because they are common on other teams.
- Do not default to a generic web-team template (e.g. don't add a mobile developer if
  there is no mobile app, don't add a data scientist if there is no data science work).
- Use precise, industry-accurate titles (e.g. "Computer Vision Engineer" rather than
  "AI Engineer" when the work is specifically about vision).

Writing the "rationale" (this is read by a recruiter who may not have a technical
background, as the main explanation of why each role exists — write it like you're
walking a colleague through your reasoning out loud, not summarizing a job):
- Write 3-5 full sentences in natural, conversational language. Never a one-line
  summary or a restated job title.
- Name the specific part(s) of the project this role is responsible for — quote or
  closely paraphrase the actual language from the project description rather than
  speaking in generic terms.
- Explain *why* that work needs a dedicated person with this specific skill set: what
  concretely would be missing, broken, slower, or at risk if this role were left unfilled
  or folded into another role.
- If it's relevant, say how this role's work connects to or depends on another role on
  the team (e.g. "the backend engineer will need the API this role designs").
- Do not use vague filler ("plays a key role", "is essential for success", "helps drive
  the project forward"). Every sentence should carry a specific, checkable reason.

Return only JSON in this exact structure, nothing else:
{
  "roles": [
    {"title": "...", "count": <integer>, "rationale": "..."}
  ]
}
"""

ROLE_REQUIREMENTS_SYSTEM_INSTRUCTION = """You are a Role Requirements Agent inside a
recruiting system.

You will be given a project description and a single role that has already been
identified as necessary for that project. Define what this role actually involves FOR
THIS PROJECT SPECIFICALLY.

Rules:
- Do not write a generic job description for the title. Every responsibility and skill
  must be justifiable by something in the project description.
- Prefer concrete, technical specifics (frameworks, data types, constraints) over vague
  phrases like "strong communication skills" or "team player".
- required_skills should be the skills someone must already have to do this job on this
  project. preferred_skills are a bonus, not mandatory.
- Do not inflate seniority or years-of-experience requirements beyond what the project's
  scope justifies.

Return only JSON in this exact structure, nothing else:
{
  "what_they_will_build": "...",
  "responsibilities": ["...", "..."],
  "required_skills": ["...", "..."],
  "preferred_skills": ["...", "..."]
}
"""

JD_WRITER_SYSTEM_INSTRUCTION = """You are a Job Description Writer Agent inside a
recruiting system.

Turn the given role requirements into a clear, well-structured job posting.

Rules:
- "about_the_role" is 1-3 sentences, written to the candidate ("You will..."),
  describing what they will actually build or work on for this project.
- responsibilities, required_skills and preferred_skills should read naturally as a job
  posting, not as a dump of the raw requirements.
- Do not add anything not supported by the given requirements.
- If revision instructions are provided, treat them as mandatory changes to the previous
  draft, not suggestions.

Return only JSON in this exact structure, nothing else:
{
  "title": "...",
  "about_the_role": "...",
  "responsibilities": ["...", "..."],
  "required_skills": ["...", "..."],
  "preferred_skills": ["...", "..."]
}
"""

REVIEW_SYSTEM_INSTRUCTION = """You are a Review Agent inside a recruiting system.

Check the drafted job description against the project and the role's actual
requirements. Look specifically for:
- Vague language ("fast-paced environment", "rockstar", "ninja", "wear many hats")
- Unrealistic or inflated requirements not justified by the project's scope (e.g.
  years-of-experience minimums that don't match the work)
- Important skills from the requirements that are missing from the draft
- Unnecessary jargon or buzzwords that don't help a real candidate self-select

Approve only if the draft is precise, realistic and fully grounded in the supplied
requirements. If you find issues, set approved to false and give revision_instructions
specific enough for the writer to fix them without guessing.

Return only JSON in this exact structure, nothing else:
{
  "approved": <true or false>,
  "issues": ["...", "..."],
  "revision_instructions": "... or null"
}
"""


def plan_team(project_description: str) -> dict:
    return _generate_json(
        TEAM_PLAN_SYSTEM_INSTRUCTION,
        f"Project description:\n{project_description}\n\nDecide the team needed to build this.",
    )


def define_role_requirements(project_description: str, role: dict) -> dict:
    user_text = (
        f"Project description:\n{project_description}\n\n"
        f"Role: {role['title']} ({role['count']} needed)\n"
        f"Why this role is needed: {role['rationale']}\n\n"
        "Define the responsibilities, required skills and preferred skills for this "
        "role, specific to this project."
    )
    return _generate_json(ROLE_REQUIREMENTS_SYSTEM_INSTRUCTION, user_text)


def write_job_description(
    project_description: str,
    role: dict,
    requirements: dict,
    previous_draft: dict | None = None,
    revision_instructions: str | None = None,
) -> dict:
    user_text = (
        f"Project description:\n{project_description}\n\n"
        f"Role: {role['title']}\n\n"
        f"What they will build: {requirements['what_they_will_build']}\n"
        f"Responsibilities: {requirements['responsibilities']}\n"
        f"Required skills: {requirements['required_skills']}\n"
        f"Preferred skills: {requirements['preferred_skills']}\n\n"
        "Write the job description."
    )
    if previous_draft is not None and revision_instructions:
        user_text += (
            f"\n\nPrevious draft:\n{previous_draft}\n\n"
            f"Mandatory revision instructions from the review agent:\n{revision_instructions}"
        )
    return _generate_json(JD_WRITER_SYSTEM_INSTRUCTION, user_text)


def review_job_description(project_description: str, role: dict, requirements: dict, jd: dict) -> dict:
    user_text = (
        f"Project description:\n{project_description}\n\n"
        f"Role: {role['title']}\n\n"
        f"Requirements the draft should be grounded in:\n{requirements}\n\n"
        f"Drafted job description:\n{jd}"
    )
    return _generate_json(REVIEW_SYSTEM_INSTRUCTION, user_text)


def generate_team_job_descriptions(project_description: str, max_revisions: int = 2):
    """Generator yielding progress events while planning a team and writing a
    reviewed job description for each role.

    Event shapes:
      {"type": "team_planned", "roles": [...]}
      {"type": "role_start", "role_index": i, "role": {...}}
      {"type": "requirements_ready", "role_index": i, "requirements": {...}}
      {"type": "draft_ready", "role_index": i, "revision": n, "jd": {...}}
      {"type": "review_ready", "role_index": i, "revision": n, "approved": bool, "issues": [...]}
      {"type": "role_finalized", "role_index": i, "role": {...}, "jd": {...}}
      {"type": "done", "results": [{"role": {...}, "jd": {...}}, ...]}
      {"type": "error", "message": "..."}
    """
    try:
        team_plan = plan_team(project_description)
        roles = team_plan.get("roles", [])
        yield {"type": "team_planned", "roles": roles}

        results = []
        for index, role in enumerate(roles):
            yield {"type": "role_start", "role_index": index, "role": role}

            requirements = define_role_requirements(project_description, role)
            yield {"type": "requirements_ready", "role_index": index, "requirements": requirements}

            jd = None
            revision_instructions = None
            revision_count = 0
            while True:
                jd = write_job_description(
                    project_description, role, requirements,
                    previous_draft=jd, revision_instructions=revision_instructions,
                )
                yield {"type": "draft_ready", "role_index": index, "revision": revision_count, "jd": jd}

                feedback = review_job_description(project_description, role, requirements, jd)
                yield {
                    "type": "review_ready",
                    "role_index": index,
                    "revision": revision_count,
                    "approved": feedback.get("approved", False),
                    "issues": feedback.get("issues", []),
                }

                if feedback.get("approved") or revision_count >= max_revisions:
                    break
                revision_count += 1
                revision_instructions = feedback.get("revision_instructions")

            yield {"type": "role_finalized", "role_index": index, "role": role, "jd": jd}
            results.append({"role": role, "jd": jd})

        yield {"type": "done", "results": results}
    except Exception as e:
        yield {"type": "error", "message": str(e)}
