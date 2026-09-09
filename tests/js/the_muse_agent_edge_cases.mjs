import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(
  new URL("../..", import.meta.url)
);
const agentPath =
  `${root}/browser_extensions/jobfinitum_chrome_agent/the_muse_agent.js`;
const source = await readFile(agentPath, "utf8");
const startupIndex = source.lastIndexOf("\n  run();");
const closeIndex = source.lastIndexOf("\n})();");

assert.notEqual(
  startupIndex,
  -1,
  "Could not locate The Muse startup call."
);
assert.notEqual(
  closeIndex,
  -1,
  "Could not locate The Muse closure."
);

const hooksToExpose = [
  "applyLinksFromText",
  "blockedPage",
  "currentJobSlug",
  "declaredApplyTarget",
  "decodeEmbeddedUrl",
  "embeddedApplyTarget",
  "externalApplyLink",
  "isExternalUrl",
  "isJobDetailPath",
  "isJobsIndex",
  "postingClosed",
  "run",
  "visibleChallenge",
];
const instrumentedSource = [
  source.slice(0, startupIndex),
  `\n  self.__theMuseTestHooks = {${hooksToExpose.join(",")}};`,
  source.slice(closeIndex),
].join("");

class MockElement {
  constructor({
    tagName = "A",
    text = "",
    href = "",
    attributes = {},
    hidden = false,
    visible = true,
  } = {}) {
    this.tagName = tagName;
    this.innerText = text;
    this.textContent = text;
    this.href = href;
    this.attributes = new Map(
      Object.entries(attributes)
    );
    this.hidden = hidden;
    this.visible = visible;
    this.style = {};
  }

  getAttribute(name) {
    if (name === "href" && this.href) {
      return this.href;
    }
    return this.attributes.get(name) ?? null;
  }

  getBoundingClientRect() {
    return this.visible
      ? {width: 120, height: 36}
      : {width: 0, height: 0};
  }
}

const state = {
  bodyText: "",
  challenges: [],
  declared: [],
  links: [],
  scripts: [],
  status: null,
};
const locationState = {
  href:
    "https://www.themuse.com/jobs/acme/platform-engineer",
  hash: "",
  hostname: "www.themuse.com",
  pathname: "/jobs/acme/platform-engineer",
  search: "",
  origin: "https://www.themuse.com",
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
  title: "Platform Engineer at Acme | The Muse",
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
  querySelectorAll(selector) {
    if (
      selector.includes("recaptcha")
      || selector.includes("hcaptcha")
      || selector.includes("cf-turnstile")
      || selector.includes("__cf_chl")
    ) {
      return state.challenges;
    }

    if (selector.includes("data-apply-link")) {
      return state.declared;
    }

    if (selector === "a[href]") {
      return state.links;
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
  decodeURIComponent,
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
  filename: "the_muse_agent.js",
}).runInContext(sandbox);
const hooks = sandbox.__theMuseTestHooks;

function resetState() {
  state.bodyText = "";
  state.challenges = [];
  state.declared = [];
  state.links = [];
  state.scripts = [];
  state.status = null;
  sentMessages.length = 0;
  storageValues.clear();
  messageResponder = () => ({ok: true});
  clockNow = 0;
  sandbox.name = "";
  locationState.href =
    "https://www.themuse.com/jobs/acme/platform-engineer";
  locationState.hash = "";
  locationState.hostname = "www.themuse.com";
  locationState.pathname =
    "/jobs/acme/platform-engineer";
  locationState.search = "";
  locationState.origin =
    "https://www.themuse.com";
  locationState.replacements.length = 0;
  documentState.title =
    "Platform Engineer at Acme | The Muse";
}

function launchHash(batch = false) {
  return (
    "#jobfinitum_agent=muse-token"
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
        adapter: "the_muse_resolver",
        target_url: locationState.href,
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
      error: error.message,
    });
  }
}

await edgeCase(
  "only external HTTP employer targets are accepted",
  async () => {
    assert.equal(
      hooks.isExternalUrl(
        "https://www.themuse.com/jobs/acme/role"
      ),
      false
    );
    assert.equal(
      hooks.isExternalUrl(
        "http://127.0.0.1:5000/auto-apply"
      ),
      false
    );
    assert.equal(
      hooks.isExternalUrl("javascript:void(0)"),
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
  "job detail and index routes are distinguished",
  async () => {
    assert.equal(hooks.isJobDetailPath(), true);
    assert.equal(
      hooks.currentJobSlug(),
      "platform-engineer"
    );
    assert.equal(hooks.isJobsIndex(), false);

    locationState.pathname = "/jobs";
    locationState.href =
      "https://www.themuse.com/jobs";
    assert.equal(hooks.isJobDetailPath(), false);
    assert.equal(hooks.isJobsIndex(), true);
  }
);

await edgeCase(
  "escaped query separators are decoded",
  async () => {
    assert.equal(
      hooks.decodeEmbeddedUrl(
        String.raw`https://jobs.lever.co/acme/role/apply?source=one\\u0026medium=two\\`
      ),
      (
        "https://jobs.lever.co/acme/role/apply"
        + "?source=one&medium=two"
      )
    );
  }
);

await edgeCase(
  "direct applyLink data is extracted",
  async () => {
    const candidates = hooks.applyLinksFromText(
      (
        '{"shortName":"platform-engineer",'
        + '"state":"live",'
        + '"applyLink":"https://jobs.lever.co/acme/role/apply"}'
      )
    );
    assert.equal(candidates.length, 1);
    assert.equal(
      candidates[0].url,
      "https://jobs.lever.co/acme/role/apply"
    );
  }
);

await edgeCase(
  "escaped Next data is extracted",
  async () => {
    const candidates = hooks.applyLinksFromText(
      String.raw`{\\"shortName\\":\\"platform-engineer\\",\\"state\\":\\"live\\",\\"applyLink\\":\\"https://job-boards.greenhouse.io/acme/jobs/123?one=1\\u0026two=2\\"}`
    );
    assert.equal(candidates.length, 1);
    assert.equal(
      candidates[0].url,
      (
        "https://job-boards.greenhouse.io/acme/jobs/123"
        + "?one=1&two=2"
      )
    );
  }
);

await edgeCase(
  "stored Muse destination shapes are extracted",
  async () => {
    const fixtures = [
      [
        (
          '"applyLink":"https://jobs.lever.co/coupa/'
          + '3b53f9ca-a645-49fa-aaac-5b1e5e3bb957/apply'
          + '?lever-source=themuse"'
        ),
        (
          "https://jobs.lever.co/coupa/"
          + "3b53f9ca-a645-49fa-aaac-5b1e5e3bb957/apply"
          + "?lever-source=themuse"
        ),
      ],
      [
        (
          '"applyLink":"https://crowdstrike.wd5.'
          + 'myworkdayjobs.com/crowdstrikecareers/job/'
          + 'technical-support-engineer"'
        ),
        (
          "https://crowdstrike.wd5.myworkdayjobs.com/"
          + "crowdstrikecareers/job/technical-support-engineer"
        ),
      ],
      [
        String.raw`\"applyLink\":\"https://cummins.jobs/job/?vs=7141\u0026utm_source=The+Muse-DE\"`,
        (
          "https://cummins.jobs/job/?vs=7141"
          + "&utm_source=The+Muse-DE"
        ),
      ],
      [
        (
          '"applyLink":"https://job-boards.greenhouse.io/'
          + 'gitlab/jobs/8644569002?gh_src=8c3e40d12us"'
        ),
        (
          "https://job-boards.greenhouse.io/gitlab/jobs/"
          + "8644569002?gh_src=8c3e40d12us"
        ),
      ],
    ];

    for (const [payload, expected] of fixtures) {
      const candidates = hooks.applyLinksFromText(payload);
      assert.equal(candidates.length, 1);
      assert.equal(candidates[0].url, expected);
    }
  }
);

await edgeCase(
  "the current job beats an unrelated payload",
  async () => {
    state.scripts = [script(
      (
        '{"shortName":"different-role",'
        + '"applyLink":"https://example.com/wrong"},'
        + '{"shortName":"platform-engineer",'
        + '"state":"live",'
        + '"applyLink":"https://jobs.ashbyhq.com/acme/application"}'
      )
    )];
    assert.equal(
      hooks.embeddedApplyTarget(),
      "https://jobs.ashbyhq.com/acme/application"
    );
  }
);

await edgeCase(
  "job indexes never consume another listing payload",
  async () => {
    locationState.pathname = "/jobs";
    locationState.href =
      "https://www.themuse.com/jobs";
    state.scripts = [script(
      '{"applyLink":"https://jobs.lever.co/wrong/apply"}'
    )];
    assert.equal(hooks.embeddedApplyTarget(), null);
  }
);

await edgeCase(
  "declared application data is supported",
  async () => {
    state.declared = [
      new MockElement({
        attributes: {
          "data-apply-link":
            "https://jobs.lever.co/acme/role/apply",
        },
      }),
    ];
    assert.equal(
      hooks.declaredApplyTarget(),
      "https://jobs.lever.co/acme/role/apply"
    );
  }
);

await edgeCase(
  "only exact external Apply anchors are used",
  async () => {
    state.links = [
      new MockElement({
        text: "Company website",
        href: "https://example.com",
      }),
      new MockElement({
        text: "Apply on company site",
        href:
          "https://job-boards.greenhouse.io/acme/jobs/123",
      }),
    ];
    assert.equal(
      hooks.externalApplyLink(),
      "https://job-boards.greenhouse.io/acme/jobs/123"
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
  "the full resolver reports the embedded ATS",
  async () => {
    locationState.hash = launchHash(true);
    state.scripts = [script(
      (
        '{"shortName":"platform-engineer",'
        + '"state":"live",'
        + '"applyLink":"https://jobs.lever.co/acme/role/apply"}'
      )
    )];
    messageResponder = (message) => respond(message);

    await hooks.run();

    const resolved = sentMessages.find(
      (message) =>
        message.type
        === "jobfinitum-job-board-resolved"
    );
    assert.equal(
      resolved.url,
      "https://jobs.lever.co/acme/role/apply"
    );
    assert.equal(resolved.batch, true);
  }
);

await edgeCase(
  "a visible challenge pauses without recycling",
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
      locationState.replacements.length,
      0
    );
  }
);

await edgeCase(
  "a blocked page falls back and advances the batch",
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
  "an expired listing closes and advances",
  async () => {
    locationState.hash = launchHash(true);
    locationState.href =
      "https://www.themuse.com/jobs";
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
    state.scripts = [script(
      (
        '{"shortName":"platform-engineer",'
        + '"applyLink":"https://jobs.ashbyhq.com/acme/application"}'
      )
    )];
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
    `${failures.length} The Muse edge-case test(s) failed.`
  );
}
