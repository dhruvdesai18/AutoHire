import json
import re

from google import genai
from google.genai import types

from app.config import GCP_PROJECT_ID

client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")


def _generate_json(system_instruction: str, user_text: str) -> dict:
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
    ]
    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        system_instruction=[types.Part.from_text(text=system_instruction)],
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=generate_content_config,
    )
    cleaned = re.sub(r"```json|```", "", response.text).strip()
    return json.loads(cleaned)


SCORING_SYSTEM_INSTRUCTION = """You are an ATS (Applicant Tracking System) resume screener.
You are given a job description and a candidate's resume text.
Extract the candidate's full name from the resume text, normalized to standard title
case (e.g. "Dhruv Desai", not "DHRUV DESAI" or "dhruv desai"), even if the resume
itself uses all-caps or other formatting.
Score how well the candidate matches the job requirements on a scale of 0-100,
considering relevant skills, experience, and education.

Return only JSON in this exact structure, nothing else:
{
  "candidate_name": "candidate's full name as found in the resume",
  "score": <integer 0-100>,
  "matched_skills": ["...", "..."],
  "missing_skills": ["...", "..."],
  "reasoning": "one or two sentence explanation of the score"
}
"""


def score_resume(resume_text: str, job_description: str) -> dict:
    user_text = f"Job Description:\n{job_description}\n\nResume:\n{resume_text}"
    return _generate_json(SCORING_SYSTEM_INSTRUCTION, user_text)


INTERVIEW_PREP_SYSTEM_INSTRUCTION = """You are an interview preparation assistant.
You are given a job description and a candidate's resume text.
Extract the candidate's email address from the resume text.
Generate exactly 5 interview questions tailored to this candidate and this role,
based on their specific experience and the job requirements.

Return only JSON in this exact structure, nothing else:
{
  "email": "candidate's email address as found in the resume",
  "questions": ["question 1", "question 2", "question 3", "question 4", "question 5"]
}
"""


def generate_interview_prep(resume_text: str, job_description: str) -> dict:
    user_text = f"Job Description:\n{job_description}\n\nResume:\n{resume_text}"
    return _generate_json(INTERVIEW_PREP_SYSTEM_INSTRUCTION, user_text)


JD_FORMAT_SYSTEM_INSTRUCTION = """You are given a raw job description. Organize it into
clear sections using only the content actually present in the text — do not invent or
add any details that aren't there. Typical sections include an overview, responsibilities,
requirements/qualifications, and anything else actually present (e.g. benefits, about the
company). Use whatever sections genuinely fit the content; skip ones that don't apply.

For each section, use "bullets" if the content is naturally a list (responsibilities,
requirements, etc.), or "content" for a short narrative paragraph (e.g. an overview).

Return only JSON in this exact structure, nothing else:
{
  "sections": [
    {"heading": "...", "content": "..."},
    {"heading": "...", "bullets": ["...", "..."]}
  ]
}
"""


def format_job_description(raw_description: str) -> dict:
    return _generate_json(JD_FORMAT_SYSTEM_INSTRUCTION, raw_description)


INTERVIEW_EVAL_SYSTEM_INSTRUCTION = """You are an Interview Assessment Analyzer.
You are given a series of interview questions. For each question, you are given
either the candidate's audio recording answering it, or a note that the candidate
did not answer it (treat unanswered questions as a negative signal).

For each answered question, transcribe what the candidate said, using English
letters only regardless of the spoken language.

Evaluate the candidate's communication skills across all their answers: clarity,
confidence, relevance of each answer to its question, and professionalism.
Score the candidate's overall communication skills on a scale of 0-100, factoring
in any unanswered questions.

Write a summary of the candidate's overall performance in not more than 200 words.

Return only JSON in this exact structure, nothing else:
{
  "answers": [
    {"question": "...", "transcript": "... or '(not answered)'", "notes": "brief note on this answer"}
  ],
  "summary": "...",
  "conversation_score": <integer 0-100>,
  "evaluation_notes": "one or two sentence explanation of the score"
}
"""


def evaluate_interview(question_recordings: list) -> dict:
    """question_recordings: list of {"question": str, "audio_bytes": bytes | None, "mime_type": str | None}"""
    parts = []
    for i, item in enumerate(question_recordings):
        parts.append(types.Part.from_text(text=f"Question {i + 1}: {item['question']}"))
        if item.get("audio_bytes"):
            parts.append(
                types.Part.from_bytes(
                    data=item["audio_bytes"], mime_type=item["mime_type"]
                )
            )
        else:
            parts.append(types.Part.from_text(text="(candidate did not answer this question)"))

    contents = [types.Content(role="user", parts=parts)]
    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        system_instruction=[
            types.Part.from_text(text=INTERVIEW_EVAL_SYSTEM_INSTRUCTION)
        ],
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=generate_content_config,
    )
    cleaned = re.sub(r"```json|```", "", response.text).strip()
    return json.loads(cleaned)
