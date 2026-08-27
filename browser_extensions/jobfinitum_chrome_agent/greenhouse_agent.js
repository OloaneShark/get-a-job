(() => {
  "use strict";

  const GREENHOUSE_HOSTS = new Set([
    "boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
  ]);

  const SUCCESS_PHRASES = [
    "thank you for applying",
    "thanks for applying",
    "thanks so much for taking the time to apply",
    "thank you for your application",
    "application submitted",
    "application has been submitted",
    "we have received your application",
    "we received your application",
    "we've received your application",
    "your application has been received",
  ];

  const VERIFY_PHRASES = [
    "please complete the captcha",
    "please complete the verification",
    "verification failed",
    "captcha failed",
    "security check",
  ];

  const LAUNCH_STORAGE_KEY =
    "jobfinitum_chrome_agent_launch_v1";

  const BATCH_RUNNER_NAME =
    "jobfinitum-auto-apply-runner";

  function isBatchRunner() {
    return window.name === BATCH_RUNNER_NAME;
  }

  async function registerBatchRunner(
    launch
  ) {
    if (!isBatchRunner()) {
      return;
    }

    await send({
      type:
        "jobfinitum-batch-register",
      origin:
        launch.origin,
    });
  }

  const sleep = (ms) =>
    new Promise(
      (resolve) => setTimeout(resolve, ms)
    );

  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();

  const lower = (value) =>
    normalize(value).toLowerCase();

  function greenhouseSubmissionConfirmed(
    value
  ) {
    const body =
      lower(value);

    if (
      SUCCESS_PHRASES.some(
        (phrase) => body.includes(
          phrase
        )
      )
    ) {
      return true;
    }

    // Normalize punctuation so straight and typographic
    // apostrophes in Greenhouse confirmations are both recognized.
    const bodyKey =
      questionMatchKey(body);

    return (
      bodyKey.includes(
        "we ve received your application"
      )
      || bodyKey.includes(
        "thanks so much for taking the time to apply"
      )
      || (
        bodyKey.includes(
          "track your application"
        )
        && bodyKey.includes(
          "back to job post"
        )
      )
    );
  }

  function statusBox(message, kind = "working") {
    let box = document.getElementById(
      "jobfinitum-agent-status"
    );

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
    box.textContent = (
      `Jobfinitum Chrome Agent — ${message}`
    );
  }

  function send(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        message,
        (response) => {
          const runtimeError =
            chrome.runtime.lastError;

          if (runtimeError) {
            reject(
              new Error(runtimeError.message)
            );
            return;
          }

          if (!response || !response.ok) {
            reject(
              new Error(
                response?.error
                || "Chrome Agent bridge failed."
              )
            );
            return;
          }

          resolve(response);
        }
      );
    });
  }

  function clearLaunch() {
    try {
      window.sessionStorage.removeItem(
        LAUNCH_STORAGE_KEY
      );
    } catch (error) {
      // Cleanup failure must not block reporting.
    }
  }

  function parseLaunch() {
    const params = new URLSearchParams(
      String(location.hash || "")
        .replace(/^#/, "")
    );

    const token = params.get("jobfinitum_agent");
    const origin = params.get("jobfinitum_origin");

    if (token && origin) {
      const launch = {token, origin};

      try {
        window.sessionStorage.setItem(
          LAUNCH_STORAGE_KEY,
          JSON.stringify(launch)
        );
      } catch (error) {
        console.warn(
          "Jobfinitum could not persist Greenhouse launch state:",
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

      if (
        saved
        && saved.token
        && saved.origin
      ) {
        return {
          token: String(saved.token),
          origin: String(saved.origin),
        };
      }
    } catch (error) {
      console.warn(
        "Jobfinitum could not restore Greenhouse launch state:",
        error
      );
    }

    return null;
  }

  function greenhouseJobIdentity() {
    const parts = location.pathname
      .split("/")
      .filter(Boolean);

    const jobsIndex = parts.indexOf("jobs");

    if (
      jobsIndex < 1
      || jobsIndex + 1 >= parts.length
    ) {
      throw new Error(
        "Could not determine the Greenhouse board token and job ID."
      );
    }

    const boardToken = parts[jobsIndex - 1];
    const jobId = parts[jobsIndex + 1];

    if (
      !boardToken
      || !/^\d+$/.test(jobId)
    ) {
      throw new Error(
        "Greenhouse board token or job ID is invalid."
      );
    }

    return {boardToken, jobId};
  }

  async function fetchGreenhouseSchema(launch) {
    const {
      boardToken,
      jobId,
    } = greenhouseJobIdentity();

    const apiUrl = (
      "https://boards-api.greenhouse.io"
      + "/v1/boards/"
      + encodeURIComponent(boardToken)
      + "/jobs/"
      + encodeURIComponent(jobId)
    );

    const response =
      await send({
        type:
          "jobfinitum-greenhouse-schema",
        origin:
          launch.origin,
        url:
          apiUrl,
      });

    return response.schema || {};
  }

  function dispatchEvents(element) {
    for (
      const name
      of ["input", "change", "blur"]
    ) {
      element.dispatchEvent(
        new Event(
          name,
          {
            bubbles: true,
          }
        )
      );
    }
  }

  function setText(element, value) {
    if (
      !element
      || value === null
      || value === undefined
      || String(value) === ""
    ) {
      return false;
    }

    const tag =
      String(
        element.tagName || ""
      ).toUpperCase();

    let prototype = null;

    if (tag === "TEXTAREA") {
      prototype =
        HTMLTextAreaElement.prototype;
    } else if (tag === "INPUT") {
      prototype =
        HTMLInputElement.prototype;
    }

    const descriptor =
      prototype
        ? Object.getOwnPropertyDescriptor(
            prototype,
            "value"
          )
        : null;

    if (descriptor?.set) {
      descriptor.set.call(
        element,
        String(value)
      );
    } else {
      element.value =
        String(value);
    }

    dispatchEvents(element);
    return true;
  }

  function rawLabelText(element) {
    if (element.labels?.length) {
      for (const label of element.labels) {
        const text =
          normalize(label.innerText);

        if (text) {
          return text;
        }
      }
    }

    const aria =
      normalize(
        element.getAttribute(
          "aria-label"
        )
      );

    if (aria) {
      return aria;
    }

    const labelledBy =
      normalize(
        element.getAttribute(
          "aria-labelledby"
        )
      );

    if (labelledBy) {
      const text =
        labelledBy
          .split(/\s+/)
          .map(
            (id) => normalize(
              document.getElementById(
                id
              )?.innerText
            )
          )
          .filter(Boolean)
          .join(" ");

      if (text) {
        return text;
      }
    }

    let current = element;

    for (
      let depth = 0;
      current && depth < 7;
      depth += 1
    ) {
      const parent = current.parentElement;

      if (!parent) {
        break;
      }

      const selectors = [
        "legend",
        ":scope > label",
        ":scope > div > label",
        ":scope > [class*=question]",
        ":scope > [class*=prompt]",
        ":scope > [class*=label]",
      ];

      for (const selector of selectors) {
        let node = null;

        try {
          node =
            parent.querySelector(
              selector
            );
        } catch (error) {
          node = null;
        }

        if (
          !node
          || node === element
          || node.contains(element)
        ) {
          continue;
        }

        const text =
          normalize(node.innerText);

        if (
          text
          && text.length <= 500
        ) {
          return text;
        }
      }

      current = parent;
    }

    return normalize(
      element.name
      || element.id
      || "Application question"
    );
  }

  function labelText(element) {
    return rawLabelText(element)
      .replace(/\s*\*+\s*$/, "")
      .trim();
  }

  function questionMatchKey(value) {
    return lower(
      value
    )
      .replace(
        /[*'"’"“”.,:;!?()[\]{}]/g,
        " "
      )
      .replace(
        /[^a-z0-9]+/g,
        " "
      )
      .replace(
        /\s+/g,
        " "
      )
      .trim();
  }

  function isVisible(element) {
    if (!element) {
      return false;
    }

    if (
      lower(element.type)
      === "hidden"
    ) {
      return false;
    }

    if (
      lower(element.type)
      === "file"
    ) {
      return true;
    }

    const style =
      getComputedStyle(element);

    const rect =
      element.getBoundingClientRect();

    return (
      style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0
    );
  }

  function isCombobox(element) {
    return Boolean(
      element
      && (
        lower(
          element.getAttribute("role")
        ) === "combobox"
        || lower(
          element.getAttribute(
            "aria-haspopup"
          )
        ) === "listbox"
      )
    );
  }

  function canonicalControl(element) {
    if (!element) {
      return null;
    }

    if (isCombobox(element)) {
      return element;
    }

    const parentCombobox =
      element.closest(
        '[role="combobox"]'
      );

    if (
      parentCombobox
      && isVisible(parentCombobox)
    ) {
      return parentCombobox;
    }

    return element;
  }

  function findProfessionalLinkInput(
    kind
  ) {
    const selectors = {
      linkedin: [
        'input[name*="linkedin" i]',
        'input[id*="linkedin" i]',
        'input[placeholder*="linkedin" i]',
      ],
      github: [
        'input[name*="github" i]',
        'input[id*="github" i]',
        'input[placeholder*="github" i]',
      ],
      website: [
        'input[name*="website" i]',
        'input[id*="website" i]',
        'input[name*="portfolio" i]',
        'input[id*="portfolio" i]',
      ],
    }[kind] || [];

    for (
      const selector
      of selectors
    ) {
      const element =
        document.querySelector(
          selector
        );

      if (
        element
        && isVisible(
          element
        )
      ) {
        return element;
      }
    }

    return findByLabel(
      kind
    );
  }

  function findByLabel(questionText) {
    const wanted =
      questionMatchKey(
        questionText
      );

    if (!wanted) {
      return null;
    }

    const seen =
      new Set();

    let fuzzy = null;

    for (
      const rawElement
      of document.querySelectorAll(
        'input, textarea, select, [role="combobox"]'
      )
    ) {
      const element =
        canonicalControl(
          rawElement
        );

      if (
        !element
        || seen.has(
          element
        )
        || !isVisible(
          element
        )
      ) {
        continue;
      }

      seen.add(
        element
      );

      const actual =
        questionMatchKey(
          labelText(
            element
          )
        );

      if (
        actual === wanted
      ) {
        return element;
      }

      if (
        !fuzzy
        && actual
        && (
          actual.includes(
            wanted
          )
          || wanted.includes(
            actual
          )
        )
      ) {
        fuzzy =
          element;
      }
    }

    return fuzzy;
  }

  function findQuestionContainerControl(
    questionText
  ) {
    const wanted =
      questionMatchKey(
        questionText
      );

    if (!wanted) {
      return null;
    }

    const labelNodes = [
      ...document.querySelectorAll(
        "label, legend"
      ),
    ];

    let fuzzyNode =
      null;

    for (
      const node
      of labelNodes
    ) {
      const actual =
        questionMatchKey(
          node.innerText
          || node.textContent
        );

      if (!actual) {
        continue;
      }

      if (
        actual === wanted
      ) {
        fuzzyNode =
          node;
        break;
      }

      if (
        !fuzzyNode
        && (
          actual.includes(
            wanted
          )
          || wanted.includes(
            actual
          )
        )
      ) {
        fuzzyNode =
          node;
      }
    }

    if (!fuzzyNode) {
      return null;
    }

    let current =
      fuzzyNode.parentElement;

    for (
      let depth = 0;
      current
      && depth < 6;
      depth += 1
    ) {
      const combobox =
        current.querySelector(
          '[role="combobox"]'
        );

      if (
        combobox
        && isVisible(
          combobox
        )
      ) {
        return combobox;
      }

      const nativeSelect =
        current.querySelector(
          "select"
        );

      if (
        nativeSelect
        && isVisible(
          nativeSelect
        )
      ) {
        return nativeSelect;
      }

      const controls = [
        ...current.querySelectorAll(
          'input[type="checkbox"], input[type="radio"]'
        ),
      ];

      if (
        controls.length
      ) {
        return controls[0];
      }

      current =
        current.parentElement;
    }

    return null;
  }

  function fieldCandidates(fieldName) {
    const name =
      String(fieldName || "").trim();

    if (!name) {
      return [];
    }

    const variants =
      new Set([
        name,
        name.endsWith("[]")
          ? name.slice(0, -2)
          : `${name}[]`,
      ]);

    const result = [];

    for (const variant of variants) {
      try {
        for (
          const element
          of document.querySelectorAll(
            `[name="${CSS.escape(variant)}"]`
          )
        ) {
          result.push(element);
        }
      } catch (error) {
        // Continue to label fallback.
      }
    }

    return result;
  }

  function findSchemaControl(question) {
    for (
      const rawElement
      of fieldCandidates(
        question.field_name
      )
    ) {
      const element =
        canonicalControl(rawElement);

      if (
        element
        && (
          isVisible(element)
          || lower(rawElement.type)
            === "checkbox"
          || lower(rawElement.type)
            === "radio"
        )
      ) {
        return element;
      }

      let current =
        rawElement.parentElement;

      for (
        let depth = 0;
        current && depth < 5;
        depth += 1
      ) {
        const combobox =
          current.querySelector(
            '[role="combobox"]'
          );

        if (
          combobox
          && isVisible(combobox)
        ) {
          return combobox;
        }

        current =
          current.parentElement;
      }
    }

    return (
      findByLabel(
        question.text
      )
      || findQuestionContainerControl(
        question.text
      )
    );
  }

  function groupControls(element) {
    const type =
      lower(element.type);

    const name =
      String(element.name || "");

    if (
      !name
      || ![
        "radio",
        "checkbox",
      ].includes(type)
    ) {
      return [element];
    }

    return [
      ...document.querySelectorAll(
        `input[type="${type}"]`
      ),
    ].filter(
      (candidate) => (
        String(candidate.name || "")
        === name
      )
    );
  }

  function choiceLabel(element) {
    if (element.id) {
      const explicit =
        document.querySelector(
          `label[for="${CSS.escape(element.id)}"]`
        );

      const text =
        normalize(
          explicit?.innerText
        );

      if (text) {
        return text;
      }
    }

    return normalize(
      element.closest("label")?.innerText
      || element.value
    );
  }

  function visibleOptionNodes() {
    const result = [];
    const seen = new Set();

    const selectors = [
      '[role="option"]',
      '[role="listbox"] [data-value]',
      '[role="listbox"] li',
      '[role="listbox"] button',
      '[id*="-option-"]',
    ];

    for (const selector of selectors) {
      for (
        const node
        of document.querySelectorAll(
          selector
        )
      ) {
        if (
          seen.has(node)
          || !isVisible(node)
        ) {
          continue;
        }

        const text =
          normalize(
            node.innerText
            || node.textContent
          );

        if (!text) {
          continue;
        }

        seen.add(node);
        result.push(node);
      }
    }

    return result;
  }

  function setComboboxSearchText(
    input,
    value
  ) {
    if (!input) {
      return false;
    }

    const descriptor =
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value"
      );

    if (descriptor?.set) {
      descriptor.set.call(
        input,
        String(value)
      );
    } else {
      input.value = String(value);
    }

    try {
      input.dispatchEvent(
        new InputEvent(
          "input",
          {
            bubbles: true,
            inputType:
              "insertText",
            data:
              String(value),
          }
        )
      );
    } catch (error) {
      input.dispatchEvent(
        new Event(
          "input",
          {bubbles: true}
        )
      );
    }

    input.dispatchEvent(
      new Event(
        "change",
        {bubbles: true}
      )
    );

    input.dispatchEvent(
      new KeyboardEvent(
        "keyup",
        {
          key:
            String(value).slice(-1)
            || " ",
          bubbles: true,
        }
      )
    );

    return true;
  }

  async function openCombobox(
    element
  ) {
    const target =
      canonicalControl(element);

    if (!target) {
      return null;
    }

    const input = (
      target.tagName === "INPUT"
        ? target
        : target.querySelector("input")
    );

    const clickTarget = (
      target.querySelector(
        '[aria-haspopup="listbox"]'
      )
      || target.querySelector("button")
      || input
      || target
    );

    try {
      clickTarget.dispatchEvent(
        new PointerEvent(
          "pointerdown",
          {bubbles: true}
        )
      );
    } catch (error) {
      // No-op.
    }

    clickTarget.dispatchEvent(
      new MouseEvent(
        "mousedown",
        {bubbles: true}
      )
    );

    clickTarget.click();

    await sleep(220);

    return {
      target,
      input,
    };
  }

  function dispatchKey(
    element,
    key
  ) {
    if (!element) {
      return;
    }

    element.dispatchEvent(
      new KeyboardEvent(
        "keydown",
        {
          key,
          code: key,
          bubbles: true,
        }
      )
    );

    element.dispatchEvent(
      new KeyboardEvent(
        "keyup",
        {
          key,
          code: key,
          bubbles: true,
        }
      )
    );
  }

  async function activateOption(
    option
  ) {
    const target =
      option?.closest?.(
        '[role="option"], [data-value], li, button'
      )
      || option;

    if (!target) {
      return;
    }

    try {
      target.scrollIntoView({
        block:
          "nearest",
      });
    } catch (error) {
      // No-op.
    }

    try {
      target.dispatchEvent(
        new PointerEvent(
          "pointerdown",
          {
            bubbles: true,
            cancelable: true,
            composed: true,
            button: 0,
            buttons: 1,
          }
        )
      );
    } catch (error) {
      // No-op.
    }

    target.dispatchEvent(
      new MouseEvent(
        "mousedown",
        {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          button: 0,
          buttons: 1,
        }
      )
    );

    try {
      target.dispatchEvent(
        new PointerEvent(
          "pointerup",
          {
            bubbles: true,
            cancelable: true,
            composed: true,
            button: 0,
          }
        )
      );
    } catch (error) {
      // No-op.
    }

    target.dispatchEvent(
      new MouseEvent(
        "mouseup",
        {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          button: 0,
        }
      )
    );

    target.click();

    await sleep(
      450
    );
  }

  function choiceParts(
    choice
  ) {
    if (
      choice
      && typeof choice === "object"
    ) {
      return [
        choice.label,
        choice.value,
        choice.platform_value,
      ]
        .map(
          (item) => normalize(item)
        )
        .filter(Boolean);
    }

    const value =
      normalize(choice);

    return value
      ? [value]
      : [];
  }

  function choiceTokens(
    choice
  ) {
    return choiceParts(
      choice
    )
      .map(
        (item) => lower(item)
      )
      .filter(Boolean);
  }

  function answerTokens(
    question,
    answer
  ) {
    const rawValues = (
      Array.isArray(answer)
        ? answer
        : [answer]
    );

    const tokens =
      new Set();

    for (const raw of rawValues) {
      for (
        const value
        of choiceParts(raw)
      ) {
        tokens.add(
          lower(value)
        );
      }

      const choice =
        matchingSchemaChoice(
          question,
          raw
        );

      for (
        const value
        of choiceParts(choice)
      ) {
        tokens.add(
          lower(value)
        );
      }
    }

    return [
      ...tokens,
    ].filter(Boolean);
  }

  function tokenMatches(
    candidate,
    tokens,
    options = {}
  ) {
    const normalized =
      lower(candidate);

    if (
      !normalized
      || !tokens?.length
    ) {
      return false;
    }

    if (
      tokens.includes(
        normalized
      )
    ) {
      return true;
    }

    if (
      !options.allowContains
    ) {
      return false;
    }

    return tokens.some(
      (token) => (
        token
        && (
          normalized.includes(token)
          || token.includes(normalized)
        )
      )
    );
  }

  function optionMatchesAnswer(
    option,
    tokens,
    options = {}
  ) {
    return [
      option?.innerText,
      option?.textContent,
      option?.getAttribute?.("data-value"),
      option?.getAttribute?.("value"),
      option?.getAttribute?.("aria-label"),
    ]
      .map(
        (item) => lower(item)
      )
      .filter(Boolean)
      .some(
        (item) => tokenMatches(
          item,
          tokens,
          options
        )
      );
  }

  function optionNodesForOpened(
    opened
  ) {
    if (
      typeof greenhouseStructuredOptionNodes
      === "function"
    ) {
      return greenhouseStructuredOptionNodes(
        opened
      );
    }

    return visibleOptionNodes();
  }

  function findOptionForAnswer(
    opened,
    tokens,
    options = {}
  ) {
    const nodes =
      optionNodesForOpened(
        opened
      );

    return (
      nodes.find(
        (node) => optionMatchesAnswer(
          node,
          tokens
        )
      )
      || (
        options.allowContains
          ? nodes.find(
              (node) => optionMatchesAnswer(
                node,
                tokens,
                {allowContains: true}
              )
            )
          : null
      )
      || null
    );
  }

  function structuredEducationSelectQuestion(
    question
  ) {
    const field =
      lower(
        question?.field_name
      );

    return (
      question?.structured_section
        === "education"
      || field.startsWith(
        "greenhouse_education_"
      )
    );
  }

  function primaryChoiceAnswer(
    question,
    value
  ) {
    const choice =
      matchingSchemaChoice(
        question,
        value
      );

    if (choice?.label) {
      return choice.label;
    }

    if (choice?.value) {
      return choice.value;
    }

    if (Array.isArray(value)) {
      return value[0] || "";
    }

    if (
      value
      && typeof value === "object"
    ) {
      return (
        value.label
        || value.value
        || value.platform_value
        || ""
      );
    }

    return value;
  }

  function matchingSchemaChoice(
    question,
    answer
  ) {
    const wanted = new Set(
      choiceTokens(
        answer
      )
    );

    if (!wanted.size) {
      return null;
    }

    return (
      question?.choices
      || []
    ).find(
      (choice) => choiceTokens(
        choice
      ).some(
        (token) => wanted.has(
          token
        )
      )
    ) || null;
  }

  function backingFieldValues(
    question
  ) {
    const result = [];

    for (
      const element
      of fieldCandidates(
        question?.field_name
      )
    ) {
      const value =
        String(
          element.value
          ?? element.getAttribute(
            "value"
          )
          ?? ""
        );

      if (
        value !== ""
      ) {
        result.push(
          value
        );
      }
    }

    return result;
  }

  function backingValueMatches(
    question,
    answer
  ) {
    const expected =
      answerTokens(
        question,
        answer
      );

    const observed =
      backingFieldValues(question);

    return observed.some(
      (value) => tokenMatches(
        value,
        expected
      )
    );
  }

  function choiceIndexForAnswer(
    question,
    value
  ) {
    const tokens =
      answerTokens(
        question,
        value
      );

    return (
      question?.choices
      || []
    ).findIndex(
      (choice) => choiceTokens(
        choice
      ).some(
        (token) => tokens.includes(
          token
        )
      )
    );
  }

  async function keyboardSelectFallback(
    element,
    value,
    question
  ) {
    const opened =
      await openCombobox(
        element
      );

    if (
      !opened
      || !opened.input
    ) {
      return false;
    }

    try {
      opened.input.focus();
    } catch (error) {
      // No-op.
    }

    const index =
      choiceIndexForAnswer(
        question,
        value
      );

    if (index < 0) {
      return false;
    }

    for (
      let step = 0;
      step <= index;
      step += 1
    ) {
      dispatchKey(
        opened.input,
        "ArrowDown"
      );

      await sleep(70);
    }

    dispatchKey(
      opened.input,
      "Enter"
    );

    await sleep(350);
    return true;
  }

  async function selectCombobox(
    element,
    value,
    question = null
  ) {
    const tokens =
      answerTokens(
        question,
        value
      );

    if (!tokens.length) {
      return false;
    }

    const opened =
      await openCombobox(
        element
      );

    if (!opened) {
      return false;
    }

    let clickedMatchedOption =
      false;

    if (
      structuredEducationSelectQuestion(
        question
      )
      && opened.input
    ) {
      const searchValue =
        primaryChoiceAnswer(
          question,
          value
        );

      try {
        opened.input.focus();
      } catch (error) {
        // Continue with event-driven selection.
      }

      setComboboxSearchText(
        opened.input,
        String(
          searchValue
        )
      );

      await sleep(
        550
      );

      const filtered =
        findOptionForAnswer(
          opened,
          tokens,
          {
            allowContains: true,
          }
        );

      if (filtered) {
        await activateOption(
          filtered
        );

        try {
          opened.input.dispatchEvent(
            new Event(
              "change",
              {bubbles: true}
            )
          );

          opened.input.blur();
        } catch (error) {
          // Greenhouse validation remains final.
        }

        await sleep(
          500
        );

        let currentElement = (
          findSchemaControl(question)
          || element
        );

        if (
          (
            question
            && backingValueMatches(
              question,
              value
            )
          )
          || tokenMatches(
            visibleControlValue(
              currentElement
            ),
            tokens,
            {
              allowContains: true,
            }
          )
        ) {
          return true;
        }

        return false;
      }

      return false;
    }

    const selected =
      findOptionForAnswer(
        opened,
        tokens
      );

    if (selected) {
      await activateOption(
        selected
      );

      clickedMatchedOption =
        true;
    } else if (
      opened.input
    ) {
      setComboboxSearchText(
        opened.input,
        String(
          value
        )
      );

      await sleep(
        250
      );

      const filtered =
        findOptionForAnswer(
          opened,
          tokens,
          {
            allowContains: true,
          }
        );

      if (filtered) {
        await activateOption(
          filtered
        );

        clickedMatchedOption =
          true;
      }
    }

    await sleep(
      300
    );

    if (
      (
        question
        && backingValueMatches(
          question,
          value
        )
      )
      || tokenMatches(
        visibleControlValue(
          element
        ),
        tokens,
        {
          allowContains: true,
        }
      )
    ) {
      return true;
    }

    if (
      clickedMatchedOption
      && structuredEducationSelectQuestion(
        question
      )
    ) {
      return true;
    }

    if (opened.input) {
      const searchValue =
        matchingSchemaChoice(
          question,
          value
        )?.label
        || (
          Array.isArray(value)
            ? value[0]
            : value
        );

      setComboboxSearchText(
        opened.input,
        String(
          searchValue
        )
      );

      await sleep(
        450
      );

      const searched =
        findOptionForAnswer(
          opened,
          tokens,
          {
            allowContains: true,
          }
        );

      if (searched) {
        await activateOption(
          searched
        );

        clickedMatchedOption =
          true;
      }
    }

    if (
      (
        question
        && backingValueMatches(
          question,
          value
        )
      )
      || tokenMatches(
        visibleControlValue(element),
        tokens,
        {
          allowContains: true,
        }
      )
    ) {
      return true;
    }

    if (
      clickedMatchedOption
      && structuredEducationSelectQuestion(
        question
      )
    ) {
      return true;
    }

    // The visual option click did not commit Greenhouse's
    // actual form value. Retry using React-select keyboard
    // navigation, then verify the backing field again.
    await keyboardSelectFallback(
      element,
      value,
      question
    );

    await sleep(
      300
    );

    const verified = (
      (
        question
        && backingValueMatches(
          question,
          value
        )
      )
      || tokenMatches(
        visibleControlValue(element),
        tokens,
        {
          allowContains: true,
        }
      )
    );

    if (!verified) {
      console.warn(
        "JOBFINITUM GREENHOUSE SELECT DID NOT COMMIT",
        {
          question:
            question?.text,
          field_name:
            question?.field_name,
          answer:
            value,
          expected:
            matchingSchemaChoice(
              question,
              value
            ),
          observed_backing_values:
            backingFieldValues(
              question
            ),
        }
      );
    }

    return verified;
  }

  function normalizeChoiceAnswers(
    value
  ) {
    if (
      Array.isArray(
        value
      )
    ) {
      return value
        .map(
          (item) => normalize(
            item
          )
        )
        .filter(Boolean);
    }

    const text =
      normalize(
        value
      );

    if (!text) {
      return [];
    }

    if (
      text.startsWith(
        "["
      )
      && text.endsWith(
        "]"
      )
    ) {
      try {
        const parsed =
          JSON.parse(
            text
          );

        if (
          Array.isArray(
            parsed
          )
        ) {
          return parsed
            .map(
              (item) => normalize(
                item
              )
            )
            .filter(Boolean);
        }
      } catch (error) {
        // Fall back to the single saved answer.
      }
    }

    return [
      text,
    ];
  }

  async function clickChoiceControl(
    control
  ) {
    if (!control) {
      return false;
    }

    const label = (
      control.id
        ? document.querySelector(
            `label[for="${CSS.escape(control.id)}"]`
          )
        : null
    ) || control.closest(
      "label"
    );

    // Greenhouse attaches React behavior around the
    // visible option/label. Prefer that clickable label when
    // available instead of mutating or clicking the raw input.
    const target = (
      label
      || control
    );

    if (!target) {
      return false;
    }

    try {
      target.dispatchEvent(
        new PointerEvent(
          "pointerdown",
          {bubbles: true}
        )
      );
    } catch (error) {
      // No-op.
    }

    target.dispatchEvent(
      new MouseEvent(
        "mousedown",
        {bubbles: true}
      )
    );

    target.click();

    await sleep(180);
    return true;
  }

  async function setChoice(
    element,
    value,
    question = null
  ) {
    const type =
      lower(
        element.type
      );

    if (
      type === "radio"
    ) {
      const wantedTokens =
        answerTokens(
          question,
          value
        );

      const radio =
        groupControls(
          element
        ).find(
          (candidate) => (
            tokenMatches(
              candidate.value,
              wantedTokens
            )
            || tokenMatches(
              choiceLabel(
                candidate
              ),
              wantedTokens
            )
          )
        );

      if (!radio) {
        return false;
      }

      if (!radio.checked) {
        await clickChoiceControl(
          radio
        );
      }

      await sleep(
        700
      );

      return Boolean(
        radio.checked
      );
    }

    if (
      type === "checkbox"
    ) {
      const requested =
        normalizeChoiceAnswers(
          value
        );

      const wanted =
        new Set(
          answerTokens(
            question,
            requested
          )
        );

      if (!wanted.size) {
        return false;
      }

      const controls =
        groupControls(
          element
        );

      const requestedControls =
        controls.filter(
          (box) => (
            tokenMatches(
              box.value,
              [
                ...wanted,
              ]
            )
            || tokenMatches(
                choiceLabel(
                  box
                ),
                [
                  ...wanted,
                ]
            )
          )
        );

      if (
        requestedControls.length
        !== requested.length
      ) {
        console.warn(
          "JOBFINITUM GREENHOUSE CHECKBOX ANSWER DID NOT MAP",
          {
            requested,
            available:
              controls.map(
                (box) => ({
                  value:
                    box.value,
                  label:
                    choiceLabel(
                      box
                    ),
                  checked:
                    box.checked,
                })
              ),
          }
        );

        return false;
      }

      // Fresh Greenhouse application tabs start unchecked.
      // Only click the requested choices. Do not click every
      // non-requested box to force false; doing that can make
      // React process multiple state updates and revert the
      // choice that was just selected.
      for (
        const box
        of requestedControls
      ) {
        if (!box.checked) {
          await clickChoiceControl(
            box
          );

          await sleep(
            250
          );
        }
      }

      // Let Greenhouse React finish its controlled rerender
      // before deciding that the answer actually stuck.
      await sleep(
        1000
      );

      return requestedControls.every(
        (box) => (
          Boolean(
            box.checked
          )
        )
      );
    }

    return false;
  }

  function resolveEmployerChoiceAnswer(
    question,
    answer
  ) {
    if (
      answer === null
      || answer === undefined
      || answer === ""
    ) {
      return answer;
    }

    const choices =
      question?.choices
      || [];

    if (!choices.length) {
      return answer;
    }

    const resolveOne = (
      rawAnswer
    ) => {
      if (
        rawAnswer
        && typeof rawAnswer === "object"
      ) {
        rawAnswer =
          rawAnswer.label
          ?? rawAnswer.value
          ?? rawAnswer.platform_value
          ?? "";
      }

      const wanted =
        lower(
          normalize(
            rawAnswer
          )
        );

      if (!wanted) {
        return rawAnswer;
      }

      for (const choice of choices) {
        const label =
          normalize(
            (
              typeof choice === "object"
                ? choice.label
                : choice
            )
            || ""
          );

        const value =
          normalize(
            (
              typeof choice === "object"
                ? choice.value
                : choice
            )
            || ""
          );

        const platformValue =
          normalize(
            (
              typeof choice === "object"
                ? choice.platform_value
                : ""
            )
            || ""
          );

        if (
          wanted === lower(label)
          || wanted === lower(value)
          || (
            platformValue
            && wanted === lower(platformValue)
          )
        ) {
          return (
            label
            || value
            || platformValue
            || rawAnswer
          );
        }
      }

      return rawAnswer;
    };

    if (Array.isArray(answer)) {
      return answer.map(
        resolveOne
      );
    }

    return resolveOne(
      answer
    );
  }

  async function applyValue(
    element,
    value,
    question = null
  ) {
    if (
      value === null
      || value === undefined
      || value === ""
    ) {
      return false;
    }

    const resolvedValue =
      resolveEmployerChoiceAnswer(
        question,
        value
      );

    if (isCombobox(element)) {
      return selectCombobox(
        element,
        resolvedValue,
        question
      );
    }

    if (element.tagName === "SELECT") {
      const wantedValues =
        answerTokens(
          question,
          resolvedValue
        );

      for (
        const option
        of element.options
      ) {
        if (
          tokenMatches(
            option.value,
            wantedValues
          )
          || tokenMatches(
            option.textContent,
            wantedValues
          )
        ) {
          element.value =
            option.value;

          dispatchEvents(
            element
          );

          return true;
        }
      }

      return false;
    }

    const type =
      lower(
        element.type
      );

    if (
      type === "radio"
      || type === "checkbox"
    ) {
      return setChoice(
        element,
        resolvedValue,
        question
      );
    }

    if (
      [
        "hidden",
        "file",
        "submit",
        "button",
      ].includes(type)
    ) {
      return false;
    }

    return setText(
      element,
      resolvedValue
    );
  }

  function findGreenhousePhoneInput() {
    const selectors = [
      'input[type="tel"]',
      'input[autocomplete="tel-national"]',
      'input[autocomplete="tel"]',
      'input[name="phone"]',
      'input[name*="phone" i]',
      'input[id*="phone" i]',
    ];

    for (
      const selector
      of selectors
    ) {
      for (
        const element
        of document.querySelectorAll(
          selector
        )
      ) {
        if (
          isVisible(
            element
          )
          && lower(
            element.type
          ) !== "hidden"
        ) {
          return element;
        }
      }
    }

    return null;
  }

  function findPhoneCountryControl(
    phoneInput
  ) {
    if (!phoneInput) {
      return null;
    }

    const phoneCombo =
      phoneInput.closest(
        '[role="combobox"]'
      );

    const allCandidates = [
      ...document.querySelectorAll(
        [
          '[role="combobox"]',
          'select',
          'button[aria-haspopup="listbox"]',
          '[aria-haspopup="listbox"]',
        ].join(",")
      ),
    ].filter(
      (element) => (
        isVisible(
          element
        )
        && element !== phoneCombo
        && !element.contains(
          phoneInput
        )
      )
    );

    function contextText(
      element
    ) {
      const parts = [
        labelText(
          element
        ),
        element.getAttribute(
          "aria-label"
        ),
      ];

      let current =
        element.parentElement;

      for (
        let depth = 0;
        current
        && depth < 3;
        depth += 1
      ) {
        const text =
          normalize(
            current.innerText
            || current.textContent
          );

        if (
          text
          && text.length <= 220
        ) {
          parts.push(
            text
          );
        }

        current =
          current.parentElement;
      }

      return questionMatchKey(
        parts
          .filter(Boolean)
          .join(" ")
      );
    }

    for (
      const candidate
      of allCandidates
    ) {
      const context =
        contextText(
          candidate
        );

      if (
        context === "country"
        || context.startsWith(
          "country "
        )
        || context.includes(
          " phone country "
        )
      ) {
        return candidate;
      }
    }

    const preceding =
      allCandidates.filter(
        (candidate) => (
          Boolean(
            candidate.compareDocumentPosition(
              phoneInput
            )
            & Node.DOCUMENT_POSITION_FOLLOWING
          )
        )
      );

    if (
      preceding.length
    ) {
      return preceding[
        preceding.length - 1
      ];
    }

    return null;
  }

  function findActualGreenhouseCountryControl() {
    const selectors = [
      'input#country',
      'input[name="country"]',
      'input[autocomplete="country-name"]',
      'input[aria-label="Country" i]',
      'input[placeholder*="country" i]',
      '[role="combobox"][aria-label="Country" i]',
      '[role="combobox"][id*="country" i]',
    ];

    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (isVisible(element) && !element.disabled) {
          return canonicalControl(element) || element;
        }
      }
    }

    const labeled = findByLabel("Country");

    if (labeled && isVisible(labeled)) {
      return canonicalControl(labeled) || labeled;
    }

    return null;
  }

  async function selectPhoneCountry(
    countryControl,
    identity
  ) {
    const actualCountry =
      findActualGreenhouseCountryControl()
      || countryControl;

    if (!actualCountry) {
      console.warn(
        "JOBFINITUM GREENHOUSE ACTUAL COUNTRY CONTROL NOT FOUND"
      );
      return false;
    }

    const countryIso =
      String(
        identity.phone_country_iso
        || ""
      )
        .trim()
        .toUpperCase();

    let countryName =
      normalize(
        identity.phone_country_name
        || identity.country
      );

    if (countryIso) {
      try {
        countryName =
          new Intl.DisplayNames(
            ["en"],
            { type: "region" }
          ).of(countryIso)
          || countryName;
      } catch (error) {
        // Keep supplied profile country.
      }
    }

    if (!countryName) {
      return false;
    }

    let opened = null;
    let input = null;

    if (isCombobox(actualCountry)) {
      opened =
        await openCombobox(
          actualCountry
        );

      input =
        opened?.input
        || actualCountry.querySelector?.("input")
        || (
          actualCountry.tagName === "INPUT"
            ? actualCountry
            : null
        );
    } else {
      input =
        actualCountry.tagName === "INPUT"
          ? actualCountry
          : actualCountry.querySelector?.("input");

      try {
        actualCountry.click();
      } catch (error) {
        // Continue with input.
      }

      try {
        input?.focus();
      } catch (error) {
        // No-op.
      }
    }

    if (!input) {
      console.warn(
        "JOBFINITUM GREENHOUSE COUNTRY SEARCH INPUT NOT FOUND"
      );
      return false;
    }

    // Use Greenhouse's real Country autocomplete. Updating only
    // the phone dial-code display does not satisfy form state.
    try {
      input.focus();
    } catch (error) {
      // No-op.
    }

    setComboboxSearchText(
      input,
      countryName
    );

    await sleep(400);

    const wanted =
      lower(countryName);

    const options =
      visibleOptionNodes();

    const option =
      options.find(
        (node) => {
          const text =
            lower(
              node.innerText
              || node.textContent
            );

          return (
            text === wanted
            || text.startsWith(`${wanted} `)
            || text.includes(wanted)
          );
        }
      );

    if (option) {
      await activateOption(option);
    } else {
      dispatchKey(
        input,
        "ArrowDown"
      );

      await sleep(100);

      dispatchKey(
        input,
        "Enter"
      );
    }

    await sleep(500);

    try {
      input.dispatchEvent(
        new Event(
          "change",
          { bubbles: true }
        )
      );

      input.blur();

      dispatchKey(
        input,
        "Tab"
      );
    } catch (error) {
      // Greenhouse remains final validation authority.
    }

    await sleep(350);

    const value =
      lower(
        input.value
        || actualCountry.innerText
        || actualCountry.textContent
        || ""
      );

    if (!value.includes(wanted)) {
      console.warn(
        "JOBFINITUM GREENHOUSE COUNTRY FORM VALUE NOT CONFIRMED",
        {
          countryName,
          countryIso,
          value,
        }
      );
    }

    return true;
  }

  async function fillGreenhouseLocationCity(
    identity
  ) {
    const city =
      normalize(
        identity.city
        || identity.location_city
        || ""
      );

    if (!city) {
      return false;
    }

    const state =
      normalize(
        identity.state_region
        || identity.state
        || ""
      );

    const query =
      state
        ? `${city}, ${state}`
        : city;

    const selectors = [
      'input#location',
      'input[name="location"]',
      'input[autocomplete="address-level2"]',
      'input[placeholder*="city" i]',
    ];

    let input = null;

    for (const selector of selectors) {
      for (
        const element
        of document.querySelectorAll(
          selector
        )
      ) {
        if (
          isVisible(element)
          && !element.disabled
        ) {
          input = element;
          break;
        }
      }

      if (input) {
        break;
      }
    }

    if (!input) {
      const labeled =
        findByLabel(
          "Location (City)"
        )
        || findByLabel(
          "Location"
        );

      input =
        labeled?.tagName === "INPUT"
          ? labeled
          : labeled?.querySelector?.(
              "input"
            );
    }

    if (!input) {
      return false;
    }

    const combo =
      input.getAttribute(
        "role"
      ) === "combobox"
      || Boolean(
        input.closest(
          '[role="combobox"]'
        )
      );

    if (!combo) {
      setText(
        input,
        city
      );

      return true;
    }

    try {
      input.focus();
    } catch (error) {
      // No-op.
    }

    setComboboxSearchText(
      input,
      query
    );

    await sleep(
      450
    );

    const cityKey =
      lower(
        city
      );

    const option =
      visibleOptionNodes()
        .find(
          (node) => (
            lower(
              node.innerText
              || node.textContent
            ).includes(
              cityKey
            )
          )
        );

    if (option) {
      await activateOption(
        option
      );
    } else {
      dispatchKey(
        input,
        "ArrowDown"
      );

      await sleep(
        100
      );

      dispatchKey(
        input,
        "Enter"
      );
    }

    await sleep(
      350
    );

    return true;
  }

  async function fillGreenhousePhone(
    identity
  ) {
    const phoneInput =
      findGreenhousePhoneInput();

    if (!phoneInput) {
      return false;
    }

    const phoneValue =
      identity.phone_national
      || identity.phone
      || "";

    if (!phoneValue) {
      return false;
    }

    // Fill Phone before touching Country. Greenhouse rerenders
    // this combined React phone component when the number changes.
    setText(
      phoneInput,
      phoneValue
    );

    await sleep(
      350
    );

    // Re-find Country after the phone rerender and commit it last.
    const countryControl =
      findPhoneCountryControl(
        phoneInput
      );

    if (countryControl) {
      await selectPhoneCountry(
        countryControl,
        identity
      );

      await sleep(
        700
      );
    }

    return true;
  }

  function fillFirst(
    selectors,
    value
  ) {
    if (
      value === null
      || value === undefined
      || String(value) === ""
    ) {
      return false;
    }

    for (const selector of selectors) {
      for (
        const element
        of document.querySelectorAll(
          selector
        )
      ) {
        if (
          !element.disabled
          && !element.readOnly
          && setText(
            element,
            value
          )
        ) {
          return true;
        }
      }
    }

    return false;
  }

  function configuredYesNo(value) {
    if (value === true) {
      return "yes";
    }

    if (value === false) {
      return "no";
    }

    const configured =
      lower(value);

    if (
      [
        "yes",
        "true",
        "1",
      ].includes(configured)
    ) {
      return "yes";
    }

    if (
      [
        "no",
        "false",
        "0",
      ].includes(configured)
    ) {
      return "no";
    }

    return "";
  }

  function isScopedExperienceQuestion(
    questionText
  ) {
    const normalized =
      lower(
        questionText
      )
        .replace(
          /[^a-z0-9]+/g,
          " "
        )
        .trim();

    if (
      !normalized.includes(
        "years"
      )
      || !normalized.includes(
        "experience"
      )
    ) {
      return false;
    }

    const generic = [
      "years of experience",
      "total years of experience",
      "how many years of experience do you have",
      "how many total years of experience do you have",
      "how many years of professional experience do you have",
      "how many years of work experience do you have",
      "what are your total years of experience",
      "what is your total years of experience",
    ];

    return !generic.includes(
      normalized
    );
  }

  function reusableAnswer(
    task,
    questionText
  ) {
    const question =
      lower(questionText);

    const values =
      task.reusable_answers || {};

    const sensitivePatterns = [
      "race",
      "ethnicity",
      "gender",
      "sex",
      "sexual orientation",
      "disability",
      "veteran",
      "religion",
    ];

    if (
      sensitivePatterns.some(
        (pattern) => (
          question.includes(pattern)
        )
      )
    ) {
      return null;
    }

    const yesNoRules = [
      [
        [
          "18 or older",
          "18 years of age or older",
          "18 years old or older",
          "at least 18",
          "over the age of 18",
        ],
        values.is_18_or_older,
      ],
      [
        [
          "authorized to work",
          "legally authorized to work",
          "eligible to work",
          "work authorization",
        ],
        values.work_authorization_default,
      ],
      [
        [
          "require sponsorship",
          "requires sponsorship",
          "need sponsorship",
          "visa sponsorship",
          "immigration sponsorship",
        ],
        values.sponsorship_default,
      ],
      [
        [
          "willing to relocate",
          "open to relocation",
          "able to relocate",
        ],
        values.willing_to_relocate,
      ],
      [
        [
          "willing to travel",
          "able to travel",
          "open to travel",
        ],
        values.willing_to_travel,
      ],
    ];

    for (
      const [
        patterns,
        rawValue,
      ]
      of yesNoRules
    ) {
      const configured =
        configuredYesNo(rawValue);

      if (
        configured
        && patterns.some(
          (pattern) => (
            question.includes(pattern)
          )
        )
      ) {
        return (
          configured === "yes"
            ? "Yes"
            : "No"
        );
      }
    }

    if (
      [
        "years of experience",
        "how many years",
        "years experience",
      ].some(
        (pattern) => (
          question.includes(pattern)
        )
      )
      && values.years_of_experience
        !== null
      && values.years_of_experience
        !== undefined
    ) {
      return String(
        values.years_of_experience
      );
    }

    if (
      [
        "salary expectation",
        "salary expectations",
        "base salary expectation",
        "desired salary",
        "expected salary",
        "compensation expectation",
        "compensation expectations",
        "desired compensation",
      ].some(
        (pattern) => (
          question.includes(pattern)
        )
      )
      && values.salary_expectation
    ) {
      return String(
        values.salary_expectation
      );
    }

    if (
      [
        "available to start",
        "availability to start",
        "start date",
        "earliest start",
        "earliest available",
      ].some(
        (pattern) => (
          question.includes(pattern)
        )
      )
      && values.available_start_date
    ) {
      return String(
        values.available_start_date
      );
    }

    return null;
  }

  function schemaType(field) {
    const type =
      String(
        field?.type || ""
      ).trim();

    const mapping = {
      input_text: "text",
      textarea: "textarea",
      multi_value_single_select:
        "select",
      multi_value_multi_select:
        "checkbox",
      input_file: "file",
      input_hidden: "hidden",
    };

    return (
      mapping[type]
      || "text"
    );
  }

  function schemaChoices(field) {
    const values =
      Array.isArray(field?.values)
        ? field.values
        : [];

    return values
      .map(
        (item) => {
          const label =
            normalize(
              item?.label
              ?? item?.value
              ?? ""
            );

          return {
            // Jobfinitum stores the human answer.
            value: label,
            label,

            // Keep Greenhouse's real backing value too.
            // React may display "Yes" while the form field
            // itself stores something like 0 or 1.
            platform_value:
              String(
                item?.value
                ?? item?.label
                ?? ""
              ),
          };
        }
      )
      .filter(
        (item) => item.label
      );
  }

  function schemaFieldRichness(
    field
  ) {
    const type =
      String(
        field?.type || ""
      );

    const values =
      Array.isArray(
        field?.values
      )
        ? field.values
        : [];

    const typeScore = {
      multi_value_single_select: 500,
      multi_value_multi_select: 500,
      textarea: 100,
      input_text: 50,
      input_file: 10,
      input_hidden: 0,
    }[type] || 0;

    return (
      typeScore
      + (
        values.length
        * 1000
      )
    );
  }

  function normalizedSchemaQuestions(
    schema
  ) {
    const result = [];

    for (
      const rawQuestion
      of (
        Array.isArray(
          schema?.questions
        )
          ? schema.questions
          : []
      )
    ) {
      const fields =
        Array.isArray(
          rawQuestion?.fields
        )
          ? rawQuestion.fields
          : [];

      const visibleFields =
        fields.filter(
          (field) => (
            String(
              field?.type || ""
            ) !== "input_hidden"
          )
        );

      const primary = (
        [...visibleFields]
          .sort(
            (left, right) => (
              schemaFieldRichness(
                right
              )
              - schemaFieldRichness(
                  left
                )
            )
          )[0]
        || fields[0]
      );

      if (!primary) {
        continue;
      }

      result.push({
        field_name:
          String(
            primary.name || ""
          ),
        text:
          normalize(
            rawQuestion.label
          ),
        type:
          schemaType(primary),
        required:
          Boolean(
            rawQuestion.required
          ),
        choices:
          schemaChoices(primary),
        adapter:
          "greenhouse_hosted",
      });
    }

    return result;
  }

  function standardSchemaQuestion(
    question
  ) {
    const field =
      lower(
        question.field_name
      );

    const text =
      lower(
        question.text
      );

    // Greenhouse Country + Phone are identity controls handled
    // only by fillGreenhousePhone(). They must never enter the
    // generic employer-question loop because Greenhouse renders
    // them inside one controlled React phone component.
    if (
      field.includes(
        "phone"
      )
      || field.includes(
        "country"
      )
      || text === "phone"
      || text === "country"
      || text === "location (city)"
      || text === "location city"
      || field === "location"
      || field === "location_city"
      || text.startsWith(
        "phone "
      )
      || text.startsWith(
        "country "
      )
      || (
        field.includes(
          "education"
        )
        && [
          "school",
          "school name",
          "degree",
          "discipline",
          "field of study",
          "major",
          "start date year",
          "start year",
          "end date year",
          "end year",
          "graduation year",
        ].includes(text)
      )
    ) {
      return true;
    }

    return [
      "first_name",
      "last_name",
      "email",
      "phone",
      "country",
      "resume",
      "resume_text",
      "cover_letter",
      "cover_letter_text",
    ].includes(
      field
    );
  }

  function profileAnswerForQuestion(
    task,
    question
  ) {
    const identity =
      task.identity
      || {};

    const reusable =
      task.reusable_answers
      || task.reusable
      || {};

    const profile =
      task.applicant_profile
      || task.profile
      || {};

    const text =
      lower(
        question?.text
      );

    const field =
      lower(
        question?.field_name
      );

    const firstValue = (
      ...values
    ) => {
      for (const value of values) {
        if (
          value !== null
          && value !== undefined
          && value !== ""
        ) {
          return value;
        }
      }

      return null;
    };

    if (
      text.includes("linkedin")
      || field.includes("linkedin")
    ) {
      return firstValue(
        identity.linkedin_url,
        profile.linkedin_url
      );
    }

    if (
      text.includes("github")
      || field.includes("github")
    ) {
      return firstValue(
        identity.github_url,
        profile.github_url
      );
    }

    if (
      text === "website"
      || text.includes("portfolio")
      || field.includes("website")
      || field.includes("portfolio")
    ) {
      return firstValue(
        identity.website_url,
        profile.website_url
      );
    }

    if (
      text === "location (city)"
      || text === "location city"
      || text === "city"
      || field === "location"
      || field === "location_city"
      || field === "city"
    ) {
      return firstValue(
        identity.city,
        identity.location_city,
        profile.city
      );
    }

    if (
      text.includes("work authorization")
      || text.includes("authorization to work")
      || text.includes("authorized to work")
      || text.includes("eligible to work")
      || field.includes("work_authorization")
    ) {
      return firstValue(
        reusable.work_authorization_default,
        identity.work_authorization_default,
        profile.work_authorization_default,
        reusable.work_authorization
      );
    }

    if (
      text.includes("sponsorship")
      || field.includes("sponsorship")
    ) {
      return firstValue(
        reusable.sponsorship_default,
        identity.sponsorship_default,
        profile.sponsorship_default
      );
    }

    if (
      text.includes("salary expectation")
      || text.includes("expected salary")
      || text.includes("desired salary")
      || text.includes("compensation expectation")
    ) {
      return firstValue(
        reusable.salary_expectation,
        identity.salary_expectation,
        profile.salary_expectation
      );
    }

    return null;
  }

  function authoritativeProfileIdentityQuestion(
    question
  ) {
    const text =
      lower(
        question?.text
      );

    const field =
      lower(
        question?.field_name
      );

    return (
      text.includes("linkedin")
      || field.includes("linkedin")
      || text.includes("github")
      || field.includes("github")
      || text === "website"
      || text.includes("portfolio")
      || field.includes("website")
      || field.includes("portfolio")
      || text === "location (city)"
      || text === "location city"
      || field === "location"
      || field === "location_city"
      || field === "city"
    );
  }

  function savedAnswerFor(
    task,
    question
  ) {
    const questions =
      task.application_questions || [];

    const wantedField =
      lower(
        question.field_name
      );

    const wantedText =
      lower(
        question.text
      );

    let fuzzy = null;

    for (const saved of questions) {
      if (
        saved.answer === null
        || saved.answer === undefined
        || saved.answer === ""
      ) {
        continue;
      }

      if (
        wantedField
        && lower(
          saved.field_name
        ) === wantedField
      ) {
        return saved.answer;
      }

      const savedText =
        lower(saved.text);

      if (
        savedText === wantedText
      ) {
        return saved.answer;
      }

      if (
        !fuzzy
        && savedText
        && wantedText
        && (
          savedText.includes(
            wantedText
          )
          || wantedText.includes(
            savedText
          )
        )
      ) {
        fuzzy = saved.answer;
      }
    }

    return fuzzy;
  }

  function savedQuestionFor(
    task,
    question
  ) {
    const questions =
      task.application_questions || [];

    const wantedField =
      lower(
        question?.field_name
      );

    const wantedText =
      lower(
        question?.text
      );

    let fuzzy = null;

    for (const saved of questions) {
      if (!saved) {
        continue;
      }

      if (
        wantedField
        && lower(
          saved.field_name
        ) === wantedField
      ) {
        return saved;
      }

      const savedText =
        lower(saved.text);

      if (
        savedText
        && savedText === wantedText
      ) {
        return saved;
      }

      if (
        !fuzzy
        && savedText
        && wantedText
        && (
          savedText.includes(
            wantedText
          )
          || wantedText.includes(
            savedText
          )
        )
      ) {
        fuzzy = saved;
      }
    }

    return fuzzy;
  }

  function uploadFieldMarker(kind) {
    const wanted = (
      kind === "resume"
        ? ["resume", "resume cv", "cv"]
        : ["cover letter"]
    );

    const candidates = [
      ...document.querySelectorAll(
        [
          "label",
          "legend",
          "h1",
          "h2",
          "h3",
          "h4",
          "span",
          "p",
          "div",
        ].join(",")
      ),
    ]
      .map((node) => ({
        node,
        key:
          questionMatchKey(
            node.innerText
            || node.textContent
          ),
      }))
      .filter(
        ({node, key}) => (
          key
          && isVisible(node)
          && wanted.some(
            (value) => (
              key === value
              || key.startsWith(
                `${value} `
              )
            )
          )
        )
      )
      .sort(
        (left, right) => (
          left.key.length
          - right.key.length
        )
      );

    return candidates[0]?.node || null;
  }

  function nodeFollows(
    node,
    marker
  ) {
    return Boolean(
      node
      && marker
      && (
        node === marker
        || marker.contains(node)
        || (
          marker.compareDocumentPosition(
            node
          )
          & Node.DOCUMENT_POSITION_FOLLOWING
        )
      )
    );
  }

  function nodePrecedes(
    node,
    marker
  ) {
    return Boolean(
      !marker
      || node === marker
      || (
        node.compareDocumentPosition(
          marker
        )
        & Node.DOCUMENT_POSITION_FOLLOWING
      )
    );
  }

  function inResumeUploadSection(
    node,
    resumeMarker = uploadFieldMarker(
      "resume"
    ),
    coverMarker = uploadFieldMarker(
      "cover_letter"
    )
  ) {
    return (
      nodeFollows(
        node,
        resumeMarker
      )
      && nodePrecedes(
        node,
        coverMarker
      )
    );
  }

  function uploadControlMeta(element) {
    const parts = [
      element.name,
      element.id,
      element.getAttribute?.(
        "aria-label"
      ),
      element.getAttribute?.(
        "data-testid"
      ),
      element.getAttribute?.(
        "data-field"
      ),
      rawLabelText(element),
    ];

    let current =
      element.parentElement;

    for (
      let depth = 0;
      current && depth < 5;
      depth += 1
    ) {
      const text =
        normalize(
          current.innerText
          || current.textContent
        );

      if (
        text
        && text.length <= 600
      ) {
        parts.push(text);
      }

      current =
        current.parentElement;
    }

    return lower(
      parts.join(" ")
    );
  }

  function resumeInput() {
    const inputs = [
      ...document.querySelectorAll(
        'input[type="file"]'
      ),
    ];

    if (!inputs.length) {
      return null;
    }

    const resumeMarker =
      uploadFieldMarker(
        "resume"
      );

    const coverMarker =
      uploadFieldMarker(
        "cover_letter"
      );

    const scored =
      inputs
        .map(
          (input, index) => {
            const meta =
              uploadControlMeta(
                input
              );

            let score = 0;

            if (
              meta.includes("resume")
              || /(^|\s)cv($|\s)/.test(
                meta
              )
            ) {
              score += 120;
            }

            if (
              meta.includes(
                "cover letter"
              )
            ) {
              score -= 160;
            }

            if (
              inResumeUploadSection(
                input,
                resumeMarker,
                coverMarker
              )
            ) {
              score += 200;
            }

            // Greenhouse renders Resume before Cover Letter. Keep
            // document order only as a low-priority final tiebreaker.
            score -= index;

            return {
              input,
              score,
            };
          }
        )
        .sort(
          (left, right) => (
            right.score
            - left.score
          )
        );

    if (
      scored[0]?.score > 0
    ) {
      return scored[0].input;
    }

    return (
      inputs.length === 1
        ? inputs[0]
        : null
    );
  }

  function resumeAttachControl() {
    const resumeMarker =
      uploadFieldMarker(
        "resume"
      );

    if (!resumeMarker) {
      return null;
    }

    const coverMarker =
      uploadFieldMarker(
        "cover_letter"
      );

    const candidates = [
      ...document.querySelectorAll(
        [
          "button",
          '[role="button"]',
          'input[type="button"]',
          "label",
        ].join(",")
      ),
    ];

    return candidates.find(
      (node) => {
        if (
          !isVisible(node)
          || !inResumeUploadSection(
            node,
            resumeMarker,
            coverMarker
          )
        ) {
          return false;
        }

        const text =
          lower(
            node.innerText
            || node.textContent
            || node.value
            || node.getAttribute?.(
              "aria-label"
            )
          );

        return (
          text === "attach"
          || text === "upload"
          || text === "browse"
          || text === "choose file"
          || text.includes(
            "attach resume"
          )
          || text.includes(
            "upload resume"
          )
        );
      }
    ) || null;
  }

  async function waitForResumeInput(
    timeoutMs
  ) {
    const started =
      Date.now();

    while (
      Date.now() - started
      < timeoutMs
    ) {
      const input =
        resumeInput();

      if (input) {
        return input;
      }

      await sleep(100);
    }

    return null;
  }

  function resumeAlreadyAttached(file) {
    const selected =
      resumeInput();

    if (
      selected?.files?.length
    ) {
      return true;
    }

    const resumeMarker =
      uploadFieldMarker(
        "resume"
      );

    if (!resumeMarker) {
      return false;
    }

    const coverMarker =
      uploadFieldMarker(
        "cover_letter"
      );

    const expectedName =
      lower(file?.name);

    const controls = [
      ...document.querySelectorAll(
        [
          "button",
          '[role="button"]',
          "a",
          "span",
        ].join(",")
      ),
    ].filter(
      (node) => inResumeUploadSection(
        node,
        resumeMarker,
        coverMarker
      )
    );

    const sectionText =
      lower(
        controls
          .map(
            (node) => (
              node.innerText
              || node.textContent
              || node.getAttribute?.(
                "aria-label"
              )
              || ""
            )
          )
          .join(" ")
      );

    return Boolean(
      (
        expectedName
        && sectionText.includes(
          expectedName
        )
      )
      || (
        !sectionText.includes(
          "attach"
        )
        && (
          sectionText.includes(
            "remove"
          )
          || sectionText.includes(
            "replace"
          )
          || sectionText.includes(
            "change file"
          )
        )
      )
    );
  }

  async function fetchResume(
    launch,
    task
  ) {
    const response =
      await send({
        type:
          "jobfinitum-resume",
        origin:
          launch.origin,
        url:
          task.resume.url,
      });

    const binary =
      atob(response.base64);

    const bytes =
      new Uint8Array(
        binary.length
      );

    for (
      let index = 0;
      index < binary.length;
      index += 1
    ) {
      bytes[index] =
        binary.charCodeAt(index);
    }

    return new File(
      [bytes],
      task.resume.filename,
      {
        type: (
          task.resume.content_type
          || response.contentType
          || "application/octet-stream"
        ),
      }
    );
  }

  async function setResumeFile(file) {
    if (
      resumeAlreadyAttached(file)
    ) {
      return true;
    }

    let selected =
      await waitForResumeInput(
        4000
      );

    // Some Greenhouse boards create the hidden file input only
    // after Attach is activated. Suppress the native picker while
    // allowing Greenhouse to materialize that input for assignment.
    if (!selected) {
      const attach =
        resumeAttachControl();

      if (attach) {
        const suppressPicker =
          (event) => {
            if (
              lower(
                event.target?.type
              ) === "file"
            ) {
              event.preventDefault();
              event.stopImmediatePropagation();
            }
          };

        document.addEventListener(
          "click",
          suppressPicker,
          true
        );

        try {
          attach.click();
          await sleep(120);
        } finally {
          document.removeEventListener(
            "click",
            suppressPicker,
            true
          );
        }

        selected =
          await waitForResumeInput(
            2000
          );
      }
    }

    if (!selected) {
      return resumeAlreadyAttached(
        file
      );
    }

    const transfer =
      new DataTransfer();

    transfer.items.add(file);

    const filesSetter =
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "files"
      )?.set;

    if (filesSetter) {
      filesSetter.call(
        selected,
        transfer.files
      );
    } else {
      selected.files =
        transfer.files;
    }

    selected.dispatchEvent(
      new Event(
        "input",
        {
          bubbles: true,
          composed: true,
        }
      )
    );

    selected.dispatchEvent(
      new Event(
        "change",
        {
          bubbles: true,
          composed: true,
        }
      )
    );

    await sleep(500);

    return Boolean(
      selected.files?.length
      || resumeAlreadyAttached(
        file
      )
    );
  }

  function selectedCheckboxLabels(
    element
  ) {
    return groupControls(
      element
    )
      .filter(
        (control) => (
          Boolean(
            control.checked
          )
        )
      )
      .map(
        (control) => lower(
          choiceLabel(
            control
          )
          || control.value
        )
      )
      .filter(Boolean);
  }

  function visibleControlValue(
    element
  ) {
    if (!element) {
      return "";
    }

    if (
      isCombobox(
        element
      )
    ) {
      const input = (
        element.tagName === "INPUT"
          ? element
          : element.querySelector(
              "input"
            )
      );

      const inputValue =
        normalize(
          input?.value
        );

      if (
        inputValue
        && ![
          "select",
          "select...",
          "choose",
          "choose...",
        ].includes(
          lower(
            inputValue
          )
        )
      ) {
        return inputValue;
      }

      const ariaValue =
        normalize(
          element.getAttribute(
            "aria-valuetext"
          )
        );

      if (ariaValue) {
        return ariaValue;
      }

      const text =
        normalize(
          element.innerText
          || element.textContent
        );

      if (
        text
        && ![
          "select",
          "select...",
          "choose",
          "choose...",
        ].includes(
          lower(
            text
          )
        )
      ) {
        return text;
      }

      return "";
    }

    if (
      element.tagName
      === "SELECT"
    ) {
      const option =
        element.options[
          element.selectedIndex
        ];

      return normalize(
        option?.textContent
        || option?.value
        || element.value
      );
    }

    return normalize(
      element.value
      || element.textContent
    );
  }

  function questionHasAnswer(
    question,
    element
  ) {
    if (!element) {
      return false;
    }

    const questionType =
      lower(
        question?.type
        || element.type
      );

    if (
      questionType === "checkbox"
      || lower(
        element.type
      ) === "checkbox"
    ) {
      return groupControls(
        element
      ).some(
        (control) => (
          Boolean(
            control.checked
          )
        )
      );
    }

    if (
      questionType === "radio"
      || lower(
        element.type
      ) === "radio"
    ) {
      return groupControls(
        element
      ).some(
        (control) => (
          Boolean(
            control.checked
          )
        )
      );
    }

    if (
      isCombobox(
        element
      )
    ) {
      const backing =
        backingFieldValues(
          question
        ).filter(
          (value) => {
            const normalized =
              lower(
                value
              );

            return (
              normalized
              && ![
                "select",
                "select...",
                "choose",
                "choose...",
              ].includes(
                normalized
              )
            );
          }
        );

      if (
        backing.length
      ) {
        return true;
      }

      const visible =
        lower(
          visibleControlValue(
            element
          )
        );

      return Boolean(
        visible
        && ![
          "select",
          "select...",
          "choose",
          "choose...",
        ].includes(
          visible
        )
      );
    }

    if (
      element.tagName
      === "SELECT"
    ) {
      const option =
        element.options[
          element.selectedIndex
        ];

      const value =
        lower(
          option?.value
          || option?.textContent
          || element.value
        );

      return Boolean(
        value
        && ![
          "select",
          "select...",
          "choose",
          "choose...",
        ].includes(
          value
        )
      );
    }

    return Boolean(
      normalize(
        element.value
        || element.textContent
      )
    );
  }

  function questionSatisfied(
    question,
    element,
    expectedAnswer
  ) {
    if (!element) {
      return false;
    }

    const type =
      lower(
        question?.type
        || element.type
      );

    if (
      type === "checkbox"
      || lower(
        element.type
      ) === "checkbox"
    ) {
      const expectedAnswers =
        normalizeChoiceAnswers(
          expectedAnswer
        );

      if (!expectedAnswers.length) {
        return false;
      }

      const selected =
        selectedCheckboxLabels(
          element
        );

      return expectedAnswers.every(
        (answer) => (
          selected.some(
            (item) => tokenMatches(
              item,
              answerTokens(
                question,
                answer
              )
            )
          )
        )
      );
    }

    if (
      type === "radio"
      || lower(
        element.type
      ) === "radio"
    ) {
      const wanted =
        answerTokens(
          question,
          expectedAnswer
        );

      return groupControls(
        element
      ).some(
        (control) => (
          control.checked
          && (
            tokenMatches(
              control.value,
              wanted
            )
            || tokenMatches(
              choiceLabel(
                control
              ),
              wanted
            )
          )
        )
      );
    }

    const wanted =
      answerTokens(
        question,
        expectedAnswer
      );

    if (
      !wanted.length
    ) {
      return false;
    }

    if (
      question
      && backingValueMatches(
        question,
        expectedAnswer
      )
    ) {
      return true;
    }

    return tokenMatches(
      visibleControlValue(
        element
      ),
      wanted,
      {
        allowContains: true,
      }
    );
  }

  async function report(
    launch,
    payload
  ) {
    return send({
      type:
        "jobfinitum-result",
      origin:
        launch.origin,
      token:
        launch.token,
      payload,
    });
  }

  async function closeCompletedAgentTab(
    launch
  ) {
    if (isBatchRunner()) {
      return;
    }

    try {
      await send({
        type:
          "jobfinitum-close-agent-tab",
        origin:
          launch.origin,
      });
    } catch (error) {
      console.warn(
        "Jobfinitum could not close the completed Greenhouse tab:",
        error
      );
    }
  }

  function visibleCaptcha() {
    return [
      ...document.querySelectorAll(
        [
          'iframe[src*="recaptcha"]',
          'iframe[src*="hcaptcha"]',
          'iframe[src*="challenges.cloudflare.com"]',
        ].join(",")
      ),
    ].some(
      (frame) => {
        const rect =
          frame.getBoundingClientRect();

        const style =
          getComputedStyle(frame);

        return (
          style.display !== "none"
          && style.visibility !== "hidden"
          && rect.width > 20
          && rect.height > 20
        );
      }
    );
  }

  function greenhouseControlInvalid(
    element
  ) {
    if (!element) {
      return false;
    }

    if (
      lower(
        element.getAttribute("aria-invalid")
      ) === "true"
      || lower(
        element.getAttribute("data-invalid")
      ) === "true"
    ) {
      return true;
    }

    const nestedInvalid =
      element.querySelector?.(
        '[aria-invalid="true"], [data-invalid="true"]'
      );

    if (nestedInvalid) {
      return true;
    }

    const rect =
      element.getBoundingClientRect();

    const errors = [
      ...document.querySelectorAll(
        [
          '[role="alert"]',
          '[class*="error"]',
          '[class*="Error"]',
        ].join(",")
      ),
    ].filter(
      (node) => isVisible(node)
    );

    for (const node of errors) {
      const message =
        lower(
          node.innerText
          || node.textContent
        );

      if (
        !message
        || !(
          message.includes("required")
          || message.includes("select a")
          || message.includes("please select")
          || message.includes("please enter")
          || message.includes("invalid")
        )
      ) {
        continue;
      }

      const errorRect =
        node.getBoundingClientRect();

      const verticallyClose = (
        errorRect.top >= rect.top - 20
        && errorRect.top <= rect.bottom + 100
      );

      const horizontallyRelated = (
        errorRect.right >= rect.left - 30
        && errorRect.left <= rect.right + 30
      );

      if (
        verticallyClose
        && horizontallyRelated
      ) {
        return true;
      }
    }

    // React comboboxes can keep an internal required input whose
    // native validity is false even while the visible selection is
    // valid. For controlled selects, trust Greenhouse's own markers.
    if (
      isCombobox(element)
      || element.getAttribute("role") === "combobox"
      || element.closest?.('[role="combobox"]')
    ) {
      return false;
    }

    try {
      if (
        typeof element.checkValidity === "function"
        && !element.checkValidity()
      ) {
        return true;
      }
    } catch (error) {
      // Ignore unavailable native validity.
    }

    return false;
  }

  function greenhouseInvalidQuestions(
    schemaQuestions
  ) {
    const result = [];

    for (
      const question
      of schemaQuestions
    ) {
      if (
        !question.required
        || standardSchemaQuestion(
          question
        )
      ) {
        continue;
      }

      const element =
        findSchemaControl(
          question
        );

      if (!element) {
        continue;
      }

      // For grouped checkbox/radio questions, the important
      // validity condition is whether the GROUP has a selected
      // answer. Calling native checkValidity() on one unchecked
      // checkbox can falsely report the entire question invalid
      // even when another option is visibly checked.
      const type =
        lower(
          question.type
          || element.type
        );

      if (
        type === "checkbox"
        || lower(
          element.type
        ) === "checkbox"
      ) {
        const checked =
          groupControls(
            element
          ).some(
            (control) => (
              Boolean(
                control.checked
              )
            )
          );

        if (checked) {
          continue;
        }
      }

      if (
        type === "radio"
        || lower(
          element.type
        ) === "radio"
      ) {
        const checked =
          groupControls(
            element
          ).some(
            (control) => (
              Boolean(
                control.checked
              )
            )
          );

        if (checked) {
          continue;
        }
      }

      if (
        greenhouseControlInvalid(
          element
        )
      ) {
        result.push(
          question
        );
      }
    }

    return result;
  }

  function findSubmit() {
    return [
      ...document.querySelectorAll(
        'button, input[type="submit"]'
      ),
    ].find(
      (element) => {
        const text =
          lower(
            element.innerText
            || element.value
            || element.getAttribute(
              "aria-label"
            )
          );

        return (
          !element.disabled
          && (
            text ===
              "submit application"
            || text ===
              "submit"
            || text.includes(
              "submit application"
            )
          )
        );
      }
    ) || null;
  }

  function visibleInteractiveVerificationChallenge() {
    const selectors = [
      'iframe[src*="hcaptcha" i]',
      'iframe[src*="recaptcha" i]',
      'iframe[title*="captcha" i]',
      'iframe[title*="challenge" i]',
      '.h-captcha',
      '.g-recaptcha',
      '[data-sitekey]',
      '[class*="captcha" i]',
      '[id*="captcha" i]',
    ];

    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!isVisible(element)) {
          continue;
        }

        const rect = element.getBoundingClientRect();

        if (
          rect.width >= 40
          && rect.height >= 30
        ) {
          return true;
        }
      }
    }

    return false;
  }

  function visibleVerificationError() {
    const candidates = [
      ...document.querySelectorAll(
        [
          '[role="alert"]',
          '[class*="error" i]',
          '[data-testid*="error" i]',
          '[aria-live="assertive"]',
        ].join(",")
      ),
    ].filter(
      (element) => isVisible(element)
    );

    return candidates.some(
      (element) => {
        const text = lower(
          element.innerText
          || element.textContent
        );

        return VERIFY_PHRASES.some(
          (phrase) => text.includes(phrase)
        );
      }
    );
  }

  const GREENHOUSE_EDUCATION_FIELDS = [
    {
      key: "greenhouse_education_school",
      field_name: "greenhouse_education_school",
      text: "School",
      labels: [
        "School",
        "School name",
        "College",
        "University",
      ],
      preferred_type: "select",
    },
    {
      key: "greenhouse_education_degree",
      field_name: "greenhouse_education_degree",
      text: "Degree",
      labels: [
        "Degree",
        "Degree type",
      ],
      preferred_type: "select",
    },
    {
      key: "greenhouse_education_discipline",
      field_name: "greenhouse_education_discipline",
      text: "Discipline",
      labels: [
        "Discipline",
        "Field of study",
        "Major",
      ],
      preferred_type: "select",
    },
    {
      key: "greenhouse_education_start_year",
      field_name: "greenhouse_education_start_year",
      text: "Start date year",
      labels: [
        "Start date year",
        "Start year",
      ],
      preferred_type: "number",
    },
    {
      key: "greenhouse_education_end_year",
      field_name: "greenhouse_education_end_year",
      text: "End date year",
      labels: [
        "End date year",
        "End year",
        "Graduation year",
      ],
      preferred_type: "number",
    },
  ];

  function greenhouseEducationComboboxFromLabel(
    labelText
  ) {
    const wanted =
      lower(
        normalize(
          labelText
        ).replace(
          /\s*\*\s*$/,
          ""
        )
      );

    if (!wanted) {
      return null;
    }

    for (
      const label
      of document.querySelectorAll(
        "label, legend"
      )
    ) {
      const actual =
        lower(
          normalize(
            label.innerText
            || label.textContent
          ).replace(
            /\s*\*\s*$/,
            ""
          )
        );

      if (
        actual !== wanted
      ) {
        continue;
      }

      const htmlFor =
        String(
          label.getAttribute?.("for")
          || label.htmlFor
          || ""
        ).trim();

      if (htmlFor) {
        const linked =
          document.getElementById(
            htmlFor
          );

        if (
          linked
          && isVisible(linked)
        ) {
          const linkedControl =
            canonicalControl(linked)
            || linked;

          if (
            isCombobox(linkedControl)
            || lower(
              linked.getAttribute?.(
                "aria-autocomplete"
              )
            ) === "list"
            || linked.getAttribute?.(
              "aria-controls"
            )
            || linked.getAttribute?.(
              "aria-owns"
            )
          ) {
            return linkedControl;
          }
        }
      }

      let current =
        label.parentElement;

      for (
        let depth = 0;
        current && depth < 4;
        depth += 1
      ) {
        const relevantLabels =
          [
            ...current.querySelectorAll(
              "label, legend"
            ),
          ]
            .map(
              (node) =>
                lower(
                  normalize(
                    node.innerText
                    || node.textContent
                  ).replace(
                    /\s*\*\s*$/,
                    ""
                  )
                )
            )
            .filter(Boolean);

        const controls =
          [
            ...current.querySelectorAll(
              [
                '[role="combobox"]',
                '[aria-haspopup="listbox"]',
                'input[aria-autocomplete="list"]',
                'input[aria-controls]',
                'input[aria-owns]',
              ].join(",")
            ),
          ]
            .map(
              (node) =>
                canonicalControl(node)
                || node
            )
            .filter(
              (node, index, items) => (
                node
                && isVisible(node)
                && items.indexOf(node)
                  === index
              )
            );

        const containsAnotherEducationLabel =
          relevantLabels.some(
            (value) => (
              value !== wanted
              && [
                "school",
                "school name",
                "college",
                "university",
                "degree",
                "degree type",
                "discipline",
                "field of study",
                "major",
                "start date year",
                "start year",
                "end date year",
                "end year",
                "graduation year",
              ].includes(value)
            )
          );

        if (
          controls.length === 1
          && !containsAnotherEducationLabel
        ) {
          return controls[0];
        }

        if (
          containsAnotherEducationLabel
        ) {
          break;
        }

        current =
          current.parentElement;
      }
    }

    return null;
  }

  function greenhouseEducationControl(
    definition
  ) {
    const wantsSelect =
      definition.preferred_type
      === "select";

    for (
      const label
      of definition.labels
    ) {
      if (wantsSelect) {
        const structured =
          greenhouseEducationComboboxFromLabel(
            label
          );

        if (structured) {
          return structured;
        }
      }

      const control =
        findByLabel(label)
        || findQuestionContainerControl(
          label
        );

      if (
        !control
        || !isVisible(control)
      ) {
        continue;
      }

      const canonical =
        canonicalControl(control)
        || control;

      if (wantsSelect) {
        if (
          isCombobox(canonical)
          || canonical.tagName
            === "SELECT"
          || lower(
            canonical.getAttribute?.(
              "aria-autocomplete"
            )
          ) === "list"
          || canonical.getAttribute?.(
            "aria-controls"
          )
          || canonical.getAttribute?.(
            "aria-owns"
          )
        ) {
          return canonical;
        }

        continue;
      }

      if (
        isCombobox(canonical)
        || canonical.tagName
          === "SELECT"
        || lower(
          canonical.getAttribute?.(
            "aria-autocomplete"
          )
        ) === "list"
      ) {
        continue;
      }

      return canonical;
    }

    return null;
  }

  function greenhouseStructuredListbox(
    opened
  ) {
    const controls = [
      opened?.input,
      opened?.target,
    ].filter(Boolean);

    for (
      const control
      of controls
    ) {
      for (
        const attribute
        of [
          "aria-controls",
          "aria-owns",
        ]
      ) {
        const raw =
          String(
            control.getAttribute?.(
              attribute
            )
            || ""
          );

        for (
          const id
          of raw.split(/\s+/)
        ) {
          if (!id) {
            continue;
          }

          const node =
            document.getElementById(
              id
            );

          if (
            node
            && isVisible(node)
          ) {
            if (
              lower(
                node.getAttribute?.(
                  "role"
                )
              ) === "listbox"
            ) {
              return node;
            }

            const listbox =
              node.querySelector?.(
                '[role="listbox"]'
              );

            if (
              listbox
              && isVisible(listbox)
            ) {
              return listbox;
            }
          }
        }
      }
    }

    return (
      [
        ...document.querySelectorAll(
          '[role="listbox"]'
        ),
      ].find(
        (node) => isVisible(node)
      )
      || null
    );
  }

  function greenhouseStructuredOptionNodes(
    opened
  ) {
    const result = [];
    const seen = new Set();

    const addNode =
      (node) => {
        if (
          !node
          || seen.has(node)
          || !isVisible(node)
        ) {
          return;
        }

        const label =
          normalize(
            node.innerText
            || node.textContent
          );

        if (!label) {
          return;
        }

        seen.add(node);
        result.push(node);
      };

    const listbox =
      greenhouseStructuredListbox(
        opened
      );

    if (listbox) {
      if (
        lower(
          listbox.getAttribute?.(
            "role"
          )
        ) === "option"
      ) {
        addNode(
          listbox
        );
      }

      for (
        const selector
        of [
          '[role="option"]',
          '[data-value]',
          '[id*="-option-"]',
          'li',
        ]
      ) {
        for (
          const node
          of listbox.querySelectorAll(
            selector
          )
        ) {
          addNode(
            node
          );
        }
      }
    }

    for (
      const node
      of visibleOptionNodes()
    ) {
      addNode(
        node
      );
    }

    return result;
  }

  function greenhouseStructuredRequired(element) {
    if (!element) {
      return false;
    }

    if (
      element.required
      || lower(element.getAttribute?.("aria-required")) === "true"
      || element.querySelector?.('[required], [aria-required="true"]')
    ) {
      return true;
    }

    const rawLabel =
      normalize(rawLabelText(element));

    if (rawLabel.includes("*")) {
      return true;
    }

    let current = element.parentElement;

    for (
      let depth = 0;
      current && depth < 4;
      depth += 1
    ) {
      const labels = [
        ...current.querySelectorAll("label, legend"),
      ];

      if (
        labels.some(
          (node) =>
            normalize(
              node.innerText || node.textContent
            ).includes("*")
        )
      ) {
        return true;
      }

      current = current.parentElement;
    }

    return false;
  }

  async function greenhouseStructuredChoices(
    element,
    definition = null
  ) {
    // JOBFINITUM GREENHOUSE SCHOOL USES LIVE SEARCH
    // The School catalog is large/virtualized. Do not treat the
    // first rendered rows as the complete school list.
    if (
      definition?.field_name
      === "greenhouse_education_school"
    ) {
      return [];
    }

    if (!element) {
      return [];
    }

    if (
      definition?.searchable_select
    ) {
      // School is intentionally a write-in answer in Jobfinitum.
      // applyValue()/selectCombobox() will type the stored school
      // name into Greenhouse and choose the matching React option.
      return [];
    }

    if (
      element.tagName === "SELECT"
    ) {
      return [
        ...element.options,
      ]
        .map(
          (option) => {
            const label =
              normalize(
                option.textContent
                || option.value
              );

            return {
              value: label,
              label,
              platform_value:
                normalize(
                  option.value
                  || label
                ),
            };
          }
        )
        .filter(
          (item) =>
            item.label
            && ![
              "select",
              "select...",
              "choose",
              "choose...",
            ].includes(
              lower(
                item.label
              )
            )
        );
    }

    const control =
      canonicalControl(
        element
      )
      || element;

    if (
      !isCombobox(control)
      && !(
        control.getAttribute?.(
          "aria-controls"
        )
        || control.getAttribute?.(
          "aria-owns"
        )
        || lower(
          control.getAttribute?.(
            "aria-autocomplete"
          )
        ) === "list"
      )
    ) {
      return [];
    }

    let opened = null;

    try {
      opened =
        await openCombobox(
          control
        );

      if (!opened) {
        return [];
      }

      await sleep(
        450
      );

      let optionNodes =
        greenhouseStructuredOptionNodes(
          opened
        );

      // Some React selects do not materialize their first option
      // until keyboard navigation begins.
      if (
        !optionNodes.length
      ) {
        const keyTarget = (
          opened.input
          || opened.target
          || control
        );

        dispatchKey(
          keyTarget,
          "ArrowDown"
        );

        await sleep(
          250
        );

        optionNodes =
          greenhouseStructuredOptionNodes(
            opened
          );
      }

      const seenLabels =
        new Set();

      const choices = [];

      const collectVisible =
        () => {
          for (
            const node
            of greenhouseStructuredOptionNodes(
              opened
            )
          ) {
            const label =
              normalize(
                node.innerText
                || node.textContent
              );

            const key =
              lower(label);

            if (
              !label
              || !key
              || seenLabels.has(key)
              || [
                "select",
                "select...",
                "choose",
                "choose...",
                "no options",
                "no options available",
              ].includes(key)
            ) {
              continue;
            }

            seenLabels.add(
              key
            );

            choices.push({
              // Jobfinitum stores the human-readable answer.
              value: label,
              label,

              // Keep any real Greenhouse backing value for replay.
              platform_value:
                String(
                  node.getAttribute?.(
                    "data-value"
                  )
                  || node.getAttribute?.(
                    "value"
                  )
                  || label
                ),
            });
          }
        };

      collectVisible();

      // Degree and Discipline are finite Greenhouse menus. Walk the
      // listbox so virtualized menus expose all options instead of
      // only the handful currently visible on screen.
      const listbox =
        greenhouseStructuredListbox(
          opened
        );

      if (listbox) {
        let scrollTarget =
          listbox;

        if (
          scrollTarget.scrollHeight
          <= scrollTarget.clientHeight
        ) {
          const scrollable =
            [
              ...listbox.querySelectorAll(
                "*"
              ),
            ].find(
              (node) => (
                node.scrollHeight
                > node.clientHeight + 4
              )
            );

          if (scrollable) {
            scrollTarget =
              scrollable;
          }
        }

        if (
          scrollTarget.scrollHeight
          > scrollTarget.clientHeight + 4
        ) {
          let unchanged = 0;

          for (
            let pass = 0;
            pass < 120;
            pass += 1
          ) {
            const before =
              scrollTarget.scrollTop;

            const maxScroll =
              Math.max(
                0,
                scrollTarget.scrollHeight
                - scrollTarget.clientHeight
              );

            const next =
              Math.min(
                maxScroll,
                before
                + Math.max(
                    80,
                    Math.floor(
                      scrollTarget.clientHeight
                      * 0.8
                    )
                  )
              );

            scrollTarget.scrollTop =
              next;

            scrollTarget.dispatchEvent(
              new Event(
                "scroll",
                {
                  bubbles: true,
                }
              )
            );

            await sleep(
              90
            );

            collectVisible();

            if (
              Math.abs(
                scrollTarget.scrollTop
                - before
              ) < 1
            ) {
              unchanged += 1;
            } else {
              unchanged = 0;
            }

            if (
              scrollTarget.scrollTop
              >= maxScroll - 2
              || unchanged >= 2
            ) {
              break;
            }
          }
        }
      }

      console.log(
        "JOBFINITUM GREENHOUSE EDUCATION CHOICES",
        {
          field_name:
            definition?.field_name
            || null,
          text:
            definition?.text
            || null,
          choice_count:
            choices.length,
          choices:
            choices.map(
              (item) => item.label
            ),
        }
      );

      return choices;
    } finally {
      const escapeTarget = (
        opened?.input
        || opened?.target
        || control
      );

      try {
        dispatchKey(
          escapeTarget,
          "Escape"
        );
      } catch (error) {
        // No-op.
      }

      await sleep(
        120
      );
    }
  }

  async function greenhouseEducationQuestions(
    task = null
  ) {
    const questions = [];

    for (
      const definition
      of GREENHOUSE_EDUCATION_FIELDS
    ) {
      const element =
        greenhouseEducationControl(
          definition
        );

      if (!element) {
        continue;
      }

      const required =
        greenhouseStructuredRequired(
          element
        );

      const savedQuestion =
        savedQuestionFor(
          task,
          definition
        );

      const savedChoices = (
        Array.isArray(
          savedQuestion?.choices
        )
          ? savedQuestion.choices
          : []
      );

      const choices = (
        definition.preferred_type
        === "select"
          ? (
              savedChoices.length
                ? savedChoices
                : await greenhouseStructuredChoices(
                    element,
                    definition
                  )
            )
          : []
      );

      const questionType =
        definition.preferred_type;

      console.log(
        "JOBFINITUM GREENHOUSE EDUCATION QUESTION",
        {
          field_name:
            definition.field_name,
          text:
            definition.text,
          type:
            questionType,
          choice_count:
            choices.length,
          element_tag:
            element.tagName,
          element_role:
            element.getAttribute?.(
              "role"
            )
            || null,
        }
      );

      questions.push({
        key:
          definition.key,
        field_name:
          definition.field_name,
        text:
          definition.text,
        type:
          questionType,
        required,
        choices,
        adapter:
          "greenhouse_hosted",
        structured_section:
          "education",
      });
    }

    return questions;
  }

  function greenhouseInvalidEducationQuestions(
    educationQuestions
  ) {
    const result = [];

    for (const question of educationQuestions) {
      if (!question.required) {
        continue;
      }

      const definition =
        GREENHOUSE_EDUCATION_FIELDS.find(
          (item) =>
            item.field_name === question.field_name
        );

      if (!definition) {
        continue;
      }

      const element =
        greenhouseEducationControl(definition);

      if (!element) {
        continue;
      }

      if (
        !questionHasAnswer(question, element)
        || greenhouseControlInvalid(element)
      ) {
        result.push(question);
      }
    }

    return result;
  }

  async function run(
    launch,
    task
  ) {
    if (
      task.adapter
      !== "greenhouse_hosted"
    ) {
      throw new Error(
        "Greenhouse Agent received a non-Greenhouse task."
      );
    }

    const initialBody =
      lower(
        document.body?.innerText
      );

    if (
      greenhouseSubmissionConfirmed(
        initialBody
      )
    ) {
      statusBox(
        "Greenhouse application submitted.",
        "success"
      );

      await report(
        launch,
        {
          status: "submitted",
          message:
            "Chrome Agent confirmed the Greenhouse application was submitted.",
          confirmation_url:
            location.href,
          detail: {
            url:
              location.href,
            executor:
              "chrome_agent",
            adapter:
              "greenhouse_hosted",
          },
        }
      );

      clearLaunch();

      await closeCompletedAgentTab(
        launch
      );

      return;
    }

    statusBox(
      "loading Greenhouse question schema…"
    );

    const schema =
      await fetchGreenhouseSchema(
        launch
      );

    const schemaQuestions =
      normalizedSchemaQuestions(
        schema
      );

    statusBox(
      "filling Greenhouse application…"
    );

    const identity =
      task.identity || {};

    fillFirst(
      [
        "#first_name",
        'input[name="first_name"]',
        'input[name="job_application[first_name]"]',
        'input[autocomplete="given-name"]',
      ],
      identity.first_name
    );

    fillFirst(
      [
        "#last_name",
        'input[name="last_name"]',
        'input[name="job_application[last_name]"]',
        'input[autocomplete="family-name"]',
      ],
      identity.last_name
    );

    fillFirst(
      [
        "#email",
        'input[name="email"]',
        'input[name="job_application[email]"]',
        'input[type="email"]',
      ],
      identity.email
    );



    const linkedin =
      findByLabel("linkedin");

    if (
      linkedin
      && identity.linkedin_url
    ) {
      await applyValue(
        linkedin,
        identity.linkedin_url
      );
    }

    const website =
      findProfessionalLinkInput(
        "website"
      );

    if (
      website
      && identity.website_url
    ) {
      await applyValue(
        website,
        identity.website_url
      );
    }

    statusBox(
      "uploading resume…"
    );

    const resume =
      await fetchResume(
        launch,
        task
      );

    if (
      !(await setResumeFile(resume))
    ) {
      await report(
        launch,
        {
          status:
            "needs_user_action",
          message:
            "Chrome Agent could not locate the Greenhouse resume upload field.",
          detail: {
            url:
              location.href,
            executor:
              "chrome_agent",
            adapter:
              "greenhouse_hosted",
          },
        }
      );

      return;
    }

    statusBox(
      "applying Greenhouse answers…"
    );

    const unanswered = [];
    const controlMissing = [];

    // GREENHOUSE STRUCTURED EDUCATION:
    // Standard Education fields are not always included in the
    // public custom-question schema, so inspect the live form.
    const educationQuestions =
      await greenhouseEducationQuestions(
        task
      );

    for (
      const question
      of schemaQuestions
    ) {
      if (
        standardSchemaQuestion(
          question
        )
      ) {
        continue;
      }

      const element =
        findSchemaControl(
          question
        );

      const savedApplicationAnswer =
        savedAnswerFor(
          task,
          question
        );

      const profileAnswer =
        profileAnswerForQuestion(
          task,
          question
        );

      // User-selected per-application answers win for employer
      // questions. Only direct identity facts stay profile-first.
      let answer =
        authoritativeProfileIdentityQuestion(
          question
        )
          ? (
              profileAnswer
              ?? savedApplicationAnswer
            )
          : (
              savedApplicationAnswer
              ?? profileAnswer
            );

      if (
        answer === null
        || answer === undefined
        || answer === ""
      ) {
        answer =
          (
            isScopedExperienceQuestion(
              question.text
            )
              ? null
              : reusableAnswer(
                  task,
                  question.text
                )
          );
      }

      const hasAnswer = (
        answer !== null
        && answer !== undefined
        && answer !== ""
      );

      // Only stop BEFORE submission when Jobfinitum truly
      // does not have an answer for a required question.
      if (
        question.required
        && !hasAnswer
      ) {
        unanswered.push(
          question
        );
        continue;
      }

      if (
        hasAnswer
        && element
      ) {
        // Greenhouse is the final authority on whether its
        // controlled React form accepted this value. Attempt
        // the fill, but do not block submission merely because
        // our local verification cannot read React's state.
        try {
          await applyValue(
            element,
            answer,
            question
          );
        } catch (error) {
          console.warn(
            "JOBFINITUM GREENHOUSE APPLY WARNING",
            {
              question:
                question.text,
              answer,
              error:
                String(
                  error?.message
                  || error
                ),
            }
          );
        }
      } else if (
        question.required
        && hasAnswer
        && !element
      ) {
        controlMissing.push(
          question
        );
      }
    }

    for (
      const question
      of educationQuestions
    ) {
      const definition =
        GREENHOUSE_EDUCATION_FIELDS.find(
          (item) =>
            item.field_name === question.field_name
        );

      if (!definition) {
        continue;
      }

      const element =
        greenhouseEducationControl(definition);

      const answer =
        savedAnswerFor(
          task,
          question
        );

      const hasAnswer = (
        answer !== null
        && answer !== undefined
        && answer !== ""
      );

      if (
        question.required
        && !hasAnswer
      ) {
        unanswered.push(question);
        continue;
      }

      if (
        hasAnswer
        && element
      ) {
        try {
          await applyValue(
            element,
            answer,
            question
          );
        } catch (error) {
          console.warn(
            "JOBFINITUM GREENHOUSE EDUCATION APPLY WARNING",
            {
              question: question.text,
              answer,
              error:
                String(
                  error?.message
                  || error
                ),
            }
          );
        }
      } else if (
        question.required
        && hasAnswer
        && !element
      ) {
        controlMissing.push(question);
      }
    }

    if (
      unanswered.length
    ) {
      statusBox(
        "more Greenhouse answers are required in Jobfinitum.",
        "warning"
      );

      await report(
        launch,
        {
          status:
            "needs_application_answer",
          message:
            (
              "Greenhouse still needs answers Jobfinitum does not have: "
              + unanswered
                  .map(
                    (item) => item.text
                  )
                  .join("; ")
            ),
          questions:
            unanswered,
          detail: {
            url:
              location.href,
            required_fields:
              unanswered.map(
                (item) => item.text
              ),
            executor:
              "chrome_agent",
            adapter:
              "greenhouse_hosted",
            schema_source:
              "greenhouse_job_board_api",
          },
        }
      );

      return;
    }

    if (
      controlMissing.length
    ) {
      console.warn(
        "JOBFINITUM GREENHOUSE CONTROLS NOT FOUND BEFORE SUBMIT",
        controlMissing.map(
          (item) => ({
            text:
              item.text,
            field_name:
              item.field_name,
            type:
              item.type,
          })
        )
      );
    }

    // Every employer-specific/schema answer has now been
    // applied. Re-assert Greenhouse's combined Country + Phone
    // identity component LAST so no generic question handling
    // can clear the committed Country selection afterward.


    await sleep(
      900
    );

    // Let React finish the final identity update, then submit.
    // Greenhouse itself remains the source of truth for whether
    // its required fields are valid.
    await sleep(
      1200
    );

    // FINAL GREENHOUSE LOCATION WRITE:
    // Location (City) comes from Applicant Profile.
    await fillGreenhouseLocationCity(
      identity
    );

    await sleep(
      450
    );

    // FINAL GREENHOUSE IDENTITY WRITE:
    // Greenhouse rerenders controlled form sections while each
    // employer question is answered. Touching the intl-tel-input
    // phone widget earlier causes Country to be repeatedly rebuilt.
    // Therefore Phone + Country are filled exactly once, after every
    // other question is complete and immediately before Submit.
    await fillGreenhousePhone(
      identity
    );

    await sleep(
      900
    );

    const submit =
      findSubmit();

    if (!submit) {
      await report(
        launch,
        {
          status:
            "needs_user_action",
          message:
            "Chrome Agent could not find the Greenhouse Submit application button.",
          detail: {
            url:
              location.href,
            executor:
              "chrome_agent",
            adapter:
              "greenhouse_hosted",
          },
        }
      );

      return;
    }

    statusBox(
      "submitting Greenhouse application…"
    );

    submit.click();

    const started =
      Date.now();

    let verificationReported =
      false;

    while (
      Date.now() - started
      < 300000
    ) {
      await sleep(750);

      const body =
        lower(
          document.body?.innerText
        );

      if (
        greenhouseSubmissionConfirmed(
          body
        )
      ) {
        statusBox(
          "Greenhouse application submitted.",
          "success"
        );

        await report(
          launch,
          {
            status:
              "submitted",
            message:
              "Chrome Agent submitted the Greenhouse application successfully.",
            confirmation_url:
              location.href,
            detail: {
              url:
                location.href,
              executor:
                "chrome_agent",
              adapter:
                "greenhouse_hosted",
            },
          }
        );

        clearLaunch();

        await closeCompletedAgentTab(
          launch
        );

        return;
      }

      // If Greenhouse itself rejected the submit because
      // a required field is invalid/missing, trust Greenhouse
      // and return ONLY those actual invalid questions.
      if (
        Date.now() - started
        >= 1500
      ) {
        const schemaInvalidQuestions =
          greenhouseInvalidQuestions(
            schemaQuestions
          );

        const educationInvalidQuestions =
          greenhouseInvalidEducationQuestions(
            educationQuestions
          );

        const invalidQuestions = [
          ...schemaInvalidQuestions,
          ...educationInvalidQuestions,
        ];

        if (
          invalidQuestions.length
        ) {
          statusBox(
            "Greenhouse identified required fields that still need attention.",
            "warning"
          );

          await report(
            launch,
            {
              status:
                "needs_application_answer",
              message:
                (
                  "Greenhouse rejected these required fields: "
                  + invalidQuestions
                      .map(
                        (item) => item.text
                      )
                      .join("; ")
                ),
              questions:
                invalidQuestions,
              detail: {
                url:
                  location.href,
                required_fields:
                  invalidQuestions.map(
                    (item) => item.text
                  ),
                validation_source:
                  "greenhouse_form",
                executor:
                  "chrome_agent",
                adapter:
                  "greenhouse_hosted",
              },
            }
          );

          return;
        }
      }

      if (
        Date.now() - started
        >= 1800
      ) {
        const verificationError =
          visibleVerificationError();

        const captcha =
          visibleInteractiveVerificationChallenge();

        if (
          (
            verificationError
            || captcha
          )
          && !verificationReported
        ) {
          verificationReported =
            true;

          statusBox(
            "human verification is required; complete the visible challenge here and the Agent will keep watching.",
            "warning"
          );

          await report(
            launch,
            {
              status:
                "waiting_verification",
              message:
                "Greenhouse has a visible human-verification challenge. Complete it here; the Browser Agent is still watching.",
              detail: {
                url:
                  location.href,
                verification_error:
                  verificationError,
                captcha_visible:
                  captcha,
                executor:
                  "chrome_agent",
                adapter:
                  "greenhouse_hosted",
              },
            }
          );
        }
      }
    }

    await report(
      launch,
      {
        status:
          verificationReported
            ? "waiting_verification"
            : "needs_user_action",
        message:
          verificationReported
            ? "Greenhouse verification is still waiting for completion."
            : "Greenhouse did not return a recognizable submission confirmation.",
        detail: {
          url:
            location.href,
          executor:
            "chrome_agent",
          adapter:
            "greenhouse_hosted",
        },
      }
    );
  }

  async function main() {
    const launch =
      parseLaunch();

    if (!launch) {
      return;
    }

    if (
      !GREENHOUSE_HOSTS.has(
        location.hostname
      )
    ) {
      return;
    }

    try {
      await registerBatchRunner(
        launch
      );

      statusBox(
        "connecting to Jobfinitum…"
      );

      const response =
        await send({
          type:
            "jobfinitum-task",
          origin:
            launch.origin,
          token:
            launch.token,
        });

      const task =
        response.task;

      await sleep(900);

      await run(
        launch,
        task
      );
    } catch (error) {
      console.error(
        "Jobfinitum Greenhouse Agent failed:",
        error
      );

      statusBox(
        `failed: ${error.message || error}`,
        "error"
      );

      try {
        await report(
          launch,
          {
            status:
              "failed",
            message:
              `Greenhouse Chrome Agent failed: ${error.message || error}`,
            detail: {
              url:
                location.href,
              executor:
                "chrome_agent",
              adapter:
                "greenhouse_hosted",
            },
          }
        );
      } catch (reportError) {
        console.error(
          "Jobfinitum Greenhouse failure report also failed:",
          reportError
        );
      }
    }
  }

  function ignoredGreenhouseOption(
    label
  ) {
    return [
      "select",
      "select...",
      "choose",
      "choose...",
      "no options",
      "no options available",
      "no results",
      "no results found",
      "loading",
      "loading...",
    ].includes(
      lower(label)
    );
  }

  function optionLabel(
    node
  ) {
    return normalize(
      node?.innerText
      || node?.textContent
      || node?.getAttribute?.(
        "aria-label"
      )
      || ""
    );
  }

  function greenhouseSchoolMatchesQuery(
    label,
    query
  ) {
    const labelKey =
      questionMatchKey(label);

    const queryKey =
      questionMatchKey(query);

    if (
      !labelKey
      || !queryKey
    ) {
      return false;
    }

    if (
      labelKey.includes(
        queryKey
      )
      || queryKey.includes(
        labelKey
      )
    ) {
      return true;
    }

    return queryKey
      .split(" ")
      .filter(Boolean)
      .every(
        (part) => labelKey.includes(
          part
        )
      );
  }

  function greenhouseSchoolFromOption(
    node
  ) {
    const label =
      optionLabel(node);

    if (
      !label
      || ignoredGreenhouseOption(
        label
      )
    ) {
      return null;
    }

    return {
      value:
        label,
      label,
      platform_value:
        String(
          node?.getAttribute?.(
            "data-value"
          )
          || node?.getAttribute?.(
            "value"
          )
          || label
        ),
    };
  }

  async function collectGreenhouseSchoolOptions(
    opened,
    query
  ) {
    const seen =
      new Set();

    const schools = [];

    const collect = () => {
      for (
        const node
        of optionNodesForOpened(
          opened
        )
      ) {
        const school =
          greenhouseSchoolFromOption(
            node
          );

        if (!school) {
          continue;
        }

        const key =
          questionMatchKey(
            school.label
          );

        if (
          seen.has(key)
          || !greenhouseSchoolMatchesQuery(
            school.label,
            query
          )
        ) {
          continue;
        }

        seen.add(key);
        schools.push(school);

        if (
          schools.length >= 30
        ) {
          break;
        }
      }

      return schools.length;
    };

    for (
      let attempt = 0;
      attempt < 20;
      attempt += 1
    ) {
      collect();

      if (
        schools.length >= 30
      ) {
        break;
      }

      if (
        schools.length
        && attempt >= 3
      ) {
        break;
      }

      await sleep(
        200
      );
    }

    return schools;
  }

  async function jobfinitumSearchGreenhouseSchools(
    rawQuery
  ) {
    const query =
      normalize(
        rawQuery
      );

    if (
      query.length < 2
    ) {
      return [];
    }

    const definition =
      GREENHOUSE_EDUCATION_FIELDS.find(
        (item) =>
          item.field_name
          === "greenhouse_education_school"
      );

    if (!definition) {
      throw new Error(
        "Greenhouse School definition was not found."
      );
    }

    const element =
      greenhouseEducationControl(
        definition
      );

    if (!element) {
      throw new Error(
        "Greenhouse School control is not available in this tab."
      );
    }

    const opened =
      await openCombobox(
        element
      );

    if (!opened) {
      throw new Error(
        "Greenhouse School dropdown could not be opened."
      );
    }

    const searchInput = (
      opened.input
      || (
        element.tagName === "INPUT"
          ? element
          : element.querySelector?.(
              "input"
            )
      )
    );

    if (!searchInput) {
      throw new Error(
        "Greenhouse School search input was not found."
      );
    }

    try {
      try {
        searchInput.focus();
      } catch (error) {
        // Continue with event-driven search.
      }

      setComboboxSearchText(
        searchInput,
        query
      );

      await sleep(
        150
      );

      dispatchKey(
        searchInput,
        "ArrowDown"
      );

      const schools =
        await collectGreenhouseSchoolOptions(
          opened,
          query
        );

      console.log(
        "JOBFINITUM GREENHOUSE LIVE SCHOOL SEARCH",
        {
          query,
          result_count:
            schools.length,
          schools:
            schools.map(
              (item) =>
                item.label
            ),
        }
      );

      return schools;
    } finally {
      try {
        dispatchKey(
          searchInput,
          "Escape"
        );
      } catch (error) {
        // No-op.
      }

      await sleep(
        80
      );
    }
  }


  chrome.runtime.onMessage.addListener(
    (
      message,
      sender,
      sendResponse
    ) => {
      if (
        !message
        || message.type
          !== "jobfinitum-greenhouse-school-search"
      ) {
        return;
      }

      (
        async () => {
          try {
            const schools =
              await jobfinitumSearchGreenhouseSchools(
                message.query
              );

            sendResponse({
              ok: true,
              schools,
              url:
                location.href,
            });
          } catch (error) {
            sendResponse({
              ok: false,
              schools: [],
              error:
                String(
                  error?.message
                  || error
                ),
              url:
                location.href,
            });
          }
        }
      )();

      return true;
    }
  );

  main();
})();
