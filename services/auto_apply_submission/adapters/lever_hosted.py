import re

from services.auto_apply_submission.adapters.base import SubmissionAdapter
from services.auto_apply_submission.browsers.factory import (
    create_browser_session,
)
from services.auto_apply_submission.human_verification import (
    wait_for_user_condition,
)
from services.auto_apply_submission.application_answer_service import (
    get_application_answer,
)
from services.auto_apply_submission.application_question_service import (
    build_question_key,
)


class LeverHostedAdapter(SubmissionAdapter):
    adapter_name = "lever_hosted"

    CAPTCHA_SELECTOR = (
        'iframe[src*="recaptcha"], '
        'iframe[src*="hcaptcha"], '
        'iframe[src*="challenges.cloudflare.com"], '
        '[class*="captcha"], '
        '[id*="captcha"]'
    )

    CAPTCHA_RESPONSE_SELECTOR = (
        'textarea[name="g-recaptcha-response"], '
        'input#hcaptchaResponseInput, '
        'input[name="h-captcha-response"], '
        'textarea[name="h-captcha-response"], '
        'input[name="cf-turnstile-response"], '
        'textarea[name="cf-turnstile-response"]'
    )

    SIGN_IN_PHRASES = (
        "sign in to apply",
        "log in to apply",
        "login to apply",
        "create an account to apply",
        "create account to apply",
        "sign in or create an account",
    )

    def _captcha_requires_action(
        self,
        page,
    ):
        try:
            responses = page.locator(
                self.CAPTCHA_RESPONSE_SELECTOR
            )

            for index in range(
                responses.count()
            ):
                item = responses.nth(
                    index
                )

                try:
                    value = (
                        item.input_value()
                        or ""
                    ).strip()
                except Exception:
                    try:
                        value = (
                            item.get_attribute(
                                "value"
                            )
                            or ""
                        ).strip()
                    except Exception:
                        value = ""

                if value:
                    return False

            return (
                page.locator(
                    self.CAPTCHA_SELECTOR
                ).count()
                > 0
            )

        except Exception:
            return False

    def _sign_in_requires_action(
        self,
        page,
    ):
        try:
            body_text = (
                page.locator(
                    "body"
                )
                .inner_text()
                .lower()
            )
        except Exception:
            return False

        return any(
            phrase in body_text
            for phrase in self.SIGN_IN_PHRASES
        )

    def _lever_hcaptcha_present(
        self,
        page,
    ):
        try:
            return (
                page.locator("#h-captcha").count() > 0
                and page.locator(
                    "#hcaptchaResponseInput"
                ).count() > 0
                and page.locator(
                    "#btn-submit"
                ).count() > 0
            )
        except Exception:
            return False

    def _lever_hcaptcha_requires_action(
        self,
        page,
    ):
        # Do not treat a CAPTCHA token as completion.
        # Lever may populate a response before the actual
        # application has been accepted.
        #
        # The handoff is complete only when Lever shows an
        # explicit successful-application result.
        try:
            body_text = (
                page.locator(
                    "body"
                )
                .inner_text()
                .lower()
            )
        except Exception:
            return True

        success_phrases = (
            "thank you for applying",
            "application submitted",
            "application has been submitted",
            "thanks for applying",
        )

        if any(
            phrase in body_text
            for phrase in success_phrases
        ):
            return False

        # Verification errors intentionally remain True.
        # This keeps the visible browser open so the user
        # can retry Submit/verification in the same handoff
        # instead of Jobfinitum closing the tab immediately.
        return True

    def _handle_verification(
        self,
        page,
        browser_session,
        resume_mode,
    ):
        if not self._captcha_requires_action(
            page
        ):
            return None

        if (
            not resume_mode
            or not getattr(
                browser_session,
                "human_handoff_available",
                False,
            )
        ):
            return {
                "status": "Waiting for Verification",
                "message": (
                    "Application is waiting for "
                    "human verification."
                ),
                "detail": {
                    "url": page.url,
                    "handoff_type": "verification",
                },
            }

        result = wait_for_user_condition(
            page,
            self._captcha_requires_action,
            label=(
                "complete the application "
                "verification challenge"
            ),
        )

        if result.get(
            "cleared"
        ):
            return None

        return {
            "status": "Waiting for Verification",
            "message": (
                "Verification is still required. "
                "Resume again when ready."
            ),
            "detail": {
                "url": page.url,
                "handoff_type": "verification",
                **result,
            },
        }

    def _handle_sign_in(
        self,
        page,
        browser_session,
        resume_mode,
    ):
        if not self._sign_in_requires_action(
            page
        ):
            return None

        if (
            not resume_mode
            or not getattr(
                browser_session,
                "human_handoff_available",
                False,
            )
        ):
            return {
                "status": "Waiting for Sign-In",
                "message": (
                    "Application requires sign-in "
                    "or account setup."
                ),
                "detail": {
                    "url": page.url,
                    "handoff_type": "sign_in",
                },
            }

        result = wait_for_user_condition(
            page,
            self._sign_in_requires_action,
            label=(
                "sign in or create the employer "
                "application account"
            ),
        )

        if result.get(
            "cleared"
        ):
            return None

        return {
            "status": "Waiting for Sign-In",
            "message": (
                "Sign-in or account setup is still "
                "required. Resume again when ready."
            ),
            "detail": {
                "url": page.url,
                "handoff_type": "sign_in",
                **result,
            },
        }

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

    def _question_text_for_control(
        self,
        page,
        item,
    ):
        def clean(value):
            text = " ".join(
                str(
                    value or ""
                ).split()
            ).strip()

            if not text:
                return ""

            lowered = text.lower()

            if lowered in {
                "select",
                "select...",
                "choose",
                "choose...",
                "type your response",
            }:
                return ""

            if (
                "cards[" in text
                and "][field" in text
            ):
                return ""

            text = text.rstrip(
                " *"
            ).strip()

            if not text:
                return ""

            if len(text) > 350:
                return ""

            return text

        try:
            values = item.evaluate(
                "el => Array.from(el.labels || [])"
                ".map(label => label.innerText || '')"
            )

            for value in (
                values or []
            ):
                candidate = clean(
                    value
                )

                if candidate:
                    return candidate
        except Exception:
            pass

        try:
            labelled_by = (
                item.get_attribute(
                    "aria-labelledby"
                )
                or ""
            ).strip()

            if labelled_by:
                values = []

                for element_id in labelled_by.split():
                    node = page.locator(
                        f'#{element_id}'
                    )

                    if node.count():
                        values.append(
                            node.first
                            .inner_text()
                        )

                candidate = clean(
                    " ".join(
                        str(value or "")
                        for value in values
                    )
                )

                if candidate:
                    return candidate
        except Exception:
            pass

        try:
            candidates = item.evaluate(
                "el => {"
                " const results = [];"
                " const pushText = (node) => {"
                "   if (!node || node === el || !node.innerText) return;"
                "   const text = node.innerText.trim();"
                "   if (text) results.push(text);"
                " };"
                " let current = el;"
                " for (let depth = 0; current && depth < 7; depth += 1) {"
                "   let previous = current.previousElementSibling;"
                "   while (previous) {"
                "     const tag = previous.tagName"
                "       ? previous.tagName.toLowerCase() : '';"
                "     const cls = String(previous.className || '').toLowerCase();"
                "     if ("
                "       ['label','legend','p','h1','h2','h3','h4','h5','h6']"
                "         .includes(tag)"
                "       || cls.includes('label')"
                "       || cls.includes('prompt')"
                "       || cls.includes('question')"
                "       || cls.includes('title')"
                "     ) {"
                "       pushText(previous);"
                "     }"
                "     previous = previous.previousElementSibling;"
                "   }"
                "   const parent = current.parentElement;"
                "   if (!parent) break;"
                "   const selectors = ["
                "     'label',"
                "     'legend',"
                "     '[class*=label]',"
                "     '[class*=prompt]',"
                "     '[class*=question-title]',"
                "     '[class*=question-label]',"
                "     'h1','h2','h3','h4','h5','h6','p'"
                "   ];"
                "   for (const selector of selectors) {"
                "     const nodes = parent.querySelectorAll(selector);"
                "     for (const node of nodes) {"
                "       if (node === el || node.contains(el)) continue;"
                "       pushText(node);"
                "     }"
                "   }"
                "   current = parent;"
                " }"
                " return results;"
                "}"
            )

            for value in (
                candidates or []
            ):
                candidate = clean(
                    value
                )

                if candidate:
                    return candidate
        except Exception:
            pass

        try:
            candidates = item.evaluate(
                "el => {"
                " const results = [];"
                " let current = el;"
                " for (let depth = 0; current && depth < 7; depth += 1) {"
                "   const parent = current.parentElement;"
                "   if (!parent) break;"
                "   for (const child of parent.childNodes) {"
                "     if (child === current) break;"
                "     if (child.nodeType === Node.TEXT_NODE) {"
                "       const text = (child.textContent || '').trim();"
                "       if (text) results.push(text);"
                "       continue;"
                "     }"
                "     if (child.nodeType === Node.ELEMENT_NODE) {"
                "       const node = child;"
                "       if (node.contains(current)) continue;"
                "       if (['SELECT','OPTION'].includes(node.tagName)) continue;"
                "       const text = (node.innerText || '').trim();"
                "       if (text) results.push(text);"
                "     }"
                "   }"
                "   current = parent;"
                " }"
                " return results;"
                "}"
            )

            for value in (
                candidates or []
            ):
                candidate = clean(
                    value
                )

                if candidate:
                    return candidate
        except Exception:
            pass

        for attribute in (
            "aria-label",
            "title",
        ):
            try:
                candidate = clean(
                    item.get_attribute(
                        attribute
                    )
                )

                if candidate:
                    return candidate
            except Exception:
                pass

        return "Application question"

    def _choose_yes_no_option(
        self,
        page,
        item,
        value,
    ):
        wanted = str(
            value
        ).strip().lower()

        try:
            tag_name = (
                item.evaluate(
                    "el => el.tagName.toLowerCase()"
                )
                or ""
            ).lower()
        except Exception:
            tag_name = ""

        try:
            input_type = (
                item.get_attribute(
                    "type"
                )
                or ""
            ).lower()
        except Exception:
            input_type = ""

        if tag_name == "select":
            try:
                options = item.locator(
                    "option"
                )

                for index in range(
                    options.count()
                ):
                    option = options.nth(
                        index
                    )

                    label = (
                        option.inner_text()
                        or ""
                    ).strip()

                    if label.lower() == wanted:
                        option_value = (
                            option.get_attribute(
                                "value"
                            )
                        )

                        item.select_option(
                            value=option_value
                        )

                        return True
            except Exception:
                return False

        if input_type == "radio":
            try:
                group_name = (
                    item.get_attribute(
                        "name"
                    )
                    or ""
                )
            except Exception:
                group_name = ""

            if not group_name:
                return False

            try:
                radios = page.locator(
                    'input[type="radio"]'
                )

                for index in range(
                    radios.count()
                ):
                    radio = radios.nth(
                        index
                    )

                    if (
                        radio.get_attribute(
                            "name"
                        )
                        != group_name
                    ):
                        continue

                    radio_id = (
                        radio.get_attribute(
                            "id"
                        )
                        or ""
                    )

                    label_text = ""

                    if radio_id:
                        label = page.locator(
                            f'label[for="{radio_id}"]'
                        )

                        if label.count():
                            label_text = (
                                label.first
                                .inner_text()
                                .strip()
                            )

                    radio_value = (
                        radio.get_attribute(
                            "value"
                        )
                        or ""
                    )

                    haystack = (
                        f"{label_text} "
                        f"{radio_value}"
                    ).strip().lower()

                    if wanted in haystack:
                        radio.check()
                        return True
            except Exception:
                return False

        return False

    def _apply_answer_to_control(
        self,
        page,
        item,
        answer,
    ):
        value = str(
            answer["value"]
        )

        try:
            tag_name = (
                item.evaluate(
                    "el => el.tagName.toLowerCase()"
                )
                or ""
            ).lower()
        except Exception:
            tag_name = ""

        try:
            input_type = (
                item.get_attribute(
                    "type"
                )
                or ""
            ).lower()
        except Exception:
            input_type = ""

        if answer["type"] == "yes_no":
            return self._choose_yes_no_option(
                page,
                item,
                value,
            )

        if tag_name == "select":
            try:
                item.select_option(
                    label=value
                )
                return True
            except Exception:
                try:
                    item.select_option(
                        value=value
                    )
                    return True
                except Exception:
                    return False

        if input_type in {
            "radio",
            "checkbox",
            "file",
            "hidden",
            "submit",
            "button",
        }:
            return False

        try:
            item.fill(
                value
            )
            return True
        except Exception:
            return False

    def _field_name(self, item):
        for attribute in ("name", "id"):
            try:
                value = (item.get_attribute(attribute) or "").strip()
            except Exception:
                value = ""

            if value:
                return value

        return ""

    def _question_type(self, item):
        try:
            tag_name = (
                item.evaluate("el => el.tagName.toLowerCase()")
                or ""
            ).lower()
        except Exception:
            tag_name = ""

        try:
            input_type = (item.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""

        if tag_name == "select":
            return "select"

        if tag_name == "textarea":
            return "textarea"

        if input_type in {
            "radio",
            "checkbox",
            "date",
            "number",
            "email",
            "url",
            "tel",
        }:
            return input_type

        return "text"

    def _question_choices(self, page, item, question_type):
        choices = []

        if question_type == "select":
            try:
                options = item.locator("option")

                for index in range(options.count()):
                    option = options.nth(index)
                    value = (option.get_attribute("value") or "").strip()
                    label = (option.inner_text() or "").strip()

                    if not value and not label:
                        continue

                    if label.lower() in {
                        "select",
                        "select...",
                        "choose",
                        "choose...",
                    }:
                        continue

                    choices.append(
                        {
                            "value": value or label,
                            "label": label or value,
                        }
                    )
            except Exception:
                pass

            return choices

        if question_type in {"radio", "checkbox"}:
            field_name = self._field_name(item)

            if not field_name:
                return choices

            try:
                controls = page.locator(
                    f'input[type="{question_type}"]'
                )

                for index in range(controls.count()):
                    control = controls.nth(index)

                    if control.get_attribute("name") != field_name:
                        continue

                    value = (control.get_attribute("value") or "").strip()
                    control_id = (control.get_attribute("id") or "").strip()
                    label_text = ""

                    if control_id:
                        label = page.locator(
                            f'label[for="{control_id}"]'
                        )

                        if label.count():
                            label_text = label.first.inner_text().strip()

                    if not label_text:
                        try:
                            label_text = str(
                                control.evaluate(
                                    "el => (el.closest('label') || el.parentElement || el).innerText || ''"
                                )
                                or ""
                            ).strip()
                        except Exception:
                            label_text = ""

                    if not value and not label_text:
                        continue

                    choices.append(
                        {
                            "value": value or label_text,
                            "label": label_text or value,
                        }
                    )
            except Exception:
                pass

        return choices

    def _question_descriptor(
        self,
        page,
        item,
    ):
        field_name = self._field_name(
            item
        )

        question_type = self._question_type(
            item
        )

        text = ""

        if question_type in {
            "radio",
            "checkbox",
        }:
            try:
                text = item.evaluate(
                    "el => {"
                    " let current = el;"
                    " for (let depth = 0;"
                    "      current && depth < 7;"
                    "      depth += 1) {"
                    "   const parent = current.parentElement;"
                    "   if (!parent) break;"
                    "   const selectors = ["
                    "     'legend',"
                    "     ':scope > label',"
                    "     ':scope > .application-label',"
                    "     ':scope > .question-label',"
                    "     ':scope > .application-question-label',"
                    "     ':scope > [class*=prompt]',"
                    "     ':scope > [class*=title]',"
                    "     ':scope > h1',"
                    "     ':scope > h2',"
                    "     ':scope > h3',"
                    "     ':scope > h4',"
                    "     ':scope > h5',"
                    "     ':scope > h6'"
                    "   ];"
                    "   for (const selector of selectors) {"
                    "     let node = null;"
                    "     try {"
                    "       node = parent.querySelector(selector);"
                    "     } catch (error) {"
                    "       node = null;"
                    "     }"
                    "     if (!node || node.contains(el)) continue;"
                    "     const value ="
                    "       (node.innerText || '').trim();"
                    "     if (value) return value;"
                    "   }"
                    "   current = parent;"
                    " }"
                    " return '';"
                    "}"
                )
            except Exception:
                text = ""

            text = " ".join(
                str(
                    text or ""
                ).split()
            ).strip()

            if (
                not text
                or text.lower()
                in {
                    "select",
                    "select...",
                    "choose",
                    "choose...",
                }
                or (
                    "cards[" in text
                    and "][field" in text
                )
            ):
                text = ""

        if not text:
            text = (
                self._question_text_for_control(
                    page,
                    item,
                )
                or "Application question"
            )

        return {
            "key": build_question_key(
                self.adapter_name,
                field_name,
                text,
            ),
            "field_name": field_name,
            "text": text.rstrip(
                " *"
            ).strip(),
            "type": question_type,
            "required": True,
            "choices": self._question_choices(
                page,
                item,
                question_type,
            ),
            "adapter": self.adapter_name,
        }

    def _apply_saved_answer(self, page, item, descriptor, value):
        question_type = descriptor["type"]

        if question_type == "select":
            wanted = str(value).strip()

            try:
                options = item.locator("option")

                for index in range(options.count()):
                    option = options.nth(index)
                    option_value = (option.get_attribute("value") or "").strip()
                    label = (option.inner_text() or "").strip()

                    if wanted in {option_value, label}:
                        item.select_option(value=option_value)
                        return True
            except Exception:
                return False

            return False

        if question_type == "radio":
            field_name = self._field_name(item)
            wanted = str(value).strip()

            try:
                radios = page.locator('input[type="radio"]')

                for index in range(radios.count()):
                    radio = radios.nth(index)

                    if radio.get_attribute("name") != field_name:
                        continue

                    radio_value = (radio.get_attribute("value") or "").strip()
                    radio_id = (radio.get_attribute("id") or "").strip()
                    label_text = ""

                    if radio_id:
                        label = page.locator(
                            f'label[for="{radio_id}"]'
                        )

                        if label.count():
                            label_text = label.first.inner_text().strip()

                    if wanted in {radio_value, label_text}:
                        radio.check()
                        return True
            except Exception:
                return False

            return False

        if question_type == "checkbox":
            field_name = self._field_name(item)
            wanted_values = value if isinstance(value, list) else [value]
            wanted_values = {
                str(item_value).strip()
                for item_value in wanted_values
                if str(item_value).strip()
            }
            matched = False

            try:
                boxes = page.locator('input[type="checkbox"]')

                for index in range(boxes.count()):
                    box = boxes.nth(index)

                    if box.get_attribute("name") != field_name:
                        continue

                    box_value = (box.get_attribute("value") or "").strip()
                    box_id = (box.get_attribute("id") or "").strip()
                    label_text = ""

                    if box_id:
                        label = page.locator(
                            f'label[for="{box_id}"]'
                        )

                        if label.count():
                            label_text = label.first.inner_text().strip()

                    should_check = bool(
                        {box_value, label_text} & wanted_values
                    )
                    box.set_checked(should_check)
                    matched = matched or should_check
            except Exception:
                return False

            return matched

        try:
            item.fill(str(value))
            return True
        except Exception:
            return False

    def _apply_saved_application_answers(self, page, application_answers):
        applied = []

        if not isinstance(application_answers, dict):
            return applied

        try:
            controls = page.locator(
                "input:required, "
                "textarea:required, "
                "select:required"
            )
            seen = set()

            for index in range(controls.count()):
                item = controls.nth(index)

                try:
                    if not item.is_visible():
                        continue
                except Exception:
                    continue

                descriptor = self._question_descriptor(page, item)
                key = descriptor["key"]

                if key in seen:
                    continue

                seen.add(key)

                if key not in application_answers:
                    continue

                if self._apply_saved_answer(
                    page,
                    item,
                    descriptor,
                    application_answers[key],
                ):
                    applied.append(key)

        except Exception:
            pass

        return applied

    def _extract_required_questions(self, page):
        questions = {}

        try:
            invalid = page.locator(
                "input:invalid, "
                "textarea:invalid, "
                "select:invalid"
            )

            for index in range(invalid.count()):
                item = invalid.nth(index)

                try:
                    if not item.is_visible():
                        continue
                except Exception:
                    continue

                kind = (item.get_attribute("type") or "").lower()

                if kind in {
                    "hidden",
                    "submit",
                    "button",
                    "file",
                }:
                    continue

                descriptor = self._question_descriptor(page, item)
                field_name = self._field_name(item).strip().lower()

                if field_name in {
                    "name",
                    "email",
                    "phone",
                    "resume",
                }:
                    continue

                questions[descriptor["key"]] = descriptor

        except Exception:
            pass

        return list(questions.values())

    def _answer_known_required_fields(
        self,
        page,
        identity,
    ):
        answered = []

        try:
            controls = page.locator(
                "input:required, "
                "textarea:required, "
                "select:required"
            )

            for index in range(
                controls.count()
            ):
                item = controls.nth(
                    index
                )

                try:
                    if not item.is_visible():
                        continue
                except Exception:
                    continue

                question_text = (
                    self._question_text_for_control(
                        page,
                        item,
                    )
                )

                answer = get_application_answer(
                    identity,
                    question_text,
                )

                if not answer:
                    continue

                if self._apply_answer_to_control(
                    page,
                    item,
                    answer,
                ):
                    answered.append(
                        {
                            "key": answer["key"],
                            "question": question_text,
                        }
                    )

        except Exception:
            pass

        return answered

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

    def submit(
        self,
        job,
        identity,
        application_email,
        resume_path,
        cover_letter_text=None,
        resume_mode=False,
        application_answers=None,
    ):
        target = job.apply_url or job.posting_url
        if not target:
            return {"status": "Failed", "message": "No application URL is available.", "detail": {}}

        with create_browser_session(
            default_timeout_ms=15000,
        ) as browser_session:
            page = browser_session.page

            try:
                page.goto(target, wait_until="domcontentloaded", timeout=30000)

                sign_in_result = (
                    self._handle_sign_in(
                        page,
                        browser_session,
                        resume_mode,
                    )
                )

                if sign_in_result:
                    return sign_in_result

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

                saved_application_answers = (
                    self._apply_saved_application_answers(
                        page,
                        application_answers,
                    )
                )

                auto_answered = (
                    self._answer_known_required_fields(
                        page,
                        identity,
                    )
                )

                unresolved = [
                    x
                    for x in self._invalid_fields(
                        page
                    )
                    if str(
                        x
                    ).strip().lower()
                    not in {
                        "name",
                        "email",
                        "phone",
                        "resume",
                    }
                ]

                if unresolved:
                    questions = self._extract_required_questions(
                        page
                    )

                    return {
                        "status": "Needs Application Answer",
                        "message": (
                            "Lever requires additional "
                            "application answers before "
                            "submission."
                        ),
                        "detail": {
                            "required_fields": unresolved,
                            "questions": questions,
                            "auto_answered": auto_answered,
                            "saved_application_answers": (
                                saved_application_answers
                            ),
                            "url": page.url,
                            "handoff_type": "application_answer",
                        },
                    }

                submit_controls = page.locator(
                    'button#btn-submit, '
                    'button[data-qa="btn-submit"], '
                    'button.template-btn-submit, '
                    'button[type="submit"], '
                    'input[type="submit"]'
                )

                submit = None

                for index in range(
                    submit_controls.count()
                ):
                    candidate_submit = (
                        submit_controls.nth(
                            index
                        )
                    )

                    try:
                        if not candidate_submit.is_visible():
                            continue

                        if not candidate_submit.is_enabled():
                            continue
                    except Exception:
                        continue

                    metadata = " ".join(
                        [
                            (
                                candidate_submit.get_attribute(
                                    "id"
                                )
                                or ""
                            ),
                            (
                                candidate_submit.get_attribute(
                                    "name"
                                )
                                or ""
                            ),
                            (
                                candidate_submit.get_attribute(
                                    "class"
                                )
                                or ""
                            ),
                            (
                                candidate_submit.get_attribute(
                                    "value"
                                )
                                or ""
                            ),
                            (
                                candidate_submit.inner_text()
                                or ""
                            ),
                        ]
                    ).lower()

                    if (
                        "hcaptcha" in metadata
                        or "recaptcha" in metadata
                        or "captcha" in metadata
                    ):
                        continue

                    submit = candidate_submit
                    break

                if submit is None:
                    return {
                        "status": "Needs User Action",
                        "message": (
                            "Jobfinitum could not find a visible "
                            "Lever application submit button."
                        ),
                        "detail": {
                            "url": page.url,
                        },
                    }

                lever_hcaptcha = (
                    self._lever_hcaptcha_present(
                        page
                    )
                )

                if lever_hcaptcha:
                    if not resume_mode:
                        return {
                            "status": "Waiting for Verification",
                            "message": (
                                "Application is waiting for "
                                "human verification."
                            ),
                            "detail": {
                                "url": page.url,
                                "handoff_type": "verification",
                            },
                        }

                    # Leave the final Lever interaction to
                    # the human. Lever may start hCaptcha when
                    # the location field is focused, or when the
                    # real Submit Application button is clicked.
                    #
                    # Jobfinitum has already filled the form.
                    # The user completes any visible challenge
                    # and clicks Submit Application as needed.
                    # We wait for Lever's actual success state,
                    # not merely for a CAPTCHA response token.
                    handoff_result = (
                        wait_for_user_condition(
                            page,
                            self._lever_hcaptcha_requires_action,
                            label=(
                                "click Submit Application, "
                                "complete Lever verification, "
                                "and wait for confirmation"
                            ),
                        )
                    )

                    if not handoff_result.get("cleared"):
                        return {
                            "status": "Waiting for Verification",
                            "message": (
                                "Lever verification is still "
                                "required. Resume again when ready."
                            ),
                            "detail": {
                                "url": page.url,
                                "handoff_type": "verification",
                                **handoff_result,
                            },
                        }

                else:
                    verification_result = (
                        self._handle_verification(
                            page,
                            browser_session,
                            resume_mode,
                        )
                    )

                    if verification_result:
                        return verification_result

                    submit.click()
                try:
                    page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=15000,
                    )
                except Exception:
                    pass

                if not lever_hcaptcha:
                    verification_result = (
                        self._handle_verification(
                            page,
                            browser_session,
                            resume_mode,
                        )
                    )

                    if verification_result:
                        return verification_result

                sign_in_result = (
                    self._handle_sign_in(
                        page,
                        browser_session,
                        resume_mode,
                    )
                )

                if sign_in_result:
                    return sign_in_result

                body_text = (
                    page.locator(
                        "body"
                    )
                    .inner_text()
                    .lower()
                )

                verification_error_phrases = (
                    "error verifying your application",
                    "verification failed",
                    "please verify your application",
                    "please complete the captcha",
                    "please complete the verification",
                )

                if any(
                    phrase in body_text
                    for phrase in verification_error_phrases
                ):
                    return {
                        "status": "Waiting for Verification",
                        "message": (
                            "Lever did not accept the current "
                            "human verification. Resume the "
                            "application and complete the "
                            "verification challenge again."
                        ),
                        "detail": {
                            "url": page.url,
                            "handoff_type": "verification",
                            "verification_error": True,
                        },
                    }

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
