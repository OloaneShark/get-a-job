import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/jobicy_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(startupIndex, -1, "Could not locate the Jobicy startup call.");
assert.notEqual(closeIndex, -1, "Could not locate the Jobicy closure.");

const hooksToExpose = [
  "blockedPage",
  "currentJobId",
  "guestHost",
  "guestRequestConfig",
  "isExternalUrl",
  "isJobsIndex",
  "postingClosed",
  "registrationOnlyGate",
  "requestGuestDestination",
  "run",
  "visibleChallenge",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__jobicyTestHooks = {${hooksToExpose.join(",")}};`,
  source.slice(closeIndex),
].join("");

class MockElement {
  constructor({
    text = "",
    attributes = {},
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
    this.innerText = text;
    this.textContent = text;
    this.attributes = {...attributes};
    this.hidden = hidden;
    this.computedStyle = {
      display: "block",
      visibility: "visible",
      opacity: "1",
      ...style,
    };
    this.rect = {...rect};
    this.style = {};
  }

  getAttribute(name) {
    return Object.hasOwn(this.attributes, name)
      ? this.attributes[name]
      : null;
  }

  getBoundingClientRect() {
    return {...this.rect};
  }

  appendChild() {}
}

let clockNow = 0;
class MockDate extends Date {
  static now() {
    clockNow += 500;
    return clockNow;
  }
}

const listeners = new Map();
const documentState = {
  bodyText: "",
  challenges: [],
  guest: null,
  meta: null,
  scripts: [],
};
const sentMessages = [];
const fetchCalls = [];
let messageResponder = () => ({ok: true});
let fetchResponder = async () => ({
  ok: true,
  async json() {
    return {
      url: "https://jobs.lever.co/example/role/apply",
    };
  },
});
const locationState = {
  href: "https://jobicy.com/jobs/152678-example-role",
  origin: "https://jobicy.com",
  hash: "",
  hostname: "jobicy.com",
  pathname: "/jobs/152678-example-role",
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

const statusElement = new MockElement();
const rootElement = new MockElement();
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
  clearTimeout() {},
  addEventListener(type, callback) {
    listeners.set(type, callback);
  },
  getComputedStyle: (element) => element.computedStyle,
  async fetch(url, options = {}) {
    fetchCalls.push({url: String(url), options});
    return fetchResponder(url, options);
  },
  document: {
    title: "Remote role at Example - Jobicy",
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
    get scripts() {
      return documentState.scripts;
    },
    addEventListener() {},
    getElementById: (id) =>
      id === "jobfinitum-agent-status" ? statusElement : null,
    createElement: () => new MockElement(),
    querySelector(selector) {
      if (selector.startsWith('meta[http-equiv="refresh"')) {
        return documentState.meta;
      }
      if (selector === '[id^="_w_"][data-t]') {
        return documentState.guest;
      }
      return null;
    },
    querySelectorAll(selector) {
      return selector.includes("recaptcha")
        ? documentState.challenges
        : [];
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
  filename: "jobicy_agent.js",
}).runInContext(sandbox);
const hooks = sandbox.__jobicyTestHooks;
const contextWindow = vm.runInContext(
  "window",
  sandbox
);

function resetState() {
  clockNow = 0;
  sandbox.document.title = "Remote role at Example - Jobicy";
  documentState.bodyText = "";
  documentState.challenges = [];
  documentState.guest = null;
  documentState.meta = null;
  documentState.scripts = [];
  sentMessages.length = 0;
  fetchCalls.length = 0;
  messageResponder = () => ({ok: true});
  fetchResponder = async () => ({
    ok: true,
    async json() {
      return {
        url: "https://jobs.lever.co/example/role/apply",
      };
    },
  });
  locationState.href = "https://jobicy.com/jobs/152678-example-role";
  locationState.origin = "https://jobicy.com";
  locationState.hash = "";
  locationState.hostname = "jobicy.com";
  locationState.pathname = "/jobs/152678-example-role";
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
        adapter: "jobicy_resolver",
        target_url: locationState.href,
      },
    };
  }
  return {ok: true};
}

function guestScript({
  action = "fpc-action",
  nonce = "nonce-value",
  postId = "152678",
} = {}) {
  return new MockElement({
    text: (
      "var asteroid={'action':'" + action
      + "','nonce':'" + nonce
      + "','post_id':" + postId
      + ",'increment_clicks':true};"
      + "headers:{'X-Jobicy-Ajax':'true'};"
      + "window.postMessage({type:'JOBICY_APPLICATION_STARTED'});"
    ),
  });
}

function installGuestMarkup(options = {}) {
  documentState.guest = new MockElement({
    attributes: {
      id: "_w_152678",
      "data-t": "Continue as guest",
    },
  });
  documentState.scripts = [
    guestScript(options),
  ];
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
  assert.equal(hooks.isExternalUrl("/jobs/example"), false);
  assert.equal(hooks.isExternalUrl("https://www.jobicy.com/jobs/example"), false);
  assert.equal(hooks.isExternalUrl("http://127.0.0.1:5000/auto-apply"), false);
  assert.equal(hooks.isExternalUrl("javascript:void(0)"), false);
  assert.equal(
    hooks.isExternalUrl("https://jobs.ashbyhq.com/example/application"),
    true
  );
});

await edgeCase("the current Jobicy job ID is read from the listing", async () => {
  assert.equal(hooks.currentJobId(), "152678");
  locationState.pathname = "/jobs/not-a-job";
  assert.equal(hooks.currentJobId(), "");
});

await edgeCase("the guest request action and nonce are extracted", async () => {
  installGuestMarkup();
  const config = hooks.guestRequestConfig();
  assert.equal(config.action, "fpc-action");
  assert.equal(config.nonce, "nonce-value");
  assert.equal(config.postId, "152678");
});

await edgeCase("a guest request for another job is rejected", async () => {
  installGuestMarkup({postId: "999999"});
  assert.equal(hooks.guestRequestConfig(), null);
});

await edgeCase("the guest request matches Jobicy's live POST contract", async () => {
  installGuestMarkup();
  const target = await hooks.requestGuestDestination(
    hooks.guestRequestConfig()
  );

  assert.equal(target, "https://jobs.lever.co/example/role/apply");
  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, "https://jobicy.com/signals.php");
  assert.equal(fetchCalls[0].options.method, "POST");
  assert.equal(
    fetchCalls[0].options.headers["X-Jobicy-Ajax"],
    "true"
  );
  const body = new URLSearchParams(fetchCalls[0].options.body);
  assert.equal(body.get("action"), "fpc-action");
  assert.equal(body.get("nonce"), "nonce-value");
  assert.equal(body.get("post_id"), "152678");
  assert.equal(body.get("increment_clicks"), "true");
});

await edgeCase("insecure and same-site destinations are rejected", async () => {
  installGuestMarkup();
  fetchResponder = async () => ({
    ok: true,
    async json() {
      return {url: "http://jobs.example.com/apply"};
    },
  });
  await assert.rejects(
    () => hooks.requestGuestDestination(hooks.guestRequestConfig()),
    /valid employer application URL/
  );

  fetchResponder = async () => ({
    ok: true,
    async json() {
      return {url: "https://jobicy.com/jobs/another"};
    },
  });
  await assert.rejects(
    () => hooks.requestGuestDestination(hooks.guestRequestConfig()),
    /valid employer application URL/
  );
});

await edgeCase("a failed guest endpoint is surfaced", async () => {
  installGuestMarkup();
  fetchResponder = async () => ({
    ok: false,
    async json() {
      return {};
    },
  });
  await assert.rejects(
    () => hooks.requestGuestDestination(hooks.guestRequestConfig()),
    /guest application request failed/
  );
});

await edgeCase("the full resolver uses Continue as guest", async () => {
  locationState.hash = launchHash({batch: true});
  installGuestMarkup();
  messageResponder = taskResponder;

  await hooks.run();

  assert.deepEqual(
    sentMessages.map((message) => message.type),
    [
      "jobfinitum-batch-register",
      "jobfinitum-job-board-watch",
      "jobfinitum-task",
      "jobfinitum-job-board-resolved",
    ]
  );
  assert.equal(sentMessages.at(-1).url, "https://jobs.lever.co/example/role/apply");
  assert.equal(sentMessages.at(-1).batch, true);
  assert.equal(fetchCalls.length, 1);
});

await edgeCase("generic application questions are not verification", async () => {
  documentState.bodyText = (
    "What gender identity do you most closely identify with? "
    + "Are you a veteran?"
  );
  assert.equal(hooks.visibleChallenge(), false);
});

await edgeCase("a visible challenge pauses without resolving a target", async () => {
  locationState.hash = launchHash({batch: true});
  documentState.challenges = [new MockElement()];
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "waiting_verification");
  assert.equal(result.payload.detail.verification_required, true);
  assert.equal(fetchCalls.length, 0);
  assert.equal(locationState.replacements.length, 0);
});

await edgeCase("a Cloudflare interstitial is verification", async () => {
  sandbox.document.title = "Just a moment...";
  documentState.bodyText =
    "Enable JavaScript and cookies to continue";
  assert.equal(hooks.visibleChallenge(), true);
  assert.equal(hooks.blockedPage(), false);
});

await edgeCase("a registration-only listing pauses for sign-in", async () => {
  locationState.hash = launchHash({batch: true});
  documentState.bodyText =
    "Create your free account, then apply.";
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "waiting_sign_in");
  assert.equal(
    result.payload.detail.sign_in_url,
    "https://jobicy.com/login"
  );
  assert.equal(
    locationState.replacements.at(-1),
    "http://127.0.0.1:5000/browser-agent?batch_wait=1"
  );
});

await edgeCase("missing guest script falls back to Manual Apply", async () => {
  locationState.hash = launchHash({batch: true});
  documentState.bodyText =
    "Create your free account, then apply.";
  documentState.guest = new MockElement({
    attributes: {
      id: "_w_152678",
      "data-t": "Continue as guest",
    },
  });
  messageResponder = taskResponder;

  await hooks.run();

  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "needs_manual_destination");
  assert.equal(fetchCalls.length, 0);
});

await edgeCase("an expired listing reports Closed and advances", async () => {
  locationState.hash = launchHash({batch: true});
  locationState.href = "https://jobicy.com/jobs";
  locationState.pathname = "/jobs";
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
});

await edgeCase("Jobicy's application-started event is a fallback", async () => {
  locationState.hash = launchHash();
  messageResponder = taskResponder;
  listeners.get("message")({
    source: contextWindow,
    origin: "https://jobicy.com",
    data: {
      type: "JOBICY_APPLICATION_STARTED",
      applyUrl: "https://jobs.ashbyhq.com/example/application",
    },
  });

  await hooks.run();

  const resolved = sentMessages.find(
    (message) => message.type === "jobfinitum-job-board-resolved"
  );
  assert.equal(
    resolved.url,
    "https://jobs.ashbyhq.com/example/application"
  );
  assert.equal(fetchCalls.length, 0);
});

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));
if (failures.length) {
  throw new Error(`${failures.length} Jobicy edge-case test(s) failed.`);
}
