import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath = `${root}/browser_extensions/jobfinitum_chrome_agent/remote_first_jobs_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(startupIndex, -1, "Could not locate the Remote First Jobs startup call.");
assert.notEqual(closeIndex, -1, "Could not locate the Remote First Jobs closure.");

const hooksToExpose = [
  "activateApplyControl",
  "applyControl",
  "applyIntentScore",
  "externalApplyLink",
  "isExternalUrl",
  "isJobsIndex",
  "run",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__remoteFirstJobsTestHooks = {${hooksToExpose.join(",")}};`,
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
    style = {},
    rect = {left: 0, top: 0, right: 180, bottom: 44, width: 180, height: 44},
    onClick = null,
  } = {}) {
    this.tagName = tagName.toUpperCase();
    this.innerText = text;
    this.textContent = text;
    this.value = "";
    this.href = href;
    this.attributes = {...attributes};
    this.disabled = disabled;
    this.hidden = hidden;
    this.computedStyle = {
      display: "block",
      visibility: "visible",
      opacity: "1",
      ...style,
    };
    this.rect = {...rect};
    this.onClick = onClick;
    this.clickCount = 0;
    this.events = [];
    this.scrollCount = 0;
    this.focusCount = 0;
    this.style = {};
  }

  getAttribute(name) {
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
    if (this.onClick) this.onClick(this);
  }

  scrollIntoView() {
    this.scrollCount += 1;
  }

  focus() {
    this.focusCount += 1;
  }

  appendChild() {}
}

const statusElement = new MockElement({tagName: "DIV"});
const rootElement = new MockElement({tagName: "HTML"});
const documentState = {elements: []};
const sentMessages = [];
let messageResponder = () => ({ok: true});
const locationState = {
  href: "https://remotefirstjobs.com/companies/example/jobs/security-engineer-123",
  hash: "",
  hostname: "remotefirstjobs.com",
  pathname: "/companies/example/jobs/security-engineer-123",
  search: "",
  replacements: [],
  replace(value) {
    this.replacements.push(String(value));
  },
};

const sessionStorage = {
  values: new Map(),
  getItem(key) { return this.values.get(key) || null; },
  setItem(key, value) { this.values.set(key, value); },
  removeItem(key) { this.values.delete(key); },
};

const sandbox = {
  URL,
  URLSearchParams,
  WeakSet,
  console,
  MouseEvent: MockEvent,
  setTimeout: (callback) => {
    callback();
    return 1;
  },
  getComputedStyle: (element) => element.computedStyle,
  document: {
    title: "Remote First Jobs listing",
    documentElement: rootElement,
    getElementById: (id) => id === "jobfinitum-agent-status" ? statusElement : null,
    createElement: () => new MockElement({tagName: "DIV"}),
    querySelectorAll: () => documentState.elements,
  },
  location: locationState,
  history: {replaceState() {}},
  sessionStorage,
  chrome: {
    runtime: {
      lastError: null,
      sendMessage(message, callback) {
        sentMessages.push(message);
        callback(messageResponder(message));
      },
    },
  },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.name = "";

vm.createContext(sandbox);
new vm.Script(instrumentedSource, {filename: "remote_first_jobs_agent.js"})
  .runInContext(sandbox);
const hooks = sandbox.__remoteFirstJobsTestHooks;

function resetState() {
  documentState.elements = [];
  sentMessages.length = 0;
  messageResponder = () => ({ok: true});
  locationState.href = "https://remotefirstjobs.com/companies/example/jobs/security-engineer-123";
  locationState.hash = "";
  locationState.hostname = "remotefirstjobs.com";
  locationState.pathname = "/companies/example/jobs/security-engineer-123";
  locationState.search = "";
  locationState.replacements.length = 0;
  sessionStorage.values.clear();
  sandbox.name = "";
}

function launchHash({batch = false} = {}) {
  return `#jobfinitum_agent=token&jobfinitum_origin=${encodeURIComponent("http://127.0.0.1:5000")}${batch ? "&jobfinitum_batch=1" : ""}`;
}

function taskResponder(message) {
  if (message.type === "jobfinitum-task") {
    return {
      ok: true,
      task: {
        adapter: "remote_first_jobs_resolver",
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
    results.push({name, passed: false, error: error.message});
  }
}

await edgeCase("only external HTTP employer targets are accepted", async () => {
  assert.equal(hooks.isExternalUrl("/a/security-engineer-123"), false);
  assert.equal(hooks.isExternalUrl("https://remotefirstjobs.com/jobs"), false);
  assert.equal(hooks.isExternalUrl("http://127.0.0.1:5000/auto-apply"), false);
  assert.equal(hooks.isExternalUrl("javascript:void(0)"), false);
  assert.equal(hooks.isExternalUrl("https://jobs.ashbyhq.com/example/application"), true);
});

await edgeCase("the live relative Apply link is selected for activation", async () => {
  const company = new MockElement({
    text: "Company website",
    href: "https://example.com",
  });
  const apply = new MockElement({
    text: "Apply",
    href: "https://remotefirstjobs.com/a/security-engineer-123",
    attributes: {"aria-label": "Apply for this job (opens in a new tab)"},
  });
  documentState.elements = [company, apply];

  assert.equal(hooks.externalApplyLink(), null);
  assert.equal(hooks.applyControl(), apply);
  assert.ok(hooks.applyIntentScore(apply) > hooks.applyIntentScore(company));
});

await edgeCase("a direct external Apply link beats unrelated company links", async () => {
  const company = new MockElement({text: "Company website", href: "https://example.com"});
  const apply = new MockElement({text: "Apply now", href: "https://jobs.lever.co/example/123/apply"});
  documentState.elements = [company, apply];

  assert.equal(hooks.externalApplyLink(), apply.href);
});

await edgeCase("disabled and aria-disabled Apply controls are ignored", async () => {
  const disabled = new MockElement({text: "Apply", href: "/a/one", disabled: true});
  const ariaDisabled = new MockElement({
    text: "Apply now",
    href: "/a/two",
    attributes: {"aria-disabled": "true"},
  });
  documentState.elements = [disabled, ariaDisabled];

  assert.equal(hooks.applyControl(), null);
});

await edgeCase("activation uses browser events and one real click", async () => {
  const apply = new MockElement({
    text: "Apply",
    href: "https://remotefirstjobs.com/a/security-engineer-123",
    attributes: {target: "_blank"},
  });
  assert.equal(await hooks.activateApplyControl(apply), true);
  assert.deepEqual(apply.events, ["pointerdown", "mousedown", "pointerup", "mouseup"]);
  assert.equal(apply.clickCount, 1);
  assert.equal(apply.scrollCount, 1);
  assert.equal(apply.getAttribute("target"), "_self");
});

await edgeCase("the full resolver follows Apply and reports the external target", async () => {
  locationState.hash = launchHash({batch: true});
  const external = new MockElement({
    text: "Apply now",
    href: "https://jobs.ashbyhq.com/example/application",
  });
  const apply = new MockElement({
    text: "Apply",
    href: "https://remotefirstjobs.com/a/security-engineer-123",
    attributes: {"aria-label": "Apply for this job (opens in a new tab)"},
    onClick: () => {
      documentState.elements = [external];
    },
  });
  documentState.elements = [apply];
  messageResponder = taskResponder;

  await hooks.run();

  assert.equal(apply.clickCount, 1);
  assert.deepEqual(
    sentMessages.map((message) => message.type),
    [
      "jobfinitum-batch-register",
      "jobfinitum-task",
      "jobfinitum-job-board-watch",
      "jobfinitum-job-board-resolved",
    ]
  );
  assert.equal(sentMessages.at(-1).url, external.href);
  assert.equal(sentMessages.at(-1).batch, true);
});

await edgeCase("a jobs-index redirect reports a closed posting", async () => {
  locationState.href = "https://remotefirstjobs.com/jobs";
  locationState.pathname = "/jobs";
  locationState.hash = launchHash();
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find((message) => message.type === "jobfinitum-result");
  assert.equal(result.payload.status, "posting_closed");
  assert.equal(
    sentMessages.some((message) => message.type === "jobfinitum-job-board-watch"),
    false
  );
});

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));
if (failures.length) {
  throw new Error(`${failures.length} Remote First Jobs edge-case test(s) failed.`);
}
