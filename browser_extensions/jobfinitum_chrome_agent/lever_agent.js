(() => {
  "use strict";

  const SUCCESS_PHRASES = [
    "thank you for applying",
    "application submitted",
    "application has been submitted",
    "thanks for applying",
    "your application was already submitted",
    "application was already submitted",
  ];

  const VERIFY_PHRASES = [
    "error verifying your application",
    "verification failed",
    "please verify your application",
    "please complete the captcha",
    "please complete the verification",
  ];

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const lower = (value) => normalize(value).toLowerCase();

  function statusBox(message, kind = "working") {
    let box = document.getElementById("jobfinitum-agent-status");
    if (!box) {
      box = document.createElement("div");
      box.id = "jobfinitum-agent-status";
      Object.assign(box.style, {
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: "2147483647",
        maxWidth: "390px",
        padding: "12px 14px",
        borderRadius: "10px",
        font: "14px/1.35 system-ui, sans-serif",
        boxShadow: "0 8px 28px rgba(0,0,0,.28)",
        border: "1px solid rgba(255,255,255,.25)",
      });
      document.documentElement.appendChild(box);
    }

    const colors = {
      working: ["#172554", "#dbeafe"],
      success: ["#052e16", "#dcfce7"],
      warning: ["#422006", "#fef3c7"],
      error: ["#450a0a", "#fee2e2"],
    };
    const selected = colors[kind] || colors.working;
    box.style.background = selected[0];
    box.style.color = selected[1];
    box.textContent = `Jobfinitum Chrome Agent — ${message}`;
  }

  function send(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, (response) => {
        const runtimeError = chrome.runtime.lastError;
        if (runtimeError) {
          reject(new Error(runtimeError.message));
          return;
        }
        if (!response || !response.ok) {
          reject(new Error(response?.error || "Chrome Agent bridge failed."));
          return;
        }
        resolve(response);
      });
    });
  }

  const LAUNCH_STORAGE_KEY = "jobfinitum_chrome_agent_launch_v1";

  const BATCH_RUNNER_NAME = "jobfinitum-auto-apply-runner";

  function isBatchRunner() {
    if (window.name === BATCH_RUNNER_NAME) {
      return true;
    }

    try {
      const saved = JSON.parse(
        window.sessionStorage.getItem(
          LAUNCH_STORAGE_KEY
        ) || "null"
      );

      return saved?.batch === true;
    } catch (error) {
      return false;
    }
  }

  async function registerBatchRunner(launch) {
    if (!isBatchRunner()) return;

    await send({
      type: "jobfinitum-batch-register",
      origin: launch.origin,
    });
  }

  function clearLaunch() {
    try {
      window.sessionStorage.removeItem(
        LAUNCH_STORAGE_KEY
      );
    } catch (error) {
      // Cleanup failure must not break result reporting.
    }
  }

  function parseLaunch() {
    const params = new URLSearchParams(
      String(location.hash || "").replace(/^#/, "")
    );

    const token = params.get("jobfinitum_agent");
    const origin = params.get("jobfinitum_origin");
    const batch = (
      params.get("jobfinitum_batch")
      === "1"
      || isBatchRunner()
    );

    if (token && origin) {
      const launch = {
        token,
        origin,
        batch,
      };

      if (batch) {
        window.name = BATCH_RUNNER_NAME;
      }

      try {
        window.sessionStorage.setItem(
          LAUNCH_STORAGE_KEY,
          JSON.stringify(launch)
        );
      } catch (error) {
        console.warn(
          "Jobfinitum could not persist Chrome Agent launch state:",
          error
        );
      }

      history.replaceState(
        null,
        document.title,
        `${location.pathname}${location.search}`
      );

      return launch;
    }

    try {
      const saved = JSON.parse(
        window.sessionStorage.getItem(
          LAUNCH_STORAGE_KEY
        ) || "null"
      );

      if (saved && saved.token && saved.origin) {
        if (saved.batch === true) {
          window.name = BATCH_RUNNER_NAME;
        }

        return {
          token: String(saved.token),
          origin: String(saved.origin),
          batch: saved.batch === true,
        };
      }
    } catch (error) {
      console.warn(
        "Jobfinitum could not restore Chrome Agent launch state:",
        error
      );
    }

    return null;
  }

  function dispatchEvents(element) {
    for (const name of ["input", "change", "blur"]) {
      element.dispatchEvent(new Event(name, {bubbles: true}));
    }
  }

  function setText(element, value) {
    if (!element || value === null || value === undefined || String(value) === "") {
      return false;
    }

    const prototype = element.tagName === "TEXTAREA"
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");

    if (descriptor?.set) {
      descriptor.set.call(element, String(value));
    } else {
      element.value = String(value);
    }

    dispatchEvents(element);
    return true;
  }

  function fillFirst(selectors, value) {
    if (value === null || value === undefined || String(value) === "") {
      return false;
    }

    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!element.disabled && !element.readOnly && setText(element, value)) {
          return true;
        }
      }
    }
    return false;
  }

  function labelText(element) {
    if (element.labels?.length) {
      for (const label of element.labels) {
        const text = normalize(label.innerText).replace(/\s*\*+\s*$/, "");
        if (text) return text;
      }
    }

    const aria = normalize(element.getAttribute("aria-label"));
    if (aria) return aria.replace(/\s*\*+\s*$/, "");

    const labelledBy = normalize(element.getAttribute("aria-labelledby"));
    if (labelledBy) {
      const text = labelledBy
        .split(/\s+/)
        .map((id) => normalize(document.getElementById(id)?.innerText))
        .filter(Boolean)
        .join(" ");
      if (text) return text.replace(/\s*\*+\s*$/, "");
    }

    const groupType = lower(element.type);
    let current = element;

    for (let depth = 0; current && depth < 7; depth += 1) {
      const parent = current.parentElement;
      if (!parent) break;

      const selectors = (groupType === "radio" || groupType === "checkbox")
        ? [
            "legend",
            ":scope > .application-label",
            ":scope > .question-label",
            ":scope > .application-question-label",
            ":scope > [class*=prompt]",
            ":scope > [class*=title]",
            ":scope > h1",
            ":scope > h2",
            ":scope > h3",
            ":scope > h4",
          ]
        : [
            ":scope > label",
            "legend",
            ":scope > .application-label",
            ":scope > .question-label",
            ":scope > [class*=prompt]",
            ":scope > [class*=title]",
            ":scope > h1",
            ":scope > h2",
            ":scope > h3",
            ":scope > h4",
          ];

      for (const selector of selectors) {
        let node = null;
        try {
          node = parent.querySelector(selector);
        } catch (error) {
          node = null;
        }

        if (!node || node === element || node.contains(element)) continue;
        const text = normalize(node.innerText);
        if (text && text.length <= 350 && !text.includes("cards[")) {
          return text.replace(/\s*\*+\s*$/, "");
        }
      }
      current = parent;
    }

    return normalize(element.name || element.id || "Application question");
  }

  function fillByLabel(pattern, value) {
    if (!value) return false;

    for (const element of document.querySelectorAll("input, textarea")) {
      if (pattern.test(lower(labelText(element)))) {
        return setText(element, value);
      }
    }
    return false;
  }

  function fieldName(element) {
    return normalize(element.name || element.id);
  }

  function groupControls(element) {
    const type = lower(element.type);
    const name = String(element.name || "");
    if (!name || !["radio", "checkbox"].includes(type)) {
      return [element];
    }

    return [...document.querySelectorAll(`input[type="${type}"]`)]
      .filter((candidate) => String(candidate.name || "") === name);
  }

  function choiceLabel(element) {
    if (element.id) {
      const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (normalize(label?.innerText)) return normalize(label.innerText);
    }

    const closest = element.closest("label");
    return normalize(closest?.innerText || element.value);
  }

  function setChoice(element, value) {
    const type = lower(element.type);

    if (type === "radio") {
      const wanted = lower(value);
      for (const radio of groupControls(element)) {
        if ([lower(radio.value), lower(choiceLabel(radio))].includes(wanted)) {
          radio.checked = true;
          dispatchEvents(radio);
          return true;
        }
      }
      return false;
    }

    if (type === "checkbox") {
      const wanted = new Set(
        (Array.isArray(value) ? value : [value]).map((item) => lower(item))
      );
      let matched = false;

      for (const box of groupControls(element)) {
        const shouldCheck = wanted.has(lower(box.value))
          || wanted.has(lower(choiceLabel(box)));
        box.checked = shouldCheck;
        dispatchEvents(box);
        matched = matched || shouldCheck;
      }
      return matched;
    }

    return false;
  }

  function applyValue(element, value) {
    if (value === null || value === undefined || value === "") return false;

    if (element.tagName === "SELECT") {
      const wanted = lower(value);
      for (const option of element.options) {
        if (wanted === lower(option.value) || wanted === lower(option.textContent)) {
          element.value = option.value;
          dispatchEvents(element);
          return true;
        }
      }
      return false;
    }

    const type = lower(element.type);
    if (type === "radio" || type === "checkbox") {
      return setChoice(element, value);
    }
    if (["hidden", "file", "submit", "button"].includes(type)) {
      return false;
    }
    return setText(element, value);
  }

  function reusableAnswer(task, questionText) {
    const question = lower(questionText);
    const values = task.reusable_answers || {};

    const yesNoRules = [
      [["18 or older", "18 years of age or older", "at least 18", "over the age of 18"], values.is_18_or_older],
      [["authorized to work", "legally authorized to work", "eligible to work", "work authorization"], values.work_authorization_default],
      [["require sponsorship", "requires sponsorship", "need sponsorship", "visa sponsorship", "immigration sponsorship"], values.sponsorship_default],
      [["willing to relocate", "open to relocation", "able to relocate"], values.willing_to_relocate],
      [["willing to travel", "able to travel", "open to travel"], values.willing_to_travel],
    ];

    for (const [patterns, value] of yesNoRules) {
      const configured = lower(value);
      if (
        patterns.some((pattern) => question.includes(pattern))
        && ["yes", "no"].includes(configured)
      ) {
        return configured === "yes" ? "Yes" : "No";
      }
    }

    if (
      ["years of experience", "how many years", "years experience"]
        .some((pattern) => question.includes(pattern))
      && values.years_of_experience !== null
      && values.years_of_experience !== undefined
    ) {
      return String(values.years_of_experience);
    }

    if (
      ["salary expectation", "salary expectations", "desired salary", "expected salary",
       "compensation expectation", "compensation expectations", "desired compensation"]
        .some((pattern) => question.includes(pattern))
      && values.salary_expectation
    ) {
      return String(values.salary_expectation);
    }

    if (
      ["available to start", "availability to start", "start date", "earliest start", "earliest available"]
        .some((pattern) => question.includes(pattern))
      && values.available_start_date
    ) {
      return String(values.available_start_date);
    }

    return null;
  }

  function requiredControls() {
    const result = [];
    const seen = new Set();

    for (const element of document.querySelectorAll(
      "input:required, textarea:required, select:required"
    )) {
      const type = lower(element.type);
      const name = fieldName(element);
      const key = (type === "radio" || type === "checkbox")
        ? `${type}|${name}`
        : `${element.tagName}|${name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(element);
    }

    return result;
  }

  function findSavedControl(question) {
    if (question.field_name) {
      const exact = [...document.querySelectorAll("input, textarea, select")]
        .find((element) => fieldName(element) === question.field_name);
      if (exact) return exact;
    }

    const wanted = lower(question.text);
    if (!wanted) return null;

    let fuzzy = null;
    for (const element of requiredControls()) {
      const actual = lower(labelText(element));
      if (actual === wanted) return element;
      if (!fuzzy && actual && (actual.includes(wanted) || wanted.includes(actual))) {
        fuzzy = element;
      }
    }
    return fuzzy;
  }

  function questionType(element) {
    if (element.tagName === "SELECT") return "select";
    if (element.tagName === "TEXTAREA") return "textarea";

    const type = lower(element.type);
    return ["radio", "checkbox", "date", "number", "email", "url", "tel"].includes(type)
      ? type
      : "text";
  }

  function questionChoices(element) {
    const type = questionType(element);

    if (type === "select") {
      return [...element.options]
        .map((option) => ({
          value: normalize(option.value || option.textContent),
          label: normalize(option.textContent || option.value),
        }))
        .filter((choice) => choice.value && !["select", "select...", "choose", "choose..."].includes(lower(choice.label)));
    }

    if (type === "radio" || type === "checkbox") {
      return groupControls(element)
        .map((control) => ({
          value: normalize(control.value || choiceLabel(control)),
          label: normalize(choiceLabel(control) || control.value),
        }))
        .filter((choice) => choice.value || choice.label);
    }

    return [];
  }

  function descriptor(element) {
    return {
      field_name: fieldName(element),
      text: labelText(element),
      type: questionType(element),
      required: true,
      choices: questionChoices(element),
      adapter: "lever_hosted",
    };
  }

  function customQuestion(element, task) {
    const type = lower(element.type);
    if (["hidden", "submit", "button", "file"].includes(type)) return false;

    const name = lower(fieldName(element));
    if (["name", "email", "phone", "resume"].includes(name)) return false;

    return reusableAnswer(task, labelText(element)) === null;
  }

  async function fetchResume(launch, task) {
    const response = await send({
      type: "jobfinitum-resume",
      origin: launch.origin,
      url: task.resume.url,
    });

    const binary = atob(response.base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }

    return new File([bytes], task.resume.filename, {
      type: task.resume.content_type || response.contentType || "application/octet-stream",
    });
  }

  function setResumeFile(file) {
    const inputs = [...document.querySelectorAll('input[type="file"]')];
    const selected = inputs.find((input) => {
      const meta = lower(`${input.name || ""} ${input.id || ""} ${labelText(input)}`);
      return meta.includes("resume");
    }) || (inputs.length === 1 ? inputs[0] : null);

    if (!selected) return false;

    const transfer = new DataTransfer();
    transfer.items.add(file);
    selected.files = transfer.files;
    dispatchEvents(selected);
    return true;
  }

  async function report(launch, payload) {
    return send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload,
    });
  }

  async function closeCompletedAgentTab(
    launch
  ) {
    if (isBatchRunner()) return;

    try {
      await send({
        type: "jobfinitum-close-agent-tab",
        origin: launch.origin,
      });
    } catch (error) {
      console.warn(
        "Jobfinitum could not close the completed Agent tab:",
        error
      );
    }
  }

  async function handOffToManualApply(
    launch,
    message,
    detail = {}
  ) {
    statusBox(
      "this Lever page needs Manual Apply.",
      "warning"
    );

    await report(
      launch,
      {
        status: "unsupported",
        message,
        detail: {
          url: location.href,
          executor: "chrome_agent",
          manual_application: true,
          ...detail,
        },
      }
    );

    clearLaunch();
    await closeCompletedAgentTab(
      launch
    );
  }

  function leverApplyLink() {
    for (const link of document.querySelectorAll(
      'a[href*="/apply"]'
    )) {
      try {
        const target = new URL(
          link.href,
          location.href
        );

        if (
          target.hostname === location.hostname
          && /\/apply\/?$/.test(
            target.pathname
          )
        ) {
          return target.href;
        }
      } catch (error) {
        // Ignore malformed links and continue looking.
      }
    }

    return "";
  }

  async function run(launch, task) {
    const initialBody = lower(
      document.body?.innerText
    );

    if (
      SUCCESS_PHRASES.some(
        (phrase) => initialBody.includes(phrase)
      )
    ) {
      const alreadySubmitted = initialBody.includes(
        "already submitted"
      );

      statusBox(
        alreadySubmitted
          ? "Lever confirms this application was already submitted."
          : "application submitted.",
        "success"
      );

      await report(
        launch,
        {
          status: "submitted",
          message: (
            alreadySubmitted
              ? (
                  "Lever confirms this application "
                  + "was already submitted."
                )
              : (
                  "Chrome Agent submitted the "
                  + "Lever application successfully."
                )
          ),
          confirmation_url: location.href,
          detail: {
            url: location.href,
            executor: "chrome_agent",
            already_submitted: alreadySubmitted,
          },
        }
      );

      clearLaunch();
      await closeCompletedAgentTab(
        launch
      );
      return;
    }

    statusBox("filling Lever application…");
    if (
      !document.querySelector(
        'input[type="file"]'
      )
    ) {
      await sleep(1200);
    }

    if (
      !document.querySelector(
        'input[type="file"]'
      )
    ) {
      const applyUrl = leverApplyLink();

      if (applyUrl) {
        statusBox(
          "opening the Lever application form..."
        );
        location.assign(applyUrl);
        return;
      }

      await handOffToManualApply(
        launch,
        (
          "Lever did not expose a standard application "
          + "form Jobfinitum can automate."
        ),
        {
          reason: "missing_application_form",
        }
      );
      return;
    }

    const identity = task.identity || {};

    fillFirst(['input[name="name"]', 'input[autocomplete="name"]'], identity.full_name);
    fillFirst(['input[name="email"]', 'input[type="email"]'], identity.email);
    fillFirst(['input[name="phone"]', 'input[type="tel"]'], identity.phone);

    // Direct value setting avoids intentionally focusing Lever's location field.
    fillFirst(
      ['input[name="location"]', 'input[id*="location" i]', 'input[placeholder*="location" i]'],
      identity.location_text
    );

    fillByLabel(/linkedin/i, identity.linkedin_url);
    fillByLabel(/github/i, identity.github_url);
    fillByLabel(/website|portfolio/i, identity.website_url);

    statusBox("uploading resume…");
    const resume = await fetchResume(launch, task);
    if (!setResumeFile(resume)) {
      await handOffToManualApply(
        launch,
        (
          "Chrome Agent could not locate a supported "
          + "Lever resume upload field."
        ),
        {
          reason: "missing_resume_field",
        }
      );
      return;
    }

    statusBox("applying saved answers…");

    for (const question of task.application_questions || []) {
      if (question.answer === null || question.answer === undefined || question.answer === "") {
        continue;
      }
      const element = findSavedControl(question);
      if (element) {
        applyValue(element, question.answer);
      }
    }

    for (const element of requiredControls()) {
      const answer = reusableAnswer(task, labelText(element));
      if (answer !== null) {
        applyValue(element, answer);
      }
    }

    await sleep(600);

    const unresolved = [];

    for (const element of requiredControls()) {
      if (!customQuestion(element, task)) continue;

      const item = descriptor(element);

      if (!element.checkValidity()) {
        unresolved.push(item);
      }
    }

    if (unresolved.length) {
      statusBox("more application answers are required in Jobfinitum.", "warning");
      await report(launch, {
        status: "needs_application_answer",
        message: "Lever requires additional application answers before submission.",
        questions: unresolved,
        detail: {
          url: location.href,
          required_fields: unresolved.map((item) => item.text),
          executor: "chrome_agent",
        },
      });
      clearLaunch();
      await closeCompletedAgentTab(
        launch
      );
      return;
    }

    const stillInvalid = requiredControls().filter((element) => !element.checkValidity());

    if (stillInvalid.length) {
      statusBox("Lever still has required fields Jobfinitum could not fill.", "warning");
      await report(launch, {
        status: "needs_user_action",
        message: "Lever still has required fields that Jobfinitum could not fill.",
        detail: {
          url: location.href,
          required_fields: stillInvalid.map((element) => labelText(element)),
        },
      });
      clearLaunch();
      await closeCompletedAgentTab(
        launch
      );
      return;
    }

    const submit = document.querySelector("button#btn-submit")
      || document.querySelector('button[data-qa="btn-submit"]')
      || document.querySelector("button.template-btn-submit");

    if (!submit || submit.disabled) {
      await handOffToManualApply(
        launch,
        (
          "Chrome Agent could not find an enabled standard "
          + "Lever Submit Application button."
        ),
        {
          reason: "missing_submit_button",
        }
      );
      return;
    }

    statusBox("submitting application…");
    submit.click();

    const started = Date.now();
    let verificationReported = false;

    while (Date.now() - started < 30000) {
      await sleep(750);
      const body = lower(document.body?.innerText);

      if (SUCCESS_PHRASES.some((phrase) => body.includes(phrase))) {
        statusBox("application submitted.", "success");
        await report(launch, {
          status: "submitted",
          message: "Chrome Agent submitted the Lever application successfully.",
          confirmation_url: location.href,
          detail: {url: location.href, executor: "chrome_agent"},
        });
        clearLaunch();
        await closeCompletedAgentTab(
          launch
        );
        return;
      }

      const verificationError = VERIFY_PHRASES.some((phrase) => body.includes(phrase));
      const visibleCaptcha = [...document.querySelectorAll(
        'iframe[src*="hcaptcha"], iframe[src*="recaptcha"], iframe[src*="challenges.cloudflare.com"]'
      )].some((frame) => {
        const rect = frame.getBoundingClientRect();
        const style = getComputedStyle(frame);
        return style.display !== "none"
          && style.visibility !== "hidden"
          && rect.width > 20
          && rect.height > 20;
      });

      if ((verificationError || visibleCaptcha) && !verificationReported) {
        verificationReported = true;
        statusBox(
          "human verification is required; complete it here and the agent will keep watching.",
          "warning"
        );
        await report(launch, {
          status: "waiting_verification",
          message: "Lever requires human verification in normal Chrome. Complete it here; the Chrome Agent is still watching.",
          detail: {
            url: location.href,
            verification_error: verificationError,
            captcha_visible: visibleCaptcha,
            executor: "chrome_agent",
          },
        });
      }
    }

    if (verificationReported) {
      await report(launch, {
        status: "waiting_verification",
        message: "Lever verification is still waiting for completion.",
        detail: {url: location.href, executor: "chrome_agent"},
      });
      return;
    }

    await handOffToManualApply(
      launch,
      (
        "Lever did not return a recognizable submission "
        + "confirmation within 30 seconds. Review it from Manual Apply."
      ),
      {
        reason: "submission_confirmation_timeout",
      }
    );
  }

  async function main() {
    const launch = parseLaunch();
    if (!launch) return;

    try {
      statusBox("connecting to Jobfinitum…");
      await registerBatchRunner(launch);

      const response = await send({
        type: "jobfinitum-task",
        origin: launch.origin,
        token: launch.token,
      });
      const task = response.task;

      if (new URL(task.target_url).hostname !== location.hostname) {
        throw new Error("Application host does not match the Jobfinitum task.");
      }

      await run(launch, task);
    } catch (error) {
      console.error("Jobfinitum Chrome Agent failed:", error);
      statusBox(`failed: ${error.message || error}`, "error");

      try {
        await report(launch, {
          status: "failed",
          message: `Chrome Agent failed: ${error.message || error}`,
          detail: {url: location.href},
        });
        clearLaunch();
        await closeCompletedAgentTab(
          launch
        );
      } catch (reportError) {
        console.error("Jobfinitum failure report also failed:", reportError);
      }
    }
  }

  main();
})();
