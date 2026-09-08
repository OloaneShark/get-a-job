import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath = `${root}/browser_extensions/jobfinitum_chrome_agent/tokyo_dev_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");
assert.notEqual(startupIndex, -1, "Could not locate the TokyoDev startup call.");
assert.notEqual(closeIndex, -1, "Could not locate the TokyoDev closure.");

const hooksToExpose = [
  "activateControl",
  "applyControl",
  "applyIntentScore",
  "externalApplyLink",
  "isApplicationRedirectPath",
  "isExternalUrl",
  "isJobsIndex",
  "isLocationConfirmationPath",
  "normalizedResidencyAnswer",
  "residencyAnswer",
  "residencyConfirmationControl",
  "run",
  "visibleChallenge",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__tokyoDevTestHooks = {${hooksToExpose.join(",")}};`,
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
    children = [],
    onClick = null,
  } = {}) {
    this.tagName = tagName.toUpperCase();
    this.innerText = text;
    this.textContent = text;
    this.value = text;
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
    this.children = children;
    this.onClick = onClick;
    this.clickCount = 0;
    this.events = [];
    this.style = {};
  }
  getAttribute(name) {
    if (name === "href" && this.href) return this.href;
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  getBoundingClientRect() {
    return {left: 0, top: 0, right: 180, bottom: 44, width: 180, height: 44};
  }
  dispatchEvent(event) {
    this.events.push(event.type);
    return true;
  }
  click() {
    this.clickCount += 1;
    if (this.onClick) this.onClick(this);
  }
  scrollIntoView() {}
  focus() {}
  appendChild() {}
  querySelectorAll() {
    return this.children;
  }
}

const state = {
  elements: [],
  challenges: [],
  form: null,
  body: "",
};
const sentMessages = [];
let messageResponder = () => ({ok: true});
const statusElement = new MockElement({tagName: "DIV"});
const locationState = {
  href: "https://www.tokyodev.com/companies/acme/jobs/platform-engineer",
  hash: "",
  hostname: "www.tokyodev.com",
  pathname: "/companies/acme/jobs/platform-engineer",
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
  setTimeout(callback) {
    callback();
    return 1;
  },
  clearTimeout() {},
  getComputedStyle(element) {
    return element.computedStyle;
  },
  document: {
    title: "TokyoDev job",
    readyState: "complete",
    documentElement: new MockElement({tagName: "HTML"}),
    get body() {
      return {innerText: state.body, textContent: state.body};
    },
    getElementById(id) {
      return id === "jobfinitum-agent-status" ? statusElement : null;
    },
    createElement() {
      return new MockElement({tagName: "DIV"});
    },
    addEventListener() {},
    querySelector(selector) {
      return selector.includes("/location_confirmation") ? state.form : null;
    },
    querySelectorAll(selector) {
      if (
        selector.includes("recaptcha")
        || selector.includes("hcaptcha")
        || selector.includes("challenges.cloudflare.com")
        || selector.includes("cf-turnstile")
        || selector.includes("cf-challenge")
      ) {
        return state.challenges;
      }
      return state.elements;
    },
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
new vm.Script(instrumentedSource, {filename: "tokyo_dev_agent.js"})
  .runInContext(sandbox);
const hooks = sandbox.__tokyoDevTestHooks;

function resetState() {
  state.elements = [];
  state.challenges = [];
  state.form = null;
  state.body = "";
  sentMessages.length = 0;
  messageResponder = () => ({ok: true});
  locationState.href =
    "https://www.tokyodev.com/companies/acme/jobs/platform-engineer";
  locationState.hash = "";
  locationState.hostname = "www.tokyodev.com";
  locationState.pathname = "/companies/acme/jobs/platform-engineer";
  locationState.search = "";
  locationState.replacements.length = 0;
  sessionStorage.values.clear();
  sandbox.name = "";
  sandbox.document.title = "TokyoDev job";
}

function launchHash(batch = false) {
  return (
    "#jobfinitum_agent=token"
    + "&jobfinitum_origin="
    + encodeURIComponent("http://127.0.0.1:5000")
    + (batch ? "&jobfinitum_batch=1" : "")
  );
}

function respond(message, task = {}, restoredLaunch = null) {
  if (message.type === "jobfinitum-job-board-restore") {
    return {ok: true, launch: restoredLaunch};
  }
  if (message.type === "jobfinitum-task") {
    return {
      ok: true,
      task: {
        adapter: "tokyo_dev_resolver",
        target_url: locationState.href,
        reusable_answers: {currently_residing_in_japan: "Unknown"},
        application_questions: [],
        ...task,
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
  assert.equal(hooks.isExternalUrl("https://www.tokyodev.com/jobs"), false);
  assert.equal(hooks.isExternalUrl("http://127.0.0.1:5000/auto-apply"), false);
  assert.equal(hooks.isExternalUrl("javascript:void(0)"), false);
  assert.equal(
    hooks.isExternalUrl("https://job-boards.greenhouse.io/acme/jobs/123"),
    true
  );
});

await edgeCase("redirect and residency paths are distinguished", async () => {
  assert.equal(
    hooks.isApplicationRedirectPath(
      "https://www.tokyodev.com/c/acme/j/role/applications/new"
    ),
    true
  );
  assert.equal(
    hooks.isLocationConfirmationPath(
      "https://www.tokyodev.com/c/acme/j/role/location_confirmation/new"
    ),
    true
  );
  assert.equal(hooks.isJobsIndex(), false);
});

await edgeCase("Continue applying outranks unrelated links", async () => {
  const company = new MockElement({
    text: "Company website",
    href: "https://example.com",
  });
  const apply = new MockElement({
    text: "Continue applying",
    href: "https://www.tokyodev.com/c/acme/j/role/applications/new",
  });
  state.elements = [company, apply];
  assert.equal(hooks.applyControl(), apply);
  assert.ok(hooks.applyIntentScore(apply) > hooks.applyIntentScore(company));
});

await edgeCase("disabled Apply controls are ignored", async () => {
  state.elements = [
    new MockElement({
      text: "Continue applying",
      href: "https://www.tokyodev.com/c/acme/j/one/applications/new",
      disabled: true,
    }),
    new MockElement({
      text: "Apply now",
      href: "https://www.tokyodev.com/c/acme/j/two/applications/new",
      attributes: {"aria-disabled": "true"},
    }),
  ];
  assert.equal(hooks.applyControl(), null);
});

await edgeCase("residency answers are normalized without guessing", async () => {
  assert.equal(hooks.normalizedResidencyAnswer("Yes"), "yes");
  assert.equal(
    hooks.normalizedResidencyAnswer("I am not a resident of Japan"),
    "no"
  );
  assert.equal(
    hooks.normalizedResidencyAnswer("I am not currently a resident of Japan"),
    "no"
  );
  assert.equal(
    hooks.normalizedResidencyAnswer("I do not currently reside in Japan"),
    "no"
  );
  assert.equal(hooks.normalizedResidencyAnswer("Unknown"), "unknown");
});

await edgeCase("saved application residency overrides the profile", async () => {
  assert.equal(
    hooks.residencyAnswer({
      reusable_answers: {currently_residing_in_japan: "No"},
      application_questions: [{
        field_name: "currently_residing_in_japan",
        text: "Do you currently reside in Japan?",
        answer: "Yes",
      }],
    }),
    "yes"
  );
});

await edgeCase("the real resident confirmation is selected", async () => {
  const cancel = new MockElement({tagName: "BUTTON", text: "Cancel"});
  const resident = new MockElement({
    tagName: "BUTTON",
    text: "I am a resident of Japan",
    attributes: {type: "submit"},
  });
  state.form = new MockElement({
    tagName: "FORM",
    children: [cancel, resident],
  });
  assert.equal(hooks.residencyConfirmationControl(), resident);
});

await edgeCase("activation keeps the handoff in the managed tab", async () => {
  const apply = new MockElement({
    text: "Continue applying",
    href: "https://www.tokyodev.com/c/acme/j/role/applications/new",
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

await edgeCase("the full resolver follows Apply and reports the ATS", async () => {
  locationState.hash = launchHash(true);
  const external = new MockElement({
    text: "Apply now",
    href: "https://job-boards.greenhouse.io/acme/jobs/123",
  });
  const apply = new MockElement({
    text: "Continue applying",
    href: "https://www.tokyodev.com/c/acme/j/role/applications/new",
    onClick() {
      state.elements = [external];
    },
  });
  state.elements = [apply];
  messageResponder = (message) => respond(message);
  await hooks.run();
  assert.equal(apply.clickCount, 1);
  const resolved = sentMessages.find(
    (message) => message.type === "jobfinitum-job-board-resolved"
  );
  assert.equal(resolved.url, external.href);
  assert.equal(resolved.batch, true);
});

await edgeCase("a confirmed resident can pass the location gate", async () => {
  locationState.href =
    "https://www.tokyodev.com/c/acme/j/role/location_confirmation/new";
  locationState.pathname =
    "/c/acme/j/role/location_confirmation/new";
  locationState.hash = launchHash();
  const external = new MockElement({
    text: "Apply now",
    href: "https://jobs.ashbyhq.com/acme/application",
  });
  const resident = new MockElement({
    tagName: "BUTTON",
    text: "I am a resident of Japan",
    onClick() {
      state.elements = [external];
    },
  });
  state.form = new MockElement({tagName: "FORM", children: [resident]});
  messageResponder = (message) => respond(message, {
    reusable_answers: {currently_residing_in_japan: "Yes"},
  });
  await hooks.run();
  assert.equal(resident.clickCount, 1);
  assert.equal(sentMessages.at(-1).type, "jobfinitum-job-board-resolved");
});

await edgeCase("a nonresident is never falsely confirmed", async () => {
  locationState.href =
    "https://www.tokyodev.com/c/acme/j/role/location_confirmation/new";
  locationState.pathname =
    "/c/acme/j/role/location_confirmation/new";
  locationState.hash = launchHash(true);
  const resident = new MockElement({
    tagName: "BUTTON",
    text: "I am a resident of Japan",
  });
  state.form = new MockElement({tagName: "FORM", children: [resident]});
  messageResponder = (message) => respond(message, {
    reusable_answers: {currently_residing_in_japan: "No"},
  });
  await hooks.run();
  assert.equal(resident.clickCount, 0);
  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "needs_manual_destination");
  assert.match(result.payload.message, /do not currently reside/i);
  assert.match(locationState.replacements.at(-1), /batch_wait=1/);
});

await edgeCase("unknown residency falls back instead of guessing", async () => {
  locationState.href =
    "https://www.tokyodev.com/c/acme/j/role/location_confirmation/new";
  locationState.pathname =
    "/c/acme/j/role/location_confirmation/new";
  locationState.hash = launchHash();
  state.form = new MockElement({
    tagName: "FORM",
    children: [new MockElement({
      tagName: "BUTTON",
      text: "I am a resident of Japan",
    })],
  });
  messageResponder = (message) => respond(message);
  await hooks.run();
  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "needs_manual_destination");
  assert.match(result.payload.message, /Applicant Profile/);
});

await edgeCase("ordinary application questions are not verification", async () => {
  state.body =
    "Please choose your nationality and Japanese proficiency.";
  assert.equal(hooks.visibleChallenge(), false);
});

await edgeCase("a visible Cloudflare challenge pauses the runner", async () => {
  locationState.hash = launchHash(true);
  state.challenges = [new MockElement({tagName: "IFRAME"})];
  messageResponder = (message) => respond(message);
  await hooks.run();
  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "waiting_verification");
  assert.equal(locationState.replacements.length, 0);
});

await edgeCase("a jobs-index redirect reports the posting closed", async () => {
  locationState.href = "https://www.tokyodev.com/jobs";
  locationState.pathname = "/jobs";
  locationState.hash = launchHash();
  messageResponder = (message) => respond(message);
  await hooks.run();
  const result = sentMessages.find(
    (message) => message.type === "jobfinitum-result"
  );
  assert.equal(result.payload.status, "posting_closed");
});

await edgeCase("a tracked redirect launch is restored", async () => {
  const external = new MockElement({
    text: "Apply now",
    href: "https://jobs.lever.co/acme/role/apply",
  });
  state.elements = [external];
  const restored = {
    token: "restored-token",
    origin: "http://127.0.0.1:5000",
    batch: false,
  };
  messageResponder = (message) => respond(message, {}, restored);
  await hooks.run();
  const resolved = sentMessages.find(
    (message) => message.type === "jobfinitum-job-board-resolved"
  );
  assert.equal(resolved.token, "restored-token");
  assert.equal(resolved.url, external.href);
});

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));
if (failures.length) {
  throw new Error(
    `${failures.length} TokyoDev edge-case test(s) failed.`
  );
}
