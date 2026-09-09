(() => {
  "use strict";

  const BOARD_HOSTS = new Set([
    "themuse.com",
    "www.themuse.com",
  ]);
  const LAUNCH_STORAGE_KEY =
    "jobfinitum_the_muse_launch_v1";
  const BATCH_RUNNER_NAME =
    "jobfinitum-auto-apply-runner";
  const ADAPTER = "the_muse_resolver";
  const RESOLVER = "the_muse_browser_agent";

  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();

  const lower = (value) =>
    normalize(value).toLowerCase();

  function send(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        message,
        (response) => {
          const runtimeError =
            chrome.runtime.lastError;

          if (runtimeError) {
            reject(new Error(runtimeError.message));
            return;
          }

          if (!response?.ok) {
            reject(new Error(
              response?.error
              || "Browser Agent bridge failed."
            ));
            return;
          }

          resolve(response);
        }
      );
    });
  }

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
        "Jobfinitum could not persist The Muse launch state:",
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
    const token = params.get("jobfinitum_agent");
    const origin = params.get("jobfinitum_origin");
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
        "Jobfinitum could not restore The Muse launch state:",
        error
      );
    }

    return null;
  }

  async function restoreTrackedLaunch() {
    try {
      const response = await send({
        type: "jobfinitum-job-board-restore",
      });
      const launch = response?.launch;

      if (launch?.token && launch?.origin) {
        return persistLaunch({
          token: String(launch.token),
          origin: String(launch.origin),
          batch: launch.batch === true,
        });
      }
    } catch (error) {
      console.warn(
        "Jobfinitum could not restore The Muse's tracked launch:",
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
        "Jobfinitum could not remove The Muse launch fragment:",
        error
      );
    }
  }

  function statusBox(message, kind = "working") {
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
        font: "14px/1.35 system-ui, sans-serif",
        boxShadow: "0 8px 28px rgba(0,0,0,.28)",
        border: "1px solid rgba(255,255,255,.25)",
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
    box.textContent =
      `Jobfinitum Browser Agent - ${message}`;
  }

  async function waitForDocument() {
    if (document.readyState !== "loading") {
      return;
    }

    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 5000);
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
      && ["", "/jobs", "/search"].includes(
        normalizedPath()
      )
    );
  }

  function isJobDetailPath() {
    return (
      BOARD_HOSTS.has(
        location.hostname.toLowerCase()
      )
      && /^\/jobs\/[^/]+\/[^/]+$/i.test(
        normalizedPath()
      )
    );
  }

  function currentJobSlug() {
    if (!isJobDetailPath()) {
      return "";
    }

    return decodeURIComponent(
      normalizedPath().split("/").at(-1) || ""
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
      "this position is no longer available",
      "this job has been removed",
      "this job has expired",
      "job posting has expired",
      "no longer accepting applications",
      "job not found",
      "page not found",
    ].some((phrase) => body.includes(phrase));
  }

  function blockedPage() {
    const body = pageText();
    return [
      "403 forbidden",
      "access denied",
      "request blocked",
      "you don't have permission to access",
      "you do not have permission to access",
    ].some((phrase) => body.includes(phrase));
  }

  function visible(element) {
    if (!element || element.hidden) {
      return false;
    }

    if (
      lower(element.getAttribute?.("aria-hidden"))
      === "true"
    ) {
      return false;
    }

    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
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
    const rendered = [
      ...document.querySelectorAll(
        selectors.join(",")
      ),
    ].some(visible);

    if (rendered) {
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
      return (
        ["http:", "https:"].includes(parsed.protocol)
        && Boolean(parsed.hostname)
        && !BOARD_HOSTS.has(
          parsed.hostname.toLowerCase()
        )
        && ![
          "127.0.0.1",
          "localhost",
          "jobfinitum.com",
          "www.jobfinitum.com",
        ].includes(parsed.hostname.toLowerCase())
      );
    } catch (error) {
      return false;
    }
  }

  function decodeEmbeddedUrl(value) {
    const decoded = String(value || "")
      .replace(/\\+u0026/gi, "&")
      .replace(/\\+u003d/gi, "=")
      .replace(/\\+u002f/gi, "/")
      .replace(/\\+\//g, "/")
      .replace(/\\+$/, "")
      .trim();

    try {
      return new URL(decoded, location.href).href;
    } catch (error) {
      return "";
    }
  }

  function applyLinksFromText(value) {
    const text = String(value || "");
    const pattern =
      /\\*["']applyLink\\*["']\s*:\s*\\*["'](https?:[^"']+?)\\*["']/gi;
    const slug = currentJobSlug();
    const candidates = [];
    let match = pattern.exec(text);

    while (match) {
      const url = decodeEmbeddedUrl(match[1]);

      if (isExternalUrl(url)) {
        const context = text
          .slice(
            Math.max(0, match.index - 700),
            match.index
          )
          .replace(/\\+/g, "")
          .toLowerCase();
        let score = 1;

        if (slug && context.includes(slug)) {
          score += 100;
        }

        if (
          context.includes('"state":"live"')
          || context.includes("'state':'live'")
        ) {
          score += 10;
        }

        candidates.push({
          url,
          score,
          index: match.index,
        });
      }

      match = pattern.exec(text);
    }

    return candidates;
  }

  function declaredApplyTarget() {
    for (const element of [
      ...document.querySelectorAll(
        "[data-apply-link], [data-apply-url], [data-application-url]"
      ),
    ]) {
      const target = (
        element.getAttribute("data-apply-link")
        || element.getAttribute("data-apply-url")
        || element.getAttribute("data-application-url")
      );

      if (isExternalUrl(target)) {
        return new URL(target, location.href).href;
      }
    }

    return null;
  }

  function embeddedApplyTarget() {
    if (!isJobDetailPath()) {
      return null;
    }

    const candidates = [];

    for (const script of [
      ...(document.scripts || []),
    ]) {
      candidates.push(
        ...applyLinksFromText(
          script.textContent || ""
        )
      );
    }

    candidates.sort((left, right) => (
      right.score - left.score
      || left.index - right.index
    ));

    return candidates[0]?.url || null;
  }

  function externalApplyLink() {
    const candidates = [
      ...document.querySelectorAll("a[href]"),
    ]
      .filter((anchor) => {
        const text = lower(
          anchor.innerText
          || anchor.textContent
          || anchor.getAttribute?.("aria-label")
          || anchor.getAttribute?.("title")
        );
        return (
          visible(anchor)
          && isExternalUrl(anchor.href)
          && (
            text === "apply"
            || text === "apply now"
            || text === "apply on company site"
            || text === "continue to application"
          )
        );
      });

    return candidates[0]?.href || null;
  }

  async function closeCompletedAgentTab(launch) {
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
        type: "jobfinitum-close-agent-tab",
        origin: launch.origin,
      });
    } catch (error) {
      console.warn(
        "Jobfinitum could not close The Muse resolver tab:",
        error
      );
    }
  }

  async function reportResolved(
    launch,
    resolvedUrl
  ) {
    statusBox(
      "resolved the employer application target.",
      "success"
    );
    await send({
      type: "jobfinitum-job-board-resolved",
      origin: launch.origin,
      token: launch.token,
      url: resolvedUrl,
      batch: launch.batch === true,
    });
    clearLaunch();
  }

  async function reportPostingClosed(
    launch,
    originalUrl
  ) {
    const message =
      "This Muse posting is no longer available.";
    statusBox(message, "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "posting_closed",
        message,
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

  async function reportVerification(launch) {
    const message = (
      "The Muse requires visible human verification before "
      + "it can reveal the employer application. "
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
    let launch = parseLaunch();

    if (!launch) {
      launch = await restoreTrackedLaunch();
    }

    if (!launch) {
      return;
    }

    try {
      if (isBatchRunner()) {
        await send({
          type: "jobfinitum-batch-register",
          origin: launch.origin,
        });
      }

      await send({
        type: "jobfinitum-job-board-watch",
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
          "This is not a The Muse resolver task."
        );
      }

      await waitForDocument();
      statusBox(
        "reading The Muse's employer application destination."
      );

      const started = Date.now();
      let lastWaitingUpdate = 0;

      while (Date.now() - started < 25000) {
        if (postingClosed()) {
          await reportPostingClosed(
            launch,
            task.target_url
          );
          return;
        }

        if (visibleChallenge()) {
          await reportVerification(launch);
          return;
        }

        if (blockedPage()) {
          await reportManualDestination(
            launch,
            (
              "The Muse blocked access to the employer link. "
              + "Open this listing from Manual Apply to continue."
            )
          );
          return;
        }

        const resolvedUrl = (
          declaredApplyTarget()
          || embeddedApplyTarget()
          || externalApplyLink()
        );

        if (resolvedUrl) {
          await reportResolved(
            launch,
            resolvedUrl
          );
          return;
        }

        if (
          Date.now() - lastWaitingUpdate >= 3000
        ) {
          lastWaitingUpdate = Date.now();
          statusBox(
            "waiting for The Muse's application data."
          );
        }

        await new Promise((resolve) =>
          setTimeout(resolve, 400)
        );
      }

      await reportManualDestination(
        launch,
        (
          "The Muse did not reveal the employer application "
          + "destination automatically. Open this listing "
          + "from Manual Apply to continue."
        )
      );
    } catch (error) {
      console.error(
        "Jobfinitum The Muse resolver failed:",
        error
      );

      try {
        await reportManualDestination(
          launch,
          (
            "The Muse could not resolve this employer application "
            + "automatically. Open this listing from Manual Apply "
            + "to continue."
          ),
          String(error.message || error)
        );
      } catch (reportError) {
        console.error(
          "Jobfinitum The Muse failure report also failed:",
          reportError
        );
      }
    }
  }

  run();
})();
