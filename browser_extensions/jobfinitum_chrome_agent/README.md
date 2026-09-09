# Jobfinitum Chrome Agent

Runs supported Jobfinitum Auto Apply tasks inside ordinary user Chrome.

Current Browser Agent support:
- Lever
- Greenhouse
- Ashby
- Remote First Jobs employer-site resolver
- Himalayas employer-site resolver
- Japan Dev employer-site resolver
- We Work Remotely employer-site resolver with sign-in pause support
- Jooble employer-site redirect resolver
- Remote OK employer-site redirect resolver
- Jobicy guest-application redirect resolver
- TokyoDev employer-application redirect resolver
- Adzuna employer-application redirect resolver
- The Muse employer-application data resolver

The Agent can:
- fill identity fields
- upload the selected resume
- fill LinkedIn / GitHub / website fields when present
- use reusable Applicant Profile answers
- use saved employer-specific answers
- return unknown required questions to Jobfinitum
- click the final application submit control
- report submission state back to Jobfinitum
- leave genuine CAPTCHA / verification for the user instead of bypassing it

## Development install

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `browser_extensions/jobfinitum_chrome_agent`

Jobfinitum detects the Browser Agent automatically. Users do not choose an
executor manually; the Jobfinitum backend routes supported ATS hosts into the
Browser Agent framework.


## Greenhouse schema

Greenhouse question types and option lists come from Greenhouse's public Job Board API.
The Browser Agent uses the official schema to preserve select and multi-select fields
instead of guessing their shape from rendered React controls.
