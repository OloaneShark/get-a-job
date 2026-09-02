(() => {
  "use strict";

  const SUCCESS_PHRASES = [
    "thank you for applying",
    "thanks for applying",
    "application submitted",
    "application has been submitted",
    "application received",
    "we received your application",
    "we've received your application",
  ];

  const VERIFY_PHRASES = [
    "please complete the captcha",
    "please complete the verification",
    "verify you are human",
    "human verification",
  ];

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const lower = (value) => normalize(value).toLowerCase();
  const cleanQuestionText = (value) => normalize(value).replace(/\s*(?:\*+|\u2731+)\s*$/, "");
  const questionMatchKey = (value) => lower(cleanQuestionText(value)).replace(/[^a-z0-9]+/g, " ").trim();

  function visible(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0;
  }

  function statusBox(message, kind = "working") {
    let box = document.getElementById("jobfinitum-agent-status");
    if (!box) {
      const root = document.documentElement || document.body;
      if (!root) return;
      box = document.createElement("div");
      box.id = "jobfinitum-agent-status";
      Object.assign(box.style, {
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: "2147483647",
        maxWidth: "390px",
        padding: "12px 14px",
        borderRadius: "0",
        font: "14px/1.35 system-ui, sans-serif",
        boxShadow: "0 8px 28px rgba(0,0,0,.28)",
        border: "1px solid rgba(255,255,255,.25)",
      });
      root.appendChild(box);
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
    box.textContent = `Jobfinitum Chrome Agent - ${message}`;
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
    if (window.name === BATCH_RUNNER_NAME) return true;
    try {
      const saved = JSON.parse(window.sessionStorage.getItem(LAUNCH_STORAGE_KEY) || "null");
      return saved?.batch === true;
    } catch (error) {
      return false;
    }
  }

  async function registerBatchRunner(launch) {
    if (!isBatchRunner()) return;
    await send({type: "jobfinitum-batch-register", origin: launch.origin});
  }

  function clearLaunch() {
    try {
      window.sessionStorage.removeItem(LAUNCH_STORAGE_KEY);
    } catch (error) {
      // Cleanup failure must not break result reporting.
    }
  }

  async function restoreChainedLaunch() {
    try {
      const response = await send({type: "jobfinitum-restore-launch"});
      const restored = response?.launch;
      if (!restored?.token || !restored?.origin) return null;
      const launch = {
        token: String(restored.token),
        origin: String(restored.origin),
        batch: restored.batch === true,
      };
      if (launch.batch) window.name = BATCH_RUNNER_NAME;
      window.sessionStorage.setItem(LAUNCH_STORAGE_KEY, JSON.stringify(launch));
      return launch;
    } catch (error) {
      return null;
    }
  }

  function parseLaunch() {
    const params = new URLSearchParams(String(location.hash || "").replace(/^#/, ""));
    const token = params.get("jobfinitum_agent");
    const origin = params.get("jobfinitum_origin");
    const batch = params.get("jobfinitum_batch") === "1" || isBatchRunner();

    if (token && origin) {
      const launch = {token, origin, batch};
      if (batch) window.name = BATCH_RUNNER_NAME;
      try {
        window.sessionStorage.setItem(LAUNCH_STORAGE_KEY, JSON.stringify(launch));
      } catch (error) {
        console.warn("Jobfinitum could not persist Ashby launch state:", error);
      }
      try {
        history.replaceState(null, document.title, `${location.pathname}${location.search}`);
      } catch (error) {
        console.warn("Jobfinitum could not remove the launch fragment yet:", error);
      }
      return launch;
    }

    try {
      const saved = JSON.parse(window.sessionStorage.getItem(LAUNCH_STORAGE_KEY) || "null");
      if (saved?.token && saved?.origin) {
        if (saved.batch === true) window.name = BATCH_RUNNER_NAME;
        return {
          token: String(saved.token),
          origin: String(saved.origin),
          batch: saved.batch === true,
        };
      }
    } catch (error) {
      console.warn("Jobfinitum could not restore Ashby launch state:", error);
    }
    return null;
  }

  function dispatchEvents(element) {
    for (const name of ["input", "change", "blur"]) {
      element.dispatchEvent(new Event(name, {bubbles: true}));
    }
  }

  function setText(element, value) {
    if (!element || value === null || value === undefined || String(value) === "") return false;
    if (!["INPUT", "TEXTAREA"].includes(element.tagName)) return false;

    const prototype = element.tagName === "TEXTAREA"
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor?.set) descriptor.set.call(element, String(value));
    else element.value = String(value);
    dispatchEvents(element);
    return true;
  }

  function answerGroups(value) {
    const values = Array.isArray(value) ? value : [value];
    return values.map((item) => {
      if (item && typeof item === "object") {
        return [item.platform_value, item.value, item.label].map(normalize).filter(Boolean);
      }
      const normalized = normalize(item);
      return normalized ? [normalized] : [];
    }).filter((group) => group.length);
  }

  function answerText(value) {
    return answerGroups(value).map((group) => group[0]).filter(Boolean).join(", ");
  }

  function choiceLabel(element) {
    if (!element) return "";
    if (element.id) {
      try {
        const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
        if (normalize(label?.innerText)) return cleanQuestionText(label.innerText);
      } catch (error) {}
    }
    return cleanQuestionText(element.closest("label")?.innerText || element.value || element.textContent);
  }

  function labelText(element) {
    if (!element) return "Application question";

    if (element.labels?.length) {
      for (const label of element.labels) {
        const text = cleanQuestionText(label.innerText);
        if (text) return text;
      }
    }

    const aria = cleanQuestionText(element.getAttribute?.("aria-label"));
    if (aria) return aria;

    const labelledBy = normalize(element.getAttribute?.("aria-labelledby"));
    if (labelledBy) {
      const text = cleanQuestionText(
        labelledBy.split(/\s+/)
          .map((id) => normalize(document.getElementById(id)?.innerText))
          .filter(Boolean)
          .join(" ")
      );
      if (text) return text;
    }

    let current = element;
    for (let depth = 0; current && depth < 6; depth += 1) {
      const parent = current.parentElement;
      if (!parent) break;
      const selectors = [
        ":scope > label",
        ":scope > legend",
        ":scope > [class*=label]",
        ":scope > [class*=Label]",
        ":scope > [class*=question]",
        ":scope > [class*=Question]",
        ":scope > h1",
        ":scope > h2",
        ":scope > h3",
        ":scope > h4",
        ":scope > p",
      ];
      for (const selector of selectors) {
        let nodes = [];
        try { nodes = [...parent.querySelectorAll(selector)]; } catch (error) {}
        for (const node of nodes) {
          if (node === element || node.contains(element)) continue;
          const text = cleanQuestionText(node.innerText);
          if (text && text.length <= 350) return text;
        }
      }
      current = parent;
    }

    return cleanQuestionText(
      element.getAttribute?.("placeholder")
      || element.name
      || element.id
      || "Application question"
    );
  }

  function fieldName(element) {
    for (const name of ["name", "data-field-path", "data-path", "data-testid", "id"]) {
      const value = normalize(element.getAttribute?.(name));
      if (value) return value;
    }
    const key = questionMatchKey(labelText(element));
    return key ? `ashby:${key}` : "ashby:application-question";
  }

  function groupControls(element) {
    const type = lower(element?.type);
    const name = String(element?.name || "");
    if (!name || !["radio", "checkbox"].includes(type)) return [element];
    return [...document.querySelectorAll(`input[type="${type}"]`)]
      .filter((candidate) => String(candidate.name || "") === name);
  }

  function controlType(element) {
    const role = lower(element.getAttribute?.("role"));
    if (role === "combobox" || element.getAttribute?.("aria-haspopup") === "listbox") return "select";
    if (element.tagName === "SELECT") return element.multiple ? "multiselect" : "select";
    if (element.tagName === "TEXTAREA") return "textarea";
    const type = lower(element.type);
    return ["radio", "checkbox", "date", "number", "email", "url", "tel"].includes(type)
      ? type
      : "text";
  }

  function isRequiredControl(element) {
    if (element.required || lower(element.getAttribute?.("aria-required")) === "true") return true;
    let current = element.parentElement;
    for (let depth = 0; current && depth < 4; depth += 1) {
      if (current.querySelector?.('[aria-required="true"], [data-required="true"]')) return true;
      const labels = [...(current.querySelectorAll?.("label, legend, [class*=label], [class*=Label]") || [])];
      if (labels.some((node) => /\*\s*$|\brequired\b/i.test(normalize(node.innerText)))) return true;
      current = current.parentElement;
    }
    return false;
  }

  function allQuestionControls() {
    const selector = ["input", "textarea", "select", '[role="combobox"]', '[aria-haspopup="listbox"]'].join(",");
    const result = [];
    const seen = new Set();
    for (const element of document.querySelectorAll(selector)) {
      if (!visible(element) || element.disabled || element.readOnly) continue;
      const type = lower(element.type);
      const role = lower(element.getAttribute?.("role"));
      if (["hidden", "submit", "button", "file", "image", "reset"].includes(type) && role !== "combobox") continue;
      const groupType = lower(element.type);
      const key = ["radio", "checkbox"].includes(groupType)
        ? `${groupType}|${element.name || fieldName(element)}`
        : `${element.tagName}|${fieldName(element)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(element);
    }
    return result;
  }

  function requiredControls() {
    return allQuestionControls().filter(isRequiredControl);
  }

  function coreQuestion(element) {
    const text = lower(labelText(element));
    const name = lower(fieldName(element));
    const combined = `${text} ${name}`;
    return /(^|\b)(full )?name(\b|$)/.test(text)
      || /\bfirst name\b|\blast name\b/.test(combined)
      || /\be-?mail\b|\bphone\b|\bresume\b|\bcv\b/.test(combined)
      || /\blinkedin\b|\bgithub\b|\bwebsite\b|\bportfolio\b/.test(combined)
      || (/\blocation\b/.test(combined) && !/\brelocat/.test(combined))
      || ["city", "state", "state / province", "postal code", "zip code"].includes(text);
  }

  function controlHasAnyValue(element) {
    const type = lower(element.type);
    if (type === "radio" || type === "checkbox") return groupControls(element).some((item) => item.checked);
    if (element.tagName === "SELECT") {
      if (element.multiple) return [...element.selectedOptions].some((option) => normalize(option.value || option.textContent));
      return Boolean(normalize(element.value || element.options[element.selectedIndex]?.textContent));
    }
    if (lower(element.getAttribute?.("role")) === "combobox" || element.getAttribute?.("aria-haspopup") === "listbox") {
      const text = normalize(element.value || element.textContent);
      return Boolean(text && !/^(select|choose)(\.\.\.)?$/i.test(text));
    }
    return Boolean(normalize(element.value));
  }

  async function chooseCustomOption(element, value) {
    const groups = answerGroups(value);
    if (!groups.length) return false;
    const wanted = new Set(groups.flat().map(lower));

    if (element.tagName === "INPUT") {
      element.focus();
      setText(element, groups[0][0]);
      element.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
    } else {
      element.click();
    }

    const started = Date.now();
    while (Date.now() - started < 3500) {
      await sleep(150);
      const options = [...document.querySelectorAll('[role="option"], [data-radix-collection-item], [data-testid*=option], [data-testid*=Option]')]
        .filter(visible);
      let selected = options.find((option) => {
        const values = [lower(option.getAttribute?.("data-value")), lower(option.getAttribute?.("value")), lower(option.innerText)];
        return values.some((item) => item && wanted.has(item));
      });
      if (!selected) {
        selected = options.find((option) => {
          const text = lower(option.innerText);
          return text && [...wanted].some((candidate) => candidate && (text.includes(candidate) || candidate.includes(text)));
        });
      }
      if (selected) {
        selected.dispatchEvent(new MouseEvent("mousedown", {bubbles: true, cancelable: true, view: window}));
        selected.click();
        await sleep(100);
        dispatchEvents(element);
        return true;
      }
    }
    return false;
  }

  async function applyValue(element, value) {
    if (value === null || value === undefined || value === "") return false;
    if (lower(element.getAttribute?.("role")) === "combobox" || element.getAttribute?.("aria-haspopup") === "listbox") {
      return chooseCustomOption(element, value);
    }

    if (element.tagName === "SELECT") {
      const wanted = new Set(answerGroups(value).flat().map(lower));
      let matched = false;
      for (const option of element.options) {
        const isMatch = wanted.has(lower(option.value)) || wanted.has(lower(option.textContent));
        if (element.multiple) {
          option.selected = isMatch;
          matched = matched || isMatch;
        } else if (isMatch) {
          element.value = option.value;
          dispatchEvents(element);
          return true;
        }
      }
      if (matched) dispatchEvents(element);
      return matched;
    }

    const type = lower(element.type);
    if (type === "radio") {
      const wanted = new Set(answerGroups(value).flat().map(lower));
      for (const radio of groupControls(element)) {
        if ([lower(radio.value), lower(choiceLabel(radio))].some((item) => wanted.has(item))) {
          radio.checked = true;
          dispatchEvents(radio);
          return true;
        }
      }
      return false;
    }

    if (type === "checkbox") {
      const wanted = new Set(answerGroups(value).flat().map(lower));
      let matched = false;
      for (const box of groupControls(element)) {
        const shouldCheck = [lower(box.value), lower(choiceLabel(box))].some((item) => wanted.has(item));
        box.checked = shouldCheck;
        dispatchEvents(box);
        matched = matched || shouldCheck;
      }
      return matched;
    }

    return setText(element, answerText(value));
  }

  function questionChoices(element) {
    if (element.tagName === "SELECT") {
      return [...element.options].map((option) => ({
        value: normalize(option.value || option.textContent),
        label: normalize(option.textContent || option.value),
      })).filter((choice) => choice.value && !["select", "select...", "choose", "choose..."].includes(lower(choice.label)));
    }
    const type = lower(element.type);
    if (type === "radio" || type === "checkbox") {
      return groupControls(element).map((control) => ({
        value: normalize(control.value || choiceLabel(control)),
        label: normalize(choiceLabel(control) || control.value),
      })).filter((choice) => choice.value || choice.label);
    }
    return [];
  }

  function descriptor(element) {
    return {
      field_name: fieldName(element),
      text: labelText(element),
      type: controlType(element),
      required: isRequiredControl(element),
      choices: questionChoices(element),
      adapter: "ashby_hosted",
    };
  }

  function reusableAnswer(task, questionText) {
    const question = lower(questionText);
    const values = task.reusable_answers || {};
    const yesNoRules = [
      [["18 or older", "18 years of age or older", "at least 18"], values.is_18_or_older],
      [["authorized to work", "legally authorized to work", "eligible to work", "work authorization"], values.work_authorization_default],
      [["require sponsorship", "requires sponsorship", "need sponsorship", "visa sponsorship", "immigration sponsorship"], values.sponsorship_default],
      [["willing to relocate", "open to relocation", "able to relocate"], values.willing_to_relocate],
      [["willing to travel", "able to travel", "open to travel"], values.willing_to_travel],
    ];

    for (const [patterns, value] of yesNoRules) {
      const configured = lower(value);
      if (patterns.some((pattern) => question.includes(pattern)) && ["yes", "no"].includes(configured)) {
        return configured === "yes" ? "Yes" : "No";
      }
    }

    if (["years of experience", "how many years", "years experience"].some((pattern) => question.includes(pattern))
        && values.years_of_experience !== null && values.years_of_experience !== undefined) {
      return String(values.years_of_experience);
    }
    if (["salary expectation", "salary expectations", "desired salary", "expected salary", "compensation expectation", "desired compensation"]
        .some((pattern) => question.includes(pattern)) && values.salary_expectation) {
      return String(values.salary_expectation);
    }
    if (["available to start", "availability to start", "start date", "earliest start", "earliest available"]
        .some((pattern) => question.includes(pattern)) && values.available_start_date) {
      return String(values.available_start_date);
    }
    if (["field of study", "academic discipline", "discipline", "major"].some((pattern) => question === pattern || question.includes(pattern))
        && values.education_discipline) {
      return String(values.education_discipline);
    }
    if (["degree", "degree type", "highest degree", "education level"].some((pattern) => question === pattern || question.includes(pattern))
        && values.education_degree) {
      return String(values.education_degree);
    }
    if (["school", "school name", "college or university", "university name"].some((pattern) => question === pattern || question.includes(pattern))
        && values.education_school) {
      return String(values.education_school);
    }
    return null;
  }

  function rememberedAnswer(task, questionText) {
    const wanted = questionMatchKey(questionText);
    if (!wanted) return null;
    for (const memory of task.answer_memories || []) {
      const answer = memory?.answer;
      if (questionMatchKey(memory?.question_text) === wanted && answer !== null && answer !== undefined && answer !== "") {
        return answer;
      }
    }
    return null;
  }

  function findSavedControl(question) {
    const controls = allQuestionControls();
    if (question.field_name) {
      const exact = controls.find((element) => fieldName(element) === question.field_name);
      if (exact) return exact;
    }
    const wanted = questionMatchKey(question.text);
    if (!wanted) return null;
    let fuzzy = null;
    for (const element of controls) {
      const actual = questionMatchKey(labelText(element));
      if (actual === wanted) return element;
      if (!fuzzy && actual && (actual.includes(wanted) || wanted.includes(actual))) fuzzy = element;
    }
    return fuzzy;
  }

  async function applySavedAshbyAnswers(task) {
    for (const question of task.application_questions || []) {
      if (question.answer === null || question.answer === undefined || question.answer === "") continue;
      const element = findSavedControl(question);
      if (element) await applyValue(element, question.answer);
    }
  }

  async function applyReusableAshbyAnswers(task) {
    for (const element of requiredControls()) {
      if (coreQuestion(element) || controlHasAnyValue(element)) continue;
      const remembered = rememberedAnswer(task, labelText(element));
      const answer = remembered !== null ? remembered : reusableAnswer(task, labelText(element));
      if (answer !== null) await applyValue(element, answer);
    }
  }

  function fillByLabel(pattern, value) {
    if (!value) return false;
    for (const element of allQuestionControls()) {
      if (["INPUT", "TEXTAREA"].includes(element.tagName) && pattern.test(lower(labelText(element)))) {
        if (setText(element, value)) return true;
      }
    }
    return false;
  }

  function fillIdentity(identity) {
    fillByLabel(/^(full )?name$|legal name/, identity.full_name);
    fillByLabel(/first name|given name/, identity.first_name);
    fillByLabel(/last name|family name|surname/, identity.last_name);
    fillByLabel(/e-?mail/, identity.email);
    fillByLabel(/phone|mobile/, identity.phone);
    fillByLabel(/linkedin/, identity.linkedin_url);
    fillByLabel(/github/, identity.github_url);
    fillByLabel(/website|portfolio|personal site/, identity.website_url);
    fillByLabel(/^city$/, identity.city);
    fillByLabel(/postal code|zip code/, identity.postal_code);
  }

  async function fetchResume(launch, task) {
    const response = await send({type: "jobfinitum-resume", origin: launch.origin, url: task.resume.url});
    const binary = atob(response.base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new File([bytes], task.resume.filename, {
      type: task.resume.content_type || response.contentType || "application/octet-stream",
    });
  }

  function setResumeFile(file) {
    const inputs = [...document.querySelectorAll('input[type="file"]')];
    const selected = inputs.find((input) => {
      const meta = lower(`${input.name || ""} ${input.id || ""} ${labelText(input)} ${input.getAttribute("accept") || ""}`);
      return meta.includes("resume") || meta.includes("cv");
    }) || (inputs.length === 1 ? inputs[0] : null);
    if (!selected) return false;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    selected.files = transfer.files;
    dispatchEvents(selected);
    return true;
  }

  function hasAshbyForm() {
    return Boolean(
      document.querySelector('input[type="file"]')
      || (document.querySelector('input[type="email"]')
        && [...document.querySelectorAll("button")].some((button) => /submit application/i.test(normalize(button.innerText))))
    );
  }

  function ashbyApplyControl() {
    const candidates = [...document.querySelectorAll("a, button")].filter(visible);
    for (const wanted of ["application", "apply now", "apply for this job", "apply"]) {
      const match = candidates.find((element) => lower(element.innerText) === wanted);
      if (match) return match;
    }
    return null;
  }

  async function waitForAshbyForm(timeoutMs = 10000) {
    const started = Date.now();
    let clickedApply = false;
    while (Date.now() - started < timeoutMs) {
      if (hasAshbyForm()) return true;
      if (!clickedApply) {
        const control = ashbyApplyControl();
        if (control) {
          clickedApply = true;
          control.click();
        }
      }
      await sleep(200);
    }
    return hasAshbyForm();
  }

  async function waitForAshbySettle(timeoutMs = 7000) {
    const started = Date.now();
    let lastMutationAt = started;
    const observer = new MutationObserver(() => { lastMutationAt = Date.now(); });
    observer.observe(document.documentElement, {childList: true, subtree: true, attributes: true});
    try {
      while (Date.now() - started < timeoutMs) {
        await sleep(200);
        if (Date.now() - started >= 2200 && Date.now() - lastMutationAt >= 700) return;
      }
    } finally {
      observer.disconnect();
    }
  }

  function customQuestion(element, task) {
    if (coreQuestion(element)) return false;
    return reusableAnswer(task, labelText(element)) === null;
  }

  async function report(launch, payload) {
    return send({type: "jobfinitum-result", origin: launch.origin, token: launch.token, payload});
  }

  async function closeCompletedAgentTab(launch) {
    if (launch?.batch === true || isBatchRunner()) {
      window.name = BATCH_RUNNER_NAME;
      const waitingUrl = new URL("/browser-agent", launch.origin);
      waitingUrl.searchParams.set("batch_wait", "1");
      location.replace(waitingUrl.href);
      return;
    }
    try {
      await send({type: "jobfinitum-close-agent-tab", origin: launch.origin});
    } catch (error) {
      console.warn("Jobfinitum could not close the completed Ashby Agent tab:", error);
    }
  }

  async function handOffToManualApply(launch, message, detail = {}) {
    statusBox("this Ashby page needs Manual Apply.", "warning");
    await report(launch, {
      status: "unsupported",
      message,
      detail: {
        url: location.href,
        executor: "chrome_agent",
        adapter: "ashby_hosted",
        manual_application: true,
        ...detail,
      },
    });
    clearLaunch();
    await closeCompletedAgentTab(launch);
  }

  async function finishConfirmedAshbySubmission(launch) {
    const body = lower(document.body?.innerText);
    if (!SUCCESS_PHRASES.some((phrase) => body.includes(phrase))) return false;
    statusBox("Ashby confirms the application was submitted.", "success");
    await report(launch, {
      status: "submitted",
      message: "Chrome Agent submitted the Ashby application successfully.",
      confirmation_url: location.href,
      detail: {url: location.href, executor: "chrome_agent", adapter: "ashby_hosted"},
    });
    clearLaunch();
    await closeCompletedAgentTab(launch);
    return true;
  }

  function visibleVerificationChallenge() {
    return [...document.querySelectorAll(
      'iframe[src*="hcaptcha"], iframe[src*="recaptcha"], iframe[src*="challenges.cloudflare.com"]'
    )].some(visible);
  }

  function submitButton() {
    const buttons = [...document.querySelectorAll('button, input[type="submit"]')]
      .filter((element) => visible(element) && !element.disabled);
    return buttons.find((element) => /^submit application$/i.test(normalize(element.innerText || element.value)))
      || buttons.find((element) => /submit application|submit$/i.test(normalize(element.innerText || element.value)))
      || null;
  }

  async function run(launch, task) {
    if (await finishConfirmedAshbySubmission(launch)) return;

    statusBox("opening Ashby application...");
    const formReady = await waitForAshbyForm();
    if (await finishConfirmedAshbySubmission(launch)) return;

    if (!formReady) {
      await handOffToManualApply(
        launch,
        "Ashby did not expose a standard hosted application form Jobfinitum can automate.",
        {reason: "missing_application_form"}
      );
      return;
    }

    const identity = task.identity || {};
    statusBox("uploading resume...");
    const resume = await fetchResume(launch, task);
    if (!setResumeFile(resume)) {
      await handOffToManualApply(
        launch,
        "Chrome Agent could not locate a supported Ashby resume upload field.",
        {reason: "missing_resume_field"}
      );
      return;
    }

    statusBox("waiting for Ashby form updates...");
    await waitForAshbySettle();

    for (let pass = 0; pass < 3; pass += 1) {
      statusBox("applying saved Ashby answers...");
      fillIdentity(identity);
      await applySavedAshbyAnswers(task);
      await applyReusableAshbyAnswers(task);
      if (pass < 2) await sleep(600);
    }

    await sleep(400);
    const unresolved = [];
    for (const element of requiredControls()) {
      if (!customQuestion(element, task)) continue;
      if (!controlHasAnyValue(element)) unresolved.push(descriptor(element));
    }

    if (unresolved.length) {
      statusBox("more Ashby application answers are required in Jobfinitum.", "warning");
      const reportResponse = await report(launch, {
        status: "needs_application_answer",
        message: "Ashby requires additional application answers before submission.",
        questions: unresolved,
        detail: {
          url: location.href,
          required_fields: unresolved.map((item) => item.text),
          executor: "chrome_agent",
          adapter: "ashby_hosted",
        },
      });
      if (reportResponse?.result?.retry_with_saved_answers) {
        statusBox("saved answers found; retrying the Ashby form.");
        await sleep(300);
        location.reload();
        return;
      }
      clearLaunch();
      await closeCompletedAgentTab(launch);
      return;
    }

    const stillInvalid = requiredControls().filter((element) => {
      if (!controlHasAnyValue(element)) return true;
      return typeof element.checkValidity === "function" && !element.checkValidity();
    });

    if (stillInvalid.length) {
      statusBox("Ashby still has required fields Jobfinitum could not fill.", "warning");
      await report(launch, {
        status: "needs_user_action",
        message: "Ashby still has required fields that Jobfinitum could not fill.",
        detail: {
          url: location.href,
          required_fields: stillInvalid.map((element) => labelText(element)),
          executor: "chrome_agent",
          adapter: "ashby_hosted",
        },
      });
      clearLaunch();
      await closeCompletedAgentTab(launch);
      return;
    }

    const submit = submitButton();
    if (!submit) {
      await handOffToManualApply(
        launch,
        "Chrome Agent could not find an enabled Ashby Submit Application button.",
        {reason: "missing_submit_button"}
      );
      return;
    }

    statusBox("submitting Ashby application...");
    submit.click();

    const started = Date.now();
    let verificationReported = false;
    while (Date.now() - started < 30000) {
      await sleep(750);
      if (await finishConfirmedAshbySubmission(launch)) return;
      const body = lower(document.body?.innerText);
      const verificationError = VERIFY_PHRASES.some((phrase) => body.includes(phrase));
      const captchaVisible = visibleVerificationChallenge();
      if ((verificationError || captchaVisible) && !verificationReported) {
        verificationReported = true;
        statusBox("human verification is required; complete it here and the agent will keep watching.", "warning");
        await report(launch, {
          status: "waiting_verification",
          message: "Ashby requires human verification in normal Chrome. Complete it here; the Chrome Agent is still watching.",
          detail: {
            url: location.href,
            verification_error: verificationError,
            captcha_visible: captchaVisible,
            executor: "chrome_agent",
            adapter: "ashby_hosted",
          },
        });
      }
    }

    if (verificationReported) {
      await report(launch, {
        status: "waiting_verification",
        message: "Ashby verification is still waiting for completion.",
        detail: {url: location.href, executor: "chrome_agent", adapter: "ashby_hosted"},
      });
      return;
    }

    await handOffToManualApply(
      launch,
      "Ashby did not return a recognizable submission confirmation within 30 seconds. Review it from Manual Apply.",
      {reason: "submission_confirmation_timeout"}
    );
  }

  async function main() {
    let launch = null;
    try {
      launch = parseLaunch();
      if (!launch) launch = await restoreChainedLaunch();
      if (!launch) return;

      statusBox("connecting to Jobfinitum...");
      await registerBatchRunner(launch);

      const response = await send({
        type: "jobfinitum-task",
        origin: launch.origin,
        token: launch.token,
      });
      const task = response.task;

      if (task.adapter !== "ashby_hosted") {
        throw new Error("Jobfinitum task is not an Ashby application.");
      }
      if (new URL(task.target_url).hostname !== location.hostname) {
        throw new Error("Application host does not match the Jobfinitum task.");
      }

      await run(launch, task);
    } catch (error) {
      console.error("Jobfinitum Ashby Agent failed:", error);
      statusBox(`failed: ${error.message || error}`, "error");
      if (!launch) return;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          await report(launch, {
            status: "failed",
            message: `Chrome Agent failed: ${error.message || error}`,
            detail: {url: location.href, adapter: "ashby_hosted"},
          });
          break;
        } catch (reportError) {
          console.error("Jobfinitum Ashby failure report also failed:", reportError);
          if (attempt === 0) await sleep(700);
        }
      }
      clearLaunch();
      await closeCompletedAgentTab(launch);
    }
  }

  main().catch((error) => {
    console.error("Jobfinitum Ashby Agent stopped during startup:", error);
  });
})();
