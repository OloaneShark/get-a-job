(() => {
  "use strict";

  const SOURCE = "jobfinitum-chrome-agent";
  const version = chrome.runtime.getManifest().version;

  function announceReady() {
    try {
      document.documentElement.dataset.jobfinitumChromeAgentVersion = version;
    } catch (error) {
      // The DOM may still be initializing.
    }

    window.postMessage(
      {
        source: SOURCE,
        type: "ready",
        version,
      },
      location.origin
    );
  }

  announceReady();

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      announceReady,
      {once: true}
    );
  } else {
    announceReady();
  }

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window
        || event.origin !== location.origin
        || !event.data
        || event.data.source
          !== "jobfinitum-site"
        || event.data.type
          !== "jobfinitum-school-search-request"
      ) {
        return;
      }

      const requestId =
        String(
          event.data.request_id
          || ""
        );

      const query =
        String(
          event.data.query
          || ""
        ).trim();

      chrome.runtime.sendMessage(
        {
          type:
            "jobfinitum-school-search",
          origin:
            location.origin,
          query,
          greenhouse_url:
            String(
              event.data.greenhouse_url
              || ""
            ),
        },
        (response) => {
          const runtimeError =
            chrome.runtime.lastError;

          window.postMessage(
            {
              source:
                SOURCE,
              type:
                "school-search-result",
              request_id:
                requestId,
              ok:
                Boolean(
                  response?.ok
                )
                && !runtimeError,
              schools:
                Array.isArray(
                  response?.schools
                )
                  ? response.schools
                  : [],
              error:
                runtimeError?.message
                || response?.error
                || "",
            },
            location.origin
          );
        }
      );
    }
  );

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window
        || event.origin !== location.origin
        || !event.data
        || event.data.source !== "jobfinitum-site"
        || event.data.type !== "jobfinitum-batch-control"
      ) {
        return;
      }

      chrome.runtime.sendMessage(
        {
          type: "jobfinitum-batch-control",
          origin: location.origin,
          action: String(event.data.action || ""),
        },
        () => {
          void chrome.runtime.lastError;
        }
      );
    }
  );


  chrome.runtime.onMessage.addListener(
    (message) => {
      if (
        !message
        || message.type !== "jobfinitum-agent-result"
      ) {
        return;
      }

      window.postMessage(
        {
          source: SOURCE,
          type: "result",
          result: message.result || {},
        },
        location.origin
      );
    }
  );
})();
