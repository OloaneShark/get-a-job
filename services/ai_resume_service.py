
from openai import OpenAI

client = OpenAI()


def analyze_resume(resume_text, job_description=""):
    prompt = f"""
You are an experienced technical recruiter and resume reviewer.

Resume:
{resume_text}

Job Description:
{job_description}

Provide:

1. Overall score (0-100)
2. ATS compatibility
3. Top strengths
4. Top weaknesses
5. Bullet point improvements
6. Missing skills
7. Overall recommendations

Respond in clear markdown.
"""

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt
    )

    return response.output_text
