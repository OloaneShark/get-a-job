
def build_resume_review_prompt(resume_text, job_description=""):
    return f"""
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


def build_interview_coach_prompt(company, position, job_description, resume_text=""):
    return f"""
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


def build_interview_coach_prompt(company, position, job_description):
    return f"""
You are an experienced technical interviewer and security engineering hiring manager.

Company:
{company}

Position:
{position}

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
