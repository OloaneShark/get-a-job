import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(
  new URL("../..", import.meta.url)
);
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/employer_site_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(
  startupIndex,
  -1,
  "Could not locate employer-site startup call."
);
assert.notEqual(
  closeIndex,
  -1,
  "Could not locate employer-site closure."
);

const hooksToExpose = [
  "applyControl",
  "decodeUrlText",
  "directKnownTarget",
  "followApplyControl",
  "greenhouseBoardTokens",
  "greenhouseJobId",
  "greenhouseTarget",
  "hasAtsFingerprint",
  "jobPageEvidence",
  "looksLikeJobsIndex",
  "pageCandidates",
  "postingClosed",
  "run",
  "signInRequired",
  "supportedTargetOnPage",
  "urlsFromText",
  "usesDedicatedAgent",
  "visibleChallenge",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__employerSiteTestHooks = {${hooksToExpose.join(",")}};`,
  source.slice(closeIndex),
].join("");

class MockElement {
  constructor({
    tagName = "A",
    text = "",
    attributes = {},
    hidden = false,
    visible = true,
    inForm = false,
  } = {}) {
    this.tagName = tagName;
    this.innerText = text;
    this.textContent = text;
    this.value = attributes.value || "";
    this.attributes = new Map(
      Object.entries(attributes)
    );
    this.hidden = hidden;
    this.visible = visible;
    this.inForm = inForm;
    this.style = {};
    this.clickCount = 0;
    this.scrollCount = 0;
  }

  get href() {
    return this.getAttribute("href") || "";
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  closest(selector) {
    return selector === "form" && this.inForm
      ? {tagName: "FORM"}
      : null;
  }

  getBoundingClientRect() {
    return this.visible
      ? {width: 140, height: 38}
      : {width: 0, height: 0};
  }

  scrollIntoView() {
    this.scrollCount += 1;
  }

  click() {
    this.clickCount += 1;
  }
}

const state = {
  bodyText: "",
  challenges: [],
  controls: [],
  fingerprints: [],
  pageElements: [],
  password: null,
  scripts: [],
  status: null,
};

const locationState = {
  href: "https://careers.example.com/jobs/platform-engineer",
  hash: "",
  hostname: "careers.example.com",
  pathname: "/jobs/platform-engineer",
  search: "",
  origin: "https://careers.example.com",
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
  title: "Platform Engineer",
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
  get scripts() {
    return state.scripts;
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
    if (selector === 'input[type="password"]') {
      return state.password;
    }
    if (
      selector.includes("grnhse")
      || selector.includes("greenhouse")
      || selector.includes("job_application")
      || selector.includes("data-qa")
      || selector.includes("lever.co")
      || selector.includes("ashby-application")
      || selector.includes("ashbyhq.com")
    ) {
      return state.fingerprints[0] || null;
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

    if (selector.includes("iframe[src]") || selector.includes("form[action]")) {
      return state.pageElements;
    }

    if (selector.includes("[role=button]")) {
      return state.controls;
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
  filename: "employer_site_agent.js",
}).runInContext(sandbox);
const hooks = sandbox.__employerSiteTestHooks;

function setLocation(value) {
  const parsed = new URL(value);
  locationState.href = parsed.href;
  locationState.hash = parsed.hash;
  locationState.hostname = parsed.hostname;
  locationState.pathname = parsed.pathname;
  locationState.search = parsed.search;
  locationState.origin = parsed.origin;
}

function resetState() {
  state.bodyText = "";
  state.challenges = [];
  state.controls = [];
  state.fingerprints = [];
  state.pageElements = [];
  state.password = null;
  state.scripts = [];
  state.status = null;
  sentMessages.length = 0;
  storageValues.clear();
  messageResponder = () => ({ok: true});
  clockNow = 0;
  sandbox.name = "";
  setLocation(
    "https://careers.example.com/jobs/platform-engineer"
  );
  locationState.replacements.length = 0;
  documentState.title = "Platform Engineer";
}

function launchHash(batch = false) {
  return (
    "#jobfinitum_agent=employer-token"
    + "&jobfinitum_origin="
    + encodeURIComponent("http://127.0.0.1:5000")
    + (batch ? "&jobfinitum_batch=1" : "")
  );
}

function respond(message, task = {}) {
  if (
    message.type
    === "jobfinitum-job-board-restore"
  ) {
    return {ok: true, launch: null};
  }

  if (message.type === "jobfinitum-task") {
    return {
      ok: true,
      task: {
        adapter: "employer_site_resolver",
        target_url: (
          "https://careers.example.com/jobs/platform-engineer"
        ),
        ...task,
      },
    };
  }

  return {ok: true};
}

function script(text) {
  return {textContent: text};
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
      error: error.stack || error.message,
    });
  }
}

await edgeCase(
  "dedicated adapters are never shadowed",
  async () => {
    assert.equal(
      hooks.usesDedicatedAgent(
        "https://jobs.ashbyhq.com/acme/role/application"
      ),
      true
    );
    assert.equal(
      hooks.usesDedicatedAgent(
        "https://www.themuse.com/jobs/acme/role"
      ),
      true
    );
    assert.equal(
      hooks.usesDedicatedAgent(
        "https://careers.acme.example/jobs/role"
      ),
      false
    );
  }
);

await edgeCase(
  "Greenhouse embeds and API URLs normalize to application targets",
  async () => {
    assert.equal(
      hooks.greenhouseTarget(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123456"
      ),
      (
        "https://job-boards.greenhouse.io/embed/job_app"
        + "?for=acme&token=123456"
      )
    );
    assert.equal(
      hooks.greenhouseTarget(
        "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123456"
      ),
      (
        "https://job-boards.greenhouse.io/embed/job_app"
        + "?for=acme&token=123456"
      )
    );
  }
);

await edgeCase(
  "branded Greenhouse page metadata is combined with gh_jid",
  async () => {
    setLocation(
      "https://careers.nebius.com/?gh_jid=4918253101"
    );
    state.scripts = [script(
      String.raw`{"board":"nebius","jobs":"https:\/\/boards-api.greenhouse.io\/v1\/boards\/nebius\/jobs?content=true"}`
    )];

    assert.equal(
      hooks.supportedTargetOnPage(),
      (
        "https://job-boards.greenhouse.io/embed/job_app"
        + "?for=nebius&token=4918253101"
      )
    );
  }
);

await edgeCase(
  "unrelated numeric token parameters are not treated as Greenhouse jobs",
  async () => {
    setLocation(
      "https://careers.example.com/jobs/role?token=123456"
    );
    state.scripts = [script(
      '{"board":"engineering"}'
    )];

    assert.equal(
      hooks.supportedTargetOnPage(),
      null
    );
  }
);

await edgeCase(
  "rendered Lever and Ashby destinations are recognized",
  async () => {
    state.pageElements = [new MockElement({
      attributes: {
        href: "https://jobs.lever.co/acme/role/apply",
      },
    })];
    assert.equal(
      hooks.supportedTargetOnPage(),
      "https://jobs.lever.co/acme/role/apply"
    );

    state.pageElements = [];
    state.scripts = [script(
      String.raw`{"apply":"https:\/\/jobs.ashbyhq.com\/acme\/role\/application"}`
    )];
    assert.equal(
      hooks.supportedTargetOnPage(),
      "https://jobs.ashbyhq.com/acme/role/application"
    );
  }
);

await edgeCase(
  "only individual supported job-board destinations are accepted",
  async () => {
    assert.equal(
      hooks.directKnownTarget(
        "https://www.themuse.com/jobs/acme/platform-engineer"
      ),
      "https://www.themuse.com/jobs/acme/platform-engineer"
    );
    assert.equal(
      hooks.directKnownTarget(
        "https://www.themuse.com/jobs"
      ),
      null
    );
  }
);

await edgeCase(
  "application buttons inside forms are never clicked",
  async () => {
    const unsafe = new MockElement({
      tagName: "BUTTON",
      text: "Apply now",
      inForm: true,
    });
    const safe = new MockElement({
      tagName: "A",
      text: "Apply now",
      attributes: {target: "_blank"},
    });
    state.controls = [unsafe, safe];

    const selected = hooks.applyControl({
      target_url: locationState.href,
    }, true);
    assert.equal(selected, safe);
    assert.equal(hooks.followApplyControl(selected), true);
    assert.equal(safe.getAttribute("target"), "_self");
    assert.equal(safe.clickCount, 1);
    assert.equal(unsafe.clickCount, 0);
  }
);

await edgeCase(
  "ordinary job pages do not trigger application controls",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    const apply = new MockElement({
      tagName: "BUTTON",
      text: "Apply now",
    });
    state.controls = [apply];
    state.bodyText = "Platform Engineer at Example";
    messageResponder = (message) => respond(
      message,
      {
        job: {
          company_name: "Example",
          position_title: "Platform Engineer",
        },
      }
    );

    await hooks.run();

    const result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(
      result.payload.status,
      "needs_manual_destination"
    );
    assert.equal(apply.clickCount, 0);
    assert.ok(
      clockNow <= 4200,
      `ordinary page scan took ${clockNow}ms`
    );
  }
);

await edgeCase(
  "ATS fingerprints allow a job-page application control",
  async () => {
    const apply = new MockElement({
      tagName: "BUTTON",
      text: "Apply now",
    });
    state.controls = [apply];
    state.fingerprints = [new MockElement()];
    state.bodyText = "Platform Engineer at Example";

    assert.equal(hooks.hasAtsFingerprint(), true);
    assert.equal(
      hooks.jobPageEvidence({
        target_url: locationState.href,
        job: {
          company_name: "Example",
          position_title: "Platform Engineer",
        },
      }),
      true
    );
    assert.equal(
      hooks.applyControl({
        target_url: locationState.href,
        job: {
          company_name: "Example",
          position_title: "Platform Engineer",
        },
      }, true),
      apply
    );
  }
);

await edgeCase(
  "full resolver reports a hidden supported ATS",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    state.pageElements = [new MockElement({
      tagName: "IFRAME",
      attributes: {
        src: (
          "https://job-boards.greenhouse.io/embed/job_app"
          + "?for=acme&token=123456"
        ),
      },
    })];
    messageResponder = (message) => respond(message);

    await hooks.run();

    const resolved = sentMessages.find(
      (message) =>
        message.type === "jobfinitum-job-board-resolved"
    );
    assert.equal(
      resolved.url,
      (
        "https://job-boards.greenhouse.io/embed/job_app"
        + "?for=acme&token=123456"
      )
    );
    assert.equal(resolved.batch, true);
  }
);

await edgeCase(
  "unknown pages fall back and recycle the batch tab",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(
      result.payload.status,
      "needs_manual_destination"
    );
    assert.equal(
      locationState.replacements.at(-1),
      "http://127.0.0.1:5000/browser-agent?batch_wait=1"
    );
    assert.ok(
      clockNow <= 4200,
      `unknown page scan took ${clockNow}ms`
    );
  }
);

await edgeCase(
  "generic careers destinations close stale job records",
  async () => {
    setLocation("https://www.jobs.abbott/us/en");
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    state.bodyText = "Search and browse careers at Abbott";
    documentState.title = "Careers at Abbott";
    messageResponder = (message) => respond(
      message,
      {
        target_url: "https://www.jobs.abbott/us/en",
        job: {
          company_name: "Abbott",
          position_title: "Software Engineer, Cloud",
        },
      }
    );

    assert.equal(
      hooks.looksLikeJobsIndex({
        job: {
          company_name: "Abbott",
          position_title: "Software Engineer, Cloud",
        },
      }),
      true
    );

    await hooks.run();

    const result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(result.payload.status, "posting_closed");
    assert.equal(
      result.payload.detail.closure_reason,
      "jobs_index_redirect"
    );
  }
);

await edgeCase(
  "404 employer destinations close stale job records",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    documentState.title = "404 | Page Not Found";
    state.bodyText = "The requested page could not be found.";
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(result.payload.status, "posting_closed");
  }
);

await edgeCase(
  "visible verification pauses without being called a form question",
  async () => {
    locationState.hash = launchHash();
    locationState.href += locationState.hash;
    state.challenges = [new MockElement()];
    messageResponder = (message) => respond(message);

    await hooks.run();

    const result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(result.payload.status, "waiting_verification");
    assert.equal(result.payload.detail.verification_required, true);
  }
);

await edgeCase(
  "sign-in walls pause and closed postings terminate",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    state.bodyText = "Sign in to continue";
    state.password = new MockElement({
      tagName: "INPUT",
    });
    messageResponder = (message) => respond(message);

    await hooks.run();
    let result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(result.payload.status, "waiting_sign_in");

    resetState();
    locationState.hash = launchHash(true);
    locationState.href += locationState.hash;
    state.bodyText = "This job is no longer available";
    messageResponder = (message) => respond(message);

    await hooks.run();
    result = sentMessages.find(
      (message) => message.type === "jobfinitum-result"
    );
    assert.equal(result.payload.status, "posting_closed");
  }
);

const failures = results.filter((result) => !result.passed);
console.log(JSON.stringify({
  passed: results.length - failures.length,
  failed: failures.length,
  results,
}, null, 2));

if (failures.length) {
  process.exitCode = 1;
}
