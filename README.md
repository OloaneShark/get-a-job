# Get a Job

Get a Job is a full-stack job search command center — track applications, vet company legitimacy, analyze your resume against real job descriptions, and generate AI-assisted resumes, cover letters, and interview prep, all in one Flask app.

This project is being built in phases. **Phase 1 (core tracking + AI tools) is complete.** See [Roadmap](#roadmap) for what's next.

## Table of Contents

- [Phase 1 Features](#phase-1-features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)
- [Roadmap](#roadmap)

## Phase 1 Features

**Application Tracking**
- Add, edit, and delete job applications with company, position, salary, and status
- Status history log per application (auto-tracks changes over time)
- Search and filter dashboard by company name, status, and visa sponsorship
- Follow-up and last-contacted date tracking
- Export all applications to CSV

**Company & Job Legitimacy**
- Company reputation lookup with strengths/warnings breakdown
- Automated legitimacy scoring and risk level for each application (flags scam red flags from company website, posting URL, recruiter email, and salary)

**Resume Tools**
- Upload and store multiple resume versions (PDF/DOCX supported)
- Automatically extracts and stores resume text for reuse across AI features
- Latest uploaded resume is automatically used for AI resume review, cover letters, and interview preparation
- In-browser resume preview and download
- Rule-based resume strength scoring with specific improvement suggestions
- AI-powered resume review against a specific job description
- Resume-to-job-description keyword match scoring, with matched/missing keywords and priority gaps

**AI-Assisted Writing**
- AI cover letter generation automatically tailored to a company, role, and the user's latest uploaded resume
- AI interview coach that generates role-specific behavioral questions, technical questions, study topics, interview strategy, and preparation checklists using both the job description and the user's latest resume
- Saved interview prep, viewable later per application
- **Graceful AI fallback:** if the AI API is unavailable, the app builds a manual prompt you can paste directly into ChatGPT instead of failing outright

**Job Import**
- Import job postings directly from a URL
- Automatically cleans and extracts job posting content
- Review and edit imported information before saving
- Save imported postings directly into the application tracker
- Built on a generic extraction pipeline that can be expanded to support multiple job platforms

**Job Descriptions**
- Save job descriptions independently of an application for later reference
- Edit and delete saved job descriptions

**Security & Accounts**
- User registration and login (bcrypt-hashed passwords, Flask-Login sessions)
- Per-user data isolation — every application, resume, and prep is scoped to its owner
- Sensitive notes encrypted at rest
- Audit logging of key user actions

## Tech Stack

| Category | Tools |
|---|---|
| Language | Python |
| Web Framework | Flask |
| Auth | Flask-Login, bcrypt |
| Forms | Flask-WTF, WTForms |
| ORM | SQLAlchemy (Flask-SQLAlchemy) |
| Database | PostgreSQL |
| AI | OpenAI API |
| Resume Parsing | pypdf, python-docx |
| Containerization | Docker, Docker Compose |
| App Server | Gunicorn |
| CI/CD | GitHub Actions |

## Architecture

```
User → Flask App → SQLAlchemy → PostgreSQL
                 → OpenAI API (resume review, cover letters, interview coaching)
                 → Local file storage (uploaded resumes)
                 → Job URL Import Pipeline
                 → Resume Extraction (DOCX/PDF)
```

If the OpenAI API call fails, the relevant route catches the exception and returns a manually-copyable prompt instead of erroring out, so the AI features degrade instead of breaking.

## Local Setup

```bash
git clone https://github.com/OloaneShark/get-a-job.git
cd get-a-job
pip install -r requirements.txt
cp .env.example .env   # then fill in your own values
python app.py
```

Or with Docker:

```bash
docker compose up --build
```

The app will be available at `http://localhost:5000`.

## Environment Variables

**Required**

```
SECRET_KEY=
DATABASE_URL=
OPENAI_API_KEY=
```

> Secrets are never committed to this repository.

## Deployment

Deployed via Docker with Gunicorn as the app server. GitHub Actions handles CI on push to `main`.

## Roadmap

Get a Job is being built in phases. Planned for future phases:

- Intelligent multi-source job discovery (supported job boards and company career pages)
- AI-powered structured extraction of job postings
- Company OSINT and trust scoring
- Automated skill-gap analysis and resume optimization
- Email parsing for application status changes
- Browser extension for one-click application logging
- Analytics dashboard (response rates, interview rate, offer rate, ATS score trends)
- Email parsing to auto-detect application status changes
- Browser extension for one-click application logging
- Team/mentor sharing of application progress
- Analytics dashboard (response rates, time-to-offer, etc.)

Phase details will be updated here as each phase ships.
