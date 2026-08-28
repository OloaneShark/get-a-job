(() => {
  "use strict";

  const HIMALAYAS_HOSTS = new Set([
    "himalayas.app",
    "www.himalayas.app",
  ]);

  const LAUNCH_STORAGE_KEY =
    "jobfinitum_himalayas_launch_v1";

  const BATCH_RUNNER_NAME =
    "jobfinitum-auto-apply-runner";

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

  const normalize = (value) =>
    String(value || "").replace(/\s+/g, " ").trim();

  const lower = (value) =>
    normalize(value).toLowerCase();

  function statusBox(message, kind = "working") {
    let box = document.getElementById(
      "jobfinitum-agent-status"
    );

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
        borderRadius: "10px",
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

    const selected =
      colors[kind] || colors.working;

    box.style.background = selected[0];
    box.style.color = selected[1];
    box.textContent =
      `Jobfinitum Browser Agent — ${message}`;
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

          if (!response || !response.ok) {
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

  function parseLaunch() {
    const params = new URLSearchParams(
      String(location.hash || "")
        .replace(/^#/, "")
    );

    const token =
      params.get("jobfinitum_agent");

    const origin =
      params.get("jobfinitum_origin");
    const batch = (
      params.get("jobfinitum_batch")
      === "1"
      || isBatchRunner()
    );

    if (token && origin) {
      const launch = {
        token,
        origin,
        batch,
      };

      if (batch) {
        window.name = BATCH_RUNNER_NAME;
      }

      try {
        window.sessionStorage.setItem(
          LAUNCH_STORAGE_KEY,
          JSON.stringify(launch)
        );
      } catch (error) {
        console.warn(
          "Jobfinitum could not persist Himalayas launch state:",
          error
        );
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
        window.sessionStorage.getItem(
          LAUNCH_STORAGE_KEY
        ) || "null"
      );

      if (
        saved?.token
        && saved?.origin
      ) {
        if (saved.batch === true) {
          window.name = BATCH_RUNNER_NAME;
        }

        return {
          token:
            String(saved.token),
          origin:
            String(saved.origin),
          batch:
            saved.batch === true,
        };
      }
    } catch (error) {
      console.warn(
        "Jobfinitum could not restore Himalayas launch state:",
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
      // Cleanup failure must not block destination reporting.
    }
  }

  function isExternalUrl(value) {
    try {
      const parsed =
        new URL(
          String(value || ""),
          location.href
        );

      const host =
        parsed.hostname
          .toLowerCase();

      const blockedHosts =
        new Set([
          "127.0.0.1",
          "localhost",
          "jobfinitum.com",
          "www.jobfinitum.com",
        ]);

      return (
        ["http:", "https:"].includes(
          parsed.protocol
        )
        && host
        && !HIMALAYAS_HOSTS.has(host)
        && !blockedHosts.has(host)
      );
    } catch (error) {
      return false;
    }
  }

  function externalApplyLink() {
    const candidates = [
      ...document.querySelectorAll(
        "a[href]"
      ),
    ]
      .map((anchor) => {
        if (!isExternalUrl(anchor.href)) {
          return null;
        }

        const text =
          lower(
            anchor.innerText
            || anchor.textContent
            || anchor.getAttribute("aria-label")
          );

        let score = 0;

        if (
          text === "apply"
          || text === "apply now"
          || text.startsWith("apply ")
        ) {
          score += 100;
        }

        if (
          lower(anchor.href).includes("apply")
        ) {
          score += 30;
        }

        return {
          href: anchor.href,
          score,
        };
      })
      .filter(Boolean)
      .sort(
        (left, right) =>
          right.score - left.score
      );

    if (
      !candidates.length
      || candidates[0].score <= 0
    ) {
      return null;
    }

    return candidates[0].href;
  }

  function applyControl() {
    const candidates = [
      ...document.querySelectorAll(
        'a, button, [role="button"]'
      ),
    ]
      .map((node) => {
        const text =
          lower(
            node.innerText
            || node.textContent
            || node.value
            || node.getAttribute("aria-label")
            || node.getAttribute("title")
          );

        let score = 0;

        if (text === "apply now") {
          score = 140;
        } else if (text === "apply") {
          score = 130;
        } else if (
          text === "continue to application"
          || text === "continue to apply"
          || text === "apply on company site"
          || text === "apply on company website"
          || text === "go to application"
        ) {
          score = 120;
        } else if (text.startsWith("apply ")) {
          score = 100;
        } else if (
          text.includes("apply now")
          || text.includes("continue to apply")
        ) {
          score = 80;
        }

        if (
          !score
          || node.disabled
          || lower(
            node.getAttribute?.(
              "aria-disabled"
            )
          ) === "true"
        ) {
          return null;
        }

        const rect =
          node.getBoundingClientRect();

        const style =
          getComputedStyle(node);

        if (
          rect.width <= 0
          || rect.height <= 0
          || style.display === "none"
          || style.visibility === "hidden"
        ) {
          return null;
        }

        if (
          node.tagName === "A"
          && isExternalUrl(
            node.href
          )
        ) {
          score += 100;
        }

        return {
          node,
          score,
        };
      })
      .filter(Boolean)
      .sort(
        (left, right) =>
          right.score - left.score
      );

    return candidates[0]?.node || null;
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
        "jobfinitum-himalayas-resolved",
      origin:
        launch.origin,
      token:
        launch.token,
      url:
        resolvedUrl,
      batch:
        launch.batch === true,
    });

    clearLaunch();
  }

  async function scanForTarget(launch) {
    const resolvedUrl =
      externalApplyLink();

    if (!resolvedUrl) {
      return false;
    }

    await reportResolved(
      launch,
      resolvedUrl
    );

    return true;
  }

  async function activateApplyControl(
    control
  ) {
    if (!control) {
      return false;
    }

    try {
      control.scrollIntoView({
        block: "center",
        inline: "center",
      });
    } catch (error) {
      // Continue with direct activation.
    }

    try {
      control.focus({
        preventScroll: true,
      });
    } catch (error) {
      // Focus is optional.
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

  async function run() {
    const launch =
      parseLaunch();

    if (!launch) {
      return;
    }

    try {
      if (isBatchRunner()) {
        await send({
          type:
            "jobfinitum-batch-register",
          origin:
            launch.origin,
        });
      }

      statusBox(
        "resolving the real employer application URL."
      );

      const taskResponse =
        await send({
          type:
            "jobfinitum-task",
          origin:
            launch.origin,
          token:
            launch.token,
        });

      const task =
        taskResponse.task || {};

      if (
        task.adapter
        !== "himalayas_resolver"
      ) {
        throw new Error(
          "This is not a Himalayas resolver task."
        );
      }

      await send({
        type:
          "jobfinitum-himalayas-watch",
        origin:
          launch.origin,
        token:
          launch.token,
        batch:
          launch.batch === true,
      });

      const started =
        Date.now();

      const clickedControls =
        new WeakSet();

      let lastWaitingUpdate = 0;

      while (
        Date.now() - started
        < 25000
      ) {
        if (
          await scanForTarget(
            launch
          )
        ) {
          return;
        }

        const control =
          applyControl();

        if (control) {
          if (
            !clickedControls.has(
              control
            )
          ) {
            clickedControls.add(
              control
            );

            statusBox(
              "opening Himalayas Apply to resolve the employer target."
            );

            await activateApplyControl(
              control
            );
          }
        } else if (
          Date.now() - lastWaitingUpdate
          >= 3000
        ) {
          lastWaitingUpdate =
            Date.now();

          statusBox(
            "waiting for Himalayas to load its Apply control."
          );
        }

        await new Promise(
          (resolve) => setTimeout(
            resolve,
            400
          )
        );
      }

      statusBox(
        "Himalayas did not expose an employer Apply destination. This job needs a manual destination check.",
        "warning"
      );

      await send({
        type:
          "jobfinitum-result",
        origin:
          launch.origin,
        token:
          launch.token,
        payload: {
          status:
            "needs_manual_destination",
          message:
            "Himalayas did not expose the employer application destination automatically. Open the saved Himalayas listing from Manual Apply to continue.",
          detail: {
            url:
              location.href,
            resolver:
              "himalayas_browser_agent",
          },
        },
      });

      clearLaunch();
    } catch (error) {
      console.error(
        "Jobfinitum Himalayas resolver failed:",
        error
      );

      statusBox(
        String(
          error.message || error
        ),
        "error"
      );

      try {
        await send({
          type:
            "jobfinitum-result",
          origin:
            launch.origin,
          token:
            launch.token,
          payload: {
            status:
              "needs_manual_destination",
            message:
              "Himalayas could not resolve this employer application automatically. Open the saved listing from Manual Apply to continue.",
            detail: {
              url:
                location.href,
              resolver:
                "himalayas_browser_agent",
              error:
                String(
                  error.message
                  || error
                ),
            },
          },
        });
      } catch (reportError) {
        console.error(
          "Jobfinitum Himalayas failure report also failed:",
          reportError
        );
      }

      clearLaunch();
    }
  }

  run();
})();
