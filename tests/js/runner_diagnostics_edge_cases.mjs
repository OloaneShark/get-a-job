import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../../browser_extensions/jobfinitum_chrome_agent/background.js", import.meta.url), "utf8");
const store = new Map();
const tabs = new Map();
const notifications = [];
const receipts = [];
let rejectRemove = false;
let rejectReceipt = false;
let listener;
const context = {
  URL, URLSearchParams, Uint8Array, AbortSignal,
  console: {info() {}, warn() {}},
  setTimeout: () => 1,
  fetch: async (url, options) => {
    if (rejectReceipt) throw new Error("Server unavailable");
    receipts.push(JSON.parse(options.body));
    return {ok: true, json: async () => ({})};
  },
  chrome: {
    runtime: {getManifest: () => ({version: "test"}), onMessage: {addListener(fn) { listener = fn; }}},
    storage: {session: {
      async get(key) { return {[key]: store.get(key)}; },
      async set(values) { for (const [key, value] of Object.entries(values)) store.set(key, structuredClone(value)); },
      async remove(keys) { for (const key of [].concat(keys)) store.delete(key); },
    }},
    tabs: {
      onCreated: {addListener() {}}, onUpdated: {addListener() {}},
      async query() { return [{id: 1}]; },
      async sendMessage(id, message) { notifications.push(structuredClone(message.result)); },
      async get(id) { if (!tabs.has(id)) throw new Error("No tab"); return {id, url: tabs.get(id)}; },
      async remove(id) { if (rejectRemove) throw new Error("Remove blocked"); tabs.delete(id); },
      async update(id, value) { tabs.set(id, value.url); return {id, ...value}; },
    },
  },
};
vm.createContext(context);
new vm.Script(source + "\nglobalThis.hooks = {registerOwnedAgentTab, getAgentTabOwnershipForTab, finishRunnerReport, runnerDetail, runnerPhase, observeRunnerTab};").runInContext(context);
const hooks = context.hooks;
const origin = "http://127.0.0.1:5000";
const token = "launch-one";
const freshResult = (batch = true) => ({
  candidate_id: 5, attempt_id: 6, status: "Needs Application Answer",
  diagnostics: {run_id: "run-one", batch},
});
async function claim(id = 20, batch = true, launchToken = token) {
  tabs.set(id, "https://jobs.lever.co/company/role/apply");
  await hooks.registerOwnedAgentTab(id, {token: launchToken, origin, batch}, {role: "application", claimApplication: true});
}
const checks = [];
async function test(name, fn) {
  store.clear(); tabs.clear(); notifications.length = 0; receipts.length = 0;
  rejectRemove = false; rejectReceipt = false;
  await fn();
  checks.push(name);
}

await test("saved-answer retry keeps its tab and increments retry count", async () => {
  await claim();
  const result = {...freshResult(), status: "Retrying With Saved Answers", retry_with_saved_answers: true};
  await hooks.finishRunnerReport(20, origin, token, result, "needs_application_answer");
  assert.match(tabs.get(20), /lever/);
  assert.equal((await hooks.runnerDetail(20)).diagnostics.retry_count, 1);
  assert.equal(receipts[0].tab_outcome, "continuing");
  assert.equal(receipts[0].batch_outcome, "retrying");
});
await test("terminal reports recycle the batch tab and record the observation", async () => {
  await claim();
  await hooks.finishRunnerReport(20, origin, token, freshResult(), "needs_application_answer");
  assert.match(tabs.get(20), /batch_wait=1/);
  assert.equal(receipts[0].tab_outcome, "recycled");
  assert.equal(notifications[0].diagnostics.tab_outcome, "recycled");
});
await test("nonbatch terminal reports confirm the tab closed", async () => {
  await claim(20, false);
  await hooks.finishRunnerReport(20, origin, token, freshResult(), "submitted");
  assert.equal(tabs.has(20), false);
  assert.equal(receipts[0].tab_outcome, "closed");
});
await test("batch CAPTCHA recycles the application tab and continues", async () => {
  await claim();
  await hooks.finishRunnerReport(20, origin, token, freshResult(), "waiting_verification");
  assert.match(tabs.get(20), /batch_wait=1/);
  assert.equal(receipts[0].tab_outcome, "recycled");
});
await test("nonbatch CAPTCHA retains the application for the user", async () => {
  await claim(20, false);
  await hooks.finishRunnerReport(20, origin, token, freshResult(false), "waiting_verification");
  assert.match(tabs.get(20), /lever/);
  assert.equal(receipts[0].tab_outcome, "retained");
});
await test("failed close is reported as still open", async () => {
  await claim(20, false);
  rejectRemove = true;
  await hooks.finishRunnerReport(20, origin, token, freshResult(), "failed");
  assert.equal(receipts[0].tab_outcome, "still_open");
});
await test("a late result cannot close or claim observations about the next launch", async () => {
  await claim(20, true, "new-launch");
  await hooks.finishRunnerReport(20, origin, token, freshResult(), "failed");
  assert.match(tabs.get(20), /lever/);
  assert.equal(receipts[0].tab_outcome, "not_observed");
});
await test("receipt network failures still deliver the result and clean up", async () => {
  await claim();
  rejectReceipt = true;
  await hooks.finishRunnerReport(20, origin, token, freshResult(), "failed");
  assert.match(tabs.get(20), /batch_wait=1/);
  assert.equal(notifications.length, 1);
});
await test("progress preserves start time and rejects a different launch token", async () => {
  await claim();
  const original = await hooks.getAgentTabOwnershipForTab(20);
  const send = (launchToken, message) => new Promise(resolve => listener(
    {type: "jobfinitum-progress", origin, token: launchToken, message},
    {tab: {id: 20}}, resolve,
  ));
  await send(token, "uploading resume...");
  assert.equal((await hooks.runnerDetail(20)).diagnostics.phase, "resume_upload");
  assert.equal((await hooks.getAgentTabOwnershipForTab(20)).startedAt, original.startedAt);
  await send("wrong-launch", "submitting application");
  assert.equal((await hooks.runnerDetail(20)).diagnostics.phase, "resume_upload");
});
await test("observing a self-recycled tab reports recycled without closing it", async () => {
  await claim();
  tabs.set(20, origin + "/browser-agent?batch_wait=1");
  assert.equal(await hooks.observeRunnerTab(20, origin, token), "recycled");
});

console.log(JSON.stringify({passed: checks.length, failed: 0, checks}, null, 2));
