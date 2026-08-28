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
      || (
        "Open the matching Greenhouse application tab first, "
        + "then type in School again so Jobfinitum can read "
        + "Greenhouse's live school dropdown."
      ),
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

      if (
        Number.isInteger(resolverTabId)
        && resolverTabId !== tabId
      ) {
        try {
          await chrome.tabs.remove(tabId);
        } catch (error) {
          // The unsupported child may already be closed.
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
        return;
      }

      await saveHimalayasResolverSession(
        tab.id,
        openerSession
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
