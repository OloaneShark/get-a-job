(() => {
  "use strict";

  const BOARD_HOSTS = new Set([
    "jooble.org",
    "www.jooble.org",
  ]);
  const LAUNCH_STORAGE_KEY =
    "jobfinitum_jooble_launch_v1";
  const BATCH_RUNNER_NAME =
    "jobfinitum-auto-apply-runner";
  const ADAPTER = "jooble_resolver";
  const RESOLVER = "jooble_browser_agent";

  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();

  const lower = (value) =>
    normalize(value).toLowerCase();

  function isBatchRunner() {
    if (window.name === BATCH_RUNNER_NAME) {
      return true;
    }

    try {
      const saved = JSON.parse(
        window.sessionStorage.getItem(
          LAUNCH_STORAGE_KEY
        ) || "null"
      );
      return saved?.batch === true;
    } catch (error) {
      return false;
    }
  }

  function persistLaunch(launch) {
    if (launch?.batch === true) {
      window.name = BATCH_RUNNER_NAME;
    }

    try {
      window.sessionStorage.setItem(
        LAUNCH_STORAGE_KEY,
        JSON.stringify(launch)
      );
    } catch (error) {
      console.warn(
        "Jobfinitum could not persist Jooble launch state:",
        error
      );
    }

    return launch;
  }

  function parseLaunch() {
    const params = new URLSearchParams(
      String(location.hash || "")
        .replace(/^#/, "")
    );
    const token = params.get(
      "jobfinitum_agent"
    );
    const origin = params.get(
      "jobfinitum_origin"
    );
    const batch = (
      params.get("jobfinitum_batch") === "1"
      || isBatchRunner()
    );

    if (token && origin) {
      return persistLaunch({
        token,
        origin,
        batch,
      });
    }

    try {
      const saved = JSON.parse(
        window.sessionStorage.getItem(
          LAUNCH_STORAGE_KEY
        ) || "null"
      );

      if (saved?.token && saved?.origin) {
        return persistLaunch({
          token: String(saved.token),
          origin: String(saved.origin),
          batch: saved.batch === true,
        });
      }
    } catch (error) {
      console.warn(
        "Jobfinitum could not restore Jooble launch state:",
        error
      );
    }

    return null;
  }

  function clearLaunch() {
    try {
      window.sessionStorage.removeItem(
        LAUNCH_STORAGE_KEY
      );
    } catch (error) {
      // Cleanup failure must not block result reporting.
    }
  }

  function scrubLaunchHash() {
    if (!String(location.hash || "")) {
      return;
    }

    try {
      history.replaceState(
        null,
        document.title,
        `${location.pathname}${location.search}`
      );
    } catch (error) {
      console.warn(
        "Jobfinitum could not remove the Jooble launch fragment:",
        error
      );
    }
  }

  function send(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        message,
        (response) => {
          const runtimeError =
            chrome.runtime.lastError;

          if (runtimeError) {
            reject(
              new Error(runtimeError.message)
            );
            return;
          }

          if (!response?.ok) {
            reject(
              new Error(
                response?.error
                || "Browser Agent bridge failed."
              )
            );
            return;
          }

          resolve(response);
        }
      );
    });
  }

  async function restoreTrackedLaunch() {
    try {
      const response = await send({
        type:
          "jobfinitum-job-board-restore",
      });
      const launch = response?.launch;

      if (
        !launch?.token
        || !launch?.origin
      ) {
        return null;
      }

      return persistLaunch({
        token: String(launch.token),
        origin: String(launch.origin),
        batch: launch.batch === true,
      });
    } catch (error) {
      return null;
    }
  }

  function statusBox(
    message,
    kind = "working"
  ) {
    let box = document.getElementById(
      "jobfinitum-agent-status"
    );

    if (!box) {
      const parent = (
        document.documentElement
        || document.body
      );

      if (!parent) {
        return;
      }

      box = document.createElement("div");
      box.id = "jobfinitum-agent-status";

      Object.assign(box.style, {
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: "2147483647",
        maxWidth: "390px",
        padding: "12px 14px",
        borderRadius: "0",
        font:
          "14px/1.35 system-ui, sans-serif",
        boxShadow:
          "0 8px 28px rgba(0,0,0,.28)",
        border:
          "1px solid rgba(255,255,255,.25)",
      });

      parent.appendChild(box);
    }

    const colors = {
      working: ["#172554", "#dbeafe"],
      success: ["#052e16", "#dcfce7"],
      warning: ["#422006", "#fef3c7"],
      error: ["#450a0a", "#fee2e2"],
    };
    const selected =
      colors[kind] || colors.working;

    box.style.background = selected[0];
    box.style.color = selected[1];
    box.textContent = (
      `Jobfinitum Browser Agent - ${message}`
    );
  }

  async function waitForDocument() {
    if (
      document.readyState !== "loading"
    ) {
      return;
    }

    await new Promise((resolve) => {
      const timer = setTimeout(
        resolve,
        5000
      );

      document.addEventListener(
        "DOMContentLoaded",
        () => {
          clearTimeout(timer);
          resolve();
        },
        {once: true}
      );
    });
  }

  function normalizedPath() {
    return location.pathname
      .replace(/\/+$/, "")
      .toLowerCase();
  }

  function isJobsIndex() {
    return (
      BOARD_HOSTS.has(
        location.hostname.toLowerCase()
      )
      && [
        "",
        "/searchresult",
      ].includes(normalizedPath())
    );
  }

  function pageText() {
    return lower(
      document.body?.innerText
      || document.body?.textContent
      || ""
    );
  }

  function postingClosed() {
    if (isJobsIndex()) {
      return true;
    }

    const body = pageText();
    return [
      "this job is no longer available",
      "this vacancy is no longer available",
      "the vacancy has been removed",
      "job posting has expired",
      "job not found",
      "page not found",
    ].some((phrase) =>
      body.includes(phrase)
    );
  }

  function blockedPage() {
    const body = pageText();
    return [
      "403 forbidden",
      "access denied",
      "request blocked",
      "you don't have permission to access",
      "you do not have permission to access",
    ].some((phrase) =>
      body.includes(phrase)
    );
  }

  function visible(element) {
    if (!element || element.hidden) {
      return false;
    }

    if (
      lower(
        element.getAttribute?.(
          "aria-hidden"
        )
      ) === "true"
    ) {
      return false;
    }

    const style =
      getComputedStyle(element);
    const rect =
      element.getBoundingClientRect();

    return (
      style.display !== "none"
      && style.visibility !== "hidden"
      && Number(style.opacity) !== 0
      && rect.width > 0
      && rect.height > 0
    );
  }

  function visibleChallenge() {
    const selectors = [
      'iframe[src*="recaptcha"]',
      'iframe[src*="hcaptcha"]',
      'iframe[src*="challenges.cloudflare.com"]',
      ".cf-turnstile",
      "#cf-challenge-running",
      'form[action*="__cf_chl"]',
      '[data-sitekey][class*="captcha"]',
      'input[name="cf-turnstile-response"]',
    ];

    const renderedChallenge = [
      ...document.querySelectorAll(
        selectors.join(",")
      ),
    ].some(visible);

    if (renderedChallenge) {
      return true;
    }

    return (
      lower(document.title).includes(
        "just a moment"
      )
      && pageText().includes(
        "enable javascript and cookies to continue"
      )
    );
  }

  function isExternalUrl(value) {
    try {
      const parsed = new URL(
        String(value || ""),
        location.href
      );
      const blockedHosts = new Set([
        ...BOARD_HOSTS,
        "127.0.0.1",
        "localhost",
        "jobfinitum.com",
        "www.jobfinitum.com",
      ]);

      return (
        ["http:", "https:"].includes(
          parsed.protocol
        )
        && Boolean(parsed.hostname)
        && !blockedHosts.has(
          parsed.hostname.toLowerCase()
        )
      );
    } catch (error) {
      return false;
    }
  }

  function metaRefreshTarget() {
    const meta = document.querySelector(
      'meta[http-equiv="refresh" i]'
    );
    const content = String(
      meta?.getAttribute("content")
      || ""
    );
    const match = content.match(
      /(?:^|;)\s*url\s*=\s*['"]?([^'"]+)['"]?/i
    );

    if (!match) {
      return null;
    }

    try {
      return new URL(
        match[1].trim(),
        location.href
      ).href;
    } catch (error) {
      return null;
    }
  }

  function continueIntentScore(element) {
    const text = lower(
      element.innerText
      || element.textContent
      || element.value
      || element.getAttribute?.(
        "aria-label"
      )
      || element.getAttribute?.("title")
    );

    if (
      text.includes("post a job")
      || text.includes("sign in")
      || text.includes("log in")
      || text.includes("privacy")
      || text.includes("terms")
      || text.includes("advertis")
    ) {
      return 0;
    }

    let score = 0;

    if (text === "continue") {
      score = 190;
    } else if (text === "apply now") {
      score = 185;
    } else if (text === "apply") {
      score = 175;
    } else if (
      text === "view job"
      || text === "view vacancy"
      || text === "open job"
    ) {
      score = 165;
    } else if (
      /^(?:continue|apply|view|open)\b/
        .test(text)
    ) {
      score = 130;
    }

    try {
      const parsed = new URL(
        element.href || "",
        location.href
      );

      if (
        BOARD_HOSTS.has(
          parsed.hostname.toLowerCase()
        )
        && parsed.pathname
          .toLowerCase()
          .startsWith("/away/")
      ) {
        score += 40;
      } else if (
        isExternalUrl(parsed.href)
        && score > 0
      ) {
        score += 25;
      }
    } catch (error) {
      // Buttons are scored by their visible label.
    }

    return score;
  }

  function continueControl() {
    return [
      ...document.querySelectorAll(
        'a, button, [role="button"]'
      ),
    ]
      .filter((element) => (
        visible(element)
        && !element.disabled
        && lower(
          element.getAttribute?.(
            "aria-disabled"
          )
        ) !== "true"
      ))
      .map((element) => ({
        element,
        score:
          continueIntentScore(element),
      }))
      .filter((candidate) =>
        candidate.score > 0
      )
      .sort((left, right) =>
        right.score - left.score
      )[0]?.element || null;
  }

  async function activateControl(control) {
    if (!control) {
      return false;
    }

    if (control.tagName === "A") {
      control.setAttribute(
        "target",
        "_self"
      );
      control.setAttribute(
        "rel",
        "noopener"
      );
    }

    try {
      control.scrollIntoView({
        block: "center",
        inline: "center",
      });
      control.focus({
        preventScroll: true,
      });
    } catch (error) {
      // Direct activation remains available.
    }

    for (const eventName of [
      "pointerdown",
      "mousedown",
      "pointerup",
      "mouseup",
    ]) {
      try {
        control.dispatchEvent(
          new MouseEvent(
            eventName,
            {
              bubbles: true,
              cancelable: true,
              view: window,
            }
          )
        );
      } catch (error) {
        // The final click remains the fallback.
      }
    }

    control.click();
    return true;
  }

  async function closeCompletedAgentTab(
    launch
  ) {
    if (
      launch?.batch === true
      || isBatchRunner()
    ) {
      window.name = BATCH_RUNNER_NAME;
      const waitingUrl = new URL(
        "/browser-agent",
        launch.origin
      );
      waitingUrl.searchParams.set(
        "batch_wait",
        "1"
      );
      location.replace(waitingUrl.href);
      return;
    }

    try {
      await send({
        type:
          "jobfinitum-close-agent-tab",
        origin: launch.origin,
      });
    } catch (error) {
      console.warn(
        "Jobfinitum could not close the Jooble resolver tab:",
        error
      );
    }
  }

  async function reportPostingClosed(
    launch,
    originalUrl
  ) {
    statusBox(
      "this Jooble posting is no longer available.",
      "warning"
    );
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "posting_closed",
        message:
          "Jooble no longer exposes this job posting.",
        final_url: location.href,
        detail: {
          url: location.href,
          final_url: location.href,
          original_url: String(
            originalUrl || ""
          ),
          resolver: RESOLVER,
        },
      },
    });
    clearLaunch();
    await closeCompletedAgentTab(
      launch
    );
  }

  async function reportVerification(
    launch
  ) {
    const message = (
      "Jooble requires visible human verification before "
      + "it can redirect to the employer application. "
      + "Complete the challenge in this tab."
    );
    statusBox(message, "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "waiting_verification",
        message,
        detail: {
          url: location.href,
          resolver: RESOLVER,
          verification_required: true,
        },
      },
    });
  }

  async function reportManualDestination(
    launch,
    message,
    error = ""
  ) {
    statusBox(message, "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status:
          "needs_manual_destination",
        message,
        detail: {
          url: location.href,
          resolver: RESOLVER,
          error,
        },
      },
    });
    clearLaunch();
    await closeCompletedAgentTab(
      launch
    );
  }

  async function run() {
    let launch = parseLaunch();

    if (!launch) {
      launch =
        await restoreTrackedLaunch();
    }

    if (!launch) {
      return;
    }

    try {
      if (isBatchRunner()) {
        await send({
          type:
            "jobfinitum-batch-register",
          origin: launch.origin,
        });
      }

      await send({
        type:
          "jobfinitum-job-board-watch",
        origin: launch.origin,
        token: launch.token,
        batch: launch.batch === true,
      });

      scrubLaunchHash();

      const taskResponse = await send({
        type: "jobfinitum-task",
        origin: launch.origin,
        token: launch.token,
      });
      const task = taskResponse.task || {};

      if (task.adapter !== ADAPTER) {
        throw new Error(
          "This is not a Jooble resolver task."
        );
      }

      await waitForDocument();
      statusBox(
        "following Jooble to the employer application."
      );

      if (postingClosed()) {
        await reportPostingClosed(
          launch,
          task.target_url
        );
        return;
      }

      const started = Date.now();
      const clickedControls =
        new WeakSet();
      let lastWaitingUpdate = 0;

      while (
        Date.now() - started < 25000
      ) {
        if (postingClosed()) {
          await reportPostingClosed(
            launch,
            task.target_url
          );
          return;
        }

        if (visibleChallenge()) {
          await reportVerification(
            launch
          );
          return;
        }

        if (blockedPage()) {
          await reportManualDestination(
            launch,
            (
              "Jooble blocked the redirect before revealing "
              + "the employer application. Open this listing "
              + "from Manual Apply to continue."
            )
          );
          return;
        }

        const refreshTarget =
          metaRefreshTarget();

        if (
          refreshTarget
          && refreshTarget !== location.href
        ) {
          statusBox(
            "following Jooble's employer redirect."
          );
          location.replace(
            refreshTarget
          );
          return;
        }

        const control =
          continueControl();

        if (
          control
          && !clickedControls.has(control)
        ) {
          clickedControls.add(control);
          statusBox(
            "opening Jooble's employer link."
          );
          await activateControl(control);
        } else if (
          !control
          && Date.now()
            - lastWaitingUpdate >= 3000
        ) {
          lastWaitingUpdate = Date.now();
          statusBox(
            "waiting for Jooble's employer redirect."
          );
        }

        await new Promise((resolve) =>
          setTimeout(resolve, 400)
        );
      }

      await reportManualDestination(
        launch,
        (
          "Jooble did not reveal the employer application "
          + "destination automatically. Open this listing "
          + "from Manual Apply to continue."
        )
      );
    } catch (error) {
      console.error(
        "Jobfinitum Jooble resolver failed:",
        error
      );

      try {
        await reportManualDestination(
          launch,
          (
            "Jooble could not resolve this employer application "
            + "automatically. Open this listing from Manual Apply "
            + "to continue."
          ),
          String(error.message || error)
        );
      } catch (reportError) {
        console.error(
          "Jobfinitum Jooble failure report also failed:",
          reportError
        );
      }
    }
  }

  run();
})();
