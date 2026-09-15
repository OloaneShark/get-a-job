import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/greenhouse_agent.js`;
let source = await readFile(agentPath, "utf8");
source = source.replace(
  /\s*main\(\);\s*\}\)\(\);\s*$/,
  `
  self.__greenhouseTestHooks = {
    applyValue,
    currentGreenhouseControl,
    greenhouseAnswerCommitted,
    stabilizeGreenhouseAnswers,
    waitForGreenhouseValue,
  };
})();`
);

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
    attributes = {},
    options = [],
    selectedIndex = -1,
    required = false,
  } = {}) {
    this.tagName = tagName.toUpperCase();
    this.type = type;
    this.id = id;
    this.name = name;
    this._value = String(value ?? "");
    this.innerText = text;
    this.textContent = text;
    this.attributes = {...attributes};
    this.options = options;
    this.selectedIndex = selectedIndex;
    this.required = required;
    this.checked = false;
    this.disabled = false;
    this.readOnly = false;
    this.parentElement = null;
    this.selectorResults = new Map();
    this.closestResults = new Map();
    this.events = [];
    this.clickCount = 0;
    this.rect = {
      left: 20,
      top: 20,
      right: 260,
      bottom: 60,
      width: 240,
      height: 40,
    };
    this.style = {
      display: "block",
      visibility: "visible",
      opacity: "1",
    };
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

  get selectedOptions() {
    return this.options.filter(
      (option, index) =>
        option.selected || index === this.selectedIndex
    );
  }

  getAttribute(name) {
    if (name === "id") return this.id || null;
    if (name === "name") return this.name || null;
    return Object.hasOwn(this.attributes, name)
      ? this.attributes[name]
      : null;
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
  }

  focus() {}

  blur() {
    this.dispatchEvent(new MockEvent("blur"));
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

  matches() {
    return false;
  }

  contains(element) {
    return element === this;
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

function option(value, text, selected = false) {
  return {
    value,
    textContent: text,
    innerText: text,
    selected,
  };
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
  options: [],
  timerHook: null,
};

const body = new MockElement({tagName: "BODY"});
const html = new MockElement({tagName: "HTML"});

const documentMock = {
  body,
  documentElement: html,
  title: "Greenhouse job",
  getElementById(id) {
    return state.controls.find(
      (control) => control.id === id
    ) || null;
  },
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  },
  querySelectorAll(selector) {
    const nameMatch = selector.match(/^\[name="(.+)"\]$/);
    if (nameMatch) {
      return state.controls.filter(
        (control) => control.name === nameMatch[1]
      );
    }

    const typeMatch = selector.match(
      /^input\[type="(radio|checkbox)"\]$/
    );
    if (typeMatch) {
      return state.controls.filter(
        (control) => control.type === typeMatch[1]
      );
    }

    if (
      selector.includes('[role="option"]')
      || selector.includes('[role="listbox"]')
      || selector.includes('[id*="-option-"]')
    ) {
      return state.options;
    }

    if (selector === "label, legend") return [];
    return [];
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
  PointerEvent: MockEvent,
  HTMLInputElement: MockInput,
  HTMLTextAreaElement: MockTextArea,
  HTMLSelectElement: MockSelect,
  CSS: {escape: (value) => String(value)},
  console,
  document: documentMock,
  location: {
    href: "https://boards.greenhouse.io/acme/jobs/123",
    hash: "",
    hostname: "boards.greenhouse.io",
    pathname: "/acme/jobs/123",
    search: "",
  },
  history: {replaceState() {}},
  getComputedStyle(element) {
    return element?.style || {
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
      onMessage: {
        addListener() {},
      },
    },
  },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.innerWidth = 1280;
sandbox.innerHeight = 720;
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
  source,
  {filename: "greenhouse_agent.js"}
).runInContext(sandbox);
const hooks = sandbox.__greenhouseTestHooks;
assert.ok(hooks, "Could not expose Greenhouse test hooks.");

function resetState() {
  state.controls = [];
  state.options = [];
  state.timerHook = null;
  mockNow = 0;
}

function question(overrides = {}) {
  return {
    control_id: "degree",
    field_name: "question_1",
    text: "Degree",
    type: "select",
    choices: [{
      value: "Bachelor's Degree",
      label: "Bachelor's Degree",
      platform_value: "bachelors",
    }],
    ...overrides,
  };
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
  "native select values are matched against labels and backing values",
  async () => {
    const select = new MockSelect({
      id: "degree",
      name: "question_1",
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 1,
    });
    state.controls = [select];

    assert.equal(
      hooks.greenhouseAnswerCommitted(
        question(),
        select,
        "Bachelor's Degree"
      ),
      true
    );
    assert.equal(
      hooks.greenhouseAnswerCommitted(
        question(),
        select,
        "Master's Degree"
      ),
      false
    );
  }
);

await edgeCase(
  "a native select cleared by a React rerender is rejected",
  async () => {
    const original = new MockSelect({
      id: "degree",
      name: "question_1",
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 0,
    });
    state.controls = [original];

    let replaced = false;
    state.timerHook = () => {
      if (replaced) return;
      replaced = true;
      state.controls = [new MockSelect({
        id: "degree",
        name: "question_1",
        options: [
          option("", "Select..."),
          option("bachelors", "Bachelor's Degree"),
        ],
        selectedIndex: 0,
      })];
    };

    assert.equal(
      await hooks.applyValue(
        original,
        "Bachelor's Degree",
        question()
      ),
      false
    );
  }
);

await edgeCase(
  "a replacement text node retaining its answer is accepted",
  async () => {
    const original = new MockInput({
      id: "major",
      name: "question_2",
    });
    state.controls = [original];
    const majorQuestion = question({
      control_id: "major",
      field_name: "question_2",
      text: "Field of Study",
      type: "text",
      choices: [],
    });

    let replaced = false;
    state.timerHook = () => {
      if (replaced) return;
      replaced = true;
      state.controls = [new MockInput({
        id: "major",
        name: "question_2",
        value: "Computer Science",
      })];
    };

    assert.equal(
      await hooks.applyValue(
        original,
        "Computer Science",
        majorQuestion
      ),
      true
    );
  }
);

await edgeCase(
  "open combobox search text is not a committed answer",
  async () => {
    const input = new MockInput({
      id: "nationality",
      name: "question_3",
      value: "American",
      attributes: {
        role: "combobox",
        "aria-expanded": "true",
      },
    });
    state.controls = [input];
    state.options = [new MockElement({
      tagName: "DIV",
      text: "American",
      attributes: {role: "option"},
    })];
    const nationality = question({
      control_id: "nationality",
      field_name: "question_3",
      text: "Please indicate your nationality",
      choices: [{
        value: "American",
        label: "American",
        platform_value: "us",
      }],
    });

    assert.equal(
      hooks.greenhouseAnswerCommitted(
        nationality,
        input,
        "American"
      ),
      false
    );
  }
);

await edgeCase(
  "closed combobox selected-value text is committed",
  async () => {
    const wrapper = new MockElement({tagName: "DIV"});
    const input = new MockInput({
      id: "nationality",
      name: "question_3",
      attributes: {
        role: "combobox",
        "aria-expanded": "false",
      },
    });
    input.parentElement = wrapper;
    const selected = new MockElement({
      tagName: "DIV",
      text: "American",
    });
    wrapper.selectorResults.set(
      [
        '[class*="single-value" i]',
        '[class*="singlevalue" i]',
        '[class*="multi-value" i]',
        '[class*="multivalue" i]',
      ].join(","),
      [selected]
    );
    state.controls = [input];
    const nationality = question({
      control_id: "nationality",
      field_name: "question_3",
      text: "Please indicate your nationality",
      choices: [{
        value: "American",
        label: "American",
        platform_value: "us",
      }],
    });

    assert.equal(
      hooks.greenhouseAnswerCommitted(
        nationality,
        input,
        "American"
      ),
      true
    );
  }
);

await edgeCase(
  "demographic multiselect requires every configured choice",
  async () => {
    const wrapper = new MockElement({tagName: "DIV"});
    const input = new MockInput({
      id: "demographic",
      name: "question_4",
      attributes: {
        role: "combobox",
        "aria-expanded": "false",
      },
    });
    input.parentElement = wrapper;
    const gender = new MockElement({
      tagName: "DIV",
      text: "Woman",
    });
    wrapper.selectorResults.set(
      [
        '[class*="single-value" i]',
        '[class*="singlevalue" i]',
        '[class*="multi-value" i]',
        '[class*="multivalue" i]',
      ].join(","),
      [gender]
    );
    state.controls = [input];
    const demographic = question({
      control_id: "demographic",
      field_name: "question_4",
      text: "Self identification",
      type: "multiselect",
      choices: [
        {value: "Woman", label: "Woman"},
        {value: "Veteran", label: "Veteran"},
      ],
    });

    assert.equal(
      hooks.greenhouseAnswerCommitted(
        demographic,
        input,
        ["Woman", "Veteran"]
      ),
      false
    );

    const veteran = new MockElement({
      tagName: "DIV",
      text: "Veteran",
    });
    wrapper.selectorResults.set(
      [
        '[class*="single-value" i]',
        '[class*="singlevalue" i]',
        '[class*="multi-value" i]',
        '[class*="multivalue" i]',
      ].join(","),
      [gender, veteran]
    );

    assert.equal(
      hooks.greenhouseAnswerCommitted(
        demographic,
        input,
        ["Woman", "Veteran"]
      ),
      true
    );
  }
);

await edgeCase(
  "settled recovery reapplies an education value cleared by React",
  async () => {
    const original = new MockSelect({
      id: "degree",
      name: "question_1",
      options: [
        option("", "Select..."),
        option("bachelors", "Bachelor's Degree"),
      ],
      selectedIndex: 1,
    });
    state.controls = [original];

    let replacement = null;
    state.timerHook = () => {
      if (replacement) return;
      original.isConnected = false;
      replacement = new MockSelect({
        id: "degree",
        name: "question_1",
        options: [
          option("", "Select..."),
          option("bachelors", "Bachelor's Degree"),
        ],
        selectedIndex: 0,
      });
      state.controls = [replacement];
    };

    const expected = [{
      question: question(),
      answer: "Bachelor's Degree",
    }];
    const missing = await hooks.stabilizeGreenhouseAnswers(expected);

    assert.equal(missing.length, 0);
    assert.equal(replacement.value, "bachelors");
  }
);

await edgeCase(
  "settled recovery returns the exact Greenhouse field that stays empty",
  async () => {
    const school = new MockInput({
      id: "school",
      name: "question_5",
    });
    state.controls = [school];
    state.timerHook = () => {
      school.value = "";
    };
    const schoolQuestion = question({
      control_id: "school",
      field_name: "question_5",
      text: "School",
      type: "text",
      choices: [],
    });

    const missing = await hooks.stabilizeGreenhouseAnswers([{
      question: schoolQuestion,
      answer: "Georgia State University",
    }]);

    assert.equal(missing.length, 1);
    assert.equal(missing[0].question.text, "School");
  }
);

await edgeCase(
  "native Greenhouse multiselects commit every configured answer",
  async () => {
    const select = new MockSelect({
      id: "ethnicity",
      name: "question_6",
      options: [
        option("", "Select..."),
        option("asian", "Asian"),
        option("white", "White"),
        option("decline", "Decline to self-identify"),
      ],
    });
    select.multiple = true;
    state.controls = [select];
    const ethnicity = question({
      control_id: "ethnicity",
      field_name: "question_6",
      text: "Ethnicity",
      type: "multiselect",
      choices: [
        {value: "Asian", label: "Asian", platform_value: "asian"},
        {value: "White", label: "White", platform_value: "white"},
      ],
    });

    assert.equal(
      await hooks.applyValue(
        select,
        ["Asian", "White"],
        ethnicity
      ),
      true
    );
    assert.deepEqual(
      select.options.filter((item) => item.selected).map(
        (item) => item.value
      ),
      ["asian", "white"]
    );
  }
);

await edgeCase(
  "custom multiselect retries preserve choices already committed",
  async () => {
    const wrapper = new MockElement({tagName: "DIV"});
    const input = new MockInput({
      id: "identity",
      name: "question_7",
      attributes: {
        role: "combobox",
        "aria-expanded": "false",
      },
    });
    input.parentElement = wrapper;
    wrapper.selectorResults.set(
      [
        '[class*="single-value" i]',
        '[class*="singlevalue" i]',
        '[class*="multi-value" i]',
        '[class*="multivalue" i]',
      ].join(","),
      [
        new MockElement({tagName: "DIV", text: "Woman"}),
        new MockElement({tagName: "DIV", text: "Veteran"}),
      ]
    );
    state.controls = [input];
    const identity = question({
      control_id: "identity",
      field_name: "question_7",
      text: "Self identification",
      type: "multiselect",
      choices: [
        {value: "Woman", label: "Woman"},
        {value: "Veteran", label: "Veteran"},
      ],
    });

    assert.equal(
      await hooks.applyValue(
        input,
        ["Woman", "Veteran"],
        identity
      ),
      true
    );
    assert.equal(input.clickCount, 0);
  }
);

await edgeCase(
  "detached Greenhouse controls cannot satisfy persistence checks",
  async () => {
    const detached = new MockInput({
      id: "major",
      name: "question_8",
      value: "Computer Science",
    });
    detached.isConnected = false;
    state.controls = [];
    const major = question({
      control_id: "major",
      field_name: "question_8",
      text: "Field of Study",
      type: "text",
      choices: [],
    });

    assert.equal(
      hooks.currentGreenhouseControl(major, detached),
      null
    );
    assert.equal(
      hooks.greenhouseAnswerCommitted(
        major,
        detached,
        "Computer Science"
      ),
      false
    );
    assert.equal(
      await hooks.applyValue(
        detached,
        "Computer Science",
        major
      ),
      false
    );
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
    `${failures.length} Greenhouse edge-case test(s) failed.`
  );
}

