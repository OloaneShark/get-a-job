
from openai import OpenAI


def get_client():
    return OpenAI()


def generate_interview_coach(company, position, job_description, resume_text=""):
    prompt = f"""
You are an experienced technical interviewer and security engineering hiring manager.

Company:
{company}

Position:
{position}

Candidate Resume:
{resume_text}

Job Description:
{job_description}

Create a complete interview preparation guide.

Include the following sections using Markdown headings:

# Interview Overview

Briefly summarize what this role is looking for.

# Likely Behavioral Questions

Provide 8–10 likely behavioral questions.

# Likely Technical Questions

Provide 10–15 technical questions specific to this role.

# Role-Specific Study Topics

List the most important concepts, tools, technologies, and frameworks the candidate should review.

# Strong Answer Tips

Provide practical advice for answering effectively.

# Red Flags to Avoid

List common mistakes candidates make when interviewing for this type of role.

# Final Preparation Checklist

Provide a concise checklist the candidate can review the day before the interview.

Rules:

- Keep the guide professional, practical, and specific to the provided role.
- Do not invent company facts.
- Do not ask follow-up questions.
- Do not offer additional services or suggestions at the end.
- Assume this guide will be displayed as a finished report inside a web application.
"""

    client = get_client()

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt
    )

    return response.output_text
