const ALLOWED_ORIGINS = [
  /^http:\/\/127\.0\.0\.1(?::\d+)?$/,
  /^http:\/\/localhost(?::\d+)?$/,
  /^https:\/\/jobfinitum\.com$/,
  /^https:\/\/www\.jobfinitum\.com$/,
];

function normalizeOrigin(value) {
  const parsed = new URL(String(value || ""));
  if (!ALLOWED_ORIGINS.some((pattern) => pattern.test(parsed.origin))) {
    throw new Error("Jobfinitum bridge origin is not allowed.");
  }
  return parsed.origin;
}


function normalizeGreenhouseSchemaUrl(value) {
  const parsed = new URL(String(value || ""));

  if (
    parsed.protocol !== "https:"
    || parsed.hostname !== "boards-api.greenhouse.io"
    || !/^\/v1\/boards\/[^/]+\/jobs\/\d+$/.test(parsed.pathname)
  ) {
    throw new Error(
      "Greenhouse schema URL is not allowed."
    );
  }

  parsed.search = "";
  parsed.searchParams.set(
    "questions",
    "true"
  );

  return parsed.href;
}

async function notifyJobfinitumTabs(result) {
  let tabs = [];

  try {
    tabs = await chrome.tabs.query({});
  } catch (error) {
    console.warn(
      "Jobfinitum could not query browser tabs:",
      error
    );
    return;
  }

  for (const tab of tabs) {
    if (typeof tab.id !== "number") {
      continue;
    }

    try {
      await chrome.tabs.sendMessage(
        tab.id,
        {
          type: "jobfinitum-agent-result",
          result: result || {},
        }
      );
    } catch (error) {
      // Most tabs do not have the Jobfinitum site bridge.
    }
  }
}


const JOBFINITUM_GREENHOUSE_SCHOOL_HOSTS =
  new Set([
    "boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
  ]);


async function jobfinitumSearchOpenGreenhouseSchoolTabs(
  rawQuery,
  rawGreenhouseUrl = ""
) {
  const query =
    String(
      rawQuery || ""
    ).trim();

  if (
    query.length < 2
  ) {
    return {
      ok: true,
      schools: [],
    };
  }

  let greenhouseUrl = "";

  if (
    String(
      rawGreenhouseUrl || ""
    ).trim()
  ) {
    try {
      const parsed =
        new URL(
          String(
            rawGreenhouseUrl
          )
        );

      const host =
        parsed.hostname
          .toLowerCase();

      if (
        parsed.protocol !== "https:"
        || !JOBFINITUM_GREENHOUSE_SCHOOL_HOSTS
            .has(host)
      ) {
        throw new Error(
          "School lookup URL is not a supported Greenhouse application URL."
        );
      }

      parsed.hash = "";
      greenhouseUrl =
        parsed.href;
    } catch (error) {
      return {
        ok: false,
        schools: [],
        error:
          String(
            error?.message
            || error
          ),
      };
    }
  }

  async function searchTab(
    tabId,
    attempts = 1
  ) {
    let lastError = "";

    for (
      let attempt = 0;
      attempt < attempts;
      attempt += 1
    ) {
      try {
        const response =
          await chrome.tabs.sendMessage(
            tabId,
            {
              type:
                "jobfinitum-greenhouse-school-search",
              query,
            }
          );

        if (
          response?.ok
        ) {
          return {
            ok: true,
            schools:
              Array.isArray(
                response.schools
              )
                ? response.schools
                : [],
            tab_id:
              tabId,
            url:
              response.url
              || "",
          };
        }

        if (
          response?.error
        ) {
          lastError =
            String(
              response.error
            );
        }
      } catch (error) {
        lastError =
          String(
            error?.message
            || error
          );
      }

      if (
        attempt + 1 < attempts
      ) {
        await new Promise(
          (resolve) =>
            setTimeout(
              resolve,
              180
            )
        );
      }
    }

    return {
      ok: false,
      schools: [],
      error:
        lastError,
    };
  }

  // First reuse an already-open Greenhouse application tab.
  const tabs =
    await chrome.tabs.query({});

  const candidates =
    tabs
      .filter(
        (tab) => {
          if (
            typeof tab.id
            !== "number"
            || !tab.url
          ) {
            return false;
          }

          try {
            const parsed =
              new URL(
                tab.url
              );

            return (
              JOBFINITUM_GREENHOUSE_SCHOOL_HOSTS
                .has(
                  parsed.hostname.toLowerCase()
                )
            );
          } catch (error) {
            return false;
          }
        }
      )
      .sort(
        (left, right) => {
          // Prefer the exact candidate application URL.
          const leftExact =
            greenhouseUrl
            && left.url
            && String(left.url)
              .split("#")[0]
              === greenhouseUrl;

          const rightExact =
            greenhouseUrl
            && right.url
            && String(right.url)
              .split("#")[0]
              === greenhouseUrl;

          if (
            leftExact !== rightExact
          ) {
            return (
              Number(rightExact)
              - Number(leftExact)
            );
          }

          const activeDifference =
            Number(
              Boolean(
                right.active
              )
            )
            - Number(
                Boolean(
                  left.active
                )
              );

          if (
            activeDifference
          ) {
            return activeDifference;
          }

          return (
            Number(
              right.lastAccessed || 0
            )
            - Number(
                left.lastAccessed || 0
              )
          );
        }
      );

  let lastError = "";

  for (
    const tab
    of candidates
  ) {
    const result =
      await searchTab(
        tab.id,
        2
      );

    if (
      result.ok
    ) {
      return result;
    }

    if (
      result.error
    ) {
      lastError =
        result.error;
    }
  }

  return {
    ok: false,
    schools: [],
    error:
      lastError
      || "School lookup is unavailable.",
  };
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {cache: "no-store", ...options});
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(
      payload.error
      || payload.message
      || `HTTP ${response.status}`
    );
  }
  return payload;
}

function bufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length))
    );
  }
  return btoa(binary);
}

const HIMALAYAS_RESOLVER_PREFIX =
  "jobfinitum_himalayas_resolver_";

const BATCH_RUNNER_STORAGE_KEY =
  "jobfinitum_batch_runner_v1";

const CHAINED_AGENT_LAUNCH_PREFIX =
  "jobfinitum_chained_agent_launch_v1_";

const CHAINED_AGENT_LAUNCH_MAX_AGE_MS =
  2 * 60 * 1000;

function chainedAgentLaunchKey(tabId) {
  return (
    CHAINED_AGENT_LAUNCH_PREFIX
    + String(tabId)
  );
}

async function saveChainedAgentLaunch(
  tabId,
  session
) {
  await chrome.storage.session.set({
    [chainedAgentLaunchKey(tabId)]: {
      token: String(session.token || ""),
      origin: normalizeOrigin(
        session.origin
      ),
      batch: session.batch === true,
      createdAt: Date.now(),
    },
  });
}

async function clearChainedAgentLaunch(
  tabId
) {
  if (typeof tabId !== "number") {
    return;
  }

  await chrome.storage.session.remove(
    chainedAgentLaunchKey(tabId)
  );
}

async function takeChainedAgentLaunch(
  tabId
) {
  if (typeof tabId !== "number") {
    return null;
  }

  const key =
    chainedAgentLaunchKey(tabId);

  const values =
    await chrome.storage.session.get(key);

  const launch = values[key] || null;
  const age = Date.now() - Number(
    launch?.createdAt || 0
  );

  if (
    !launch?.token
    || !launch?.origin
    || age < 0
    || age > CHAINED_AGENT_LAUNCH_MAX_AGE_MS
  ) {
    await chrome.storage.session.remove(key);
    return null;
  }

  return {
    token: String(launch.token),
    origin: normalizeOrigin(
      launch.origin
    ),
    batch: launch.batch === true,
  };
}

async function saveBatchRunner(
  tabId,
  origin
) {
  await chrome.storage.session.set({
    [BATCH_RUNNER_STORAGE_KEY]: {
      tabId,
      origin,
    },
  });
}

async function positionBatchRunnerNextToJobfinitum(
  runnerTab,
  origin
) {
  if (
    typeof runnerTab?.id !== "number"
    || typeof runnerTab?.windowId !== "number"
  ) {
    return false;
  }

  const tabs = await chrome.tabs.query({
    windowId: runnerTab.windowId,
  });

  const isJobfinitumTab = (tab) => {
    if (
      tab.id === runnerTab.id
      || !tab.url
    ) {
      return false;
    }

    try {
      return new URL(tab.url).origin === origin;
    } catch (error) {
      return false;
    }
  };

  let anchor = null;

  if (
    typeof runnerTab.openerTabId
    === "number"
  ) {
    anchor = tabs.find(
      (tab) => (
        tab.id === runnerTab.openerTabId
        && isJobfinitumTab(tab)
      )
    );
  }

  if (!anchor) {
    anchor = tabs.find((tab) => {
      if (!isJobfinitumTab(tab)) {
        return false;
      }

      try {
        return new URL(tab.url).pathname
          .startsWith("/auto-apply");
      } catch (error) {
        return false;
      }
    });
  }

  if (!anchor) {
    anchor = tabs.find(isJobfinitumTab);
  }

  if (!anchor) {
    return false;
  }

  await chrome.tabs.move(
    runnerTab.id,
    {
      index: anchor.index + 1,
    }
  );

  return true;
}

async function getBatchRunner() {
  const values =
    await chrome.storage.session.get(
      BATCH_RUNNER_STORAGE_KEY
    );

  return (
    values[BATCH_RUNNER_STORAGE_KEY]
    || null
  );
}

async function clearBatchRunner() {
  await chrome.storage.session.remove(
    BATCH_RUNNER_STORAGE_KEY
  );
}

async function closeBatchRunner(origin) {
  const runner =
    await getBatchRunner();

  if (
    !runner
    || runner.origin !== origin
  ) {
    return false;
  }

  await clearBatchRunner();
  await clearChainedAgentLaunch(
    runner.tabId
  );

  try {
    await chrome.tabs.remove(
      runner.tabId
    );
  } catch (error) {
    // It may already have been closed by the queue page.
  }

  return true;
}

function himalayasResolverKey(tabId) {
  return (
    HIMALAYAS_RESOLVER_PREFIX
    + String(tabId)
  );
}

async function saveHimalayasResolverSession(
  tabId,
  session
) {
  await chrome.storage.session.set({
    [himalayasResolverKey(tabId)]:
      session,
  });
}

async function getHimalayasResolverSession(
  tabId
) {
  const key =
    himalayasResolverKey(tabId);

  const values =
    await chrome.storage.session.get(
      key
    );

  return values[key] || null;
}

async function deleteHimalayasResolverSession(
  tabId
) {
  await chrome.storage.session.remove(
    himalayasResolverKey(tabId)
  );
}

function externalHimalayasTarget(
  value,
  jobfinitumOrigin = ""
) {
  const parsed =
    new URL(
      String(value || "")
    );

  if (
    !["http:", "https:"].includes(
      parsed.protocol
    )
  ) {
    throw new Error(
      "Resolved application URL must use HTTP or HTTPS."
    );
  }

  const host =
    parsed.hostname.toLowerCase();

  const blockedHosts =
    new Set([
      "himalayas.app",
      "www.himalayas.app",
      "127.0.0.1",
      "localhost",
      "jobfinitum.com",
      "www.jobfinitum.com",
    ]);

  let normalizedJobfinitumOrigin = "";

  try {
    normalizedJobfinitumOrigin =
      jobfinitumOrigin
        ? normalizeOrigin(
            jobfinitumOrigin
          )
        : "";
  } catch (error) {
    normalizedJobfinitumOrigin = "";
  }

  if (
    !host
    || blockedHosts.has(host)
    || (
      normalizedJobfinitumOrigin
      && parsed.origin === normalizedJobfinitumOrigin
    )
  ) {
    throw new Error(
      "Resolved application URL is not an external employer target."
    );
  }

  return parsed.href;
}

function chainedAgentUrl(
  resolvedUrl,
  session
) {
  const parsed =
    new URL(
      resolvedUrl
    );

  const launchParams = {
      jobfinitum_agent:
        String(
          session.token || ""
        ),
      jobfinitum_origin:
        String(
          session.origin || ""
        ),
    };

  if (session.batch === true) {
    launchParams.jobfinitum_batch = "1";
  }

  parsed.hash =
    new URLSearchParams(
      launchParams
    ).toString();

  return parsed.href;
}

async function resolveHimalayasTargetOnce(
  tabId,
  value,
  session = null
) {
  const currentSession =
    session
    || await getHimalayasResolverSession(
      tabId
    );

  if (!currentSession) {
    return false;
  }

  const resolvedUrl =
    externalHimalayasTarget(
      value,
      currentSession.origin
    );

  const origin =
    normalizeOrigin(
      currentSession.origin
    );

  const token =
    encodeURIComponent(
      String(
        currentSession.token || ""
      )
    );

  const result =
    await fetchJson(
      `${origin}/api/chrome-agent/result/${token}`,
      {
        method: "POST",
        headers: {
          "Content-Type":
            "application/json",
        },
        body: JSON.stringify({
          status:
            "resolved_application_target",
          resolved_url:
            resolvedUrl,
          detail: {
            resolver:
              "himalayas_browser_agent",
          },
        }),
      }
    );

  await notifyJobfinitumTabs(
    result
  );

  await deleteHimalayasResolverSession(
    tabId
  );

  if (
    result.continue_in_chrome_agent
  ) {
    const resolverTabId = Number(
      currentSession.resolverTabId
    );

    if (currentSession.batch === true) {
      // Transfer batch ownership before removing the listing
      // tab, so Stop Auto Apply always targets the live tab.
      await saveBatchRunner(
        tabId,
        origin
      );
    }

    if (
      Number.isInteger(resolverTabId)
      && resolverTabId !== tabId
    ) {
      await deleteHimalayasResolverSession(
        resolverTabId
      );

      try {
        await chrome.tabs.remove(
          resolverTabId
        );
      } catch (error) {
        console.warn(
          "Jobfinitum could not close the completed Himalayas resolver tab:",
          error
        );
      }
    }

    await saveChainedAgentLaunch(
      tabId,
      currentSession
    );

    await chrome.tabs.update(
      tabId,
      {
        url:
          chainedAgentUrl(
            result.resolved_url
            || resolvedUrl,
            currentSession
          ),
      }
    );
  } else if (
    result.manual_application
    && result.resolved_url
  ) {
    if (currentSession.batch === true) {
      const resolverTabId = Number(
        currentSession.resolverTabId
      );

      const tabsToClose = [tabId];

      if (Number.isInteger(resolverTabId)) {
        await deleteHimalayasResolverSession(
          resolverTabId
        );

        if (resolverTabId !== tabId) {
          tabsToClose.push(resolverTabId);
        }
      }

      for (const closingTabId of tabsToClose) {
        try {
          await chrome.tabs.remove(
            closingTabId
          );
        } catch (error) {
          // A completed resolver tab may already be closed.
        }
      }

      return true;
    }

    const resolverTabId = Number(
      currentSession.resolverTabId
    );

    if (
      Number.isInteger(resolverTabId)
      && resolverTabId !== tabId
    ) {
      await deleteHimalayasResolverSession(
        resolverTabId
      );

      try {
        await chrome.tabs.remove(
          resolverTabId
        );
      } catch (error) {
        console.warn(
          "Jobfinitum could not close the completed Himalayas resolver tab:",
          error
        );
      }
    }

    await chrome.tabs.update(
      tabId,
      {
        url:
          String(
            result.resolved_url
          ),
      }
    );
  }

  return true;
}


const HIMALAYAS_RESOLUTIONS_IN_FLIGHT =
  new Map();


async function resolveHimalayasTarget(
  tabId,
  value,
  session = null
) {
  const existing =
    HIMALAYAS_RESOLUTIONS_IN_FLIGHT.get(
      tabId
    );

  if (existing) {
    return existing;
  }

  const resolution =
    resolveHimalayasTargetOnce(
      tabId,
      value,
      session
    );

  HIMALAYAS_RESOLUTIONS_IN_FLIGHT.set(
    tabId,
    resolution
  );

  try {
    return await resolution;
  } finally {
    if (
      HIMALAYAS_RESOLUTIONS_IN_FLIGHT.get(
        tabId
      ) === resolution
    ) {
      HIMALAYAS_RESOLUTIONS_IN_FLIGHT.delete(
        tabId
      );
    }
  }
}


chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) {
    return false;
  }

  (async () => {
    if (
      message.type
      === "jobfinitum-restore-launch"
    ) {
      const launch =
        await takeChainedAgentLaunch(
          sender?.tab?.id
        );

      sendResponse({
        ok: true,
        launch,
      });
      return;
    }

    const origin = normalizeOrigin(message.origin);

    if (
      message.type
      === "jobfinitum-batch-register"
    ) {
      const tabId = sender?.tab?.id;

      if (typeof tabId !== "number") {
        throw new Error(
          "Chrome Agent could not identify the batch runner tab."
        );
      }

      await saveBatchRunner(
        tabId,
        origin
      );

      try {
        await positionBatchRunnerNextToJobfinitum(
          sender.tab,
          origin
        );
      } catch (error) {
        console.warn(
          "Jobfinitum could not position the Auto Apply runner tab:",
          error
        );
      }

      sendResponse({ok: true});
      return;
    }

    if (
      message.type
      === "jobfinitum-batch-control"
    ) {
      if (message.action !== "stop") {
        throw new Error(
          "Unknown Auto Apply batch action."
        );
      }

      await closeBatchRunner(origin);
      sendResponse({ok: true});
      return;
    }

    if (message.type === "jobfinitum-task") {
      const token = encodeURIComponent(String(message.token || ""));
      const task = await fetchJson(
        `${origin}/api/chrome-agent/task/${token}`
      );

      await clearChainedAgentLaunch(
        sender?.tab?.id
      );

      await notifyJobfinitumTabs({
        candidate_id:
          task.candidate_id,
        status:
          "Agent Running",
        adapter:
          task.adapter,
        agent_version:
          chrome.runtime.getManifest().version,
      });

      sendResponse({ok: true, task});
      return;
    }

    if (
      message.type
      === "jobfinitum-school-search"
    ) {
      const result =
        await jobfinitumSearchOpenGreenhouseSchoolTabs(
          message.query,
          message.greenhouse_url
        );

      sendResponse(
        result
      );

      return;
    }

    if (
      message.type
      === "jobfinitum-greenhouse-schema"
    ) {
      const schemaUrl =
        normalizeGreenhouseSchemaUrl(
          message.url
        );

      const schema =
        await fetchJson(
          schemaUrl
        );

      sendResponse({
        ok: true,
        schema,
      });

      return;
    }

    if (message.type === "jobfinitum-resume") {
      const resumeUrl = new URL(message.url, origin);
      if (resumeUrl.origin !== origin) {
        throw new Error("Resume URL origin mismatch.");
      }

      const response = await fetch(resumeUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`Resume fetch failed: HTTP ${response.status}`);
      }

      sendResponse({
        ok: true,
        base64: bufferToBase64(await response.arrayBuffer()),
        contentType: (
          response.headers.get("content-type")
          || "application/octet-stream"
        ),
      });
      return;
    }

    if (message.type === "jobfinitum-result") {
      const token = encodeURIComponent(String(message.token || ""));
      const result = await fetchJson(
        `${origin}/api/chrome-agent/result/${token}`,
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(message.payload || {}),
        }
      );

      await notifyJobfinitumTabs(
        result
      );

      const resultStatus = String(
        message.payload?.status || ""
      ).toLowerCase();

      const senderTabId = sender?.tab?.id;

      if (
        typeof senderTabId === "number"
        && [
          "needs_manual_destination",
          "posting_closed",
        ].includes(resultStatus)
      ) {
        const resolverSession =
          await getHimalayasResolverSession(
            senderTabId
          );

        await deleteHimalayasResolverSession(
          senderTabId
        );

        const resolverTabId = Number(
          resolverSession?.resolverTabId
        );

        if (
          Number.isInteger(resolverTabId)
          && resolverTabId !== senderTabId
        ) {
          await deleteHimalayasResolverSession(
            resolverTabId
          );

          try {
            await chrome.tabs.remove(
              resolverTabId
            );
          } catch (error) {
            // The listing tab may already be closed.
          }
        }
      }

      sendResponse({ok: true, result});
      return;
    }

    if (
      message.type
      === "jobfinitum-himalayas-watch"
    ) {
      const tabId =
        sender?.tab?.id;

      if (
        typeof tabId
        !== "number"
      ) {
        throw new Error(
          "Himalayas resolver could not identify its tab."
        );
      }

      await saveHimalayasResolverSession(
        tabId,
        {
          token:
            String(
              message.token || ""
            ),
          origin,
          batch:
            message.batch === true,
          resolverTabId:
            tabId,
        }
      );

      sendResponse({
        ok: true,
      });

      return;
    }

    if (
      message.type
      === "jobfinitum-himalayas-resolved"
    ) {
      const tabId =
        sender?.tab?.id;

      if (
        typeof tabId
        !== "number"
      ) {
        throw new Error(
          "Himalayas resolver could not identify its tab."
        );
      }

      await resolveHimalayasTarget(
        tabId,
        message.url,
        {
          token:
            String(
              message.token || ""
            ),
          origin,
          batch:
            message.batch === true,
          resolverTabId:
            tabId,
        }
      );

      sendResponse({
        ok: true,
      });

      return;
    }

    if (message.type === "jobfinitum-close-agent-tab") {
      const tabId = sender?.tab?.id;

      if (typeof tabId !== "number") {
        throw new Error(
          "Chrome Agent could not identify its tab."
        );
      }

      const runner =
        await getBatchRunner();

      if (
        runner?.tabId === tabId
        && runner.origin === origin
      ) {
        sendResponse({ok: true});

        setTimeout(() => {
          const waitingUrl = new URL(
            "/browser-agent",
            origin
          );
          waitingUrl.searchParams.set(
            "batch_wait",
            "1"
          );

          chrome.tabs.update(
            tabId,
            {url: waitingUrl.href}
          ).catch((error) => {
            console.warn(
              "Jobfinitum could not return the Agent tab to its waiting page:",
              error
            );
          });
        }, 150);

        return;
      }

      sendResponse({ok: true});

      setTimeout(() => {
        chrome.tabs.remove(tabId).catch(
          (error) => {
            console.warn(
              "Jobfinitum could not close the completed Agent tab:",
              error
            );
          }
        );
      }, 150);

      return;
    }

    throw new Error("Unknown Jobfinitum Chrome Agent message.");
  })().catch((error) => {
    sendResponse({
      ok: false,
      error: String(error.message || error),
    });
  });

  return true;
});


chrome.tabs.onCreated.addListener(
  async (tab) => {
    try {
      if (
        typeof tab.id
        !== "number"
        || typeof tab.openerTabId
        !== "number"
      ) {
        return;
      }

      const openerSession =
        await getHimalayasResolverSession(
          tab.openerTabId
        );

      if (!openerSession) {
        let openerOrigin = "";

        try {
          const openerTab =
            await chrome.tabs.get(
              tab.openerTabId
            );

          openerOrigin = normalizeOrigin(
            openerTab.url
          );
        } catch (error) {
          return;
        }

        setTimeout(
          async () => {
            try {
              const currentTab =
                await chrome.tabs.get(
                  tab.id
                );

              const currentUrl = String(
                currentTab.url || ""
              );

              if (
                !currentUrl
                || currentUrl === "about:blank"
              ) {
                const runner =
                  await getBatchRunner();

                if (
                  runner?.tabId === tab.id
                  && runner.origin === openerOrigin
                ) {
                  await clearBatchRunner();
                }

                await chrome.tabs.remove(
                  tab.id
                );
              }
            } catch (error) {
              // The child tab may have navigated or closed already.
            }
          },
          12000
        );

        return;
      }

      await saveHimalayasResolverSession(
        tab.id,
        openerSession
      );

      setTimeout(
        async () => {
          try {
            const session =
              await getHimalayasResolverSession(
                tab.id
              );

            if (!session) {
              return;
            }

            const currentTab =
              await chrome.tabs.get(
                tab.id
              );

            const currentUrl = String(
              currentTab.url || ""
            );

            if (
              tab.id !== Number(
                session.resolverTabId
              )
              && (
                !currentUrl
                || currentUrl === "about:blank"
              )
            ) {
              await deleteHimalayasResolverSession(
                tab.id
              );

              await chrome.tabs.remove(
                tab.id
              );
            }
          } catch (error) {
            // The child tab may have navigated or closed already.
          }
        },
        12000
      );
    } catch (error) {
      console.warn(
        "Jobfinitum could not track Himalayas child tab:",
        error
      );
    }
  }
);
chrome.tabs.onUpdated.addListener(
  async (
    tabId,
    changeInfo,
    tab
  ) => {
    if (!changeInfo.url) {
      return;
    }

    try {
      let session =
        await getHimalayasResolverSession(
          tabId
        );

      if (
        !session
        && typeof tab.openerTabId
        === "number"
      ) {
        session =
          await getHimalayasResolverSession(
            tab.openerTabId
          );

        if (session) {
          await saveHimalayasResolverSession(
            tabId,
            session
          );
        }
      }

      if (!session) {
        return;
      }

      const parsed =
        new URL(
          changeInfo.url
        );

      if (
        parsed.origin
        === normalizeOrigin(
          session.origin
        )
      ) {
        await deleteHimalayasResolverSession(
          tabId
        );

        return;
      }

      const host =
        parsed.hostname.toLowerCase();

      if (
        host === "himalayas.app"
        || host === "www.himalayas.app"
      ) {
        return;
      }

      if (
        !["http:", "https:"].includes(
          parsed.protocol
        )
      ) {
        return;
      }

      await new Promise(
        (resolve) => setTimeout(
          resolve,
          900
        )
      );

      const settledTab =
        await chrome.tabs.get(
          tabId
        );

      const settledUrl =
        String(
          settledTab.url
          || ""
        );

      if (!settledUrl) {
        return;
      }

      try {
        externalHimalayasTarget(
          settledUrl,
          session.origin
        );
      } catch (error) {
        await deleteHimalayasResolverSession(
          tabId
        );

        return;
      }

      await resolveHimalayasTarget(
        tabId,
        settledUrl,
        session
      );
    } catch (error) {
      console.warn(
        "Jobfinitum Himalayas navigation resolver failed:",
        error
      );
    }
  }
);
