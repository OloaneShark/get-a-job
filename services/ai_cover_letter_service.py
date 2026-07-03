
from openai import OpenAI


def get_client():
    return OpenAI()


from openai import OpenAI


def get_client():
    return OpenAI()


def generate_cover_letter(company, position, resume_text, job_description):
    prompt = f"""
You are a professional career coach and technical recruiter.

Write a professional cover letter for this job application.

Company:
{company}

Position:
{position}

Resume:
{resume_text}

Job Description:
{job_description}

Rules:
- Keep it professional.
- Keep it concise.
- Do not invent experience.
- Emphasize relevant technical skills.
- Mention why the candidate is a good fit.
- Avoid sounding generic.
- Use a confident but respectful tone.
"""

    client = get_client()

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt
    )

    return response.output_text