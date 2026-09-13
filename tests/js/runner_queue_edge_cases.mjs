import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";

const raw = await readFile(new URL("../../static/js/chrome_agent_site.js", import.meta.url), "utf8");
const begin = raw.lastIndexOf("(() => {", raw.indexOf('const STORAGE_KEY ='));
const end = raw.indexOf("  const existingState =", begin);
const source = raw.slice(begin, end) + "\nglobalThis.hooks = {saveState, loadState, submitNext, stopBatch, handleBatchTimeout, showRunnerDetails};})();";
const values = new Map();
const calls = [];
const events = new Map();
const timers = [];
const controls = new Map();
let submitFails = false;
let interruptResponse = null;
function node() {
  return {
    dataset: {}, value: "csrf", children: [], textContent: "",
    addEventListener() {}, appendChild(child) { this.children.push(child); },
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; }, remove() {},
    submit() { if (submitFails) throw new Error("Launch failed"); calls.push({launch: this.action}); },
  };
}
const context = {
  console, URL, Date,
  location: {origin: "http://127.0.0.1:5000", reload() {}},
  fetch: async (url, options) => {
    const payload = JSON.parse(options.body);
    calls.push({url, payload});
    return {ok: true, json: async () => interruptResponse || {}};
  },
  document: {
    documentElement: {dataset: {}}, body: node(),
    getElementById(id) { if (!controls.has(id)) controls.set(id, node()); return controls.get(id); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    createElement() { return node(); },
  },
  sessionStorage: {
    getItem(key) { return values.get(key); },
    setItem(key, value) { values.set(key, value); }, removeItem(key) { values.delete(key); },
  },
  addEventListener(name, fn) { events.set(name, fn); },
  setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
  postMessage(message) { calls.push({control: message}); },
};
context.window = context;
vm.createContext(context);
new vm.Script(source).runInContext(context);
const runtimeWindow = new vm.Script("window").runInContext(context);
const hooks = context.hooks;
const result = () => ({
  candidate_id: 10, attempt_id: 12, status: "Failed",
  diagnostics: {run_id: "old-run", reason_label: "Browser Agent failed"},
});
const state = () => ({
  active: true, completed: 1, total: 2, current: null,
  remaining: [{candidate_id: 11, action_url: "/launch/11"}], pending_receipt: result(),
});
function reset() { values.clear(); calls.length = 0; timers.length = 0; submitFails = false; interruptResponse = null; }
const checks = [];
async function test(name, fn) { reset(); await fn(); checks.push(name); }

await test("batch advancement is recorded only after launching the next job", async () => {
  hooks.saveState(state());
  hooks.submitNext();
  assert.equal(calls[0].launch, "/launch/11");
  assert.equal(calls[1].payload.batch_outcome, "advanced");
  assert.equal(hooks.loadState().pending_receipt, null);
});
await test("a launch failure never claims the batch advanced", async () => {
  hooks.saveState(state()); submitFails = true;
  assert.throws(() => hooks.submitNext(), /Launch failed/);
  assert.equal(calls.some(call => call.payload?.batch_outcome === "advanced"), false);
});
await test("the last job reports completion instead of advancement", async () => {
  hooks.saveState({...state(), remaining: []});
  hooks.submitNext();
  assert.equal(calls.find(call => call.payload)?.payload.batch_outcome, "complete");
  assert.equal(hooks.loadState(), null);
});
await test("a verification result records the reason and advances the batch", async () => {
  hooks.saveState({...state(), current: {candidate_id: 10}});
  events.get("message")({
    source: runtimeWindow, origin: context.location.origin,
    data: {source: "jobfinitum-chrome-agent", type: "result", result: {
      ...result(), status: "Waiting for Verification",
      diagnostics: {run_id: "old-run", reason_label: "Human verification required"},
    }},
  });
  assert.equal(hooks.loadState().current, null);
  assert.equal(hooks.loadState().pending_receipt.status, "Waiting for Verification");
  assert.equal(calls.some(call => call.payload?.batch_outcome === "paused"), false);
  timers.at(-1)();
  assert.equal(hooks.loadState().current.candidate_id, 11);
  assert.equal(calls.find(call => call.payload)?.payload.batch_outcome, "advanced");
});
await test("stopping preserves the current launch diagnostics after state is cleared", async () => {
  hooks.saveState({
    ...state(), current: {candidate_id: 10},
    current_started_at: Date.now() - 1000,
    current_diagnostics: {run_id: "current-run", phase: "resume_upload"},
  });
  interruptResponse = {...result(), diagnostics: {run_id: "current-run"}};
  await hooks.stopBatch();
  const interrupted = calls.find(call => call.url?.endsWith("/interrupt"));
  assert.equal(interrupted.payload.diagnostics.run_id, "current-run");
  assert.equal(interrupted.payload.diagnostics.phase, "resume_upload");
  assert.ok(interrupted.payload.diagnostics.elapsed_ms >= 1000);
  assert.equal(calls.find(call => call.control)?.control.action, "stop");
});

console.log(JSON.stringify({passed: checks.length, failed: 0, checks}, null, 2));
