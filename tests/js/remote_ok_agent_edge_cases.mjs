import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/remote_ok_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(startupIndex, -1, "Could not locate the Remote OK startup call.");
assert.notEqual(closeIndex, -1, "Could not locate the Remote OK closure.");

const hooksToExpose = [
  "activateControl",
  "blockedPage",
  "continueControl",
  "continueIntentScore",
  "isApplyRedirect",
  "isExternalUrl",
  "isJobsIndex",
  "metaRefreshTarget",
  "postingClosed",
  "run",
  "visibleChallenge",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__remoteOkTestHooks = {${hooksToExpose.join(",")}};`,
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
    this.clickCount = 0;
    this.events = [];
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
  }

  scrollIntoView() {}

  focus() {}

  appendChild() {}
}

let clockNow = 0;
class MockDate extends Date {
  static now() {
    clockNow += 500;
    return clockNow;
  }
}

const statusElement = new MockElement({tagName: "DIV"});
const rootElement = new MockElement({tagName: "HTML"});
const documentState = {
  bodyText: "",
  controls: [],
  challenges: [],
  meta: null,
};
const sentMessages = [];
let messageResponder = () => ({ok: true});
const locationState = {
  href: "https://remoteok.com/remote-jobs/example-role-123",
  hash: "",
  hostname: "remoteok.com",
  pathname: "/remote-jobs/example-role-123",
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
  Date: MockDate,
  console,
  MouseEvent: MockEvent,
  setTimeout: (callback) => {
    callback();
    return 1;
  },
  clearTimeout() {},
  getComputedStyle: (element) => element.computedStyle,
  document: {
    title: "Remote role at Example",
    readyState: "complete",
    documentElement: rootElement,
    body: {
      get innerText() {
        return documentState.bodyText;
      },
      get textContent() {
        return documentState.bodyText;
      },
    },
    addEventListener() {},
    getElementById: (id) =>
      id === "jobfinitum-agent-status" ? statusElement : null,
    createElement: () => new MockElement({tagName: "DIV"}),
    querySelector(selector) {
      return selector.startsWith('meta[http-equiv="refresh"')
        ? documentState.meta
        : null;
    },
    querySelectorAll(selector) {
      return selector.includes("recaptcha")
        ? documentState.challenges
        : documentState.controls;
    },
  },
  location: locationState,
  history: {
    replaceState() {
      locationState.hash = "";
    },
  },
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
  filename: "remote_ok_agent.js",
}).runInContext(sandbox);
const hooks = sandbox.__remoteOkTestHooks;

function resetState() {
  clockNow = 0;
  sandbox.document.title = "Remote role at Example";
  documentState.bodyText = "";
  documentState.controls = [];
  documentState.challenges = [];
  documentState.meta = null;
  sentMessages.length = 0;
  messageResponder = () => ({ok: true});
  locationState.href = "https://remoteok.com/remote-jobs/example-role-123";
  locationState.hash = "";
  locationState.hostname = "remoteok.com";
  locationState.pathname = "/remote-jobs/example-role-123";
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
        adapter: "remote_ok_resolver",
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
  assert.equal(hooks.isExternalUrl("/l/123"), false);
  assert.equal(
    hooks.isExternalUrl("https://www.remoteok.com/l/123"),
    false
  );
  assert.equal(hooks.isExternalUrl("http://127.0.0.1:5000/auto-apply"), false);
  assert.equal(hooks.isExternalUrl("javascript:void(0)"), false);
  assert.equal(
    hooks.isExternalUrl("https://jobs.lever.co/example/role/apply"),
    true
  );
});

await edgeCase("the primary Apply action beats promotions and tooltips", async () => {
  const promotion = new MockElement({
    text: "Unlock your remote career potential with Remote OK Premium",
    href: "https://remoteok.com/premium",
  });
  const tooltip = new MockElement({
    text: "Apply",
    href: "https://remoteok.com/l/123",
    attributes: {class: "no-border tooltip"},
  });
  const apply = new MockElement({
    text: "Apply now",
    href: "https://remoteok.com/l/123",
    attributes: {
      class: "button action-apply",
      "data-job-id": "123",
    },
  });
  documentState.controls = [promotion, tooltip, apply];

  assert.equal(hooks.continueIntentScore(promotion), 0);
  assert.equal(hooks.continueControl(), apply);
});

await edgeCase("hidden and disabled Apply controls are ignored", async () => {
  const hidden = new MockElement({
    text: "Apply now",
    href: "https://remoteok.com/l/123",
    hidden: true,
  });
  const disabled = new MockElement({
    text: "Apply for this job",
    href: "https://remoteok.com/l/123",
    disabled: true,
  });
  const visible = new MockElement({
    text: "Apply",
    href: "https://remoteok.com/l/123",
  });
  documentState.controls = [hidden, disabled, visible];

  assert.equal(hooks.continueControl(), visible);
});

await edgeCase("activation stays in the managed resolver tab", async () => {
  const apply = new MockElement({
    text: "Apply now",
    href: "https://remoteok.com/l/123",
    attributes: {target: "_blank"},
  });

  assert.equal(await hooks.activateControl(apply), true);
  assert.deepEqual(
    apply.events,
    ["pointerdown", "mousedown", "pointerup", "mouseup"]
  );
  assert.equal(apply.clickCount, 1);
  assert.equal(apply.getAttribute("target"), "_self");
});

await edgeCase("job indexes and Apply redirects are distinguished", async () => {
  locationState.pathname = "/remote-jobs";
  assert.equal(hooks.isJobsIndex(), true);
  locationState.pathname = "/l/1135318";
  assert.equal(hooks.isApplyRedirect(), true);
  assert.equal(hooks.isJobsIndex(), false);
});

await edgeCase("expired job language is recognized", async () => {
  documentState.bodyText =
    "This job is no longer available and has been removed.";
  assert.equal(hooks.postingClosed(), true);
});

await edgeCase("meta refresh destinations are parsed safely", async () => {
  documentState.meta = new MockElement({
    attributes: {
      content: "0; URL='https://jobs.ashbyhq.com/example/application'",
    },
  });
  assert.equal(
    hooks.metaRefreshTarget(),
    "https://jobs.ashbyhq.com/example/application"
  );
  documentState.meta = new MockElement({attributes: {content: "5"}});
  assert.equal(hooks.metaRefreshTarget(), null);
});

await edgeCase("a rendered Apply control is clicked only once", async () => {
  locationState.hash = launchHash({batch: true});
  const apply = new MockElement({
    text: "Apply now",
    href: "https://remoteok.com/l/123",
    attributes: {
      class: "button action-apply",
      "data-job-id": "123",
    },
  });
  documentState.controls = [apply];
  messageResponder = taskResponder;

  await hooks.run();

  assert.equal(apply.clickCount, 1);
  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "needs_manual_destination");
  assert.equal(
    locationState.replacements.at(-1),
    "http://127.0.0.1:5000/browser-agent?batch_wait=1"
  );
});

await edgeCase("a stalled no-JavaScript handoff falls back cleanly", async () => {
  locationState.hash = launchHash({batch: true});
  locationState.href = "https://remoteok.com/l/1135318";
  locationState.pathname = "/l/1135318";
  documentState.bodyText =
    "Please enable JavaScript in your browser to apply to this job";
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "needs_manual_destination");
  assert.equal(
    locationState.replacements.at(-1),
    "http://127.0.0.1:5000/browser-agent?batch_wait=1"
  );
});

await edgeCase("a meta redirect remains inside the tracked tab", async () => {
  locationState.hash = launchHash();
  documentState.meta = new MockElement({
    attributes: {
      content: "0;url=https://job-boards.greenhouse.io/example/jobs/123",
    },
  });
  messageResponder = taskResponder;

  await hooks.run();

  assert.equal(
    locationState.replacements.at(-1),
    "https://job-boards.greenhouse.io/example/jobs/123"
  );
  assert.equal(
    sentMessages.some((message) => message.type === "jobfinitum-result"),
    false
  );
});

await edgeCase("visible verification pauses without closing the tab", async () => {
  locationState.hash = launchHash({batch: true});
  documentState.challenges = [new MockElement({tagName: "IFRAME"})];
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "waiting_verification");
  assert.equal(result.payload.detail.verification_required, true);
  assert.equal(locationState.replacements.length, 0);
});

await edgeCase("a Cloudflare interstitial is verification", async () => {
  sandbox.document.title = "Just a moment...";
  documentState.bodyText =
    "Enable JavaScript and cookies to continue";

  assert.equal(hooks.visibleChallenge(), true);
  assert.equal(hooks.blockedPage(), false);
});

await edgeCase("an access block becomes Manual Apply and advances", async () => {
  locationState.hash = launchHash({batch: true});
  documentState.bodyText = "403 Forbidden. Access denied.";
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "needs_manual_destination");
  assert.equal(result.payload.detail.resolver, "remote_ok_browser_agent");
  assert.equal(
    locationState.replacements.at(-1),
    "http://127.0.0.1:5000/browser-agent?batch_wait=1"
  );
});

await edgeCase("an expired listing reports Closed and advances", async () => {
  locationState.hash = launchHash({batch: true});
  locationState.href = "https://remoteok.com/remote-jobs";
  locationState.pathname = "/remote-jobs";
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "posting_closed");
  assert.equal(
    locationState.replacements.at(-1),
    "http://127.0.0.1:5000/browser-agent?batch_wait=1"
  );
});

await edgeCase("a stripped launch fragment is restored", async () => {
  documentState.bodyText = "Request blocked";
  messageResponder = (message) => {
    if (message.type === "jobfinitum-job-board-restore") {
      return {
        ok: true,
        launch: {
          token: "restored-token",
          origin: "http://127.0.0.1:5000",
          batch: true,
        },
      };
    }
    return taskResponder(message);
  };

  await hooks.run();

  assert.equal(sentMessages[0].type, "jobfinitum-job-board-restore");
  const watch = sentMessages.find(
    (message) => message.type === "jobfinitum-job-board-watch"
  );
  assert.equal(watch.token, "restored-token");
  assert.equal(watch.batch, true);
});

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));
if (failures.length) {
  throw new Error(`${failures.length} Remote OK edge-case test(s) failed.`);
}

