import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const backgroundPath = `${root}/browser_extensions/jobfinitum_chrome_agent/background.js`;
const source = await readFile(backgroundPath, "utf8");
const storage = new Map();
const tabUpdates = [];
const tabRemovals = [];
const tabUrls = new Map();
const fetchCalls = [];
let fetchResult = {
  continue_in_chrome_agent: true,
  resolved_url: "https://jobs.ashbyhq.com/example/application",
};
let runtimeMessageListener = null;

const sandbox = {
  URL,
  URLSearchParams,
  Uint8Array,
  console,
  btoa: (value) => Buffer.from(value, "binary").toString("base64"),
  setTimeout: (callback) => {
    callback();
    return 1;
  },
  fetch: async (url, options = {}) => {
    fetchCalls.push({url: String(url), options});
    return {
      ok: true,
      async json() {
        return {...fetchResult};
      },
    };
  },
  chrome: {
    webNavigation: {
      onBeforeNavigate: {addListener() {}},
    },
    runtime: {
      getManifest: () => ({version: "test"}),
      onMessage: {
        addListener(listener) {
          runtimeMessageListener = listener;
        },
      },
    },
    storage: {
      session: {
        async set(values) {
          for (const [key, value] of Object.entries(values)) storage.set(key, value);
        },
        async get(key) {
          if (typeof key === "string") return {[key]: storage.get(key)};
          return {};
        },
        async remove(key) {
          for (const item of Array.isArray(key) ? key : [key]) storage.delete(item);
        },
      },
    },
    tabs: {
      onCreated: {addListener() {}},
      onUpdated: {addListener() {}},
      async query() { return []; },
      async sendMessage() { return {ok: true}; },
      async move() {},
      async remove(tabId) {
        tabRemovals.push(tabId);
        tabUrls.delete(tabId);
      },
      async update(tabId, update) {
        tabUpdates.push({tabId, update});
        if (update.url) {
          tabUrls.set(tabId, String(update.url));
        }
        return {id: tabId, ...update};
      },
      async get(tabId) {
        return {
          id: tabId,
          url: tabUrls.get(tabId) || "about:blank",
        };
      },
    },
  },
};
sandbox.globalThis = sandbox;

const exposed = `
globalThis.__jobBoardResolverHooks = {
  chainedAgentUrl,
  cleanupOwnedAgentTabs,
  cleanupTerminalAgentTab,
  closeOwnedAgentTab,
  externalHimalayasTarget,
  getAgentTabOwnershipForTab,
  getBatchRunner,
  getHimalayasResolverSession,
  registerResolverLaunchFromUrl,
  registerOwnedAgentTab,
  resolverLaunchFromUrl,
  resolverNameForUrl,
  resolveHimalayasTargetOnce,
  saveBatchRunner,
  saveHimalayasResolverSession,
};
`;

vm.createContext(sandbox);
new vm.Script(`${source}\n${exposed}`, {filename: "background.js"}).runInContext(sandbox);
const hooks = sandbox.__jobBoardResolverHooks;

function dispatchBackgroundMessage(
  message,
  sender
) {
  return new Promise((resolve) => {
    const keepsChannelOpen =
      runtimeMessageListener(
        message,
        sender,
        resolve
      );

    if (!keepsChannelOpen) {
      resolve(null);
    }
  });
}

assert.equal(
  hooks.resolverNameForUrl("https://himalayas.app/jobs/example"),
  "himalayas_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl("https://remotefirstjobs.com/companies/example/jobs/one"),
  "remote_first_jobs_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl("https://japan-dev.com/jobs/example/current-job"),
  "japan_dev_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl("https://weworkremotely.com/remote-jobs/example"),
  "we_work_remotely_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl("https://jooble.org/away/123"),
  "jooble_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl("https://remoteok.com/remote-jobs/example"),
  "remote_ok_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl("https://jobicy.com/jobs/152678-example"),
  "jobicy_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl(
    "https://www.tokyodev.com/c/acme/j/role/applications/new"
  ),
  "tokyo_dev_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl(
    "https://www.adzuna.co.uk/jobs/land/ad/123"
  ),
  "adzuna_browser_agent"
);
assert.equal(
  hooks.resolverNameForUrl(
    "https://www.themuse.com/jobs/acme/platform-engineer"
  ),
  "the_muse_browser_agent"
);
assert.equal(hooks.resolverNameForUrl("https://jobs.ashbyhq.com/example"), "");
assert.equal(
  hooks.resolverNameForUrl(
    "https://careers.example.com/jobs/platform-engineer"
  ),
  "employer_site_browser_agent"
);

for (const blocked of [
  "https://himalayas.app/jobs/example",
  "https://remotefirstjobs.com/a/example",
  "https://japan-dev.com/jobs/example/current-job",
  "https://weworkremotely.com/remote-jobs/example",
  "https://jooble.org/away/123",
  "https://remoteok.com/l/123",
  "https://jobicy.com/jobs/152678-example",
  "https://www.tokyodev.com/c/acme/j/role/applications/new",
  "https://www.adzuna.com.au/land/ad/123",
  "https://www.themuse.com/jobs/acme/platform-engineer",
  "http://127.0.0.1:5000/auto-apply",
]) {
  assert.throws(
    () => hooks.externalHimalayasTarget(blocked, "http://127.0.0.1:5000"),
    /not an external employer target/
  );
}
assert.equal(
  hooks.externalHimalayasTarget(
    "https://jobs.ashbyhq.com/example/application",
    "http://127.0.0.1:5000"
  ),
  "https://jobs.ashbyhq.com/example/application"
);
assert.equal(
  hooks.externalHimalayasTarget(
    "https://www.themuse.com/jobs/acme/platform-engineer",
    "http://127.0.0.1:5000",
    "employer_site_browser_agent"
  ),
  "https://www.themuse.com/jobs/acme/platform-engineer"
);

const session = {
  token: "candidate-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: 41,
  resolver: "remote_first_jobs_browser_agent",
};
await hooks.saveHimalayasResolverSession(42, session);
assert.equal(
  (await hooks.getHimalayasResolverSession(42)).resolver,
  "remote_first_jobs_browser_agent"
);

await hooks.resolveHimalayasTargetOnce(
  42,
  "https://jobs.ashbyhq.com/example/application",
  session
);

const postedPayload = JSON.parse(fetchCalls[0].options.body);
assert.equal(postedPayload.status, "resolved_application_target");
assert.equal(postedPayload.detail.resolver, "remote_first_jobs_browser_agent");
assert.equal(tabUpdates.length, 1);
assert.equal(tabUpdates[0].tabId, 42);

const chained = new URL(tabUpdates[0].update.url);
const chainedParams = new URLSearchParams(chained.hash.replace(/^#/, ""));
assert.equal(chained.origin, "https://jobs.ashbyhq.com");
assert.equal(chainedParams.get("jobfinitum_agent"), "candidate-token");
assert.equal(chainedParams.get("jobfinitum_origin"), "http://127.0.0.1:5000");
assert.equal(chainedParams.get("jobfinitum_batch"), "1");

fetchResult = {
  status: "Waiting for Verification",
  attempt_id: 91,
  diagnostics: {run_id: "verification-run", batch: true},
};
const verificationSession = {
  token: "verification-candidate-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: 43,
  resolver: "remote_first_jobs_browser_agent",
};
tabUrls.set(43, "https://remotefirstjobs.com/jobs/example");
await hooks.resolveHimalayasTargetOnce(
  43,
  "https://jobs.ashbyhq.com/example/application",
  verificationSession
);
assert.equal(
  tabUrls.get(43),
  "http://127.0.0.1:5000/browser-agent?batch_wait=1"
);
fetchResult = {
  continue_in_chrome_agent: true,
  resolved_url: "https://jobs.ashbyhq.com/example/application",
};

const joobleLaunchUrl = (
  "https://jooble.org/away/123"
  + "#jobfinitum_agent=jooble-token"
  + "&jobfinitum_origin=http%3A%2F%2F127.0.0.1%3A5000"
  + "&jobfinitum_batch=1"
);

const employerLaunchUrl = (
  "https://careers.example.com/jobs/platform-engineer"
  + "#jobfinitum_agent=employer-token"
  + "&jobfinitum_origin=http%3A%2F%2F127.0.0.1%3A5000"
  + "&jobfinitum_batch=1"
);
const employerLaunch = hooks.resolverLaunchFromUrl(
  employerLaunchUrl
);
assert.equal(employerLaunch.token, "employer-token");
assert.equal(
  employerLaunch.resolver,
  "employer_site_browser_agent"
);
assert.equal(employerLaunch.batch, true);
const joobleLaunch = hooks.resolverLaunchFromUrl(joobleLaunchUrl);
assert.equal(joobleLaunch.token, "jooble-token");
assert.equal(joobleLaunch.origin, "http://127.0.0.1:5000");
assert.equal(joobleLaunch.batch, true);
assert.equal(joobleLaunch.resolver, "jooble_browser_agent");

const registeredJooble = await hooks.registerResolverLaunchFromUrl(
  88,
  joobleLaunchUrl
);
assert.equal(registeredJooble.resolverTabId, 88);
assert.equal(
  (await hooks.getHimalayasResolverSession(88)).resolver,
  "jooble_browser_agent"
);

const tokyoDevLaunchUrl = (
  "https://www.tokyodev.com/c/acme/j/role/applications/new"
  + "#jobfinitum_agent=tokyodev-token"
  + "&jobfinitum_origin=http%3A%2F%2F127.0.0.1%3A5000"
  + "&jobfinitum_batch=1"
);
const tokyoDevLaunch = hooks.resolverLaunchFromUrl(tokyoDevLaunchUrl);
assert.equal(tokyoDevLaunch.token, "tokyodev-token");
assert.equal(tokyoDevLaunch.origin, "http://127.0.0.1:5000");
assert.equal(tokyoDevLaunch.batch, true);
assert.equal(tokyoDevLaunch.resolver, "tokyo_dev_browser_agent");

const registeredTokyoDev = await hooks.registerResolverLaunchFromUrl(
  89,
  tokyoDevLaunchUrl
);
assert.equal(registeredTokyoDev.resolverTabId, 89);
assert.equal(
  (await hooks.getHimalayasResolverSession(89)).resolver,
  "tokyo_dev_browser_agent"
);

const adzunaLaunchUrl = (
  "https://www.adzuna.com/land/ad/5849361556"
  + "#jobfinitum_agent=adzuna-token"
  + "&jobfinitum_origin=http%3A%2F%2F127.0.0.1%3A5000"
  + "&jobfinitum_batch=1"
);
const adzunaLaunch = hooks.resolverLaunchFromUrl(
  adzunaLaunchUrl
);
assert.equal(adzunaLaunch.token, "adzuna-token");
assert.equal(
  adzunaLaunch.origin,
  "http://127.0.0.1:5000"
);
assert.equal(adzunaLaunch.batch, true);
assert.equal(
  adzunaLaunch.resolver,
  "adzuna_browser_agent"
);

const registeredAdzuna =
  await hooks.registerResolverLaunchFromUrl(
    90,
    adzunaLaunchUrl
  );
assert.equal(registeredAdzuna.resolverTabId, 90);
assert.equal(
  (await hooks.getHimalayasResolverSession(90)).resolver,
  "adzuna_browser_agent"
);

const theMuseLaunchUrl = (
  "https://www.themuse.com/jobs/acme/platform-engineer"
  + "#jobfinitum_agent=the-muse-token"
  + "&jobfinitum_origin=http%3A%2F%2F127.0.0.1%3A5000"
  + "&jobfinitum_batch=1"
);
const theMuseLaunch = hooks.resolverLaunchFromUrl(
  theMuseLaunchUrl
);
assert.equal(theMuseLaunch.token, "the-muse-token");
assert.equal(
  theMuseLaunch.origin,
  "http://127.0.0.1:5000"
);
assert.equal(theMuseLaunch.batch, true);
assert.equal(
  theMuseLaunch.resolver,
  "the_muse_browser_agent"
);

const registeredTheMuse =
  await hooks.registerResolverLaunchFromUrl(
    91,
    theMuseLaunchUrl
  );
assert.equal(registeredTheMuse.resolverTabId, 91);
assert.equal(
  (await hooks.getHimalayasResolverSession(91)).resolver,
  "the_muse_browser_agent"
);

await hooks.resolveHimalayasTargetOnce(
  88,
  "https://jobs.lever.co/example/role/apply",
  registeredJooble
);
const jooblePayload = JSON.parse(fetchCalls.at(-1).options.body);
assert.equal(jooblePayload.detail.resolver, "jooble_browser_agent");
const joobleChained = new URL(tabUpdates.at(-1).update.url);
const joobleParams = new URLSearchParams(
  joobleChained.hash.replace(/^#/, "")
);
assert.equal(joobleChained.origin, "https://jobs.ashbyhq.com");
assert.equal(joobleParams.get("jobfinitum_agent"), "jooble-token");
assert.equal(joobleParams.get("jobfinitum_batch"), "1");

tabUrls.set(
  77,
  "https://job-boards.greenhouse.io/example/jobs/123"
);
await hooks.saveBatchRunner(
  77,
  "http://127.0.0.1:5000"
);
assert.equal(
  await hooks.cleanupTerminalAgentTab(
    77,
    "http://127.0.0.1:5000"
  ),
  true
);
const recycled = tabUpdates.at(-1);
assert.equal(recycled.tabId, 77);
assert.equal(
  recycled.update.url,
  "http://127.0.0.1:5000/browser-agent?batch_wait=1"
);

tabUrls.set(
  78,
  "https://jobs.lever.co/example/role/apply"
);
assert.equal(
  await hooks.cleanupTerminalAgentTab(
    78,
    "http://127.0.0.1:5000"
  ),
  true
);
assert.equal(tabRemovals.at(-1), 78);

tabUrls.set(
  79,
  "http://127.0.0.1:5000/browser-agent?batch_wait=1"
);
assert.equal(
  await hooks.cleanupTerminalAgentTab(
    79,
    "http://127.0.0.1:5000"
  ),
  false
);
assert.equal(tabRemovals.includes(79), false);

const ownedSession = {
  token: "owned-candidate-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: 100,
  resolver: "remote_first_jobs_browser_agent",
};
tabUrls.set(
  100,
  "https://remotefirstjobs.com/jobs/example"
);
tabUrls.set(
  101,
  "https://job-boards.greenhouse.io/example/jobs/456"
);
tabUrls.set(
  102,
  "https://job-boards.greenhouse.io/example/jobs/456"
);
await hooks.registerOwnedAgentTab(
  100,
  ownedSession,
  {
    role: "resolver",
    reason: "test_resolver",
  }
);
await hooks.registerOwnedAgentTab(
  101,
  ownedSession,
  {
    role: "resolver_child",
    reason: "test_child",
  }
);
await hooks.registerOwnedAgentTab(
  102,
  ownedSession,
  {
    role: "resolver_child",
    reason: "test_duplicate_child",
  }
);
const primaryClaim =
  await hooks.registerOwnedAgentTab(
    101,
    ownedSession,
    {
      role: "application",
      reason: "test_primary_application",
      claimApplication: true,
    }
  );
const duplicateClaim =
  await hooks.registerOwnedAgentTab(
    102,
    ownedSession,
    {
      role: "application",
      reason: "test_duplicate_application",
      claimApplication: true,
    }
  );
assert.equal(primaryClaim.accepted, true);
assert.equal(duplicateClaim.accepted, false);
assert.equal(
  (await hooks.getAgentTabOwnershipForTab(100))
    .applicationTabId,
  101
);
await hooks.closeOwnedAgentTab(
  102,
  "duplicate_application_tab"
);
assert.equal(tabRemovals.at(-1), 102);
await hooks.cleanupOwnedAgentTabs(
  101,
  ownedSession.origin,
  {
    mode: "terminal",
    reason: "submitted",
  }
);
assert.equal(tabRemovals.includes(100), true);
assert.equal(
  tabUpdates.at(-1).tabId,
  101
);
assert.equal(
  tabUpdates.at(-1).update.url,
  "http://127.0.0.1:5000/browser-agent?batch_wait=1"
);
assert.equal(
  await hooks.getAgentTabOwnershipForTab(101),
  null
);

const handoffSession = {
  token: "handoff-candidate-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: 110,
  resolver: "employer_site_browser_agent",
};
tabUrls.set(
  110,
  "https://careers.example.com/jobs/security"
);
tabUrls.set(
  111,
  "https://jobs.lever.co/example/security/apply"
);
await hooks.registerOwnedAgentTab(
  110,
  handoffSession,
  {
    role: "resolver",
    reason: "test_handoff_resolver",
  }
);
await hooks.registerOwnedAgentTab(
  111,
  handoffSession,
  {
    role: "application",
    reason: "test_handoff_application",
    claimApplication: true,
  }
);
await hooks.cleanupOwnedAgentTabs(
  111,
  handoffSession.origin,
  {
    mode: "handoff",
    reason: "waiting_sign_in",
  }
);
assert.equal(tabRemovals.includes(110), true);
assert.equal(tabRemovals.includes(111), false);
assert.equal(tabUrls.get(111), "https://jobs.lever.co/example/security/apply");
assert.equal(await hooks.getBatchRunner(), null);

tabUrls.set(
  120,
  "https://jobs.ashbyhq.com/example/application"
);
tabUrls.set(
  121,
  "https://jobs.ashbyhq.com/example/application"
);
const firstHostedRegistration =
  await dispatchBackgroundMessage(
    {
      type: "jobfinitum-batch-register",
      origin: "http://127.0.0.1:5000",
      token: "hosted-duplicate-token",
    },
    {
      tab: {
        id: 120,
        url: tabUrls.get(120),
      },
    }
  );
const duplicateHostedRegistration =
  await dispatchBackgroundMessage(
    {
      type: "jobfinitum-batch-register",
      origin: "http://127.0.0.1:5000",
      token: "hosted-duplicate-token",
    },
    {
      tab: {
        id: 121,
        url: tabUrls.get(121),
      },
    }
  );
await new Promise(
  (resolve) => setTimeout(resolve, 5)
);
assert.equal(firstHostedRegistration.ok, true);
assert.equal(
  duplicateHostedRegistration.duplicate,
  true
);
assert.equal(tabRemovals.includes(121), true);
await dispatchBackgroundMessage(
  {
    type: "jobfinitum-batch-control",
    origin: "http://127.0.0.1:5000",
    action: "stop",
  },
  {
    tab: {
      id: 79,
      url: tabUrls.get(79),
    },
  }
);
assert.equal(tabRemovals.includes(120), true);

const watchdogSession = {
  token: "watchdog-candidate-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: null,
  resolver: "",
};
tabUrls.set(
  130,
  "https://jobs.lever.co/example/watchdog/apply"
);
await hooks.registerOwnedAgentTab(
  130,
  watchdogSession,
  {
    role: "application",
    reason: "test_watchdog_application",
    claimApplication: true,
  }
);
const watchdogAdvance =
  await dispatchBackgroundMessage(
    {
      type: "jobfinitum-batch-control",
      origin: "http://127.0.0.1:5000",
      action: "advance",
    },
    {
      tab: {
        id: 79,
        url: tabUrls.get(79),
      },
    }
  );
assert.equal(watchdogAdvance.ok, true);
assert.equal(
  tabUrls.get(130),
  "http://127.0.0.1:5000/browser-agent?batch_wait=1"
);
assert.equal(
  await hooks.getAgentTabOwnershipForTab(130),
  null
);

const lateSession = {
  token: "late-result-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: null,
  resolver: "",
};
const currentSession = {
  token: "current-result-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: null,
  resolver: "",
};
tabUrls.set(
  140,
  "https://jobs.ashbyhq.com/example/late"
);
tabUrls.set(
  141,
  "https://jobs.ashbyhq.com/example/current"
);
await hooks.registerOwnedAgentTab(
  140,
  lateSession,
  {
    role: "application",
    reason: "test_late_application",
    claimApplication: true,
  }
);
await hooks.registerOwnedAgentTab(
  141,
  currentSession,
  {
    role: "application",
    reason: "test_current_application",
    claimApplication: true,
  }
);
await hooks.cleanupOwnedAgentTabs(
  140,
  lateSession.origin,
  {
    mode: "terminal",
    reason: "late_submitted_result",
  }
);
assert.equal(tabRemovals.includes(140), true);
assert.equal((await hooks.getBatchRunner()).tabId, 141);
await dispatchBackgroundMessage(
  {
    type: "jobfinitum-batch-control",
    origin: "http://127.0.0.1:5000",
    action: "stop",
  },
  {
    tab: {
      id: 79,
      url: tabUrls.get(79),
    },
  }
);

const concurrentSession = {
  token: "concurrent-claim-token",
  origin: "http://127.0.0.1:5000",
  batch: true,
  resolverTabId: 150,
  resolver: "remote_ok_browser_agent",
};
tabUrls.set(
  150,
  "https://jobs.lever.co/example/first/apply"
);
tabUrls.set(
  151,
  "https://jobs.lever.co/example/second/apply"
);
await hooks.registerOwnedAgentTab(
  150,
  concurrentSession,
  {
    role: "resolver_child",
    reason: "test_concurrent_first",
  }
);
await hooks.registerOwnedAgentTab(
  151,
  concurrentSession,
  {
    role: "resolver_child",
    reason: "test_concurrent_second",
  }
);
const concurrentClaims = await Promise.all([
  hooks.registerOwnedAgentTab(
    150,
    concurrentSession,
    {
      role: "application",
      reason: "test_concurrent_claim",
      claimApplication: true,
    }
  ),
  hooks.registerOwnedAgentTab(
    151,
    concurrentSession,
    {
      role: "application",
      reason: "test_concurrent_claim",
      claimApplication: true,
    }
  ),
]);
assert.equal(
  concurrentClaims.filter(
    (claim) => claim.accepted
  ).length,
  1
);
await dispatchBackgroundMessage(
  {
    type: "jobfinitum-batch-control",
    origin: "http://127.0.0.1:5000",
    action: "stop",
  },
  {
    tab: {
      id: 79,
      url: tabUrls.get(79),
    },
  }
);

console.log(JSON.stringify({
  passed: 45,
  failed: 0,
  checks: [
    "Himalayas resolver identity",
    "Remote First Jobs resolver identity",
    "Japan Dev resolver identity",
    "We Work Remotely resolver identity",
    "Jooble resolver identity",
    "Remote OK resolver identity",
    "Jobicy resolver identity",
    "TokyoDev resolver identity",
    "Adzuna resolver identity",
    "The Muse resolver identity",
    "unsupported resolver host",
    "generic employer-site resolver identity",
    "aggregator target rejection",
    "Adzuna country-domain target rejection",
    "The Muse target rejection",
    "external ATS acceptance",
    "employer-site to named-resolver chaining",
    "child-session resolver preservation",
    "backend resolver attribution",
    "chained ATS launch state",
    "resolver verification recycles the batch tab",
    "Jooble launch parsing",
    "employer-site launch parsing",
    "Jooble pre-navigation registration",
    "TokyoDev pre-navigation registration",
    "Adzuna pre-navigation registration",
    "The Muse pre-navigation registration",
    "Jooble backend resolver attribution",
    "Jooble chained ATS launch state",
    "terminal batch-tab recycling",
    "stray application-tab removal",
    "Jobfinitum waiting-tab preservation",
    "single application-tab ownership",
    "duplicate application rejection",
    "duplicate application cleanup",
    "owned resolver cleanup",
    "owned batch-tab recycling",
    "human-handoff resolver cleanup",
    "human-handoff application retention",
    "hosted duplicate message rejection",
    "hosted duplicate message cleanup",
    "batch stop ownership cleanup",
    "watchdog advance tab recycling",
    "late result cannot replace current runner",
    "concurrent child tabs produce one owner",
  ],
}, null, 2));
