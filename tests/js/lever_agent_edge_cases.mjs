import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/lever_agent.js`;
const source = await readFile(agentPath, "utf8");
const mainIndex = source.lastIndexOf(
  "\n  main().catch((error) => {"
);
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(
  mainIndex,
  -1,
  "Could not locate the Lever agent startup call."
);
assert.notEqual(
  closeIndex,
  -1,
  "Could not locate the Lever agent closure."
);

const exposedFunctions = [
  "applyValue",
  "configuredLeverAnswer",
  "controlHasValue",
  "currentLeverControl",
  "setChoice",
  "stabilizeLeverAnswers",
  "unpersistedLeverAnswers",
  "waitForLeverValue",
];

const instrumentedSource = [
  source.slice(0, mainIndex),
  `\n  self.__leverTestHooks = {${exposedFunctions.join(",")}};`,
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
    tagName = "INPUT",
    type = "text",
    id = "",
    name = "",
    value = "",
    text = "",
    required = false,
    options = [],
    selectedIndex = -1,
    onClick = null,
  } = {}) {
    this.tagName = tagName.toUpperCase();
    this.type = type;
    this.id = id;
    this.name = name;
    this._value = String(value ?? "");
    this.innerText = text;
    this.textContent = text;
    this.required = required;
    this.options = options;
    this.selectedIndex = selectedIndex;
    this.onClick = onClick;
    this.checked = false;
    this.disabled = false;
    this.readOnly = false;
    this.labels = [];
    this.events = [];
    this.clickCount = 0;
    this.attributes = {};
    this.parentElement = null;
    this.closestResults = new Map();
    this.selectorResults = new Map();
  }

  get value() {
    return this._value;
  }

  set value(nextValue) {
    this._value = String(nextValue ?? "");
    if (this.tagName === "SELECT") {
      const index = this.options.findIndex(
        (option) => String(option.value) === this._value
      );
      if (index >= 0) this.selectedIndex = index;
    }
  }

  getAttribute(name) {
    if (name === "id") return this.id || null;
    if (name === "name") return this.name || null;
    return Object.hasOwn(this.attributes, name)
      ? this.attributes[name]
      : null;
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

  closest(selector) {
    return this.closestResults.get(selector) || null;
  }

  querySelector(selector) {
    return (this.selectorResults.get(selector) || [])[0] || null;
  }

  querySelectorAll(selector) {
    return this.selectorResults.get(selector) || [];
  }

  contains(element) {
    return element === this;
  }

  cloneNode() {
    return new MockElement({
      tagName: this.tagName,
      type: this.type,
      name: this.name,
      value: this.value,
      text: this.innerText,
    });
  }

  checkValidity() {
    if (!this.required) return true;
    if (["checkbox", "radio"].includes(this.type)) {
      return this.checked;
    }
    return Boolean(this.value);
  }
}

class MockInput extends MockElement {
  constructor(options = {}) {
    super({...options, tagName: "INPUT"});
  }
}

class MockTextArea extends MockElement {
  constructor(options = {}) {
    super({...options, tagName: "TEXTAREA", type: ""});
  }
}

class MockSelect extends MockElement {
  constructor(options = {}) {
    super({...options, tagName: "SELECT", type: ""});
    if (
      this.selectedIndex >= 0
      && !options.value
    ) {
      this._value = String(
        this.options[this.selectedIndex]?.value ?? ""
      );
    }
  }
}

function option(value, text) {
  return {value, textContent: text};
}

function label(text) {
  return new MockElement({tagName: "LABEL", text});
}

let mockNow = 0;
class MockDate extends Date {
  static now() {
    mockNow += 250;
    return mockNow;
  }
}

const state = {
  controls: [],
  timerHook: null,
};

const documentMock = {
  body: new MockElement({tagName: "BODY"}),
  documentElement: new MockElement({tagName: "HTML"}),
  title: "Lever job",
  querySelectorAll(selector) {
    if (
      selector === "input, textarea, select"
      || selector ===
        "input:required, textarea:required, select:required"
    ) {
      return selector.includes(":required")
        ? state.controls.filter((control) => control.required)
        : state.controls;
    }

    const typeMatch = selector.match(
      /^input\[type="(radio|checkbox)"\]$/
    );
    if (typeMatch) {
      return state.controls.filter(
        (control) => control.type === typeMatch[1]
      );
    }

    return [];
  },
  querySelector() {
    return null;
  },
  getElementById() {
    return null;
  },
  createElement() {
    return new MockElement({tagName: "DIV"});
  },
};

const sandbox = {
  URL,
  URLSearchParams,
  Date: MockDate,
  Event: MockEvent,
  KeyboardEvent: MockEvent,
  MouseEvent: MockEvent,
  HTMLInputElement: MockInput,
  HTMLTextAreaElement: MockTextArea,
  HTMLSelectElement: MockSelect,
  CSS: {escape: (value) => String(value)},
  console,
  document: documentMock,
  location: {
    href: "https://jobs.lever.co/acme/role/apply",
    hash: "",
    hostname: "jobs.lever.co",
    pathname: "/acme/role/apply",
    search: "",
  },
  history: {replaceState() {}},
  getComputedStyle() {
    return {
      display: "block",
      visibility: "visible",
      opacity: "1",
    };
  },
  setTimeout(callback) {
    if (state.timerHook) state.timerHook();
    callback();
    return 1;
  },
  clearTimeout() {},
  chrome: {
    runtime: {
      lastError: null,
      sendMessage(message, callback) {
        callback({ok: true});
      },
    },
  },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.name = "";
sandbox.sessionStorage = {
  values: new Map(),
  getItem(key) {
    return this.values.get(key) || null;
  },
  setItem(key, value) {
    this.values.set(key, value);
  },
  removeItem(key) {
    this.values.delete(key);
  },
};

vm.createContext(sandbox);
new vm.Script(
  instrumentedSource,
  {filename: "lever_agent.js"}
).runInContext(sandbox);
const hooks = sandbox.__leverTestHooks;

function resetState() {
  state.controls = [];
  state.timerHook = null;
  mockNow = 0;
}

const results = [];
async function edgeCase(name, callback) {
  resetState();
  try {
    await callback();
    results.push({name, passed: true});
  } catch (error) {
    results.push({
      name,
      passed: false,
      error: error.message,
    });
  }
}

await edgeCase(
  "native selects use the browser setter and remain selected",
  async () => {
    const select = new MockSelect({
      name: "degree",
      required: true,
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 0,
    });
    select.labels = [label("Degree *")];
    state.controls = [select];

    assert.equal(
      await hooks.applyValue(select, "Bachelor's Degree"),
      true
    );
    assert.equal(select.value, "bachelors");
    assert.deepEqual(
      select.events,
      ["input", "change", "blur"]
    );
  }
);

await edgeCase(
  "a select cleared by a React rerender is rejected",
  async () => {
    const original = new MockSelect({
      name: "degree",
      required: true,
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 0,
    });
    original.labels = [label("Degree *")];
    state.controls = [original];

    let replaced = false;
    state.timerHook = () => {
      if (replaced) return;
      replaced = true;
      const cleared = new MockSelect({
        name: "degree",
        required: true,
        options: [
          option("", "Select..."),
          option("bachelors", "Bachelor's Degree"),
        ],
        selectedIndex: 0,
      });
      cleared.labels = [label("Degree *")];
      state.controls = [cleared];
    };

    assert.equal(
      await hooks.applyValue(original, "Bachelor's Degree"),
      false
    );
    assert.equal(state.controls[0].value, "");
  }
);

await edgeCase(
  "a rerendered text field is verified on the replacement node",
  async () => {
    const original = new MockInput({
      name: "major",
      required: true,
    });
    original.labels = [label("Field of Study *")];
    state.controls = [original];

    let replaced = false;
    state.timerHook = () => {
      if (replaced) return;
      replaced = true;
      const replacement = new MockInput({
        name: "major",
        value: "Computer Science",
        required: true,
      });
      replacement.labels = [label("Field of Study *")];
      state.controls = [replacement];
    };

    assert.equal(
      await hooks.applyValue(original, "Computer Science"),
      true
    );
    assert.equal(
      hooks.currentLeverControl(original),
      state.controls[0]
    );
  }
);

await edgeCase(
  "a text answer removed by a rerender is rejected",
  async () => {
    const original = new MockInput({
      name: "school",
      required: true,
    });
    original.labels = [label("School *")];
    state.controls = [original];

    let replaced = false;
    state.timerHook = () => {
      if (replaced) return;
      replaced = true;
      const cleared = new MockInput({
        name: "school",
        required: true,
      });
      cleared.labels = [label("School *")];
      state.controls = [cleared];
    };

    assert.equal(
      await hooks.applyValue(
        original,
        "Georgia State University"
      ),
      false
    );
  }
);

await edgeCase(
  "radio and checkbox values are changed with real clicks",
  async () => {
    const yes = new MockInput({
      name: "authorized",
      type: "radio",
      value: "yes",
    });
    const no = new MockInput({
      name: "authorized",
      type: "radio",
      value: "no",
    });
    yes.closestResults.set("label", label("Yes"));
    no.closestResults.set("label", label("No"));

    const python = new MockInput({
      name: "skills",
      type: "checkbox",
      value: "python",
    });
    const sql = new MockInput({
      name: "skills",
      type: "checkbox",
      value: "sql",
    });
    python.closestResults.set("label", label("Python"));
    sql.closestResults.set("label", label("SQL"));
    state.controls = [yes, no, python, sql];

    assert.equal(await hooks.applyValue(yes, "Yes"), true);
    assert.equal(yes.clickCount, 1);
    assert.equal(
      await hooks.applyValue(
        python,
        ["Python", "SQL"]
      ),
      true
    );
    assert.equal(python.clickCount, 1);
    assert.equal(sql.clickCount, 1);
  }
);

await edgeCase(
  "per-application answers override remembered and profile answers",
  async () => {
    const degree = new MockSelect({
      name: "degree",
      required: true,
      options: [
        option("", "Select..."),
        option("ba", "Bachelor of Arts"),
        option("bs", "Bachelor of Science"),
      ],
      selectedIndex: 0,
    });
    degree.labels = [label("Degree *")];

    const task = {
      application_questions: [{
        field_name: "degree",
        text: "Degree",
        answer: "Bachelor of Science",
      }],
      answer_memories: [{
        question_text: "Degree",
        answer: "Bachelor of Arts",
      }],
      reusable_answers: {
        education_degree: "Bachelor's Degree",
      },
    };

    assert.equal(
      hooks.configuredLeverAnswer(task, degree),
      "Bachelor of Science"
    );
  }
);

await edgeCase(
  "configured answers cleared by React are returned as unpersisted",
  async () => {
    const degree = new MockSelect({
      name: "degree",
      required: true,
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 0,
    });
    degree.labels = [label("Degree *")];
    state.controls = [degree];

    const missing = hooks.unpersistedLeverAnswers({
      application_questions: [],
      answer_memories: [],
      reusable_answers: {
        education_degree: "Bachelor's Degree",
      },
    });

    assert.equal(missing.length, 1);
    assert.equal(missing[0].text, "Degree");
  }
);

await edgeCase(
  "settled recovery reapplies a degree cleared by React",
  async () => {
    const original = new MockSelect({
      name: "degree",
      required: true,
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 1,
    });
    original.labels = [label("Degree *")];
    state.controls = [original];

    let replacement = null;
    state.timerHook = () => {
      if (replacement) return;
      original.isConnected = false;
      replacement = new MockSelect({
        name: "degree",
        required: true,
        options: [
          option("", "Select..."),
          option("bachelors", "Bachelor's Degree"),
        ],
        selectedIndex: 0,
      });
      replacement.labels = [label("Degree *")];
      state.controls = [replacement];
    };

    const missing = await hooks.stabilizeLeverAnswers({
      application_questions: [],
      answer_memories: [],
      reusable_answers: {
        education_degree: "Bachelor's Degree",
      },
    });

    assert.equal(missing.length, 0);
    assert.equal(replacement.value, "bachelors");
  }
);

await edgeCase(
  "settled recovery returns the exact field that React keeps clearing",
  async () => {
    const school = new MockInput({
      name: "school",
      required: true,
    });
    school.labels = [label("School *")];
    state.controls = [school];
    state.timerHook = () => {
      school.value = "";
    };

    const missing = await hooks.stabilizeLeverAnswers({
      application_questions: [],
      answer_memories: [],
      reusable_answers: {
        education_school: "Georgia State University",
      },
    });

    assert.equal(missing.length, 1);
    assert.equal(missing[0].text, "School");
  }
);

await edgeCase(
  "detached controls are never accepted as current React state",
  async () => {
    const detached = new MockInput({
      name: "major",
      value: "Computer Science",
      required: true,
    });
    detached.labels = [label("Field of Study *")];
    detached.isConnected = false;
    state.controls = [];

    assert.equal(hooks.currentLeverControl(detached), null);
  }
);

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));

if (failures.length) {
  throw new Error(
    `${failures.length} Lever edge-case test(s) failed.`
  );
}

