# Jobfinitum Chrome Agent

Runs supported Jobfinitum Auto Apply tasks inside ordinary user Chrome.

V1 supports Lever and automates:
- identity fields
- resume upload
- LinkedIn / GitHub / website
- reusable Applicant Profile answers
- saved employer-specific answers
- final Submit Application click
- status reporting back to Jobfinitum

If Lever genuinely displays human verification, the agent leaves the tab open,
reports Verification Required, and keeps watching for a successful submission.

## One-time install

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `browser_extensions/jobfinitum_chrome_agent`

Then use **Run Chrome Agent** from Jobfinitum's Auto Apply Queue.
