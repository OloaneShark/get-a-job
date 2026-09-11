# Changelog

This file records meaningful Jobfinitum changes. The project is under active
development, so unreleased work may continue to evolve before a tagged release.

## Unreleased

### Job discovery

- Expanded discovery to 28 registered adapters across ATS boards, remote-job
  feeds, public APIs, regional boards, and configurable company sources.
- Added shared caching, deduplication, search profiles, saved and ignored jobs,
  scheduled discovery, and stale-posting lifecycle cleanup.
- Added the admin source registry, discovery queue, validation, and approval
  workflow.

### Auto Apply

- Added the normal-Chrome Jobfinitum Agent with hosted Greenhouse, Lever, and
  Ashby submission adapters.
- Added resolvers for Himalayas, Remote First Jobs, Japan Dev, We Work Remotely,
  Jooble, Remote OK, Jobicy, TokyoDev, Adzuna, and The Muse.
- Added Applicant Profile answers, remembered questions, resume selection,
  queue limits, missing-answer handoff, CAPTCHA pauses, submission confirmation,
  watchdog recovery, and managed tab cleanup.
- Added evidence-gated handling for employer sites that wrap Greenhouse, Lever,
  or Ashby forms.
- Reduced generic wrapper inspection time and prevented ordinary employer pages
  from being clicked without ATS evidence.
- Added closed-posting detection for 404 pages, removed jobs, and redirects to a
  generic careers index.

### Applications and intelligence

- Added application history, search, pagination, CSV export, job URL import, and
  saved job-description workflows.
- Added resume versioning, extraction, preview, analysis, AI review, and job
  matching.
- Added company research, application intelligence, cover letters, interview
  coaching, and saved interview preparation.

### Accounts and interface

- Added email verification, Google OAuth, optional TOTP two-factor
  authentication, recovery codes, security settings, and account deletion.
- Added the public landing experience, authenticated navigation, Resumes menu,
  responsive sidebars, and consistent light and dark themes.
- Improved contrast, tab selection, pagination controls, queue checkboxes, and
  admin discovery usability.

### Maintenance

- Added a live duplicate-aware Flask route catalog in `routes.py`.
- Removed an obsolete duplicate application-detail route registration.
- Updated the dependency lock and deployment migration sequence.
- Added Python and JavaScript regression coverage for routes, source adapters,
  browser resolvers, hosted ATS forms, and employer-site wrapper detection.

## v1.1

- Improved the dashboard, sidebar navigation, and application analytics.

## v1.0

- Added the initial application tracker, resume management, AI assistance,
  company lookup, and job URL import workflows.
