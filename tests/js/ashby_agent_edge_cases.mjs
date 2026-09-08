import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath = `${root}/browser_extensions/jobfinitum_chrome_agent/ashby_agent.js`;
const source = await readFile(agentPath, "utf8");
const mainIndex = source.lastIndexOf("\n  main().catch((error) => {");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(mainIndex, -1, "Could not locate the Ashby agent startup call.");
assert.notEqual(closeIndex, -1, "Could not locate the Ashby agent closure.");

const exposedFunctions = [
  "answerText",
  "applyValue",
  "ashbyControlInvalid",
  "chooseCustomOption",
  "controlHasAnyValue",
  "controlType",
  "fieldName",
  "finishConfirmedAshbySubmission",
  "handOffToManualApply",
  "isRequiredControl",
  "labelText",
  "placeholderChoice",
  "questionControlVisible",
  "reusableAnswer",
  "reportRequiredAnswers",
  "resumeFileAttached",
  "run",
  "setResumeFile",
  "visibleVerificationChallenge",
  "visibleVerificationError",
];

const instrumentedSource = [
  source.slice(0, mainIndex),
  `\n  self.__ashbyTestHooks = {${exposedFunctions.join(",")}};`,
  source.slice(closeIndex),
].join("");

class MockEvent {
  constructor(type, options = {}) {
    this.type = type;
    Object.assign(this, options);
  }
}

class MockElement {
  constructor({
    tagName = "DIV",
    type = "",
    id = "",
    name = "",
    value = "",
    text = "",
    attributes = {},
    classes = [],
    rect = {left: 0, top: 0, right: 160, bottom: 40, width: 160, height: 40},
    style = {},
    required = false,
    disabled = false,
    readOnly = false,
    valid = true,
    onClick = null,
  } = {}) {
    this.tagName = tagName.toUpperCase();
    this.type = type;
    this.id = id;
    this.name = name;
    this._value = String(value ?? "");
    this.innerText = text;
    this.textContent = text;
    this.attributes = {...attributes};
    this.classNames = new Set(classes);
    this.className = classes.join(" ");
    this.classList = {contains: (nameToFind) => this.classNames.has(nameToFind)};
    this.rect = {...rect};
    this.computedStyle = {
      display: "block",
      visibility: "visible",
      opacity: "1",
      ...style,
    };
    this.parentElement = null;
    this.disabled = disabled;
    this.readOnly = readOnly;
    this.required = required;
    this.valid = valid;
    this.onClick = onClick;
    this.checked = false;
    this.files = [];
    this.labels = [];
    this.events = [];
    this.clickCount = 0;
    this.focusCount = 0;
    this.scrollCount = 0;
    this.selectorResults = new Map();
    this.closestResults = new Map();
    this.style = {};
  }

  get value() {
    return this._value;
  }

  set value(nextValue) {
    this._value = String(nextValue ?? "");
  }

  getAttribute(name) {
    if (name === "id") return this.id || null;
    if (name === "name") return this.name || null;
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getBoundingClientRect() {
    return {...this.rect};
  }

  dispatchEvent(event) {
    this.events.push(event.type);
    return true;
  }

  click() {
    this.clickCount += 1;
    if (this.type === "checkbox") this.checked = !this.checked;
    if (this.type === "radio") this.checked = true;
    if (this.onClick) this.onClick(this);
  }

  focus() {
    this.focusCount += 1;
  }

  scrollIntoView() {
    this.scrollCount += 1;
  }

  appendChild() {}

  contains(element) {
    return element === this;
  }

  matches(selector) {
    if (selector === "form") return this.tagName === "FORM";
    return false;
  }

  closest(selector) {
    if (this.closestResults.has(selector)) return this.closestResults.get(selector);
    let current = this.parentElement;
    while (current) {
      if (selector === "label" && current.tagName === "LABEL") return current;
      if (selector === ".ashby-application-form-field-entry"
          && current.classList?.contains("ashby-application-form-field-entry")) {
        return current;
      }
      if (selector === "[data-field-path]" && current.getAttribute?.("data-field-path")) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  querySelector(selector) {
    return (this.selectorResults.get(selector) || [])[0] || null;
  }

  querySelectorAll(selector) {
    return this.selectorResults.get(selector) || [];
  }

  checkValidity() {
    return this.valid !== false;
  }
}

class MockInput extends MockElement {
  constructor(options = {}) {
    super({...options, tagName: "INPUT"});
  }
}

class MockTextArea extends MockElement {
  constructor(options = {}) {
    super({...options, tagName: "TEXTAREA"});
  }
}

class MockSelect extends MockElement {
  constructor(options = {}) {
    super({...options, tagName: "SELECT"});
    this.options = options.options || [];
    this.multiple = Boolean(options.multiple);
    this.selectedIndex = Number.isInteger(options.selectedIndex) ? options.selectedIndex : -1;
    if (this.selectedIndex >= 0 && !options.value) {
      this._value = String(this.options[this.selectedIndex]?.value ?? "");
    }
  }

  get value() {
    return this._value;
  }

  set value(nextValue) {
    this._value = String(nextValue ?? "");
    const nextIndex = this.options.findIndex((option) => String(option.value) === this._value);
    if (nextIndex >= 0) this.selectedIndex = nextIndex;
  }

  get selectedOptions() {
    return this.options.filter((option, index) => option.selected || index === this.selectedIndex);
  }
}

class MockDataTransfer {
  constructor() {
    this.files = [];
    this.items = {add: (file) => this.files.push(file)};
  }
}

class MockFile {
  constructor(parts, name, options = {}) {
    this.name = name;
    this.type = options.type || "";
    this.size = parts.reduce((total, part) => total + (part.byteLength ?? part.length ?? 0), 0);
  }
}

let mockNow = 0;
class MockDate extends Date {
  static now() {
    mockNow += 250;
    return mockNow;
  }
}

const statusElement = new MockElement({id: "jobfinitum-agent-status"});
const bodyElement = new MockElement({tagName: "BODY"});
const rootElement = new MockElement({tagName: "HTML"});
const documentState = {
  queryAll: () => [],
  queryOne: () => null,
  byId: (id) => (id === statusElement.id ? statusElement : null),
};
const sentMessages = [];
let messageResponder = () => ({ok: true});
const locationState = {
  href: "https://jobs.ashbyhq.com/example/posting/application",
  hash: "",
  hostname: "jobs.ashbyhq.com",
  pathname: "/example/posting/application",
  search: "",
  reloadCount: 0,
  replacements: [],
  reload() {
    this.reloadCount += 1;
  },
  replace(url) {
    this.replacements.push(String(url));
  },
};

const sandbox = {
  URL,
  URLSearchParams,
  WeakSet,
  Date: MockDate,
  console,
  setTimeout: (callback) => {
    callback();
    return 1;
  },
  clearTimeout: () => {},
  Event: MockEvent,
  KeyboardEvent: MockEvent,
  MouseEvent: MockEvent,
  HTMLInputElement: MockInput,
  HTMLTextAreaElement: MockTextArea,
  HTMLSelectElement: MockSelect,
  DataTransfer: MockDataTransfer,
  File: MockFile,
  CSS: {escape: (value) => String(value)},
  getComputedStyle: (element) => element?.computedStyle || {
    display: "block",
    visibility: "visible",
    opacity: "1",
  },
  document: {
    body: bodyElement,
    documentElement: rootElement,
    title: "Ashby job",
    querySelectorAll: (selector) => documentState.queryAll(selector),
    querySelector: (selector) => documentState.queryOne(selector),
    getElementById: (id) => documentState.byId(id),
    createElement: () => new MockElement(),
  },
  location: locationState,
  history: {replaceState: () => {}},
  chrome: {
    runtime: {
      lastError: null,
      sendMessage(message, callback) {
        sentMessages.push(message);
        callback(messageResponder(message));
      },
    },
  },
  MutationObserver: class {
    observe() {}
    disconnect() {}
  },
  atob: (value) => Buffer.from(value, "base64").toString("binary"),
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.name = "";
sandbox.innerWidth = 1280;
sandbox.innerHeight = 720;
sandbox.sessionStorage = {
  values: new Map(),
  getItem(key) { return this.values.get(key) || null; },
  setItem(key, value) { this.values.set(key, value); },
  removeItem(key) { this.values.delete(key); },
};

vm.createContext(sandbox);
new vm.Script(instrumentedSource, {filename: "ashby_agent.js"}).runInContext(sandbox);
const hooks = sandbox.__ashbyTestHooks;

function resetState() {
  documentState.queryAll = () => [];
  documentState.queryOne = () => null;
  documentState.byId = (id) => (id === statusElement.id ? statusElement : null);
  bodyElement.innerText = "";
  bodyElement.textContent = "";
  sentMessages.length = 0;
  messageResponder = () => ({ok: true});
  locationState.reloadCount = 0;
  locationState.replacements.length = 0;
  sandbox.name = "";
  sandbox.sessionStorage.values.clear();
  mockNow = 0;
}

const results = [];
async function edgeCase(name, callback) {
  resetState();
  try {
    await callback();
    results.push({name, passed: true});
  } catch (error) {
    results.push({name, passed: false, error: error.message});
  }
}

function option(value, text, {disabled = false, selected = false} = {}) {
  return {value, textContent: text, disabled, selected};
}

function visibleOption(text, value = text) {
  return new MockElement({
    text,
    attributes: {"data-value": value},
    classes: ["ashby-application-form-input-autocomplete-popup-result"],
  });
}

function makeFieldEntry(titleText) {
  const entry = new MockElement({classes: ["ashby-application-form-field-entry"]});
  const title = new MockElement({text: titleText});
  entry.selectorResults.set(".ashby-application-form-question-title", [title]);
  return entry;
}

function runnerTask(overrides = {}) {
  return {
    adapter: "ashby_hosted",
    target_url: locationState.href,
    identity: {},
    reusable_answers: {},
    application_questions: [],
    answer_memories: [],
    resume: {
      filename: "latest-resume.pdf",
      content_type: "application/pdf",
      url: "/api/chrome-agent/resume/token",
    },
    ...overrides,
  };
}

function configureRunnerDom({controls = [], resumeInput, submit, challenge = null, getSuccess = () => null}) {
  const form = new MockElement({classes: ["ashby-application-form-container"]});
  const allControls = [resumeInput, ...controls].filter(Boolean);
  documentState.queryAll = (selector) => {
    if (selector === ".ashby-application-form-container") return [form];
    if (selector === ".ashby-application-form-success-container") {
      const success = getSuccess();
      return success ? [success] : [];
    }
    if (selector === 'input[type="file"]') return resumeInput ? [resumeInput] : [];
    if (selector.startsWith("input,textarea,select")) return allControls;
    if (selector === '.ashby-application-form-submit-button button, .ashby-application-form-submit-button input[type="submit"]') {
      return submit ? [submit] : [];
    }
    if (selector === 'button, input[type="submit"]') return submit ? [submit] : [];
    if (selector.includes('title*="challenge"')) return challenge ? [challenge] : [];
    if (selector.startsWith('input[type="radio"]')) return controls.filter((item) => item.type === "radio");
    if (selector.startsWith('input[type="checkbox"]')) return controls.filter((item) => item.type === "checkbox");
    return [];
  };
  documentState.queryOne = (selector) => {
    if (selector === 'input[type="file"]') return resumeInput;
    if (selector === 'input[type="email"]') return controls.find((item) => item.type === "email") || null;
    return null;
  };
  messageResponder = (message) => {
    if (message.type === "jobfinitum-resume") {
      return {
        ok: true,
        base64: Buffer.from("resume data").toString("base64"),
        contentType: "application/pdf",
      };
    }
    return {ok: true};
  };
}

await edgeCase("Japan language answers use profile values without guessing", async () => {
  const configured = {
    reusable_answers: {
      japanese_proficiency: "Conversational",
      english_proficiency: "Fluent",
      currently_residing_in_japan: "No",
    },
  };
  assert.equal(
    hooks.reusableAnswer(configured, "Are you fluent in Japanese?"),
    "Conversational"
  );
  assert.equal(
    hooks.reusableAnswer(configured, "What is your English ability?"),
    "Fluent"
  );
  assert.equal(
    hooks.reusableAnswer(configured, "Do you currently reside in Japan?"),
    "No"
  );
  assert.equal(
    hooks.reusableAnswer(
      {reusable_answers: {japanese_proficiency: "Unknown"}},
      "What is your Japanese proficiency?"
    ),
    null
  );
});

await edgeCase("blank select placeholders stay unanswered", async () => {
  const select = new MockSelect({
    required: true,
    options: [option("", "Select...", {disabled: true})],
    selectedIndex: 0,
  });
  assert.equal(hooks.placeholderChoice("Please select an option..."), true);
  assert.equal(hooks.controlHasAnyValue(select), false);
});

await edgeCase("false-like select values remain valid answers", async () => {
  const select = new MockSelect({
    options: [option("", "Select...", {disabled: true}), option("0", "No")],
    selectedIndex: 1,
    value: "0",
  });
  assert.equal(hooks.controlHasAnyValue(select), true);
});

await edgeCase("native selects update through the browser setter and events", async () => {
  const select = new MockSelect({
    options: [option("", "Select..."), option("US", "United States")],
    selectedIndex: 0,
  });
  assert.equal(await hooks.applyValue(select, "United States"), true);
  assert.equal(select.value, "US");
  assert.deepEqual(select.events, ["input", "change", "blur"]);
});

await edgeCase("radio and checkbox answers use real clicks", async () => {
  const yesLabel = new MockElement({tagName: "LABEL", text: "Yes"});
  const noLabel = new MockElement({tagName: "LABEL", text: "No"});
  const yes = new MockInput({type: "radio", name: "authorized", value: "yes"});
  const no = new MockInput({type: "radio", name: "authorized", value: "no"});
  yes.closestResults.set("label", yesLabel);
  no.closestResults.set("label", noLabel);
  const pythonLabel = new MockElement({tagName: "LABEL", text: "Python"});
  const sqlLabel = new MockElement({tagName: "LABEL", text: "SQL"});
  const python = new MockInput({type: "checkbox", name: "skills", value: "python"});
  const sql = new MockInput({type: "checkbox", name: "skills", value: "sql"});
  python.closestResults.set("label", pythonLabel);
  sql.closestResults.set("label", sqlLabel);
  documentState.queryAll = (selector) => {
    if (selector === 'input[type="radio"]') return [yes, no];
    if (selector === 'input[type="checkbox"]') return [python, sql];
    return [];
  };

  assert.equal(await hooks.applyValue(yes, "Yes"), true);
  assert.equal(yes.checked, true);
  assert.equal(yes.clickCount, 1);
  assert.equal(await hooks.applyValue(python, ["Python", "SQL"]), true);
  assert.equal(python.checked, true);
  assert.equal(sql.checked, true);
  assert.equal(python.clickCount, 1);
  assert.equal(sql.clickCount, 1);
});

await edgeCase("hidden styled choice inputs remain usable", async () => {
  const label = new MockElement({tagName: "LABEL", text: "Yes"});
  const radio = new MockInput({type: "radio", style: {opacity: "0"}});
  radio.closestResults.set("label", label);
  assert.equal(hooks.questionControlVisible(radio), true);
});

await edgeCase("education controls keep distinct labels and keys", async () => {
  const title = new MockElement({text: "Education *"});
  const entry = new MockElement({classes: ["ashby-application-form-field-entry"]});
  entry.selectorResults.set(".ashby-application-form-question-title", [title]);
  const school = new MockInput({id: "education-0-school", attributes: {placeholder: "Search schools..."}});
  const degree = new MockInput({id: "education-0-degree", attributes: {placeholder: "e.g. Bachelor of Science"}});
  const major = new MockInput({id: "education-0-major", attributes: {placeholder: "e.g. Computer Science"}});
  for (const input of [school, degree, major]) input.closestResults.set(".ashby-application-form-field-entry", entry);

  assert.deepEqual(
    [hooks.labelText(school), hooks.labelText(degree), hooks.labelText(major)],
    ["School", "Degree", "Field of Study"]
  );
  assert.equal(new Set([hooks.fieldName(school), hooks.fieldName(degree), hooks.fieldName(major)]).size, 3);
});

await edgeCase("custom combobox chooses an exact result", async () => {
  const input = new MockInput({
    attributes: {role: "combobox"},
    classes: ["ashby-application-form-input-autocomplete"],
  });
  const result = visibleOption("Georgia State University", "gsu");
  documentState.queryAll = (selector) => selector.includes('[role="option"]') ? [result] : [];

  assert.equal(await hooks.chooseCustomOption(input, "Georgia State University"), true);
  assert.equal(result.clickCount, 1);
});

await edgeCase("short answers never fuzzy-match a different option", async () => {
  const input = new MockInput({attributes: {role: "combobox"}});
  const wrongResult = visibleOption("None of the above", "none");
  documentState.queryAll = (selector) => selector.includes('[role="option"]') ? [wrongResult] : [];

  assert.equal(await hooks.chooseCustomOption(input, "No"), false);
  assert.equal(wrongResult.clickCount, 0);
});

await edgeCase("Male never fuzzy-matches Female", async () => {
  const input = new MockInput({attributes: {role: "combobox"}});
  const wrongResult = visibleOption("Female", "female");
  documentState.queryAll = (selector) => selector.includes('[role="option"]') ? [wrongResult] : [];

  assert.equal(await hooks.chooseCustomOption(input, "Male"), false);
  assert.equal(wrongResult.clickCount, 0);
});

await edgeCase("custom selections remain valid when React clears the search text", async () => {
  const input = new MockInput({attributes: {role: "combobox"}});
  const result = visibleOption("Georgia State University", "gsu");
  documentState.queryAll = (selector) => selector.includes('[role="option"]') ? [result] : [];

  assert.equal(await hooks.chooseCustomOption(input, "Georgia State University"), true);
  input.value = "";
  assert.equal(hooks.controlHasAnyValue(input), true);
});

await edgeCase("repeated saved-answer passes preserve a confirmed custom selection", async () => {
  const input = new MockInput({attributes: {role: "combobox"}});
  const result = visibleOption("Georgia State University", "gsu");
  documentState.queryAll = (selector) => selector.includes('[role="option"]') ? [result] : [];

  assert.equal(await hooks.chooseCustomOption(input, "Georgia State University"), true);
  input.value = "";
  documentState.queryAll = () => [];
  assert.equal(await hooks.chooseCustomOption(input, "Georgia State University"), true);
  assert.equal(result.clickCount, 1);
});

await edgeCase("an unselected custom wrapper is not mistaken for an answer", async () => {
  const wrapper = new MockElement({
    text: "Country Select...",
    classes: ["ashby-application-form-input-autocomplete"],
  });
  assert.equal(hooks.controlHasAnyValue(wrapper), false);
});

await edgeCase("resume upload chooses the resume input instead of a cover letter", async () => {
  const coverLetter = new MockInput({type: "file", id: "cover-letter", name: "cover_letter"});
  const resume = new MockInput({type: "file", id: "resume", name: "resume"});
  documentState.queryAll = (selector) => selector === 'input[type="file"]' ? [coverLetter, resume] : [];
  const file = {name: "latest-resume.pdf", size: 1234};

  const selected = hooks.setResumeFile(file);
  assert.equal(selected, resume);
  assert.equal(resume.files[0], file);
  assert.equal(coverLetter.files.length, 0);
});

await edgeCase("visible Ashby upload errors override the local file assignment", async () => {
  const entry = new MockElement({classes: ["ashby-application-form-field-entry"]});
  const error = new MockElement({text: "Upload failed. Try again."});
  entry.selectorResults.set(
    '[role="alert"], [aria-live="assertive"], [class*="error" i], [data-testid*="error" i]',
    [error]
  );
  const input = new MockInput({type: "file"});
  const file = {name: "latest-resume.pdf", size: 1234};
  input.files = [file];
  input.closestResults.set(".ashby-application-form-field-entry", entry);

  assert.equal(hooks.resumeFileAttached(input, file), false);
});

await edgeCase("hidden upload errors do not reject an attached resume", async () => {
  const entry = new MockElement({classes: ["ashby-application-form-field-entry"]});
  const hiddenError = new MockElement({text: "Old upload error", style: {display: "none"}});
  entry.selectorResults.set(
    '[role="alert"], [aria-live="assertive"], [class*="error" i], [data-testid*="error" i]',
    [hiddenError]
  );
  const input = new MockInput({type: "file"});
  const file = {name: "latest-resume.pdf", size: 1234};
  input.files = [file];
  input.closestResults.set(".ashby-application-form-field-entry", entry);

  assert.equal(hooks.resumeFileAttached(input, file), true);
});

await edgeCase("background CAPTCHA text does not create a verification pause", async () => {
  bodyElement.innerText = "This role mentions human verification in its description.";
  assert.equal(hooks.visibleVerificationError(), "");
  assert.equal(hooks.visibleVerificationChallenge(), false);
});

await edgeCase("a rendered challenge below the fold is detected and brought into view", async () => {
  const challenge = new MockElement({
    tagName: "IFRAME",
    attributes: {src: "https://google.com/recaptcha/api2/bframe", title: "recaptcha challenge"},
    rect: {left: 20, top: 1200, right: 324, bottom: 1278, width: 304, height: 78},
  });
  documentState.queryAll = (selector) => selector.includes('title*="challenge"') ? [challenge] : [];

  assert.equal(hooks.visibleVerificationChallenge(), true);
  assert.equal(challenge.scrollCount, 1);
});

await edgeCase("a hidden challenge is ignored", async () => {
  const challenge = new MockElement({
    tagName: "IFRAME",
    style: {opacity: "0"},
    rect: {left: 20, top: 20, right: 324, bottom: 98, width: 304, height: 78},
  });
  documentState.queryAll = (selector) => selector.includes('title*="challenge"') ? [challenge] : [];
  assert.equal(hooks.visibleVerificationChallenge(), false);
});

await edgeCase("generic success language inside a live form is never submitted proof", async () => {
  bodyElement.innerText = "Thank you for applying your experience to this role.";
  const form = new MockElement({classes: ["ashby-application-form-container"]});
  documentState.queryAll = (selector) => {
    if (selector === ".ashby-application-form-success-container") return [];
    if (selector === ".ashby-application-form-container") return [form];
    return [];
  };
  assert.equal(await hooks.finishConfirmedAshbySubmission({origin: "http://127.0.0.1:5000", token: "token"}), false);
  assert.equal(sentMessages.length, 0);
});

await edgeCase("Ashby success container reports Submitted", async () => {
  const success = new MockElement({
    text: "Your application was successfully submitted. We'll contact you if there are next steps.",
    classes: ["ashby-application-form-success-container"],
  });
  documentState.queryAll = (selector) => selector === ".ashby-application-form-success-container" ? [success] : [];
  const launch = {origin: "http://127.0.0.1:5000", token: "token", batch: false};

  assert.equal(await hooks.finishConfirmedAshbySubmission(launch), true);
  assert.equal(sentMessages.find((message) => message.type === "jobfinitum-result")?.payload?.status, "submitted");
});

await edgeCase("saved-answer retry reloads without clearing the launch", async () => {
  sandbox.sessionStorage.setItem("jobfinitum_chrome_agent_launch_v1", "saved-launch");
  messageResponder = (message) => message.type === "jobfinitum-result"
    ? {ok: true, result: {retry_with_saved_answers: true}}
    : {ok: true};

  await hooks.reportRequiredAnswers(
    {origin: "http://127.0.0.1:5000", token: "token", batch: true},
    [{text: "Preferred name"}],
    "Additional answer required.",
    "test"
  );
  assert.equal(locationState.reloadCount, 1);
  assert.equal(sandbox.sessionStorage.getItem("jobfinitum_chrome_agent_launch_v1"), "saved-launch");
});

await edgeCase("manual fallback marks unsupported and returns a batch tab", async () => {
  const launch = {origin: "http://127.0.0.1:5000", token: "token", batch: true};
  await hooks.handOffToManualApply(launch, "Unsupported Ashby form.", {reason: "test"});
  const result = sentMessages.find((message) => message.type === "jobfinitum-result");
  assert.equal(result.payload.status, "unsupported");
  assert.equal(result.payload.detail.manual_application, true);
  assert.equal(locationState.replacements.length, 1);
  assert.match(locationState.replacements[0], /\/browser-agent\?batch_wait=1$/);
});

await edgeCase("full runner returns unknown required fields for an answer", async () => {
  const resumeEntry = makeFieldEntry("Resume *");
  const resumeInput = new MockInput({type: "file", id: "resume", name: "resume"});
  resumeInput.closestResults.set(".ashby-application-form-field-entry", resumeEntry);
  const questionEntry = makeFieldEntry("Why are you interested in this role? *");
  const question = new MockTextArea({name: "motivation", required: true});
  question.closestResults.set(".ashby-application-form-field-entry", questionEntry);
  const submit = new MockElement({tagName: "BUTTON", text: "Submit Application"});
  configureRunnerDom({controls: [question], resumeInput, submit});

  await hooks.run(
    {origin: "http://127.0.0.1:5000", token: "token", batch: true},
    runnerTask()
  );

  const result = sentMessages.find((message) => message.type === "jobfinitum-result");
  assert.equal(result.payload.status, "needs_application_answer");
  assert.equal(
    Array.from(result.payload.detail.required_fields).join("|"),
    "Why are you interested in this role?"
  );
  assert.equal(submit.clickCount, 0);
  assert.equal(locationState.replacements.length, 1);
});

await edgeCase("full runner fills a saved answer and requires Ashby success proof", async () => {
  const resumeEntry = makeFieldEntry("Resume *");
  const resumeInput = new MockInput({type: "file", id: "resume", name: "resume"});
  resumeInput.closestResults.set(".ashby-application-form-field-entry", resumeEntry);
  const questionEntry = makeFieldEntry("Why are you interested in this role? *");
  const question = new MockTextArea({name: "motivation", required: true});
  question.closestResults.set(".ashby-application-form-field-entry", questionEntry);
  let success = null;
  const submit = new MockElement({
    tagName: "BUTTON",
    text: "Submit Application",
    onClick: () => {
      success = new MockElement({
        text: "Your application was successfully submitted. We'll contact you if there are next steps.",
        classes: ["ashby-application-form-success-container"],
      });
    },
  });
  configureRunnerDom({controls: [question], resumeInput, submit, getSuccess: () => success});

  await hooks.run(
    {origin: "http://127.0.0.1:5000", token: "token", batch: true},
    runnerTask({
      application_questions: [{
        field_name: "motivation",
        text: "Why are you interested in this role?",
        answer: "The work aligns with my experience.",
      }],
    })
  );

  assert.equal(question.value, "The work aligns with my experience.");
  assert.equal(submit.clickCount, 1);
  assert.equal(sentMessages.find((message) => message.type === "jobfinitum-result")?.payload?.status, "submitted");
});

await edgeCase("visible CAPTCHA with a disabled submit pauses instead of falling back", async () => {
  const resumeEntry = makeFieldEntry("Resume *");
  const resumeInput = new MockInput({type: "file", id: "resume", name: "resume"});
  resumeInput.closestResults.set(".ashby-application-form-field-entry", resumeEntry);
  const submit = new MockElement({tagName: "BUTTON", text: "Submit Application", disabled: true});
  const challenge = new MockElement({
    tagName: "IFRAME",
    rect: {left: 20, top: 20, right: 324, bottom: 98, width: 304, height: 78},
  });
  configureRunnerDom({resumeInput, submit, challenge});

  await hooks.run(
    {origin: "http://127.0.0.1:5000", token: "token", batch: true},
    runnerTask()
  );

  const statuses = sentMessages
    .filter((message) => message.type === "jobfinitum-result")
    .map((message) => message.payload.status);
  assert.deepEqual(statuses, ["waiting_verification"]);
  assert.equal(locationState.replacements.length, 0);
});

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({passed: results.length - failures.length, failed: failures.length, results}, null, 2));
if (failures.length) {
  throw new Error(`${failures.length} Ashby edge-case test(s) failed.`);
}
