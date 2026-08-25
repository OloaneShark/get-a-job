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
