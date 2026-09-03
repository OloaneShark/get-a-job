(() => {
  "use strict";

  const BOARD_HOSTS = new Set([
    "remotefirstjobs.com",
    "www.remotefirstjobs.com",
  ]);
  const LAUNCH_STORAGE_KEY = "jobfinitum_remote_first_jobs_launch_v1";
  const BATCH_RUNNER_NAME = "jobfinitum-auto-apply-runner";
  const ADAPTER = "remote_first_jobs_resolver";
  const RESOLVER = "remote_first_jobs_browser_agent";

  const normalize = (value) =>
    String(value || "").replace(/\s+/g, " ").trim();

  const lower = (value) => normalize(value).toLowerCase();

  function isBatchRunner() {
    if (window.name === BATCH_RUNNER_NAME) return true;

    try {
      const saved = JSON.parse(
        window.sessionStorage.getItem(LAUNCH_STORAGE_KEY) || "null"
      );
      return saved?.batch === true;
    } catch (error) {
      return false;
    }
  }

  function statusBox(message, kind = "working") {
    let box = document.getElementById("jobfinitum-agent-status");
    if (!box) {
      box = document.createElement("div");
      box.id = "jobfinitum-agent-status";
      Object.assign(box.style, {
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: "2147483647",
        maxWidth: "390px",
        padding: "12px 14px",
        borderRadius: "8px",
        font: "14px/1.35 system-ui, sans-serif",
        boxShadow: "0 8px 28px rgba(0,0,0,.28)",
        border: "1px solid rgba(255,255,255,.25)",
      });
      document.documentElement.appendChild(box);
    }

    const colors = {
      working: ["#172554", "#dbeafe"],
      success: ["#052e16", "#dcfce7"],
      warning: ["#422006", "#fef3c7"],
      error: ["#450a0a", "#fee2e2"],
    };
    const selected = colors[kind] || colors.working;
    box.style.background = selected[0];
    box.style.color = selected[1];
    box.textContent = `Jobfinitum Browser Agent - ${message}`;
  }

  function send(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, (response) => {
        const runtimeError = chrome.runtime.lastError;
        if (runtimeError) {
          reject(new Error(runtimeError.message));
          return;
        }
        if (!response?.ok) {
          reject(new Error(response?.error || "Browser Agent bridge failed."));
          return;
        }
        resolve(response);
      });
    });
  }

  function parseLaunch() {
    const params = new URLSearchParams(
      String(location.hash || "").replace(/^#/, "")
    );
    const token = params.get("jobfinitum_agent");
    const origin = params.get("jobfinitum_origin");
    const batch = params.get("jobfinitum_batch") === "1" || isBatchRunner();

    if (token && origin) {
      const launch = {token, origin, batch};
      if (batch) window.name = BATCH_RUNNER_NAME;

      try {
        window.sessionStorage.setItem(
          LAUNCH_STORAGE_KEY,
          JSON.stringify(launch)
        );
      } catch (error) {
        console.warn("Jobfinitum could not persist Remote First Jobs launch state:", error);
      }

      history.replaceState(
        null,
        document.title,
        `${location.pathname}${location.search}`
      );
      return launch;
    }

    try {
      const saved = JSON.parse(
        window.sessionStorage.getItem(LAUNCH_STORAGE_KEY) || "null"
      );
      if (saved?.token && saved?.origin) {
        if (saved.batch === true) window.name = BATCH_RUNNER_NAME;
        return {
          token: String(saved.token),
          origin: String(saved.origin),
          batch: saved.batch === true,
        };
      }
    } catch (error) {
      console.warn("Jobfinitum could not restore Remote First Jobs launch state:", error);
    }

    return null;
  }

  function clearLaunch() {
    try {
      window.sessionStorage.removeItem(LAUNCH_STORAGE_KEY);
    } catch (error) {
      // Cleanup failure must not block result reporting.
    }
  }

  function isJobsIndex() {
    return BOARD_HOSTS.has(location.hostname.toLowerCase())
      && location.pathname.replace(/\/+$/, "") === "/jobs";
  }

  function visible(element) {
    if (!element || element.hidden) return false;
    if (lower(element.getAttribute?.("aria-hidden")) === "true") return false;

    const style = getComputedStyle(element);
    if (
      style.display === "none"
      || style.visibility === "hidden"
      || Number(style.opacity) === 0
    ) {
      return false;
    }

    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isExternalUrl(value) {
    try {
      const parsed = new URL(String(value || ""), location.href);
      const blockedHosts = new Set([
        ...BOARD_HOSTS,
        "127.0.0.1",
        "localhost",
        "jobfinitum.com",
        "www.jobfinitum.com",
      ]);
      return ["http:", "https:"].includes(parsed.protocol)
        && Boolean(parsed.hostname)
        && !blockedHosts.has(parsed.hostname.toLowerCase());
    } catch (error) {
      return false;
    }
  }

  function applyIntentScore(element) {
    const text = lower(
      element.innerText
      || element.textContent
      || element.value
      || element.getAttribute?.("aria-label")
      || element.getAttribute?.("title")
    );
    const ariaLabel = lower(element.getAttribute?.("aria-label"));
    let score = 0;

    if (text === "apply now") score = 160;
    else if (text === "apply") score = 150;
    else if (/^apply for this job\b/.test(text)) score = 145;
    else if (
      text === "continue to application"
      || text === "continue to apply"
      || text === "apply on company site"
      || text === "apply on company website"
    ) score = 140;
    else if (/^apply\b/.test(text)) score = 115;

    if (/^apply for this job\b/.test(ariaLabel)) score += 20;

    try {
      const parsed = new URL(element.href || "", location.href);
      if (/^\/a\/[^/]+\/?$/.test(parsed.pathname)) score += 80;
      if (lower(parsed.pathname).includes("apply")) score += 20;
    } catch (error) {
      // Non-link controls are scored by their label.
    }

    return score;
  }

  function externalApplyLink() {
    const candidates = [...document.querySelectorAll("a[href]")]
      .filter((anchor) => visible(anchor) && isExternalUrl(anchor.href))
      .map((anchor) => ({
        href: anchor.href,
        score: applyIntentScore(anchor),
      }))
      .filter((candidate) => candidate.score > 0)
      .sort((left, right) => right.score - left.score);

    return candidates[0]?.href || null;
  }

  function applyControl() {
    const candidates = [
      ...document.querySelectorAll('a, button, [role="button"]'),
    ]
      .filter((element) => (
        visible(element)
        && !element.disabled
        && lower(element.getAttribute?.("aria-disabled")) !== "true"
      ))
      .map((element) => ({
        element,
        score: applyIntentScore(element),
      }))
      .filter((candidate) => candidate.score > 0)
      .sort((left, right) => right.score - left.score);

    return candidates[0]?.element || null;
  }

  async function closeCompletedAgentTab(launch) {
    if (launch?.batch === true || isBatchRunner()) {
      window.name = BATCH_RUNNER_NAME;
      const waitingUrl = new URL("/browser-agent", launch.origin);
      waitingUrl.searchParams.set("batch_wait", "1");
      location.replace(waitingUrl.href);
      return;
    }

    try {
      await send({
        type: "jobfinitum-close-agent-tab",
        origin: launch.origin,
      });
    } catch (error) {
      console.warn("Jobfinitum could not close the Remote First Jobs tab:", error);
    }
  }

  async function reportPostingClosed(launch, originalUrl) {
    statusBox("this Remote First Jobs posting is no longer available.", "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "posting_closed",
        message: "Remote First Jobs redirected this removed posting to its jobs index.",
        final_url: location.href,
        detail: {
          url: location.href,
          final_url: location.href,
          original_url: String(originalUrl || ""),
          resolver: RESOLVER,
        },
      },
    });
    clearLaunch();
    await closeCompletedAgentTab(launch);
  }

  async function reportResolved(launch, resolvedUrl) {
    statusBox("resolved the employer application target.", "success");
    await send({
      type: "jobfinitum-job-board-resolved",
      origin: launch.origin,
      token: launch.token,
      url: resolvedUrl,
      batch: launch.batch === true,
    });
    clearLaunch();
  }

  async function scanForTarget(launch) {
    const resolvedUrl = externalApplyLink();
    if (!resolvedUrl) return false;
    await reportResolved(launch, resolvedUrl);
    return true;
  }

  async function activateApplyControl(control) {
    if (!control) return false;

    try {
      const target = new URL(control.href || "", location.href);
      if (
        control.tagName === "A"
        && BOARD_HOSTS.has(target.hostname.toLowerCase())
        && /^\/a\/[^/]+\/?$/.test(target.pathname)
      ) {
        control.setAttribute("target", "_self");
      }
    } catch (error) {
      // Non-link controls continue through their ordinary click behavior.
    }

    try {
      control.scrollIntoView({block: "center", inline: "center"});
      control.focus({preventScroll: true});
    } catch (error) {
      // Direct activation still works when scrolling or focus is unavailable.
    }

    for (const eventName of [
      "pointerdown",
      "mousedown",
      "pointerup",
      "mouseup",
    ]) {
      try {
        control.dispatchEvent(new MouseEvent(eventName, {
          bubbles: true,
          cancelable: true,
          view: window,
        }));
      } catch (error) {
        // The final click remains the fallback.
      }
    }

    control.click();
    return true;
  }

  async function reportManualDestination(launch, message, error = "") {
    statusBox(message, "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "needs_manual_destination",
        message,
        detail: {
          url: location.href,
          resolver: RESOLVER,
          error,
        },
      },
    });
    clearLaunch();
    await closeCompletedAgentTab(launch);
  }

  async function run() {
    const launch = parseLaunch();
    if (!launch) return;

    try {
      if (isBatchRunner()) {
        await send({
          type: "jobfinitum-batch-register",
          origin: launch.origin,
        });
      }

      statusBox("resolving the real employer application URL.");
      const taskResponse = await send({
        type: "jobfinitum-task",
        origin: launch.origin,
        token: launch.token,
      });
      const task = taskResponse.task || {};
      if (task.adapter !== ADAPTER) {
        throw new Error("This is not a Remote First Jobs resolver task.");
      }

      if (isJobsIndex()) {
        await reportPostingClosed(launch, task.target_url);
        return;
      }

      await send({
        type: "jobfinitum-job-board-watch",
        origin: launch.origin,
        token: launch.token,
        batch: launch.batch === true,
      });

      const started = Date.now();
      const clickedControls = new WeakSet();
      let lastWaitingUpdate = 0;

      while (Date.now() - started < 25000) {
        if (isJobsIndex()) {
          await reportPostingClosed(launch, task.target_url);
          return;
        }

        if (await scanForTarget(launch)) return;

        const control = applyControl();
        if (control && !clickedControls.has(control)) {
          clickedControls.add(control);
          statusBox("opening Apply to resolve the employer target.");
          await activateApplyControl(control);
        } else if (!control && Date.now() - lastWaitingUpdate >= 3000) {
          lastWaitingUpdate = Date.now();
          statusBox("waiting for Remote First Jobs to load its Apply control.");
        }

        await new Promise((resolve) => setTimeout(resolve, 400));
      }

      await reportManualDestination(
        launch,
        "Remote First Jobs did not expose the employer application destination automatically. Open the saved listing from Manual Apply to continue."
      );
    } catch (error) {
      console.error("Jobfinitum Remote First Jobs resolver failed:", error);
      try {
        await reportManualDestination(
          launch,
          "Remote First Jobs could not resolve this employer application automatically. Open the saved listing from Manual Apply to continue.",
          String(error.message || error)
        );
      } catch (reportError) {
        console.error("Jobfinitum Remote First Jobs failure report also failed:", reportError);
      }
    }
  }

  run();
})();
