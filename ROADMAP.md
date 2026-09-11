# Jobfinitum Roadmap

Jobfinitum is an active job-search operations platform. This roadmap separates
features that are already working from the reliability and coverage work that
still needs to be completed.

## Shipped Foundations

### Accounts and security

- [x] Email/password registration and login
- [x] Email verification and Google OAuth
- [x] Optional TOTP two-factor authentication and recovery codes
- [x] Per-user data isolation, encrypted notes, CSRF protection, and audit logs
- [x] Profile, password, security, and account-deletion settings

### Applications and resumes

- [x] Application tracking, filtering, history, search, and CSV export
- [x] Multiple PDF and DOCX resume versions
- [x] Resume extraction, preview, download, analysis, and job matching
- [x] Company research, trust scoring, and application intelligence
- [x] Cover letters, interview coaching, and saved interview preparation

### Job discovery

- [x] Twenty-eight registered discovery adapters
- [x] Search profiles with remote, location, salary, technology, visa, and title filters
- [x] Shared job cache, deduplication, saved jobs, and ignored jobs
- [x] Scheduled discovery and closed-posting lifecycle checks
- [x] Admin source registry and source discovery approval workflow

### Auto Apply

- [x] Search-profile queue staging and account-wide daily limits
- [x] Resume selection per Auto Apply profile
- [x] Reusable Applicant Profile answers and remembered application questions
- [x] Greenhouse, Lever, and Ashby hosted-form adapters
- [x] Ten middleman job-board resolvers
- [x] Evidence-gated detection of branded Greenhouse, Lever, and Ashby wrappers
- [x] Missing-answer, sign-in, CAPTCHA, verification, and manual-apply handoffs
- [x] Confirmed-submission handling and managed browser-tab cleanup

## Active Reliability Priorities

1. Cache host-level wrapper outcomes so repeatedly unsupported employer sites can
   bypass redundant browser inspection without hiding new job-specific evidence.
2. Continue hardening batch continuity and tab ownership when employer pages
   redirect, duplicate a tab, return 404, or fall back to a generic careers index.
3. Expand controlled React field persistence tests for education, nationality,
   demographic, and other dynamic ATS controls.
4. Improve runner diagnostics so every stop has a precise user-facing reason and
   enough structured detail for regression testing.
5. Keep source lifecycle checks fast and accurate as discovery volume grows.

## Submission Coverage

Discovery support and automated submission support are separate. A source may
find jobs while its destination ATS still requires Manual Apply.

Planned native submission adapters, in current priority order:

1. Zoho Recruit
2. Workday
3. SmartRecruiters
4. Workable

Additional middleman resolvers will be added from observed posting volume and
destination quality rather than company-specific exceptions.

## Product Expansion

- [ ] Email-based interview, rejection, offer, and status detection
- [ ] Interview and follow-up reminders with calendar export
- [ ] Application conversion and salary analytics
- [ ] Recruiter and networking contact workflows
- [ ] Additional resume tailoring and skill-gap guidance
- [ ] Mobile layout and accessibility hardening
- [ ] Optional local or alternate AI providers

## Engineering Work

- [ ] Extract the largest `app.py` route groups into Flask blueprints
- [ ] Add automated migration ordering and schema-version tracking
- [ ] Expand end-to-end tests for authenticated browser workflows
- [ ] Add structured health metrics for discovery and Auto Apply adapters
- [ ] Document production backup, restore, and incident procedures

## Product Direction

The goal is a focused workspace that can discover opportunities, evaluate them,
prepare strong application material, automate supported repetitive work, and
keep the user in control whenever a decision or human verification is required.
