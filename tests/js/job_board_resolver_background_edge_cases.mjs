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
        return {
          continue_in_chrome_agent: true,
          resolved_url: "https://jobs.ashbyhq.com/example/application",
        };
      },
    };
  },
  chrome: {
    webNavigation: {
      onBeforeNavigate: {addListener() {}},
    },
    runtime: {
      getManifest: () => ({version: "test"}),
      onMessage: {addListener() {}},
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
  cleanupTerminalAgentTab,
  externalHimalayasTarget,
  getHimalayasResolverSession,
  registerResolverLaunchFromUrl,
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

const joobleLaunchUrl = (
  "https://jooble.org/away/123"
  + "#jobfinitum_agent=jooble-token"
  + "&jobfinitum_origin=http%3A%2F%2F127.0.0.1%3A5000"
  + "&jobfinitum_batch=1"
);
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

console.log(JSON.stringify({
  passed: 28,
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
    "aggregator target rejection",
    "Adzuna country-domain target rejection",
    "The Muse target rejection",
    "external ATS acceptance",
    "child-session resolver preservation",
    "backend resolver attribution",
    "chained ATS launch state",
    "Jooble launch parsing",
    "Jooble pre-navigation registration",
    "TokyoDev pre-navigation registration",
    "Adzuna pre-navigation registration",
    "The Muse pre-navigation registration",
    "Jooble backend resolver attribution",
    "Jooble chained ATS launch state",
    "terminal batch-tab recycling",
    "stray application-tab removal",
    "Jobfinitum waiting-tab preservation",
  ],
}, null, 2));
