(() => {
  "use strict";

  const SOURCE = "jobfinitum-chrome-agent";

  const statusBox = document.getElementById(
    "jobfinitum-browser-agent-status"
  );

  const statusText = document.getElementById(
    "jobfinitum-browser-agent-status-text"
  );

  const versionText = document.getElementById(
    "jobfinitum-browser-agent-version"
  );

  if (!statusBox || !statusText) {
    return;
  }

  let connected = false;
  let dirtyQuestionForm = false;

  function requiredAgentForms() {
    return [
      ...document.querySelectorAll(
        'form[data-jobfinitum-agent-required="true"]'
      ),
    ];
  }

  function setFormsEnabled(enabled) {
    for (const form of requiredAgentForms()) {
      for (const button of form.querySelectorAll("button")) {
        button.disabled = !enabled;

        if (!enabled) {
          button.title = (
            "Jobfinitum Browser Agent is required "
            + "for this application host."
          );
        } else {
          button.removeAttribute("title");
        }
      }
    }
  }

  function setConnected(version) {
    connected = true;

    statusBox.classList.remove(
      "alert-warning"
    );

    statusBox.classList.add(
      "alert-success"
    );

    statusText.textContent = "Connected";

    if (versionText) {
      versionText.textContent = (
        version
          ? `v${version}`
          : ""
      );
    }

    setFormsEnabled(true);
  }

  function setDisconnected() {
    if (connected) {
      return;
    }

    statusBox.classList.remove(
      "alert-success"
    );

    statusBox.classList.add(
      "alert-warning"
    );

    statusText.textContent = "Not detected";

    if (versionText) {
      versionText.textContent = "";
    }

    setFormsEnabled(false);
  }

  function inspectBridgeMarker() {
    const version = (
      document.documentElement.dataset
        .jobfinitumChromeAgentVersion
      || ""
    ).trim();

    if (version) {
      setConnected(version);
      return true;
    }

    return false;
  }

  for (const form of document.querySelectorAll(
    ".application-question-form"
  )) {
    form.addEventListener(
      "input",
      () => {
        dirtyQuestionForm = true;
      }
    );

    form.addEventListener(
      "change",
      () => {
        dirtyQuestionForm = true;
      }
    );

    form.addEventListener(
      "submit",
      () => {
        dirtyQuestionForm = false;
      }
    );
  }

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window
        || event.origin !== location.origin
        || !event.data
        || event.data.source !== SOURCE
      ) {
        return;
      }

      if (event.data.type === "ready") {
        setConnected(
          String(
            event.data.version
            || ""
          )
        );

        return;
      }

      if (event.data.type === "result") {
        const result = event.data.result || {};

        if (
          location.pathname.startsWith(
            "/auto-apply"
          )
          && !dirtyQuestionForm
        ) {
          window.setTimeout(
            () => {
              location.reload();
            },
            350
          );
          return;
        }

        statusText.textContent = (
          result.status
            ? (
                `Connected — ${result.status} received. `
                + "Refresh to update the queue."
              )
            : "Connected"
        );
      }
    }
  );

  if (!inspectBridgeMarker()) {
    window.setTimeout(
      inspectBridgeMarker,
      150
    );

    window.setTimeout(
      () => {
        if (!inspectBridgeMarker()) {
          setDisconnected();
        }
      },
      1200
    );
  }
})();
