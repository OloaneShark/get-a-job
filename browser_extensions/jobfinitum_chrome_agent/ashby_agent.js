(() => {
  "use strict";

  const SUCCESS_PHRASES = [
    "your application was successfully submitted",
    "thank you for applying",
    "thanks for applying",
    "application submitted",
    "application has been submitted",
    "application received",
    "we received your application",
    "we've received your application",
  ];

  const VERIFY_ERROR_PHRASES = [
    "there was a problem verifying this submission with captcha",
    "please complete the captcha",
    "please complete the verification",
  ];

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const lower = (value) => normalize(value).toLowerCase();
  const cleanQuestionText = (value) => normalize(value).replace(/\s*(?:\*+|\u2731+)\s*$/, "");
  const questionMatchKey = (value) => lower(cleanQuestionText(value)).replace(/[^a-z0-9]+/g, " ").trim();
  const customControls = new WeakSet();
  const confirmedCustomSelections = new WeakMap();

  function isCustomControl(element) {
    return customControls.has(element)
      || lower(element?.getAttribute?.("role")) === "combobox"
      || element?.getAttribute?.("aria-haspopup") === "listbox"
      || element?.classList?.contains("ashby-application-form-input-autocomplete");
  }

  function visible(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;

    let current = element;
    for (let depth = 0; current && depth < 10; depth += 1) {
      const style = getComputedStyle(current);
      if (style.display === "none"
          || style.visibility === "hidden"
          || style.visibility === "collapse"
          || Number(style.opacity) <= 0.01
          || lower(current.getAttribute?.("aria-hidden")) === "true") {
        return false;
      }
      current = current.parentElement;
    }
    return true;
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

  function dispatchEvents(element, {blur = true} = {}) {
    const eventNames = blur ? ["input", "change", "blur"] : ["input", "change"];
    for (const name of eventNames) {
      element.dispatchEvent(new Event(name, {bubbles: true}));
    }
  }

  function setText(element, value, {blur = true} = {}) {
    if (!element || value === null || value === undefined || String(value) === "") return false;
    if (!["INPUT", "TEXTAREA"].includes(element.tagName)) return false;

    const prototype = element.tagName === "TEXTAREA"
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor?.set) descriptor.set.call(element, String(value));
    else element.value = String(value);
    dispatchEvents(element, {blur});
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

    const ashbyEntry = element.closest?.(".ashby-application-form-field-entry");
    const elementMeta = lower([
      element.name,
      element.id,
      element.getAttribute?.("placeholder"),
      element.getAttribute?.("aria-label"),
    ].filter(Boolean).join(" "));
    if (ashbyEntry) {
      if (/search schools?|school|college|university/.test(elementMeta)) return "School";
      if (/degree/.test(elementMeta)) return "Degree";
      if (/major|field of study|discipline/.test(elementMeta)) return "Field of Study";
    }
    const ashbyTitle = ashbyEntry?.querySelector(
      ".ashby-application-form-question-title"
    );
    const ashbyText = cleanQuestionText(ashbyTitle?.innerText);
    if (ashbyText) return ashbyText;

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
    const educationSubfield = labelText(element);
    if (["School", "Degree", "Field of Study"].includes(educationSubfield)) {
      const subfieldId = normalize(element.getAttribute?.("id"));
      if (subfieldId) return subfieldId;
    }
    for (const name of ["name", "data-field-path", "data-path", "data-testid", "id"]) {
      const value = normalize(element.getAttribute?.(name));
      if (value) return value;
    }
    const pathContainer = element.closest?.("[data-field-path]");
    const fieldPath = normalize(pathContainer?.getAttribute?.("data-field-path"));
    if (fieldPath) return fieldPath;
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

  function questionControlVisible(element, rawElement = element) {
    if (visible(element) || (rawElement !== element && visible(rawElement))) return true;
    if (!["radio", "checkbox"].includes(lower(element?.type))) return false;

    let label = element.closest?.("label");
    if (!label && element.id) {
      try {
        label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      } catch (error) {}
    }
    return visible(label) || visible(element.parentElement);
  }

  function controlType(element) {
    if (isCustomControl(element)) {
      const customRoot = element.closest?.('[aria-multiselectable="true"], [data-multiselect="true"]');
      const classText = lower(`${element.className || ""} ${element.parentElement?.className || ""}`);
      return customRoot || classText.includes("multiselect") ? "multiselect" : "select";
    }
    if (element.tagName === "SELECT") return element.multiple ? "multiselect" : "select";
    if (element.tagName === "TEXTAREA") return "textarea";
    const type = lower(element.type);
    return ["radio", "checkbox", "date", "number", "email", "url", "tel"].includes(type)
      ? type
      : "text";
  }

  function isRequiredControl(element) {
    if (element.required || lower(element.getAttribute?.("aria-required")) === "true") return true;

    const ashbyEntry = element.closest?.(".ashby-application-form-field-entry");
    if (ashbyEntry) {
      if (ashbyEntry.querySelector(
        '[aria-required="true"], [data-required="true"], input:required, textarea:required, select:required'
      )) {
        return true;
      }
      const title = ashbyEntry.querySelector(".ashby-application-form-question-title");
      return /\*\s*$|\brequired\b/i.test(normalize(title?.innerText));
    }

    let current = element.parentElement;
    for (let depth = 0; current && depth < 4; depth += 1) {
      if (current.matches?.("form")) break;
      if (current.matches?.('[aria-required="true"], [data-required="true"]')) return true;
      const labels = [...(current.querySelectorAll?.(
        ":scope > label, :scope > legend, :scope > [class*=label], :scope > [class*=Label]"
      ) || [])];
      if (labels.some((node) => /\*\s*$|\brequired\b/i.test(normalize(node.innerText)))) return true;
      current = current.parentElement;
    }
    return false;
  }

  function allQuestionControls() {
    const selector = [
      "input",
      "textarea",
      "select",
      '[role="combobox"]',
      '[aria-haspopup="listbox"]',
      ".ashby-application-form-input-autocomplete",
    ].join(",");
    const result = [];
    const seen = new Set();
    for (const rawElement of document.querySelectorAll(selector)) {
      const rawRole = lower(rawElement.getAttribute?.("role"));
      const rawCustom = rawRole === "combobox"
        || rawElement.getAttribute?.("aria-haspopup") === "listbox"
        || rawElement.classList?.contains("ashby-application-form-input-autocomplete");
      const element = rawCustom && rawElement.tagName !== "INPUT"
        ? rawElement.querySelector?.('input[role="combobox"], input[aria-autocomplete], input') || rawElement
        : rawElement;
      if (rawCustom) customControls.add(element);
      if (!questionControlVisible(element, rawElement) || element.disabled || element.readOnly) continue;
      const type = lower(element.type);
      const role = lower(element.getAttribute?.("role"));
      if (["hidden", "submit", "button", "file", "image", "reset"].includes(type) && role !== "combobox") continue;
      const groupType = lower(element.type);
      const custom = isCustomControl(element) || rawCustom;
      const key = ["radio", "checkbox"].includes(groupType)
        ? `${groupType}|${element.name || fieldName(element)}`
        : custom
        ? `custom|${fieldName(element)}`
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
    return /^(?:(?:full|legal|preferred) )?name$/.test(text)
      || /\bfirst name\b|\blast name\b/.test(combined)
      || /\be-?mail\b|\bphone\b|\bresume\b|\bcv\b/.test(combined)
      || /\blinkedin\b|\bgithub\b|\bwebsite\b|\bportfolio\b/.test(combined)
      || [
        "city",
        "current city",
        "location",
        "current location",
        "city and state",
        "city / state",
        "state",
        "state / province",
        "province",
        "country",
        "postal code",
        "zip code",
      ].includes(text);
  }

  function controlHasAnyValue(element) {
    const type = lower(element.type);
    if (type === "radio" || type === "checkbox") return groupControls(element).some((item) => item.checked);
    if (element.tagName === "SELECT") {
      if (element.multiple) {
        return [...element.selectedOptions].some((option) => {
          const value = normalize(option.value);
          const text = normalize(option.textContent);
          return Boolean(value || (text && !placeholderChoice(text)));
        });
      }
      const option = element.options[element.selectedIndex];
      const value = normalize(option?.value ?? element.value);
      const text = normalize(option?.textContent);
      if (option?.disabled && !value) return false;
      return Boolean(value || (text && !placeholderChoice(text)));
    }
    if (isCustomControl(element)) {
      if (confirmedCustomSelections.has(element)) return true;
      const nestedInput = element.tagName === "INPUT"
        ? null
        : element.querySelector?.('input[role="combobox"], input[aria-autocomplete], input');
      const selectedNode = element.querySelector?.(
        '[aria-selected="true"], [data-selected="true"], [data-state="checked"], '
        + '[class*="selected-value" i], [class*="multi-value" i]'
      );
      const text = normalize(
        element.tagName === "INPUT" || element.tagName === "TEXTAREA"
          ? element.value
          : element.getAttribute?.("aria-valuetext")
            || element.getAttribute?.("data-value")
            || nestedInput?.value
            || selectedNode?.innerText
            || (element.tagName === "BUTTON" ? element.textContent : "")
      );
      return Boolean(text && !placeholderChoice(text));
    }
    return Boolean(normalize(element.value));
  }

  function placeholderChoice(value) {
    return /^(?:please\s+)?(?:select|choose)(?:\s+(?:an?\s+)?option)?(?:\.\.\.)?$/i.test(normalize(value));
  }

  function visibleOptionNodes() {
    return [...document.querySelectorAll(
      [
        '[role="option"]',
        '[data-radix-collection-item]',
        '[data-testid*=option]',
        '[data-testid*=Option]',
        ".ashby-application-form-input-autocomplete-popup-result",
      ].join(",")
    )].filter(visible);
  }

  function fuzzyChoiceMatch(optionText, candidateText) {
    const optionKey = questionMatchKey(optionText);
    const candidateKey = questionMatchKey(candidateText);
    if (candidateKey.length < 3 || optionKey.length < 3) return false;
    const containsPhrase = (text, phrase) => text === phrase
      || text.startsWith(`${phrase} `)
      || text.endsWith(` ${phrase}`)
      || text.includes(` ${phrase} `);
    return containsPhrase(optionKey, candidateKey)
      || containsPhrase(candidateKey, optionKey);
  }

  async function chooseCustomOption(element, value) {
    const groups = answerGroups(value);
    if (!groups.length) return false;
    const requestedGroups = controlType(element) === "multiselect" ? groups : [groups[0]];
    const confirmedValues = new Set(
      answerGroups(confirmedCustomSelections.get(element)).flat().map(lower)
    );
    const pendingGroups = requestedGroups.filter(
      (group) => !group.some((candidate) => confirmedValues.has(lower(candidate)))
    );
    if (!pendingGroups.length) return true;
    const originalValue = normalize(element.value);
    let matchedCount = 0;

    for (const group of pendingGroups) {
      const wanted = new Set(group.map(lower));
      if (element.tagName === "INPUT") {
        element.focus();
        setText(element, group[0], {blur: false});
        element.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
      } else {
        element.click();
      }

      const started = Date.now();
      let selected = null;
      while (Date.now() - started < 3500 && !selected) {
        await sleep(150);
        const options = visibleOptionNodes();
        selected = options.find((option) => {
          const values = [
            lower(option.getAttribute?.("data-value")),
            lower(option.getAttribute?.("value")),
            lower(option.innerText),
          ];
          return values.some((item) => item && wanted.has(item));
        }) || options.find((option) => {
          const text = lower(option.innerText);
          return text && [...wanted].some(
            (candidate) => candidate && fuzzyChoiceMatch(text, candidate)
          );
        });
      }

      if (!selected) {
        if (!matchedCount && element.tagName === "INPUT") {
          setText(element, originalValue, {blur: false});
          element.dispatchEvent(new Event("blur", {bubbles: true}));
        }
        if (!confirmedValues.size) confirmedCustomSelections.delete(element);
        return false;
      }

      selected.dispatchEvent(new MouseEvent("mousedown", {bubbles: true, cancelable: true, view: window}));
      selected.click();
      matchedCount += 1;
      confirmedValues.add(lower(group[0]));
      confirmedCustomSelections.set(element, [...confirmedValues]);
      await sleep(150);
    }

    dispatchEvents(element);
    return matchedCount === pendingGroups.length;
  }

  async function applyValue(element, value) {
    if (value === null || value === undefined || value === "") return false;
    if (isCustomControl(element)) {
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
          const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
          if (setter) setter.call(element, option.value);
          else element.value = option.value;
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
          if (!radio.checked) radio.click();
          else dispatchEvents(radio);
          return radio.checked;
        }
      }
      return false;
    }

    if (type === "checkbox") {
      const wanted = new Set(answerGroups(value).flat().map(lower));
      let matched = false;
      for (const box of groupControls(element)) {
        const shouldCheck = [lower(box.value), lower(choiceLabel(box))].some((item) => wanted.has(item));
        if (box.checked !== shouldCheck) box.click();
        else dispatchEvents(box);
        matched = matched || shouldCheck;
      }
      return matched;
    }

    return setText(element, answerText(value));
  }

  async function questionChoices(element) {
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

    if (isCustomControl(element)) {
      if (element.tagName === "INPUT") {
        element.focus();
        element.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
      } else {
        element.click();
      }
      await sleep(200);
      const choices = visibleOptionNodes().map((option) => ({
        value: normalize(option.getAttribute?.("data-value") || option.getAttribute?.("value") || option.innerText),
        label: normalize(option.innerText || option.getAttribute?.("data-value") || option.getAttribute?.("value")),
      })).filter((choice) => choice.value && !placeholderChoice(choice.label));
      element.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
      element.dispatchEvent(new Event("blur", {bubbles: true}));
      return choices;
    }
    return [];
  }

  async function descriptor(element) {
    return {
      field_name: fieldName(element),
      text: labelText(element),
      type: controlType(element),
      required: isRequiredControl(element),
      choices: await questionChoices(element),
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
    for (const element of allQuestionControls()) {
      if (coreQuestion(element) || controlHasAnyValue(element)) continue;
      const remembered = rememberedAnswer(task, labelText(element));
      const answer = remembered !== null ? remembered : reusableAnswer(task, labelText(element));
      if (answer !== null) await applyValue(element, answer);
    }
  }

  async function fillByLabel(pattern, value) {
    if (!value) return false;
    for (const element of allQuestionControls()) {
      if (["INPUT", "TEXTAREA"].includes(element.tagName) && pattern.test(lower(labelText(element)))) {
        if (await applyValue(element, value)) return true;
      }
    }
    return false;
  }

  async function fillIdentity(identity) {
    await fillByLabel(/^(full )?name$|legal name/, identity.full_name);
    await fillByLabel(/first name|given name/, identity.first_name);
    await fillByLabel(/last name|family name|surname/, identity.last_name);
    await fillByLabel(/e-?mail/, identity.email);
    await fillByLabel(/phone|mobile/, identity.phone);
    await fillByLabel(/linkedin/, identity.linkedin_url);
    await fillByLabel(/github/, identity.github_url);
    await fillByLabel(/website|portfolio|personal site/, identity.website_url);
    await fillByLabel(
      /^(?:current )?(?:city|location)(?:\s*(?:and|\/)\s*(?:state|region))?$/,
      identity.location_text || identity.city
    );
    await fillByLabel(/^state(?:\s*\/\s*province)?$|^province$/, identity.state_region);
    await fillByLabel(/^country$/, identity.country);
    await fillByLabel(/postal code|zip code/, identity.postal_code);
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
    if (!selected) return null;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    selected.files = transfer.files;
    dispatchEvents(selected);
    return selected;
  }

  function resumeFileAttached(input, file) {
    const entry = input?.closest?.(".ashby-application-form-field-entry");
    const errors = entry?.querySelectorAll?.(
      '[role="alert"], [aria-live="assertive"], [class*="error" i], [data-testid*="error" i]'
    ) || [];
    if ([...errors].some((node) => visible(node) && normalize(node.innerText))) {
      return false;
    }
    if ([...(input?.files || [])].some((item) => item.name === file.name && item.size === file.size)) {
      return true;
    }
    const entryText = normalize(
      entry?.innerText
    );
    return Boolean(entryText && entryText.includes(file.name));
  }

  function hasAshbyForm() {
    if ([...document.querySelectorAll(".ashby-application-form-container")].some(visible)) {
      return true;
    }
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

  function applicationAnswerQuestion(element) {
    return !coreQuestion(element);
  }

  function ashbyControlInvalid(element) {
    if (!controlHasAnyValue(element)) return true;
    const type = lower(element.type);
    if (!["radio", "checkbox"].includes(type)
        && typeof element.checkValidity === "function"
        && !element.checkValidity()) {
      return true;
    }
    if (lower(element.getAttribute?.("aria-invalid")) === "true") return true;

    const entry = element.closest?.(".ashby-application-form-field-entry");
    if (!entry) return false;
    const errorNodes = entry.querySelectorAll(
      '[role="alert"], [aria-live="assertive"], [class*="error" i], [data-testid*="error" i]'
    );
    return [...errorNodes].some((node) => visible(node) && normalize(node.innerText));
  }

  async function describeControls(controls) {
    const questions = [];
    const seen = new Set();
    for (const element of controls) {
      const key = fieldName(element);
      if (seen.has(key)) continue;
      seen.add(key);
      questions.push(await descriptor(element));
    }
    return questions;
  }

  async function reportRequiredAnswers(launch, questions, message, validationSource) {
    statusBox("more Ashby application answers are required in Jobfinitum.", "warning");
    const reportResponse = await report(launch, {
      status: "needs_application_answer",
      message,
      questions,
      detail: {
        url: location.href,
        required_fields: questions.map((item) => item.text),
        validation_source: validationSource,
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
    const successContainer = [...document.querySelectorAll(
      ".ashby-application-form-success-container"
    )].find(visible);
    const successText = lower(successContainer?.innerText);
    const stableConfirmation = successContainer
      && SUCCESS_PHRASES.some((phrase) => successText.includes(phrase));
    const body = lower(document.body?.innerText);
    const fallbackConfirmation = !hasAshbyForm()
      && !submitButton()
      && body.includes("your application was successfully submitted");
    if (!stableConfirmation && !fallbackConfirmation) return false;
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
    const selectors = [
      'iframe[src*="hcaptcha" i]',
      'iframe[src*="recaptcha" i][title*="challenge" i]',
      '.g-recaptcha iframe[src*="recaptcha" i]',
      'iframe[src*="challenges.cloudflare.com" i]',
      'iframe[src*="challenge-platform" i]',
      '.h-captcha[data-sitekey]',
      '.cf-turnstile[data-sitekey]',
    ];
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!visible(element)) continue;
        const rect = element.getBoundingClientRect();
        const intersectsViewport = rect.right > 0
          && rect.bottom > 0
          && rect.left < window.innerWidth
          && rect.top < window.innerHeight;
        if (rect.width < 40 || rect.height < 30) continue;
        if (!intersectsViewport) {
          try { element.scrollIntoView({block: "center", inline: "nearest"}); } catch (error) {}
        }
        return true;
      }
    }
    return false;
  }

  function visibleVerificationError() {
    const candidates = [...document.querySelectorAll(
      '[role="alert"], [aria-live="assertive"], [class*="error" i], [data-testid*="error" i]'
    )].filter(visible);
    for (const element of candidates) {
      const text = lower(element.innerText);
      if (VERIFY_ERROR_PHRASES.some((phrase) => text.includes(phrase))) return normalize(element.innerText);
    }
    return "";
  }

  function submitButton() {
    const preferred = [...document.querySelectorAll(
      '.ashby-application-form-submit-button button, .ashby-application-form-submit-button input[type="submit"]'
    )].find((element) => visible(element) && !element.disabled);
    if (preferred) return preferred;
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
    const resumeInput = setResumeFile(resume);
    if (!resumeInput) {
      await handOffToManualApply(
        launch,
        "Chrome Agent could not locate a supported Ashby resume upload field.",
        {reason: "missing_resume_field"}
      );
      return;
    }

    statusBox("waiting for Ashby form updates...");
    await waitForAshbySettle();
    if (!resumeFileAttached(resumeInput, resume)) {
      await handOffToManualApply(
        launch,
        "Chrome Agent could not confirm that Ashby accepted the selected resume.",
        {reason: "resume_upload_failed"}
      );
      return;
    }

    for (let pass = 0; pass < 3; pass += 1) {
      statusBox("applying saved Ashby answers...");
      await fillIdentity(identity);
      await applySavedAshbyAnswers(task);
      await applyReusableAshbyAnswers(task);
      if (pass < 2) await sleep(600);
    }

    await waitForAshbySettle(5000);
    await fillIdentity(identity);
    await applySavedAshbyAnswers(task);
    await applyReusableAshbyAnswers(task);
    await sleep(500);

    const unresolvedControls = requiredControls().filter(
      (element) => applicationAnswerQuestion(element) && !controlHasAnyValue(element)
    );
    const unresolved = await describeControls(unresolvedControls);

    if (unresolved.length) {
      await reportRequiredAnswers(
        launch,
        unresolved,
        "Ashby requires additional application answers before submission.",
        "ashby_required_fields"
      );
      return;
    }

    const invalidAnswerControls = requiredControls().filter(
      (element) => applicationAnswerQuestion(element) && ashbyControlInvalid(element)
    );
    if (invalidAnswerControls.length) {
      await reportRequiredAnswers(
        launch,
        await describeControls(invalidAnswerControls),
        "Ashby rejected required application answers before submission.",
        "ashby_client_validation"
      );
      return;
    }

    const stillInvalid = requiredControls().filter(
      (element) => coreQuestion(element) && ashbyControlInvalid(element)
    );

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
      const captchaVisible = visibleVerificationChallenge();
      if (captchaVisible) {
        statusBox("human verification is required before Ashby enables submission.", "warning");
        await report(launch, {
          status: "waiting_verification",
          message: "Ashby has a visible human-verification challenge. Complete it here, then resume this application from Jobfinitum.",
          detail: {
            url: location.href,
            verification_error: Boolean(visibleVerificationError()),
            captcha_visible: true,
            executor: "chrome_agent",
            adapter: "ashby_hosted",
          },
        });
        return;
      }
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
    let deadline = started + 30000;
    let verificationReported = false;
    let verificationError = "";
    while (Date.now() < deadline) {
      await sleep(750);
      if (await finishConfirmedAshbySubmission(launch)) return;

      if (Date.now() - started >= 1500) {
        const rejectedControls = requiredControls().filter(
          (element) => applicationAnswerQuestion(element) && ashbyControlInvalid(element)
        );
        if (rejectedControls.length) {
          await reportRequiredAnswers(
            launch,
            await describeControls(rejectedControls),
            "Ashby rejected required fields after submission.",
            "ashby_submit_validation"
          );
          return;
        }
      }

      verificationError = visibleVerificationError() || verificationError;
      const captchaVisible = visibleVerificationChallenge();
      if (captchaVisible && !verificationReported) {
        verificationReported = true;
        deadline = Date.now() + 300000;
        statusBox("human verification is required; complete the visible challenge here and the agent will keep watching.", "warning");
        await report(launch, {
          status: "waiting_verification",
          message: "Ashby has a visible human-verification challenge. Complete it here; the Chrome Agent is still watching.",
          detail: {
            url: location.href,
            verification_error: Boolean(verificationError),
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
      verificationError
        ? "Ashby could not verify the submission with CAPTCHA and did not show a challenge that can be completed. Review it from Manual Apply."
        : "Ashby did not return a recognizable submission confirmation within 30 seconds. Review it from Manual Apply.",
      {
        reason: verificationError ? "captcha_verification_failed" : "submission_confirmation_timeout",
        verification_error: verificationError,
      }
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
