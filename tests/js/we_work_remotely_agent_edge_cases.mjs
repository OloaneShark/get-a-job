import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/we_work_remotely_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(
  startupIndex,
  -1,
  "Could not locate the We Work Remotely startup call."
);
assert.notEqual(
  closeIndex,
  -1,
  "Could not locate the We Work Remotely closure."
);

const hooksToExpose = [
  "activateApplyControl",
  "applyControl",
  "applyIntentScore",
  "externalApplyLink",
  "isExternalUrl",
  "isJobsIndex",
  "isSignInPage",
  "lockedApplyControl",
  "run",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__weWorkRemotelyTestHooks = {${hooksToExpose.join(",")}};`,
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
    rect = {
      left: 0,
      top: 0,
      right: 180,
      bottom: 44,
      width: 180,
      height: 44,
    },
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
  href: "https://weworkremotely.com/remote-jobs/example-role",
  hash: "",
  hostname: "weworkremotely.com",
  pathname: "/remote-jobs/example-role",
  search: "",
  replacements: [],
  replace(value) {
    this.replacements.push(String(value));
  },
};

const sessionStorage = {
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
    title: "We Work Remotely listing",
    documentElement: rootElement,
    getElementById: (id) =>
      id === "jobfinitum-agent-status" ? statusElement : null,
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
new vm.Script(instrumentedSource, {
  filename: "we_work_remotely_agent.js",
}).runInContext(sandbox);
const hooks = sandbox.__weWorkRemotelyTestHooks;

function resetState() {
  documentState.elements = [];
  sentMessages.length = 0;
  messageResponder = () => ({ok: true});
  locationState.href =
    "https://weworkremotely.com/remote-jobs/example-role";
  locationState.hash = "";
  locationState.hostname = "weworkremotely.com";
  locationState.pathname = "/remote-jobs/example-role";
  locationState.search = "";
  locationState.replacements.length = 0;
  sessionStorage.values.clear();
  sandbox.name = "";
}

function launchHash({batch = false} = {}) {
  const origin = encodeURIComponent("http://127.0.0.1:5000");
  return (
    `#jobfinitum_agent=token&jobfinitum_origin=${origin}`
    + (batch ? "&jobfinitum_batch=1" : "")
  );
}

function taskResponder(message) {
  if (message.type === "jobfinitum-task") {
    return {
      ok: true,
      task: {
        adapter: "we_work_remotely_resolver",
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
  assert.equal(hooks.isExternalUrl("/remote-jobs/example"), false);
  assert.equal(
    hooks.isExternalUrl("https://www.weworkremotely.com/remote-jobs/example"),
    false
  );
  assert.equal(
    hooks.isExternalUrl("http://127.0.0.1:5000/auto-apply"),
    false
  );
  assert.equal(hooks.isExternalUrl("javascript:void(0)"), false);
  assert.equal(
    hooks.isExternalUrl("https://jobs.ashbyhq.com/example/application"),
    true
  );
});

await edgeCase("the real Apply control ignores Auto-Apply promotions", async () => {
  const promotion = new MockElement({
    text: "AI Auto-Apply",
    href: "https://example.com/job-copilot",
  });
  const apply = new MockElement({
    text: "Apply now",
    href: "https://weworkremotely.com/remote-jobs/example-role/apply",
    attributes: {class: "apply-btn"},
  });
  documentState.elements = [promotion, apply];

  assert.equal(hooks.applyIntentScore(promotion), 0);
  assert.equal(hooks.applyControl(), apply);
});

await edgeCase("locked Apply controls are recognized as an account gate", async () => {
  const locked = new MockElement({
    text: "Apply now",
    href: (
      "https://weworkremotely.com/job-seekers/account/register"
      + "?alert=Create+an+account"
    ),
    attributes: {
      class: "apply-btn apply-btn--locked",
      title: "Create an account to view full job details.",
    },
  });
  documentState.elements = [locked];

  assert.equal(hooks.lockedApplyControl(), locked);
  assert.equal(hooks.externalApplyLink(), null);
});

await edgeCase("account pages are recognized as sign-in gates", async () => {
  locationState.pathname = "/job-seekers/account/register";
  assert.equal(hooks.isSignInPage(), true);
  locationState.pathname = "/job-seekers/account/login";
  assert.equal(hooks.isSignInPage(), true);
  locationState.pathname = "/remote-jobs/example-role";
  assert.equal(hooks.isSignInPage(), false);
});

await edgeCase("activation stays in the managed resolver tab", async () => {
  const apply = new MockElement({
    text: "Apply now",
    href: "https://weworkremotely.com/remote-jobs/example-role/apply",
    attributes: {target: "_blank"},
  });
  assert.equal(await hooks.activateApplyControl(apply), true);
  assert.deepEqual(
    apply.events,
    ["pointerdown", "mousedown", "pointerup", "mouseup"]
  );
  assert.equal(apply.clickCount, 1);
  assert.equal(apply.getAttribute("target"), "_self");
});

await edgeCase("a direct employer target chains into the ATS agent", async () => {
  locationState.hash = launchHash({batch: true});
  const external = new MockElement({
    text: "Apply now",
    href: "https://jobs.lever.co/example/role/apply",
  });
  documentState.elements = [external];
  messageResponder = taskResponder;

  await hooks.run();

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

await edgeCase("a locked listing pauses for sign-in and returns the batch tab", async () => {
  locationState.hash = launchHash({batch: true});
  const locked = new MockElement({
    text: "Apply now",
    href: "https://weworkremotely.com/job-seekers/account/register",
    attributes: {class: "apply-btn apply-btn--locked"},
  });
  documentState.elements = [locked];
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "waiting_sign_in");
  assert.equal(
    result.payload.detail.sign_in_url,
    locked.href
  );
  assert.equal(locked.clickCount, 0);
  assert.equal(
    locationState.replacements.at(-1),
    "http://127.0.0.1:5000/browser-agent?batch_wait=1"
  );
});

await edgeCase("an interactive resume opens the account page", async () => {
  locationState.hash = launchHash();
  const locked = new MockElement({
    text: "Apply now",
    href: "https://weworkremotely.com/job-seekers/account/register",
    attributes: {class: "apply-btn apply-btn--locked"},
  });
  documentState.elements = [locked];
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "waiting_sign_in");
  assert.equal(locationState.replacements.at(-1), locked.href);
  assert.equal(
    sentMessages.some(
      (message) => message.type === "jobfinitum-close-agent-tab"
    ),
    false
  );
});

await edgeCase("an index redirect reports a closed posting", async () => {
  locationState.href = "https://weworkremotely.com/";
  locationState.pathname = "/";
  locationState.hash = launchHash();
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "posting_closed");
  assert.equal(
    sentMessages.some(
      (message) => message.type === "jobfinitum-job-board-watch"
    ),
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
  throw new Error(
    `${failures.length} We Work Remotely edge-case test(s) failed.`
  );
}
