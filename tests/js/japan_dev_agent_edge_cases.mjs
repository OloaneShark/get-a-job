import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const agentPath = `${root}/browser_extensions/jobfinitum_chrome_agent/japan_dev_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(startupIndex, -1, "Could not locate the Japan Dev startup call.");
assert.notEqual(closeIndex, -1, "Could not locate the Japan Dev closure.");

const hooksToExpose = [
  "activateApplyControl",
  "applyControl",
  "applyIntentScore",
  "embeddedApplicationTarget",
  "externalApplyLink",
  "isExternalUrl",
  "isJobsIndex",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__japanDevTestHooks = {${hooksToExpose.join(",")}};`,
  source.slice(closeIndex),
].join("");

class MockEvent {
  constructor(type, options = {}) {
    this.type = type;
    Object.assign(this, options);
  }
}

class MockElement {
  constructor({text = "", href = "", className = "", hidden = false} = {}) {
    this.tagName = "A";
    this.innerText = text;
    this.textContent = text;
    this.value = "";
    this.href = href;
    this.hidden = hidden;
    this.disabled = false;
    this.attributes = {class: className};
    this.style = {};
    this.clickCount = 0;
    this.events = [];
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getBoundingClientRect() {
    return {width: 180, height: 44};
  }

  dispatchEvent(event) {
    this.events.push(event.type);
    return true;
  }

  scrollIntoView() {}

  focus() {}

  click() {
    this.clickCount += 1;
  }
}

let controls = [];
const locationState = {
  href: "https://japan-dev.com/jobs/example/target-job",
  hostname: "japan-dev.com",
  pathname: "/jobs/example/target-job",
  hash: "",
  search: "",
  replace() {},
};
const documentState = {
  querySelector() {
    return null;
  },
  querySelectorAll() {
    return controls;
  },
  getElementById() {
    return null;
  },
  createElement() {
    return new MockElement();
  },
  documentElement: {appendChild() {}},
  title: "Japan Dev job",
};
const storage = new Map();
const context = vm.createContext({
  URL,
  URLSearchParams,
  JSON,
  Date,
  Promise,
  WeakSet,
  console,
  setTimeout,
  clearTimeout,
  location: locationState,
  document: documentState,
  history: {replaceState() {}},
  getComputedStyle: () => ({
    display: "block",
    visibility: "visible",
    opacity: "1",
  }),
  MouseEvent: MockEvent,
  chrome: {
    runtime: {
      lastError: null,
      sendMessage(_message, callback) {
        callback({ok: true});
      },
    },
  },
  self: {},
  window: {
    name: "",
    location: locationState,
    sessionStorage: {
      getItem(key) {
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        storage.set(key, String(value));
      },
      removeItem(key) {
        storage.delete(key);
      },
    },
  },
});
context.window.window = context.window;
context.window.document = documentState;
context.window.history = context.history;

vm.runInContext(instrumentedSource, context, {filename: agentPath});
const hooks = context.self.__japanDevTestHooks;

const employerUrl = "https://jobs.lever.co/example/target-job/apply";
const payload = [
  "unused",
  {slug: 2, application_url: 3},
  "target-job",
  employerUrl,
  {slug: 5, application_url: 6},
  "different-job",
  "https://jobs.ashbyhq.com/example/different-job",
];
const nuxtRoot = {
  querySelector(selector) {
    return selector === "#__NUXT_DATA__"
      ? {textContent: JSON.stringify(payload)}
      : null;
  },
};

assert.equal(
  hooks.embeddedApplicationTarget(
    nuxtRoot,
    "https://japan-dev.com/jobs/example/target-job"
  ),
  employerUrl,
  "The current job must resolve through its Nuxt application_url reference."
);
assert.equal(
  hooks.embeddedApplicationTarget(
    nuxtRoot,
    "https://japan-dev.com/jobs/example/missing-job"
  ),
  null,
  "A related job record must not be used for the current listing."
);
assert.equal(
  hooks.embeddedApplicationTarget(
    {querySelector: () => ({textContent: "{broken"})},
    locationState.href
  ),
  null,
  "Malformed page data must fall back without throwing."
);
assert.equal(hooks.isExternalUrl("https://japan-dev.com/jobs/example/one"), false);
assert.equal(hooks.isExternalUrl("mailto:jobs@example.com"), false);
assert.equal(hooks.isExternalUrl("https://jobs.ashbyhq.com/example/one"), true);

const topApply = new MockElement({
  text: "APPLY NOW",
  className: "btn btn__top-apply",
});
const relatedApply = new MockElement({text: "Apply"});
assert.ok(
  hooks.applyIntentScore(topApply) > hooks.applyIntentScore(relatedApply),
  "The primary Japan Dev Apply control must outrank related-job controls."
);

controls = [
  new MockElement({
    text: "Company",
    href: "https://example.com/about",
  }),
  new MockElement({
    text: "Apply now",
    href: employerUrl,
  }),
];
assert.equal(hooks.externalApplyLink(), employerUrl);

const externalControl = controls[1];
await hooks.activateApplyControl(externalControl);
assert.equal(externalControl.attributes.target, "_self");
assert.equal(externalControl.clickCount, 1);

locationState.pathname = "/jobs/";
assert.equal(hooks.isJobsIndex(), true);
locationState.pathname = "/jobs/example/target-job";
assert.equal(hooks.isJobsIndex(), false);

console.log("Japan Dev Browser Agent edge cases passed.");
