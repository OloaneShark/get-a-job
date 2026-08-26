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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) {
    return false;
  }

  (async () => {
    const origin = normalizeOrigin(message.origin);

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

    if (message.type === "jobfinitum-close-agent-tab") {
      const tabId = sender?.tab?.id;

      if (typeof tabId !== "number") {
        throw new Error(
          "Chrome Agent could not identify its tab."
        );
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
