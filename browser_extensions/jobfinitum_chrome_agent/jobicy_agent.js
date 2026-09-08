(() => {
  "use strict";

  const BOARD_HOSTS = new Set([
    "jobicy.com",
    "www.jobicy.com",
  ]);
  const LAUNCH_STORAGE_KEY =
    "jobfinitum_jobicy_launch_v1";
  const BATCH_RUNNER_NAME =
    "jobfinitum-auto-apply-runner";
  const ADAPTER = "jobicy_resolver";
  const RESOLVER = "jobicy_browser_agent";
  let observedExternalTarget = "";

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window
        || event.origin !== location.origin
        || event.data?.type
          !== "JOBICY_APPLICATION_STARTED"
      ) {
        return;
      }

      const target = String(
        event.data?.applyUrl || ""
      );

      if (isExternalUrl(target)) {
        observedExternalTarget = target;
      }
    }
  );

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
        "Jobfinitum could not persist Jobicy launch state:",
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
        "Jobfinitum could not restore Jobicy launch state:",
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
        "Jobfinitum could not remove the Jobicy launch fragment:",
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
        "/jobs",
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
      "this job has been removed",
      "this job has expired",
      "job posting has expired",
      "no longer accepting applications",
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

  function currentJobId() {
    const match = normalizedPath().match(
      /^\/jobs\/(\d+)(?:-|$)/
    );
    return match ? match[1] : "";
  }

  function guestHost() {
    return document.querySelector(
      '[id^="_w_"][data-t]'
    );
  }

  function guestRequestConfig() {
    const expectedJobId =
      currentJobId();

    for (const script of [
      ...document.scripts,
    ]) {
      const text = String(
        script.textContent || ""
      );

      if (
        !text.includes(
          "JOBICY_APPLICATION_STARTED"
        )
        || !text.includes(
          "X-Jobicy-Ajax"
        )
      ) {
        continue;
      }

      const action = text.match(
        /['"]action['"]\s*:\s*['"]([^'"]+)['"]/
      )?.[1];
      const nonce = text.match(
        /['"]nonce['"]\s*:\s*['"]([^'"]+)['"]/
      )?.[1];
      const postId = text.match(
        /['"]post_id['"]\s*:\s*['"]?(\d+)['"]?/
      )?.[1];

      if (
        !action
        || !nonce
        || !postId
        || (
          expectedJobId
          && postId !== expectedJobId
        )
      ) {
        continue;
      }

      return {
        action,
        nonce,
        postId,
      };
    }

    return null;
  }

  async function requestGuestDestination(
    config
  ) {
    const response = await fetch(
      new URL(
        "/signals.php",
        location.origin
      ).href,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type":
            "application/x-www-form-urlencoded; charset=UTF-8",
          "X-Jobicy-Ajax": "true",
          "X-Requested-With":
            "XMLHttpRequest",
        },
        body: new URLSearchParams({
          action: config.action,
          nonce: config.nonce,
          post_id: config.postId,
          increment_clicks: "true",
        }).toString(),
      }
    );

    if (!response.ok) {
      throw new Error(
        "Jobicy's guest application request failed."
      );
    }

    const payload =
      await response.json();
    const target = new URL(
      String(payload?.url || ""),
      location.href
    );

    if (
      target.protocol !== "https:"
      || !isExternalUrl(target.href)
    ) {
      throw new Error(
        "Jobicy did not return a valid employer application URL."
      );
    }

    target.username = "";
    target.password = "";
    return target.href;
  }

  function registrationOnlyGate() {
    return (
      !guestHost()
      && pageText().includes(
        "create your free account, then apply"
      )
    );
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
      type:
        "jobfinitum-job-board-resolved",
      origin: launch.origin,
      token: launch.token,
      url: resolvedUrl,
      batch: launch.batch === true,
    });
    clearLaunch();
  }

  async function reportSignInRequired(
    launch
  ) {
    const signInUrl = new URL(
      "/login",
      location.origin
    ).href;
    const message = (
      "Jobicy requires an account before it reveals the "
      + "employer application destination. Sign into Jobicy, "
      + "then resume this application from Jobfinitum."
    );
    statusBox(message, "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "waiting_sign_in",
        message,
        detail: {
          url: location.href,
          sign_in_url: signInUrl,
          resolver: RESOLVER,
        },
      },
    });
    clearLaunch();

    if (launch.batch !== true) {
      location.replace(signInUrl);
      return;
    }

    await closeCompletedAgentTab(
      launch
    );
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
        "Jobfinitum could not close the Jobicy resolver tab:",
        error
      );
    }
  }

  async function reportPostingClosed(
    launch,
    originalUrl
  ) {
    statusBox(
      "this Jobicy posting is no longer available.",
      "warning"
    );
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status: "posting_closed",
        message:
          "Jobicy no longer exposes this job posting.",
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
      "Jobicy requires visible human verification before "
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
          "This is not a Jobicy resolver task."
        );
      }

      await waitForDocument();
      statusBox(
        "resolving Jobicy's guest application destination."
      );

      if (postingClosed()) {
        await reportPostingClosed(
          launch,
          task.target_url
        );
        return;
      }

      const started = Date.now();
      let guestRequestStarted =
        false;
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
              "Jobicy blocked the redirect before revealing "
              + "the employer application. Open this listing "
              + "from Manual Apply to continue."
            )
          );
          return;
        }

        if (observedExternalTarget) {
          await reportResolved(
            launch,
            observedExternalTarget
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
            "following Jobicy's employer redirect."
          );
          location.replace(
            refreshTarget
          );
          return;
        }

        const guestConfig =
          guestRequestConfig();

        if (
          guestConfig
          && !guestRequestStarted
        ) {
          guestRequestStarted = true;
          statusBox(
            "using Jobicy's Continue as guest application path."
          );

          try {
            const resolvedUrl =
              await requestGuestDestination(
                guestConfig
              );
            await reportResolved(
              launch,
              resolvedUrl
            );
            return;
          } catch (error) {
            await reportManualDestination(
              launch,
              (
                "Jobicy's guest application path did not return "
                + "a usable employer destination. Open this "
                + "listing from Manual Apply to continue."
              ),
              String(error.message || error)
            );
            return;
          }
        }

        if (
          Date.now()
          - lastWaitingUpdate >= 3000
        ) {
          lastWaitingUpdate = Date.now();
          statusBox(
            "waiting for Jobicy's Continue as guest application path."
          );
        }

        await new Promise((resolve) =>
          setTimeout(resolve, 400)
        );
      }

      if (registrationOnlyGate()) {
        await reportSignInRequired(
          launch
        );
        return;
      }

      await reportManualDestination(
        launch,
        (
          "Jobicy did not reveal the employer application "
          + "destination automatically. Open this listing "
          + "from Manual Apply to continue."
        )
      );
    } catch (error) {
      console.error(
        "Jobfinitum Jobicy resolver failed:",
        error
      );

      try {
        await reportManualDestination(
          launch,
          (
            "Jobicy could not resolve this employer application "
            + "automatically. Open this listing from Manual Apply "
            + "to continue."
          ),
          String(error.message || error)
        );
      } catch (reportError) {
        console.error(
          "Jobfinitum Jobicy failure report also failed:",
          reportError
        );
      }
    }
  }

  run();
})();
