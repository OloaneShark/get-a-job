import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(
  new URL("../..", import.meta.url)
);
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/adzuna_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(
  startupIndex,
  -1,
  "Could not locate the Adzuna startup call."
);
assert.notEqual(
  closeIndex,
  -1,
  "Could not locate the Adzuna closure."
);

const hooksToExpose = [
  "activateControl",
  "applyControl",
  "applyIntentScore",
  "blockedPage",
  "externalApplyLink",
  "isAdzunaHandoffUrl",
  "isExternalUrl",
  "isJobsIndex",
  "metaRefreshTarget",
  "postingClosed",
  "run",
  "visibleChallenge",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__adzunaTestHooks = {${hooksToExpose.join(",")}};`,
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
    tagName = "A",
    text = "",
    href = "",
    attributes = {},
    disabled = false,
    hidden = false,
    visible = true,
    onClick = null,
  } = {}) {
    this.tagName = tagName;
    this.innerText = text;
    this.textContent = text;
    this.value = text;
    this.href = href;
    this.attributes = new Map(
      Object.entries(attributes)
    );
    this.disabled = disabled;
    this.hidden = hidden;
    this.visible = visible;
    this.onClick = onClick;
    this.clickCount = 0;
    this.events = [];
    this.style = {};
  }

  getAttribute(name) {
    if (name === "href" && this.href) {
      return this.href;
    }
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getBoundingClientRect() {
    return this.visible
      ? {width: 120, height: 36}
      : {width: 0, height: 0};
  }

  dispatchEvent(event) {
    this.events.push(event.type);
    return true;
  }

  scrollIntoView() {}

  focus() {}

  click() {
    this.clickCount += 1;
    this.onClick?.();
  }
}

const state = {
  bodyText: "",
  challenges: [],
  elements: [],
  meta: null,
  status: null,
};
const locationState = {
  href:
    "https://www.adzuna.com/land/ad/5849361556",
  hash: "",
  hostname: "www.adzuna.com",
  pathname: "/land/ad/5849361556",
  search: "",
  origin: "https://www.adzuna.com",
  replacements: [],
  replace(value) {
    this.replacements.push(String(value));
  },
};
const storageValues = new Map();
const sentMessages = [];
let messageResponder = () => ({ok: true});
let clockNow = 0;

const documentState = {
  readyState: "complete",
  title: "Adzuna job",
  body: {
    get innerText() {
      return state.bodyText;
    },
    get textContent() {
      return state.bodyText;
    },
  },
  documentElement: {
    appendChild(element) {
      if (element.id === "jobfinitum-agent-status") {
        state.status = element;
      }
    },
  },
  getElementById(id) {
    if (id === "jobfinitum-agent-status") {
      return state.status;
    }
    return null;
  },
  createElement(tagName) {
    return new MockElement({
      tagName: tagName.toUpperCase(),
    });
  },
  querySelector(selector) {
    if (selector.includes("meta[http-equiv")) {
      return state.meta;
    }
    return null;
  },
  querySelectorAll(selector) {
    if (
      selector.includes("recaptcha")
      || selector.includes("hcaptcha")
      || selector.includes("cf-turnstile")
      || selector.includes("__cf_chl")
    ) {
      return state.challenges;
    }

    if (selector === "a[href]") {
      return state.elements.filter(
        (element) => element.tagName === "A"
      );
    }

    if (selector.includes("button")) {
      return state.elements;
    }

    return [];
  },
  addEventListener(name, callback) {
    if (name === "DOMContentLoaded") {
      callback();
    }
  },
};

const sandbox = {
  URL,
  URLSearchParams,
  MouseEvent: MockEvent,
  chrome: {
    runtime: {
      lastError: null,
      sendMessage(message, callback) {
        sentMessages.push(message);
        callback(messageResponder(message));
      },
    },
  },
  console,
  document: documentState,
  getComputedStyle(element) {
    return {
      display: element.visible ? "block" : "none",
      visibility: "visible",
      opacity: "1",
    };
  },
  history: {
    replaceState() {
      locationState.hash = "";
    },
  },
  location: locationState,
  name: "",
  sessionStorage: {
    getItem(key) {
      return storageValues.get(key) ?? null;
    },
    setItem(key, value) {
      storageValues.set(key, String(value));
    },
    removeItem(key) {
      storageValues.delete(key);
    },
  },
  setTimeout(callback, delay = 0) {
    clockNow += Number(delay) || 0;
    callback();
    return clockNow;
  },
  clearTimeout() {},
  Date: {
    now() {
      return clockNow;
    },
  },
};
sandbox.window = sandbox;
sandbox.self = sandbox;

vm.createContext(sandbox);
new vm.Script(instrumentedSource, {
  filename: "adzuna_agent.js",
}).runInContext(sandbox);
const hooks = sandbox.__adzunaTestHooks;

function resetState() {
  state.bodyText = "";
  state.challenges = [];
  state.elements = [];
  state.meta = null;
  state.status = null;
  sentMessages.length = 0;
  storageValues.clear();
  messageResponder = () => ({ok: true});
  clockNow = 0;
  sandbox.name = "";
  locationState.href =
    "https://www.adzuna.com/land/ad/5849361556";
  locationState.hash = "";
  locationState.hostname = "www.adzuna.com";
  locationState.pathname = "/land/ad/5849361556";
  locationState.search = "";
  locationState.origin = "https://www.adzuna.com";
  locationState.replacements.length = 0;
  documentState.title = "Adzuna job";
}

function launchHash(batch = false) {
  return (
    "#jobfinitum_agent=adzuna-token"
    + "&jobfinitum_origin="
    + encodeURIComponent("http://127.0.0.1:5000")
    + (batch ? "&jobfinitum_batch=1" : "")
  );
}

function respond(message, restoredLaunch = null) {
  if (
    message.type
    === "jobfinitum-job-board-restore"
  ) {
    return {ok: true, launch: restoredLaunch};
  }

  if (message.type === "jobfinitum-task") {
    return {
      ok: true,
      task: {
        adapter: "adzuna_resolver",
        target_url: locationState.href,
      },
    };
  }

  return {ok: true};
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
  "all official Adzuna domains stay inside the resolver",
  async () => {
    assert.equal(
      hooks.isExternalUrl(
        "https://www.adzuna.co.uk/jobs/land/ad/123"
      ),
      false
    );
    assert.equal(
      hooks.isExternalUrl(
        "https://www.adzuna.com.au/land/ad/123"
      ),
      false
    );
    assert.equal(
      hooks.isExternalUrl(
        "https://jobs.lever.co/acme/role/apply"
      ),
      true
    );
  }
);

await edgeCase(
  "Adzuna handoff paths are recognized",
  async () => {
    assert.equal(
      hooks.isAdzunaHandoffUrl(
        "https://www.adzuna.com/land/ad/123"
      ),
      true
    );
    assert.equal(
      hooks.isAdzunaHandoffUrl(
        "https://adzuna.co.uk/jobs/land/ad/456"
      ),
      true
    );
    assert.equal(
      hooks.isAdzunaHandoffUrl(
        "https://www.adzuna.com/jobs"
      ),
      false
    );
  }
);

await edgeCase(
  "exact Apply links outrank unrelated external links",
  async () => {
    const company = new MockElement({
      text: "Company website",
      href: "https://example.com",
    });
    const apply = new MockElement({
      text: "Apply now",
      href:
        "https://job-boards.greenhouse.io/acme/jobs/123",
    });
    state.elements = [company, apply];
    assert.equal(hooks.externalApplyLink(), apply.href);
    assert.ok(
      hooks.applyIntentScore(apply)
      > hooks.applyIntentScore(company)
    );
  }
);

await edgeCase(
  "unrelated external links are ignored",
  async () => {
    state.elements = [
      new MockElement({
        text: "Privacy policy",
        href: "https://example.com/privacy",
      }),
    ];
    assert.equal(hooks.externalApplyLink(), null);
  }
);

await edgeCase(
  "disabled Apply controls are ignored",
  async () => {
    state.elements = [
      new MockElement({
        text: "Apply now",
        href:
          "https://www.adzuna.com/land/ad/456",
        disabled: true,
      }),
      new MockElement({
        tagName: "BUTTON",
        text: "Apply",
        attributes: {"aria-disabled": "true"},
      }),
    ];
    assert.equal(hooks.applyControl(), null);
  }
);

await edgeCase(
  "activation keeps the handoff in the managed tab",
  async () => {
    const apply = new MockElement({
      text: "Apply now",
      href:
        "https://www.adzuna.com/land/ad/456",
      attributes: {target: "_blank"},
    });
    assert.equal(
      await hooks.activateControl(apply),
      true
    );
    assert.equal(
      apply.getAttribute("target"),
      "_self"
    );
    assert.equal(apply.clickCount, 1);
  }
);

await edgeCase(
  "an external meta refresh is accepted",
  async () => {
    state.meta = new MockElement({
      attributes: {
        content:
          "0; URL=https://jobs.ashbyhq.com/acme/application",
      },
    });
    assert.equal(
      hooks.metaRefreshTarget(),
      "https://jobs.ashbyhq.com/acme/application"
    );
  }
);

await edgeCase(
  "demographic questions are not human verification",
  async () => {
    state.bodyText = (
      "What gender identity do you most closely "
      + "identify with? Are you a veteran?"
    );
    assert.equal(hooks.visibleChallenge(), false);
  }
);

await edgeCase(
  "a visible challenge is human verification",
  async () => {
    state.challenges = [new MockElement()];
    assert.equal(hooks.visibleChallenge(), true);
  }
);

await edgeCase(
  "the full resolver reports a supported employer target",
  async () => {
    locationState.hash = launchHash(true);
    state.elements = [
      new MockElement({
        text: "Apply now",
        href:
          "https://job-boards.greenhouse.io/acme/jobs/123",
      }),
    ];
    messageResponder = (message) => respond(message);

    await hooks.run();

    const resolved = sentMessages.find(
      (message) =>
        message.type
        === "jobfinitum-job-board-resolved"
    );
    assert.equal(
      resolved.url,
      "https://job-boards.greenhouse.io/acme/jobs/123"
    );
    assert.equal(resolved.batch, true);
  }
);

await edgeCase(
  "a visible challenge pauses without recycling the tab",
  async () => {
    locationState.hash = launchHash(true);
    state.challenges = [new MockElement()];
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) =>
        message.type === "jobfinitum-result"
    );
    assert.equal(
      result.payload.status,
      "waiting_verification"
    );
    assert.equal(
      result.payload.detail.verification_required,
      true
    );
    assert.equal(
      locationState.replacements.length,
      0
    );
  }
);

await edgeCase(
  "a blocked redirect falls back and advances the batch",
  async () => {
    locationState.hash = launchHash(true);
    state.bodyText = "403 Forbidden";
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) =>
        message.type === "jobfinitum-result"
    );
    assert.equal(
      result.payload.status,
      "needs_manual_destination"
    );
    assert.match(
      locationState.replacements.at(-1),
      /batch_wait=1/
    );
  }
);

await edgeCase(
  "an expired listing closes and advances the batch",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href =
      "https://www.adzuna.com/jobs";
    locationState.pathname = "/jobs";
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) =>
        message.type === "jobfinitum-result"
    );
    assert.equal(
      result.payload.status,
      "posting_closed"
    );
    assert.match(
      locationState.replacements.at(-1),
      /batch_wait=1/
    );
  }
);

await edgeCase(
  "tracked launch state is restored after navigation",
  async () => {
    state.elements = [
      new MockElement({
        text: "Apply",
        href:
          "https://jobs.lever.co/acme/role/apply",
      }),
    ];
    messageResponder = (message) => respond(
      message,
      {
        token: "restored-token",
        origin: "http://127.0.0.1:5000",
        batch: true,
      }
    );

    await hooks.run();

    assert.equal(
      sentMessages[0].type,
      "jobfinitum-job-board-restore"
    );
    const watch = sentMessages.find(
      (message) =>
        message.type
        === "jobfinitum-job-board-watch"
    );
    assert.equal(watch.token, "restored-token");
  }
);

await edgeCase(
  "a resolver timeout falls back and advances",
  async () => {
    locationState.hash = launchHash(true);
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) =>
        message.type === "jobfinitum-result"
    );
    assert.equal(
      result.payload.status,
      "needs_manual_destination"
    );
    assert.match(
      locationState.replacements.at(-1),
      /batch_wait=1/
    );
  }
);

const failures = results.filter(
  (result) => !result.passed
);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));

if (failures.length) {
  throw new Error(
    `${failures.length} Adzuna edge-case test(s) failed.`
  );
}
