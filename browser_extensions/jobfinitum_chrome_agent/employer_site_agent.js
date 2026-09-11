(() => {
  "use strict";

  const LAUNCH_STORAGE_KEY =
    "jobfinitum_employer_site_launch_v1";
  const BATCH_RUNNER_NAME =
    "jobfinitum-auto-apply-runner";
  const ADAPTER = "employer_site_resolver";
  const RESOLVER = "employer_site_browser_agent";
  const FAST_SCAN_MS = 1800;
  const ATS_EVIDENCE_SCAN_MS = 7000;
  const AFTER_APPLY_SCAN_MS = 5000;
  const MAX_SCAN_MS = 9000;
  const INDEX_SETTLE_MS = 1000;
  const POLL_INTERVAL_MS = 250;
  const MAX_SCRIPT_SCAN_CHARACTERS = 750000;

  const GREENHOUSE_HOSTS = new Set([
    "boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
    "grnh.se",
  ]);

  const HOSTED_ATS_HOSTS = new Set([
    ...GREENHOUSE_HOSTS,
    "jobs.lever.co",
    "jobs.eu.lever.co",
    "jobs.ashbyhq.com",
  ]);

  const RESOLVER_HOSTS = new Set([
    "himalayas.app",
    "www.himalayas.app",
    "remotefirstjobs.com",
    "www.remotefirstjobs.com",
    "japan-dev.com",
    "www.japan-dev.com",
    "weworkremotely.com",
    "www.weworkremotely.com",
    "jooble.org",
    "www.jooble.org",
    "remoteok.com",
    "www.remoteok.com",
    "jobicy.com",
    "www.jobicy.com",
    "tokyodev.com",
    "www.tokyodev.com",
    "themuse.com",
    "www.themuse.com",
  ]);

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

  function adzunaHost(host) {
    return /^(?:www\.)?adzuna\.(?:com|com\.au|at|be|com\.br|ca|fr|de|in|it|com\.mx|nl|co\.nz|pl|sg|co\.za|es|ch|co\.uk)$/.test(
      host
    );
  }

  function usesDedicatedAgent(value = location.href) {
    try {
      const parsed = new URL(value);
      const host = parsed.hostname.toLowerCase();

      return (
        HOSTED_ATS_HOSTS.has(host)
        || RESOLVER_HOSTS.has(host)
        || adzunaHost(host)
        || host === "127.0.0.1"
        || host === "localhost"
        || host === "jobfinitum.com"
        || host === "www.jobfinitum.com"
      );
    } catch (error) {
      return true;
    }
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
        "Jobfinitum could not persist the employer-site launch state:",
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
      return persistLaunch({token, origin, batch});
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
        "Jobfinitum could not restore the employer-site launch state:",
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
        "Jobfinitum could not restore the tracked employer-site launch:",
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
        "Jobfinitum could not remove the employer-site launch fragment:",
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

  function visible(element) {
    if (!element || element.hidden) {
      return false;
    }

    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();

    return (
      style.display !== "none"
      && style.visibility !== "hidden"
      && style.opacity !== "0"
      && rect.width > 0
      && rect.height > 0
    );
  }

  function pageText() {
    return lower(
      document.body?.innerText
      || document.body?.textContent
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
      'input[name="cf-turnstile-response"]',
    ];

    return selectors.some((selector) => (
      [...document.querySelectorAll(selector)]
        .some(visible)
    ));
  }

  function signInRequired() {
    const password = document.querySelector?.(
      'input[type="password"]'
    );
    const text = pageText();

    return (
      visible(password)
      && (
        text.includes("sign in")
        || text.includes("log in")
        || text.includes("login")
      )
    );
  }

  function postingClosed() {
    const text = pageText();
    const title = lower(document.title);
    const phrases = [
      "this job is no longer available",
      "this position is no longer available",
      "this job has been removed",
      "this job has expired",
      "this position has been filled",
      "job posting has expired",
      "job no longer exists",
      "position is no longer open",
      "no longer accepting applications",
      "the page you requested could not be found",
      "the page you're looking for doesn't exist",
      "we couldn't find that page",
      "page not found",
    ];

    return (
      /(?:^|\s)404(?:\s|$)/.test(title)
      || phrases.some((phrase) => (
        title.includes(phrase)
        || text.includes(phrase)
      ))
    );
  }

  function decodeUrlText(value) {
    return String(value || "")
      .replace(/\\u002[fF]/g, "/")
      .replace(/\\u0026/g, "&")
      .replace(/\\u003[dD]/g, "=")
      .replace(/\\\//g, "/")
      .replace(/&amp;/gi, "&")
      .trim()
      .replace(/[),.;]+$/, "");
  }

  function urlsFromText(value) {
    const decoded = decodeUrlText(value);
    const matches = decoded.match(
      /https?:\/\/[^\s"'<>\\]+/gi
    ) || [];

    return matches.map(decodeUrlText);
  }

  function greenhouseEmbed(board, jobId) {
    if (
      !/^[A-Za-z0-9_-]+$/.test(board)
      || !/^\d+$/.test(jobId)
    ) {
      return null;
    }

    const target = new URL(
      "https://job-boards.greenhouse.io/embed/job_app"
    );
    target.searchParams.set("for", board);
    target.searchParams.set("token", jobId);
    return target.href;
  }

  function greenhouseTarget(value) {
    try {
      const parsed = new URL(
        decodeUrlText(value),
        location.href
      );
      const host = parsed.hostname.toLowerCase();
      const path = parsed.pathname
        .split("/")
        .filter(Boolean);

      if (host === "boards-api.greenhouse.io") {
        const boardIndex = path.indexOf("boards");
        const jobsIndex = path.indexOf("jobs");

        if (
          boardIndex >= 0
          && jobsIndex === boardIndex + 2
        ) {
          return greenhouseEmbed(
            path[boardIndex + 1],
            path[jobsIndex + 1] || ""
          );
        }
      }

      if (!GREENHOUSE_HOSTS.has(host)) {
        return null;
      }

      if (host === "grnh.se") {
        return parsed.href;
      }

      if (
        path[0] === "embed"
        && path[1] === "job_app"
      ) {
        return greenhouseEmbed(
          parsed.searchParams.get("for") || "",
          parsed.searchParams.get("token") || ""
        );
      }

      const jobsIndex = path.indexOf("jobs");

      if (
        jobsIndex >= 1
        && /^\d+$/.test(path[jobsIndex + 1] || "")
      ) {
        return parsed.href;
      }
    } catch (error) {
      return null;
    }

    return null;
  }

  function directKnownTarget(value) {
    const greenhouse = greenhouseTarget(value);

    if (greenhouse) {
      return greenhouse;
    }

    try {
      const parsed = new URL(
        decodeUrlText(value),
        location.href
      );
      const host = parsed.hostname.toLowerCase();
      const path = parsed.pathname
        .split("/")
        .filter(Boolean);

      if (
        (host === "jobs.lever.co"
          || host === "jobs.eu.lever.co")
        && path.length >= 2
      ) {
        return parsed.href;
      }

      if (
        host === "jobs.ashbyhq.com"
        && path.length >= 2
      ) {
        return parsed.href;
      }

      const pathText = parsed.pathname.toLowerCase();
      const isResolverJob = (
        (
          (host === "himalayas.app"
            || host === "www.himalayas.app")
          && pathText.includes("/jobs/")
        )
        || (
          (host === "remotefirstjobs.com"
            || host === "www.remotefirstjobs.com")
          && pathText.includes("/jobs/")
        )
        || (
          (host === "japan-dev.com"
            || host === "www.japan-dev.com")
          && pathText.includes("/jobs/")
        )
        || (
          (host === "weworkremotely.com"
            || host === "www.weworkremotely.com")
          && pathText.includes("/remote-jobs/")
        )
        || (
          (host === "jooble.org"
            || host === "www.jooble.org")
          && pathText.includes("/away/")
        )
        || (
          (host === "remoteok.com"
            || host === "www.remoteok.com")
          && (
            pathText.includes("/remote-jobs/")
            || pathText.includes("/l/")
          )
        )
        || (
          (host === "jobicy.com"
            || host === "www.jobicy.com")
          && pathText.includes("/jobs/")
        )
        || (
          (host === "tokyodev.com"
            || host === "www.tokyodev.com")
          && pathText.includes("/c/")
        )
        || (
          (host === "themuse.com"
            || host === "www.themuse.com")
          && pathText.includes("/jobs/")
        )
        || (
          adzunaHost(host)
          && (
            pathText.includes("/land/ad/")
            || pathText.includes("/jobs/land/ad/")
          )
        )
      );

      if (isResolverJob) {
        return parsed.href;
      }
    } catch (error) {
      return null;
    }

    return null;
  }

  function greenhouseBoardTokens(values) {
    const tokens = [];

    for (const value of values) {
      const decoded = decodeUrlText(value);

      try {
        const parsed = new URL(decoded, location.href);
        const host = parsed.hostname.toLowerCase();
        const path = parsed.pathname
          .split("/")
          .filter(Boolean);

        for (const key of [
          "for",
          "gh_board",
          "board",
          "board_token",
        ]) {
          const token = parsed.searchParams.get(key);

          if (/^[A-Za-z0-9_-]+$/.test(token || "")) {
            tokens.push(token);
          }
        }

        if (host === "boards-api.greenhouse.io") {
          const boardIndex = path.indexOf("boards");

          if (boardIndex >= 0 && path[boardIndex + 1]) {
            tokens.push(path[boardIndex + 1]);
          }
        }
      } catch (error) {
        // Non-URL page data is inspected by the patterns below.
      }

      const patterns = [
        /["'](?:greenhouseBoard|greenhouse_board|boardToken|board_token|board)["']\s*:\s*["']([A-Za-z0-9_-]+)["']/gi,
        /boards\/([A-Za-z0-9_-]+)\/jobs/gi,
        /[?&]for=([A-Za-z0-9_-]+)/gi,
      ];

      for (const pattern of patterns) {
        let match = pattern.exec(decoded);

        while (match) {
          tokens.push(match[1]);
          match = pattern.exec(decoded);
        }
      }
    }

    return [...new Set(tokens)];
  }

  function greenhouseJobId(values) {
    for (const value of values) {
      const decoded = decodeUrlText(value);

      try {
        const parsed = new URL(decoded, location.href);
        const ghJobId = parsed.searchParams.get("gh_jid");

        if (/^\d+$/.test(ghJobId || "")) {
          return ghJobId;
        }

        const host = parsed.hostname.toLowerCase();
        const token = parsed.searchParams.get("token");

        if (
          GREENHOUSE_HOSTS.has(host)
          && /^\d+$/.test(token || "")
        ) {
          return token;
        }
      } catch (error) {
        // Raw script data is inspected below.
      }

      const match = decoded.match(
        /(?:gh_jid[=":]+|\/jobs\/)(\d{5,})/i
      );

      if (match) {
        return match[1];
      }
    }

    return "";
  }

  function pageCandidates({includeScripts = true} = {}) {
    const candidates = [];
    const elements = [
      ...document.querySelectorAll(
        "a[href], iframe[src], form[action], [data-apply-url], "
        + "[data-application-url], [data-job-url], [data-url]"
      ),
    ];

    for (const element of elements) {
      for (const attribute of [
        "href",
        "src",
        "action",
        "data-apply-url",
        "data-application-url",
        "data-job-url",
        "data-url",
      ]) {
        const value = element.getAttribute?.(attribute);

        if (value) {
          candidates.push(value);
        }
      }
    }

    if (includeScripts) {
      let remainingCharacters = MAX_SCRIPT_SCAN_CHARACTERS;

      for (const script of [...(document.scripts || [])]) {
        const source = script.getAttribute?.("src");

        if (source) {
          candidates.push(source);
        }

        if (remainingCharacters <= 0) {
          break;
        }

        const rawText = String(script.textContent || "");

        if (
          !/(?:greenhouse(?:\.io)?|boards-api\.greenhouse\.io|gh_jid|jobs(?:\.eu)?\.lever\.co|ashbyhq\.com)/i.test(
            rawText
          )
        ) {
          continue;
        }

        const text = rawText.slice(
          0,
          remainingCharacters
        );
        remainingCharacters -= text.length;
        candidates.push(text);
        candidates.push(...urlsFromText(text));
      }
    }

    candidates.push(location.href);
    return candidates;
  }

  function supportedTargetOnPage(values = null) {
    const candidates = Array.isArray(values)
      ? values
      : pageCandidates();

    for (const value of candidates) {
      const target = directKnownTarget(value);

      if (target) {
        return target;
      }
    }

    const jobId = greenhouseJobId(candidates);

    if (jobId) {
      const board = greenhouseBoardTokens(candidates)[0];
      const target = greenhouseEmbed(board || "", jobId);

      if (target) {
        return target;
      }
    }

    return null;
  }

  function hasAtsFingerprint(candidates = null) {
    const selectors = [
      "#grnhse_app",
      'form[action*="greenhouse.io"]',
      'input[name^="job_application["]',
      '[data-qa="btn-submit"]',
      'form[action*="lever.co"]',
      ".ashby-application-form-container",
      '[class*="ashby-application-form"]',
      'script[src*="ashbyhq.com"]',
    ];

    if (
      selectors.some((selector) =>
        document.querySelector?.(selector)
      )
    ) {
      return true;
    }

    const values = Array.isArray(candidates)
      ? candidates
      : pageCandidates();

    return values.some((value) =>
      /(?:greenhouse\.io|boards-api\.greenhouse\.io|[?&]gh_jid=\d+|jobs(?:\.eu)?\.lever\.co|ashbyhq\.com)/i.test(
        decodeUrlText(value)
      )
    );
  }

  function jobIdentity(task) {
    const job = task?.job || {};

    return {
      company: lower(job.company_name),
      title: lower(job.position_title),
    };
  }

  function pageHasJobIdentity(task) {
    const identity = jobIdentity(task);
    const title = lower(document.title);
    const text = pageText();

    if (
      identity.title.length >= 4
      && (
        title.includes(identity.title)
        || text.includes(identity.title)
      )
    ) {
      return true;
    }

    return (
      identity.company.length >= 4
      && identity.title.length >= 4
      && text.includes(identity.company)
      && identity.title
        .split(" ")
        .filter((part) => part.length >= 4)
        .slice(0, 3)
        .every((part) => text.includes(part))
    );
  }

  function jobSpecificUrl(value) {
    try {
      const parsed = new URL(value, location.href);
      const path = parsed.pathname.toLowerCase();
      const queryKeys = new Set([
        "gh_jid",
        "jobid",
        "job_id",
        "selectedjobid",
        "requisitionid",
        "reqid",
      ]);
      const hasJobQuery = [
        ...parsed.searchParams.entries(),
      ].some(([key, item]) => (
        queryKeys.has(key.toLowerCase())
        && normalize(item)
      ));

      if (hasJobQuery) {
        return true;
      }

      return (
        /\/(?:jobs?|positions?|openings?|vacancies?|requisitions?)\/[^/]+/.test(
          path
        )
        || /\/careers\/(?:jobs?\/)?[^/]+/.test(path)
      );
    } catch (error) {
      return false;
    }
  }

  function jobsIndexUrl(value) {
    try {
      const parsed = new URL(value, location.href);

      if (jobSpecificUrl(parsed.href)) {
        return false;
      }

      const path = parsed.pathname
        .toLowerCase()
        .replace(/\/+$/, "");

      if (
        [
          "",
          "/jobs",
          "/careers",
          "/openings",
          "/positions",
          "/search",
          "/job-search",
          "/en",
          "/en-us",
          "/us/en",
          "/us/en-us",
        ].includes(path)
      ) {
        return true;
      }

      return /^\/[a-z]{2}(?:-[a-z]{2})?\/(?:jobs|careers|search)$/.test(
        path
      );
    } catch (error) {
      return false;
    }
  }

  function looksLikeJobsIndex(task) {
    const identity = jobIdentity(task);

    return (
      identity.title.length >= 4
      && jobsIndexUrl(location.href)
      && !pageHasJobIdentity(task)
    );
  }

  function jobPageEvidence(task) {
    return (
      samePage(task.target_url, location.href)
      && (
        pageHasJobIdentity(task)
        || jobSpecificUrl(location.href)
      )
    );
  }

  function samePage(left, right) {
    try {
      const leftUrl = new URL(left);
      const rightUrl = new URL(right);
      leftUrl.hash = "";
      rightUrl.hash = "";
      return leftUrl.href === rightUrl.href;
    } catch (error) {
      return false;
    }
  }

  function applyControl(task, atsEvidence = false) {
    if (
      !atsEvidence
      || !jobPageEvidence(task)
    ) {
      return null;
    }

    const allowedText = new Set([
      "apply",
      "apply now",
      "apply for this job",
      "apply to this job",
      "continue to application",
      "start application",
    ]);
    const controls = [
      ...document.querySelectorAll(
        "a[href], button, [role=button], input[type=button]"
      ),
    ];

    return controls.find((element) => {
      const text = lower(
        element.innerText
        || element.textContent
        || element.value
        || element.getAttribute?.("aria-label")
        || element.getAttribute?.("title")
      );

      return (
        visible(element)
        && allowedText.has(text)
        && !element.closest?.("form")
      );
    }) || null;
  }

  function followApplyControl(control) {
    if (!control) {
      return false;
    }

    if (control.getAttribute?.("target") === "_blank") {
      control.setAttribute("target", "_self");
    }

    control.scrollIntoView?.({block: "center"});
    control.click();
    return true;
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
        "Jobfinitum could not close the employer-site resolver tab:",
        error
      );
    }
  }

  async function reportResolved(launch, resolvedUrl) {
    statusBox(
      "found a supported application system.",
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

  async function reportResult(
    launch,
    status,
    message,
    detail = {}
  ) {
    statusBox(message, "warning");
    await send({
      type: "jobfinitum-result",
      origin: launch.origin,
      token: launch.token,
      payload: {
        status,
        message,
        final_url: location.href,
        detail: {
          url: location.href,
          final_url: location.href,
          resolver: RESOLVER,
          ...detail,
        },
      },
    });

    if (status !== "waiting_verification") {
      clearLaunch();
      await closeCompletedAgentTab(launch);
    }
  }

  async function run() {
    if (usesDedicatedAgent()) {
      return;
    }

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
        return;
      }

      await waitForDocument();

      const started = Date.now();
      let deadline = started + FAST_SCAN_MS;
      let followedApply = false;
      let atsEvidence = false;
      let evidenceMessageShown = false;
      let indexDetectedAt = null;
      let scriptScans = 0;
      let nextScriptScanAt = started;

      while (
        Date.now() < deadline
        && Date.now() - started < MAX_SCAN_MS
      ) {
        const now = Date.now();
        const includeScripts = (
          scriptScans < 2
          && now >= nextScriptScanAt
        );
        const candidates = pageCandidates({
          includeScripts,
        });

        if (includeScripts) {
          scriptScans += 1;
          nextScriptScanAt = now + 750;
        }

        const target = supportedTargetOnPage(candidates);

        if (target) {
          await reportResolved(launch, target);
          return;
        }

        if (
          !atsEvidence
          && hasAtsFingerprint(candidates)
        ) {
          atsEvidence = true;
          deadline = Math.max(
            deadline,
            started + ATS_EVIDENCE_SCAN_MS
          );
        }

        if (atsEvidence && !evidenceMessageShown) {
          statusBox(
            "recognized a supported application-system fingerprint."
          );
          evidenceMessageShown = true;
        }

        if (visibleChallenge()) {
          await reportResult(
            launch,
            "waiting_verification",
            (
              "The employer page requires human verification before "
              + "Jobfinitum can inspect its application destination."
            ),
            {verification_required: true}
          );
          return;
        }

        if (signInRequired()) {
          await reportResult(
            launch,
            "waiting_sign_in",
            (
              "The employer page requires sign-in before it reveals "
              + "the application destination."
            ),
            {sign_in_required: true}
          );
          return;
        }

        if (postingClosed()) {
          await reportResult(
            launch,
            "posting_closed",
            "The employer site reports that this job is no longer available."
          );
          return;
        }

        if (looksLikeJobsIndex(task)) {
          indexDetectedAt = indexDetectedAt || now;

          if (now - indexDetectedAt >= INDEX_SETTLE_MS) {
            await reportResult(
              launch,
              "posting_closed",
              (
                "The employer site redirected this job to a general "
                + "careers page, so the original posting is no longer available."
              ),
              {closure_reason: "jobs_index_redirect"}
            );
            return;
          }
        } else {
          indexDetectedAt = null;
        }

        if (!followedApply) {
          const control = applyControl(
            task,
            atsEvidence
          );

          if (control) {
            followedApply = followApplyControl(control);
            deadline = Math.min(
              started + MAX_SCAN_MS,
              Math.max(
                deadline,
                now + AFTER_APPLY_SCAN_MS
              )
            );
            statusBox(
              "opened the employer's application destination."
            );
          }
        }

        await new Promise((resolve) =>
          setTimeout(resolve, POLL_INTERVAL_MS)
        );
      }

      await reportResult(
        launch,
        "needs_manual_destination",
        (
          "Jobfinitum inspected this employer page but did not find a "
          + "trustworthy destination for an installed Auto Apply adapter."
        )
      );
    } catch (error) {
      console.error(
        "Jobfinitum employer-site resolver failed:",
        error
      );

      try {
        await reportResult(
          launch,
          "needs_manual_destination",
          (
            "Jobfinitum could not safely resolve this employer's "
            + "application system."
          ),
          {error: String(error.message || error)}
        );
      } catch (reportError) {
        console.error(
          "Jobfinitum employer-site failure reporting also failed:",
          reportError
        );
      }
    }
  }

  run();
})();
