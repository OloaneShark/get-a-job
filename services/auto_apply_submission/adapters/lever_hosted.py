import os
import re

from playwright.sync_api import sync_playwright

from services.auto_apply_submission.adapters.base import SubmissionAdapter


class LeverHostedAdapter(SubmissionAdapter):
    adapter_name = "lever_hosted"

    def _fill_first(self, page, selectors, value):
        if not value:
            return False
        for selector in selectors:
            locator = page.locator(selector)
            for index in range(locator.count()):
                item = locator.nth(index)
                try:
                    if item.is_visible():
                        item.fill(value)
                        return True
                except Exception:
                    continue
        return False

    def _fill_label(self, page, pattern, value):
        if not value:
            return False
        try:
            locator = page.get_by_label(re.compile(pattern, re.I))
            if locator.count() and locator.first.is_visible():
                locator.first.fill(value)
                return True
        except Exception:
            pass
        return False

    def _invalid_fields(self, page):
        result = []
        try:
            invalid = page.locator("input:invalid, textarea:invalid, select:invalid")
            for index in range(invalid.count()):
                item = invalid.nth(index)
                if not item.is_visible():
                    continue
                kind = (item.get_attribute("type") or "").lower()
                if kind in {"hidden", "submit", "button"}:
                    continue
                result.append(
                    item.get_attribute("aria-label")
                    or item.get_attribute("name")
                    or item.get_attribute("placeholder")
                    or item.get_attribute("id")
                    or "Required field"
                )
        except Exception:
            pass
        return sorted(set(result))

    def submit(self, job, identity, application_email, resume_path, cover_letter_text=None):
        target = job.apply_url or job.posting_url
        if not target:
            return {"status": "Failed", "message": "No application URL is available.", "detail": {}}

        headless = str(os.getenv("AUTO_APPLY_BROWSER_HEADLESS", "true")).strip().lower() in {"1", "true", "yes", "on"}

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(15000)

            try:
                page.goto(target, wait_until="domcontentloaded", timeout=30000)

                if page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], [class*="captcha"], [id*="captcha"]').count():
                    return {"status": "Needs User Action", "message": "Lever application requires CAPTCHA completion.", "detail": {"url": page.url}}

                body_text = page.locator("body").inner_text().lower()
                if "sign in to apply" in body_text or "create an account to apply" in body_text:
                    return {"status": "Needs User Action", "message": "Lever application requires account setup or sign-in.", "detail": {"url": page.url}}

                full_name = f"{identity.first_name} {identity.last_name}".strip()
                self._fill_first(page, ('input[name="name"]', 'input[autocomplete="name"]'), full_name)
                self._fill_first(page, ('input[name="email"]', 'input[type="email"]'), application_email)
                self._fill_first(page, ('input[name="phone"]', 'input[type="tel"]'), identity.phone)
                self._fill_label(page, "linkedin", identity.linkedin_url)
                self._fill_label(page, "github", identity.github_url)
                self._fill_label(page, "website|portfolio", identity.website_url)

                files = page.locator('input[type="file"]')
                uploaded = False
                for index in range(files.count()):
                    item = files.nth(index)
                    name = ((item.get_attribute("name") or "") + " " + (item.get_attribute("id") or "")).lower()
                    if "resume" in name or files.count() == 1:
                        try:
                            item.set_input_files(resume_path)
                            uploaded = True
                            break
                        except Exception:
                            continue

                if not uploaded:
                    return {"status": "Needs User Action", "message": "Jobfinitum could not locate the Lever resume upload field.", "detail": {"url": page.url}}

                unresolved = [x for x in self._invalid_fields(page) if str(x).strip().lower() not in {"name", "email", "phone", "resume"}]
                if unresolved:
                    return {
                        "status": "Needs User Action",
                        "message": "Lever requires additional application answers before submission.",
                        "detail": {"required_fields": unresolved, "url": page.url},
                    }

                submit = page.locator('button[type="submit"], input[type="submit"]')
                if submit.count() < 1:
                    return {"status": "Needs User Action", "message": "Jobfinitum could not find the Lever submission button.", "detail": {"url": page.url}}

                submit.first.click()
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass

                body_text = page.locator("body").inner_text().lower()
                if any(p in body_text for p in ("thank you for applying", "application submitted", "application has been submitted", "thanks for applying")):
                    return {
                        "status": "Submitted",
                        "message": "Lever application submitted successfully.",
                        "detail": {"url": page.url},
                        "confirmation_url": page.url,
                    }

                invalid = self._invalid_fields(page)
                error_text = ""
                try:
                    errors = page.locator(".error, .errors, [role='alert']")
                    if errors.count():
                        error_text = errors.first.inner_text().strip()
                except Exception:
                    pass

                if invalid or error_text:
                    return {
                        "status": "Needs User Action",
                        "message": "Lever requires additional information before submission.",
                        "detail": {"required_fields": invalid, "error": error_text, "url": page.url},
                    }

                return {"status": "Needs User Action", "message": "Lever did not return a recognizable confirmation. Review manually.", "detail": {"url": page.url}}

            except Exception as error:
                return {"status": "Failed", "message": f"Lever browser submission failed: {type(error).__name__}: {error}", "detail": {"url": page.url}}
            finally:
                context.close()
                browser.close()
