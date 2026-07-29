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
Score how well the candidate matches the job requirements on a scale of 0-100,
considering relevant skills, experience, and education.

Return only JSON in this exact structure, nothing else:
{
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


INTERVIEW_EVAL_SYSTEM_INSTRUCTION = """You are an Interview Conversation Analyzer.
You are given an audio recording of a job interview and the list of questions the
candidate was asked. Diarize the audio: identify each speaker and label them as
"Interviewer" or "Candidate" based on context. Transcribe the conversation, using
English letters only regardless of the spoken language.

Evaluate the Candidate's conversation skills specifically: clarity of communication,
confidence, relevance of answers to the questions asked, and professionalism.
Score the candidate's conversation skills on a scale of 0-100.

Write a summary of the interview in not more than 200 words.

Return only JSON in this exact structure, nothing else:
{
  "conversation": [
    {"speaker": "Interviewer", "message": "..."},
    {"speaker": "Candidate", "message": "..."}
  ],
  "summary": "...",
  "conversation_score": <integer 0-100>,
  "evaluation_notes": "one or two sentence explanation of the score"
}
"""


def evaluate_interview(audio_bytes: bytes, mime_type: str, questions: list) -> dict:
    questions_text = "\n".join(f"- {q}" for q in questions)
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                types.Part.from_text(
                    text=f"Interview questions asked:\n{questions_text}"
                ),
            ],
        )
    ]
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
