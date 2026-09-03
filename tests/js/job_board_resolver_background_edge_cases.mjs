import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const backgroundPath = `${root}/browser_extensions/jobfinitum_chrome_agent/background.js`;
const source = await readFile(backgroundPath, "utf8");
const storage = new Map();
const tabUpdates = [];
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
      async remove() {},
      async update(tabId, update) {
        tabUpdates.push({tabId, update});
        return {id: tabId, ...update};
      },
      async get(tabId) { return {id: tabId, url: "about:blank"}; },
    },
  },
};
sandbox.globalThis = sandbox;

const exposed = `
globalThis.__jobBoardResolverHooks = {
  chainedAgentUrl,
  externalHimalayasTarget,
  getHimalayasResolverSession,
  resolverNameForUrl,
  resolveHimalayasTargetOnce,
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
assert.equal(hooks.resolverNameForUrl("https://jobs.ashbyhq.com/example"), "");

for (const blocked of [
  "https://himalayas.app/jobs/example",
  "https://remotefirstjobs.com/a/example",
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

console.log(JSON.stringify({
  passed: 8,
  failed: 0,
  checks: [
    "Himalayas resolver identity",
    "Remote First Jobs resolver identity",
    "unsupported resolver host",
    "aggregator target rejection",
    "external ATS acceptance",
    "child-session resolver preservation",
    "backend resolver attribution",
    "chained ATS launch state",
  ],
}, null, 2));
