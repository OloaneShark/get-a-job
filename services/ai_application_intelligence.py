
from openai import OpenAI


def get_client():
    return OpenAI()


def generate_application_intelligence(
    application,
    resume_text,
    resume_review,
    job_match,
    interview_guide,
    company_intelligence
):
    prompt = f"""
You are an experienced senior technical recruiter,
career coach,
and engineering hiring manager.

Analyze the following job application.

Company:
{application.company_name}

Position:
{application.position_title}

Location:
{application.location}

Salary:
{application.salary}

Visa Sponsorship:
{application.visa_sponsorship}

Application Status:
{application.status}

Trust Score:
{application.legitimacy_score}/100

Risk Level:
{application.risk_level}

--------------------------------------------------

Job Description

{application.job_description}

--------------------------------------------------

Resume

{resume_text}

--------------------------------------------------

Resume Review

{resume_review}

--------------------------------------------------

Job Match Analysis

{job_match}

--------------------------------------------------

Interview Guide

{interview_guide}

--------------------------------------------------

Company Intelligence

{company_intelligence}

--------------------------------------------------

Create a professional executive report.

Use these exact sections.

# Executive Summary

# Overall Readiness (0-100)

# Biggest Strengths

# Biggest Weaknesses

# Missing Skills

# Resume Improvements

# Interview Risks

# Hiring Risk

# Final Recommendation

# Immediate Next Steps

Rules:

Keep every recommendation specific.

Do not invent experience.

Do not repeat information.

Keep it professional.

Return Markdown only.
"""

    client = get_client()

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    return response.output_text