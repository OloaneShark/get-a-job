# Jobfinitum

Jobfinitum is a job-search operations workspace for discovering roles, managing
applications, maintaining resume versions, researching employers, and reducing
repetitive application work.

The application is under active development. It currently includes the core
tracking platform, multi-source job discovery, scheduled lifecycle cleanup,
search profiles, AI-assisted preparation tools, and a normal-Chrome Auto Apply
agent.

## Current Capabilities

### Accounts and security

- Email/password registration with bcrypt password hashing
- Email verification with console, Resend, or Amazon SES delivery
- Google OAuth login
- Optional TOTP two-factor authentication and recovery codes
- Profile, password, 2FA, and account-deletion settings
- Per-user data isolation, CSRF protection, encrypted notes, and audit logging

### Job discovery

- 28 registered source adapters
- Public feeds, job boards, ATS boards, and configurable company sources
- Search profiles with title, location, remote, salary, technology, visa, and
  Auto Apply preferences
- Shared job cache, deduplication, saved jobs, ignored jobs, and bulk actions
- Job lifecycle checks that remove closed or stale postings
- Admin source registry, source discovery queue, validation, and approval tools

Registered discovery sources:

`Greenhouse`, `Lever`, `Ashby`, `Remote OK`, `We Work Remotely`, `Remotive`,
`Himalayas`, `Jobicy`, `Arbeitnow`, `Japan Dev`, `TokyoDev`, `Workday`,
`Recruitee`, `Adzuna`, `Jooble`, `USAJobs`, `The Muse`, `Python.org Jobs`,
`Hacker News Jobs`, `CNCF GitJobs`, `Remote First Jobs`, `Y Combinator Jobs`,
`AI Dev Jobs`, `Green Japan`, `BambooHR`, `Workable`, `Amazon Jobs`, and
`Apple Jobs`.

Discovery support does not automatically mean submission support. Unsupported
application systems are handed to the user as Manual Apply instead of being
reported as submitted.

### Auto Apply

- Search-profile staging rules and account-wide daily limits
- Explicit resume selection per Auto Apply profile
- Applicant Profile identity, contact, authorization, education, language, and
  reusable-answer fields
- Remembered application answers with per-answer deletion
- Queue states for review, sign-in, verification, missing answers, user action,
  manual apply, failure, submission, and rejection
- Batch execution with watchdog handling and managed tab cleanup
- Unknown required questions return to Jobfinitum as Needs Application Answer
- CAPTCHA and genuine human verification pause for the user; they are never
  bypassed
- Submission is marked complete only after the employer page confirms it

Normal-Chrome submission adapters:

- Hosted ATS forms: Greenhouse, Lever, and Ashby
- Middleman resolvers: Himalayas, Remote First Jobs, Japan Dev, We Work
  Remotely, Jooble, Remote OK, Jobicy, TokyoDev, Adzuna, and The Muse
- Evidence-gated employer-site scanner for branded Greenhouse, Lever, and Ashby
  wrappers

The unpacked extension lives in
`browser_extensions/jobfinitum_chrome_agent`.

### Applications, resumes, and AI

- Application create, edit, detail, delete, search, status history, and CSV
  export workflows
- Job URL import and independent saved job descriptions
- Company legitimacy, risk, and application-intelligence reports
- Multiple PDF/DOCX resume versions with extraction, preview, and download
- Resume analysis, resume-to-job matching, AI resume review, cover letters,
  interview coaching, and saved interview preparation
- Manual prompt fallback when an AI request cannot be completed

## Architecture

```text
Browser
  -> Flask routes and Jinja templates
  -> SQLAlchemy models
  -> PostgreSQL
  -> job-source services and schedulers
  -> OpenAI-backed analysis services
  -> Jobfinitum Chrome Agent
       -> board resolver
       -> hosted ATS adapter
       -> confirmed result API
```

Runtime route handlers currently live in `app.py`. The root `routes.py` module
provides a live, duplicate-aware route catalog while route extraction into
Flask blueprints remains future architecture work.

## Requirements

- Python 3.12 or newer; the Docker image currently uses Python 3.14
- PostgreSQL
- Chrome for the normal-browser Auto Apply agent
- Node.js only when running the JavaScript edge-case harnesses directly
- An OpenAI API key only for AI-backed features

Python packages are pinned in `requirements.txt`.

## Local Setup

Windows PowerShell:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Create a `.env` file and configure at least the required values below, then run
the idempotent migrations used by the application:

```powershell
python migrate_account_security.py
python migrate_shared_job_cache.py
python migrate_auto_apply.py
python migrate_auto_apply_submission.py
python migrate_application_answer_memory.py
python migrate_application_answer_profile.py
python migrate_job_application_capacity.py
python app.py
```

Jobfinitum will be available at `http://127.0.0.1:5000`.

Docker:

```bash
docker compose up --build
```

## Environment

Required:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask sessions and signed Chrome Agent task tokens |
| `DATABASE_URL` | SQLAlchemy PostgreSQL connection URL |
| `ENCRYPTION_KEY` | Encryption for sensitive stored fields |
| `SECURITY_HASH_KEY` | Stable hashing for security-sensitive values |

Optional feature configuration:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | AI resume, cover-letter, interview, and intelligence tools |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google OAuth |
| `EMAIL_BACKEND` | `console`, `resend`, or `ses` |
| `EMAIL_FROM`, `RESEND_API_KEY`, `AWS_SES_REGION` | Verification email delivery |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna discovery |
| `JOOBLE_API_KEY` | Jooble discovery |
| `USAJOBS_API_KEY`, `USAJOBS_API_EMAIL` | USAJobs discovery |
| `THE_MUSE_API_KEY` | The Muse discovery |
| `AI_DEV_JOBS_API_KEY` | AI Dev Jobs discovery |
| `GREENHOUSE_EDUCATION_BOARD_TOKEN` | Greenhouse school lookup seed |
| `JOB_SCHEDULER_ENABLED` | Enables scheduled discovery |
| `JOB_LIFECYCLE_ENABLED` | Enables closed-posting lifecycle checks |
| `JOB_SOURCE_DEBUG` | Enables source diagnostics |
| `AUTO_APPLY_BROWSER_MODE` | Legacy Playwright mode: `ephemeral` or `persistent` |
| `AUTO_APPLY_BROWSER_CHANNEL` | Persistent browser channel |
| `AUTO_APPLY_BROWSER_PROFILE_DIR` | Persistent browser profile directory |
| `AUTO_APPLY_BROWSER_HEADLESS` | Legacy browser visibility |
| `AUTO_APPLY_HUMAN_HANDOFF_TIMEOUT_SECONDS` | Human handoff timeout |

Do not commit `.env` or production credentials.

## Chrome Agent

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose Load unpacked.
4. Select `browser_extensions/jobfinitum_chrome_agent`.
5. Reload the extension after any agent or manifest change.

Jobfinitum checks the installed extension version on the Browser Agent settings
page.

## Routes

Print the current route inventory:

```powershell
python routes.py
```

The command groups routes by feature, reports the total, and exits with an error
if two handlers claim an overlapping method on the same URL rule.

## Tests

```powershell
python -m unittest discover -s tests
python -m compileall -q app.py services tests
python -m pip check
```

The JavaScript edge harnesses use Node. The Playwright package includes a Node
runtime in this development environment:

```powershell
.\venv\Lib\site-packages\playwright\driver\node.exe tests\js\employer_site_agent_edge_cases.mjs
.\venv\Lib\site-packages\playwright\driver\node.exe tests\js\job_board_resolver_background_edge_cases.mjs
```

## Project Status

See `ROADMAP.md` for current priorities and `CHANGELOG.md` for shipped work.
