(() => {
  "use strict";

  const SOURCE = "jobfinitum-chrome-agent";
  const REQUIRED_AGENT_VERSION = "0.4.22";

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
  let detectedVersion = "";
  let dirtyQuestionForm = false;

  function batchRunnerActive() {
    try {
      const state = JSON.parse(
        window.sessionStorage.getItem(
          "jobfinitum_auto_apply_batch_v1"
        ) || "null"
      );

      return Boolean(
        state?.active
      );
    } catch (error) {
      return false;
    }
  }

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
    const currentVersion = String(
      version || ""
    ).trim();
    const versionMatches = (
      currentVersion === REQUIRED_AGENT_VERSION
    );

    detectedVersion = currentVersion;
    connected = versionMatches;

    statusBox.classList.remove(
      versionMatches
        ? "alert-warning"
        : "alert-success"
    );

    statusBox.classList.add(
      versionMatches
        ? "alert-success"
        : "alert-warning"
    );

    statusText.textContent = versionMatches
      ? "Connected"
      : `Reload required: v${REQUIRED_AGENT_VERSION}`;

    if (versionText) {
      versionText.textContent = (
        currentVersion
          ? `v${currentVersion}`
          : ""
      );
    }

    setFormsEnabled(versionMatches);
  }

  function setDisconnected() {
    if (connected || detectedVersion) {
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

        if (batchRunnerActive()) {
          return;
        }

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
                `Connected - ${result.status} received. `
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
(() => {
  "use strict";

  const EXTENSION_SOURCE =
    "jobfinitum-chrome-agent";

  const SITE_SOURCE =
    "jobfinitum-site";

  const REQUIRED_AGENT_VERSION =
    "0.4.22";

  const STORAGE_KEY =
    "jobfinitum_auto_apply_batch_v1";

  const RUNNER_NAME =
    "jobfinitum-auto-apply-runner";

  const BATCH_ITEM_TIMEOUT_MS =
    90000;

  const FINAL_STATUSES =
    new Set([
      "Submitted",
      "Needs Application Answer",
      "Needs User Action",
      "Unsupported",
      "Failed",
      "Rejected",
      "Closed",
      "Waiting for Verification",
      "Waiting for Sign-In",
    ]);

  const PAUSE_STATUSES =
    new Set([
      "Waiting for Verification",
      "Waiting for Sign-In",
    ]);

  const RESOLVED_APPLICATION_STATUS =
    "Resolved Application Target";

  const AGENT_RUNNING_STATUS =
    "Agent Running";

  const startButton =
    document.getElementById(
      "jobfinitum-batch-start"
    );

  const stopButton =
    document.getElementById(
      "jobfinitum-batch-stop"
    );

  const progress =
    document.getElementById(
      "jobfinitum-batch-progress"
    );

  const rejectCheckedButton =
    document.getElementById(
      "jobfinitum-reject-checked"
    );

  const resetCheckedButton =
    document.getElementById(
      "jobfinitum-reset-checked"
    );

  const resetAllRejectedButton =
    document.getElementById(
      "jobfinitum-reset-all-rejected"
    );

  const selectPageControl =
    document.getElementById(
      "jobfinitum-select-page"
    );

  const reviewCheckboxes = [
    ...document.querySelectorAll(
      "[data-jobfinitum-review-select]"
    ),
  ];

  const csrfToken =
    document.getElementById(
      "jobfinitum-batch-csrf-token"
    )?.value || "";

  let preparedBatch = null;
  let batchPreparationStarted = false;
  let batchWatchdog = null;
  let resolvedRelaunchTimer = null;

  if (
    !startButton
    || !stopButton
    || !progress
  ) {
    return;
  }

  function loadState() {
    try {
      return JSON.parse(
        window.sessionStorage.getItem(
          STORAGE_KEY
        ) || "null"
      );
    } catch (error) {
      return null;
    }
  }

  function saveState(state) {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(state)
    );
  }

  function clearState() {
    window.sessionStorage.removeItem(
      STORAGE_KEY
    );
  }

  function agentVersion() {
    return String(
      document.documentElement.dataset
        .jobfinitumChromeAgentVersion
      || ""
    ).trim();
  }

  function agentConnected() {
    return (
      agentVersion()
      === REQUIRED_AGENT_VERSION
    );
  }

  function updateControls(state = loadState()) {
    const active =
      Boolean(state?.active);

    startButton.disabled = (
      active
      || !agentConnected()
      || !Array.isArray(
        preparedBatch?.candidates
      )
    );

    stopButton.disabled =
      !active;

    if (rejectCheckedButton) {
      rejectCheckedButton.dataset.batchActive = (
        active ? "1" : "0"
      );
      rejectCheckedButton.disabled = (
        active
        || Number(
          rejectCheckedButton.dataset.selectedCount
          || "0"
        ) < 1
      );
    }

    if (resetCheckedButton) {
      resetCheckedButton.dataset.batchActive = (
        active ? "1" : "0"
      );
      resetCheckedButton.disabled = (
        active
        || Number(
          resetCheckedButton.dataset.selectedCount
          || "0"
        ) < 1
      );
    }

    if (resetAllRejectedButton) {
      resetAllRejectedButton.disabled = active;
    }

    for (const checkbox of reviewCheckboxes) {
      checkbox.disabled = active;
    }

    if (selectPageControl) {
      selectPageControl.disabled = (
        active
        || reviewCheckboxes.length < 1
      );
    }

    if (!active) {
      return;
    }

    progress.textContent = (
      `Running ${state.completed + 1} of ${state.total}`
    );
  }

  function sendBatchControl(action) {
    window.postMessage(
      {
        source:
          SITE_SOURCE,
        type:
          "jobfinitum-batch-control",
        action,
      },
      location.origin
    );
  }

  function clearBatchWatchdog() {
    if (batchWatchdog === null) {
      return;
    }

    window.clearTimeout(
      batchWatchdog
    );
    batchWatchdog = null;
  }

  function clearResolvedRelaunch() {
    if (resolvedRelaunchTimer === null) {
      return;
    }

    window.clearTimeout(
      resolvedRelaunchTimer
    );
    resolvedRelaunchTimer = null;
  }

  function interruptUrlFor(candidate) {
    if (candidate?.interrupt_url) {
      return candidate.interrupt_url;
    }

    const candidateId = Number(
      candidate?.candidate_id
    );

    if (!Number.isInteger(candidateId)) {
      return "";
    }

    return (
      "/api/auto-apply/batch-candidates/"
      + encodeURIComponent(candidateId)
      + "/interrupt"
    );
  }

  async function interruptCandidate(
    candidate,
    reason
  ) {
    const url =
      interruptUrlFor(candidate);

    if (!url) {
      throw new Error(
        "The interrupted application could not be identified."
      );
    }

    const response = await fetch(
      url,
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({reason}),
      }
    );

    const payload = await response.json();

    if (!response.ok) {
      throw new Error(
        payload.error
        || `HTTP ${response.status}`
      );
    }

    return payload;
  }

  async function handleBatchTimeout(
    candidateId
  ) {
    const state = loadState();

    if (
      !state?.active
      || Number(
        state.current?.candidate_id
      ) !== Number(candidateId)
    ) {
      return;
    }

    progress.textContent = (
      "The Browser Agent did not report back; moving to the next job"
    );

    try {
      await interruptCandidate(
        state.current,
        "timeout"
      );
    } catch (error) {
      await stopBatch({
        closeRunner: true,
        recoverCurrent: false,
      });
      progress.textContent = (
        `Batch stopped: ${error.message || error}`
      );
      return;
    }

    const latestState = loadState();

    if (
      !latestState?.active
      || Number(
        latestState.current?.candidate_id
      ) !== Number(candidateId)
    ) {
      return;
    }

    latestState.completed += 1;
    latestState.current = null;
    latestState.current_started_at = null;
    saveState(latestState);
    updateControls(latestState);

    window.setTimeout(
      submitNext,
      300
    );
  }

  function scheduleBatchWatchdog(state) {
    clearBatchWatchdog();

    if (
      !state?.active
      || !state.current
    ) {
      return;
    }

    const startedAt = Number(
      state.current_started_at
      || 0
    );

    const elapsed = startedAt
      ? Date.now() - startedAt
      : BATCH_ITEM_TIMEOUT_MS;

    const delay = Math.max(
      0,
      BATCH_ITEM_TIMEOUT_MS - elapsed
    );

    const candidateId =
      state.current.candidate_id;

    batchWatchdog = window.setTimeout(
      () => {
        batchWatchdog = null;
        handleBatchTimeout(
          candidateId
        );
      },
      delay
    );
  }

  function submitCandidate(candidate) {
    if (!candidate?.action_url) {
      throw new Error(
        "The Auto Apply candidate has no launch URL."
      );
    }

    const form =
      document.createElement("form");

    form.method = "POST";
    form.action = candidate.action_url;
    form.target = RUNNER_NAME;
    form.hidden = true;

    const csrf =
      document.createElement("input");

    csrf.type = "hidden";
    csrf.name = "csrf_token";
    csrf.value = csrfToken;

    form.appendChild(csrf);

    const batchMode =
      document.createElement("input");

    batchMode.type = "hidden";
    batchMode.name = "jobfinitum_batch";
    batchMode.value = "1";

    form.appendChild(batchMode);
    document.body.appendChild(form);
    form.submit();
    form.remove();
  }

  function submitNext() {
    const state =
      loadState();

    if (
      !state?.active
      || state.current
    ) {
      updateControls(state);
      return;
    }

    const next =
      state.remaining.shift();

    if (!next) {
      const completed =
        state.completed;

      clearBatchWatchdog();
      clearState();
      updateControls(null);
      progress.textContent = (
        `Batch complete: ${completed} processed`
      );
      sendBatchControl("stop");

      window.setTimeout(
        () => location.reload(),
        700
      );
      return;
    }

    state.current = next;
    state.current_started_at =
      Date.now();
    saveState(state);
    updateControls(state);

    submitCandidate(next);
    scheduleBatchWatchdog(state);
  }

  async function stopBatch({
    closeRunner = true,
    recoverCurrent = true,
  } = {}) {
    const state = loadState();

    clearBatchWatchdog();
    clearResolvedRelaunch();
    clearState();
    preparedBatch = null;
    batchPreparationStarted = false;
    updateControls(null);
    progress.textContent = (
      "Batch stopped; refreshing available jobs"
    );

    if (closeRunner) {
      sendBatchControl("stop");
    }

    if (
      recoverCurrent
      && state?.current
    ) {
      try {
        await interruptCandidate(
          state.current,
          "stopped"
        );
      } catch (error) {
        progress.textContent = (
          "Batch stopped; reset the interrupted job before retrying"
        );
      }
    }

    window.setTimeout(
      prepareBatch,
      closeRunner ? 300 : 0
    );
  }

  async function prepareBatch() {
    if (batchPreparationStarted) {
      return;
    }

    batchPreparationStarted = true;
    progress.textContent = (
      "Preparing Auto Apply batch"
    );

    try {
      const response = await fetch(
        startButton.dataset.candidatesUrl,
        {
          credentials: "same-origin",
          cache: "no-store",
        }
      );

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(
          payload.error
          || `HTTP ${response.status}`
        );
      }

      preparedBatch = {
        ...payload,
        candidates: Array.isArray(
          payload.candidates
        )
          ? payload.candidates
          : [],
      };

      progress.textContent = (
        preparedBatch.candidates.length
          ? (
              preparedBatch.recovered_interrupted
                ? (
                    `${preparedBatch.candidates.length} jobs ready; `
                    + `${preparedBatch.recovered_interrupted} interrupted jobs restored`
                  )
                : `${preparedBatch.candidates.length} jobs ready`
            )
          : (
              preparedBatch.skipped_out_of_spec
                ? "No eligible jobs; out-of-spec jobs were skipped"
                : "No pending supported jobs to run"
            )
      );
    } catch (error) {
      preparedBatch = null;
      progress.textContent = (
        `Could not prepare batch: ${error.message || error}`
      );
    }

    updateControls();
  }

  function startBatch() {
    if (
      !agentConnected()
      || loadState()?.active
      || !Array.isArray(
        preparedBatch?.candidates
      )
    ) {
      return;
    }

    startButton.disabled = true;
    const payload = preparedBatch;
    const candidates = payload.candidates;

    if (!candidates.length) {
      progress.textContent = (
        payload.skipped_out_of_spec
          ? "No eligible jobs; out-of-spec jobs were skipped"
          : "No pending supported jobs to run"
      );
      updateControls(null);
      return;
    }

    preparedBatch = null;

    saveState({
      active: true,
      agent_version: agentVersion(),
      total: candidates.length,
      completed: 0,
      current: null,
      current_started_at: null,
      remaining: candidates,
    });

    // This synchronous form submission runs directly inside the
    // user's click, so Chrome opens the first real application
    // instead of an intermediate about:blank worker tab.
    submitNext();
  }

  startButton.addEventListener(
    "click",
    startBatch
  );

  stopButton.addEventListener(
    "click",
    () => stopBatch()
  );

  window.addEventListener(
    "jobfinitum:queue-changed",
    () => {
      if (loadState()?.active) {
        return;
      }

      preparedBatch = null;
      batchPreparationStarted = false;
      prepareBatch();
    }
  );

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window
        || event.origin !== location.origin
        || !event.data
      ) {
        return;
      }

      if (
        event.data.source
          === EXTENSION_SOURCE
        && event.data.type === "ready"
      ) {
        updateControls();
        resumePersistedBatch();
        return;
      }

      if (
        event.data.source
          !== EXTENSION_SOURCE
        || event.data.type !== "result"
      ) {
        return;
      }

      const result =
        event.data.result || {};

      const state =
        loadState();

      if (!state?.active) {
        return;
      }

      if (
        Number(
          result.candidate_id
        )
        !== Number(
          state.current?.candidate_id
        )
      ) {
        return;
      }

      if (
        result.status
        === RESOLVED_APPLICATION_STATUS
        && result.continue_in_chrome_agent
      ) {
        const relaunchCount = Number(
          state.current.resolved_relaunch_count
          || 0
        );

        if (relaunchCount > 0) {
          return;
        }

        state.current.resolved_relaunch_count =
          relaunchCount + 1;
        state.current_started_at = Date.now();
        clearBatchWatchdog();
        clearResolvedRelaunch();
        saveState(state);
        updateControls(state);
        progress.textContent =
          "Opening the resolved employer application";

        resolvedRelaunchTimer =
          window.setTimeout(
            () => {
              resolvedRelaunchTimer = null;
              const latestState = loadState();

              if (
                !latestState?.active
                || Number(
                  latestState.current?.candidate_id
                ) !== Number(
                  result.candidate_id
                )
              ) {
                return;
              }

              submitCandidate(
                latestState.current
              );
              scheduleBatchWatchdog(
                latestState
              );
            },
            1500
          );
        return;
      }

      if (
        result.status
        === AGENT_RUNNING_STATUS
      ) {
        clearResolvedRelaunch();
        state.current_started_at = Date.now();
        saveState(state);
        scheduleBatchWatchdog(state);
        updateControls(state);
        progress.textContent =
          "Filling the employer application";
        return;
      }

      if (
        !FINAL_STATUSES.has(
          String(result.status || "")
        )
      ) {
        return;
      }

      state.completed += 1;
      state.current = null;
      state.current_started_at = null;
      clearBatchWatchdog();
      clearResolvedRelaunch();

      if (
        PAUSE_STATUSES.has(
          result.status
        )
      ) {
        clearState();
        updateControls(null);
        progress.textContent = (
          `Batch paused: ${result.status}`
        );
        window.setTimeout(
          () => location.reload(),
          700
        );
        return;
      }

      saveState(state);
      updateControls(state);

      window.setTimeout(
        submitNext,
        500
      );
    }
  );

  function resumePersistedBatch() {
    const state = loadState();
    const version = agentVersion();

    if (!state?.active || !version) {
      return;
    }

    if (!agentConnected()) {
      stopBatch();
      progress.textContent = (
        `Reload Browser Agent v${REQUIRED_AGENT_VERSION} before starting Auto Apply`
      );
      return;
    }

    if (state.agent_version !== version) {
      stopBatch();
      return;
    }

    if (!state.current) {
      submitNext();
      return;
    }

    if (
      Number(
        state.current_started_at
        || 0
      ) > 0
    ) {
      scheduleBatchWatchdog(state);
    } else {
      stopBatch();
    }
  }

  const existingState =
    loadState();

  updateControls(existingState);
  resumePersistedBatch();

  window.setTimeout(
    updateControls,
    250
  );

  if (!existingState?.active) {
    prepareBatch();
  }
})();

(() => {
  "use strict";

  const forms = [
    ...document.querySelectorAll(
      'form[data-jobfinitum-single-reject="true"]'
    ),
  ];

  if (!forms.length) {
    return;
  }

  function changeStatusCount(
    status,
    difference
  ) {
    if (!status) {
      return;
    }

    const count =
      document.querySelector(
        `[data-jobfinitum-status-count="${CSS.escape(status)}"]`
      );

    if (!count) {
      return;
    }

    const current = Number(
      count.textContent || "0"
    );

    count.textContent = String(
      Math.max(
        0,
        current + difference
      )
    );
  }

  for (const form of forms) {
    form.addEventListener(
      "submit",
      async (event) => {
        event.preventDefault();

        const card = form.closest(
          "[data-jobfinitum-candidate-card]"
        );

        const button = form.querySelector(
          'button[type="submit"]'
        );

        if (!card || !button || button.disabled) {
          return;
        }

        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = "Rejecting...";

        try {
          const response = await fetch(
            form.action,
            {
              method: "POST",
              body: new FormData(form),
              credentials: "same-origin",
              cache: "no-store",
              headers: {
                "X-Requested-With":
                  "XMLHttpRequest",
                "Accept":
                  "application/json",
              },
            }
          );

          const payload = await response.json();

          if (!response.ok || !payload.success) {
            throw new Error(
              payload.message
              || `HTTP ${response.status}`
            );
          }

          const previousStatus = String(
            card.dataset.jobfinitumCandidateStatus
            || ""
          );

          const previousExecution = String(
            card.dataset.jobfinitumCandidateExecution
            || ""
          );

          if (previousStatus === "Pending Review") {
            changeStatusCount(
              "Pending Review",
              -1
            );
          }

          if (
            previousExecution
            && previousExecution !== "Not Started"
            && previousExecution !== "Submitted"
          ) {
            changeStatusCount(
              previousExecution,
              -1
            );
          }

          changeStatusCount(
            "Rejected",
            1
          );

          card.remove();
          window.dispatchEvent(
            new CustomEvent(
              "jobfinitum:queue-changed"
            )
          );

          const cards = document.getElementById(
            "jobfinitum-auto-apply-cards"
          );

          if (
            cards
            && !cards.querySelector(
              "[data-jobfinitum-candidate-card]"
            )
          ) {
            cards.innerHTML = (
              '<div class="alert alert-info mb-0">'
              + "No jobs remain on this page."
              + "</div>"
            );
          }
        } catch (error) {
          button.disabled = false;
          button.textContent = originalLabel;
          window.alert(
            `Could not reject this job: ${error.message || error}`
          );
        }
      }
    );
  }
})();

(() => {
  "use strict";

  const form =
    document.getElementById(
      "jobfinitum-bulk-review-form"
    );

  const rejectButton =
    document.getElementById(
      "jobfinitum-reject-checked"
    );

  const rejectLabel =
    document.getElementById(
      "jobfinitum-reject-checked-label"
    );

  const resetButton =
    document.getElementById(
      "jobfinitum-reset-checked"
    );

  const resetLabel =
    document.getElementById(
      "jobfinitum-reset-checked-label"
    );

  const selectPage =
    document.getElementById(
      "jobfinitum-select-page"
    );

  const checkboxes = [
    ...document.querySelectorAll(
      "[data-jobfinitum-review-select]"
    ),
  ];

  if (
    !form
    || !rejectButton
    || !rejectLabel
    || !selectPage
  ) {
    return;
  }

  function selectedCheckboxes() {
    return checkboxes.filter(
      (checkbox) => checkbox.checked
    );
  }

  function updateSelection() {
    const selected =
      selectedCheckboxes().length;

    rejectButton.dataset.selectedCount =
      String(selected);

    rejectButton.disabled = (
      selected < 1
      || rejectButton.dataset.batchActive
        === "1"
    );

    rejectLabel.textContent = (
      selected
        ? `Reject Checked Jobs (${selected})`
        : "Reject Checked Jobs"
    );

    if (resetButton) {
      resetButton.dataset.selectedCount =
        String(selected);

      resetButton.disabled = (
        selected < 1
        || resetButton.dataset.batchActive
          === "1"
      );
    }

    if (resetLabel) {
      resetLabel.textContent = (
        selected
          ? `Reset Checked for Review (${selected})`
          : "Reset Checked for Review"
      );
    }

    const checkedCount =
      checkboxes.filter(
        (checkbox) => checkbox.checked
      ).length;

    selectPage.checked = (
      checkboxes.length > 0
      && checkedCount === checkboxes.length
    );
    selectPage.indeterminate = (
      checkedCount > 0
      && checkedCount < checkboxes.length
    );
    selectPage.disabled = (
      checkboxes.length < 1
      || rejectButton.dataset.batchActive
        === "1"
    );
  }

  selectPage.addEventListener(
    "change",
    () => {
      for (const checkbox of checkboxes) {
        checkbox.checked = selectPage.checked;
      }

      updateSelection();
    }
  );

  for (const checkbox of checkboxes) {
    checkbox.addEventListener(
      "change",
      updateSelection
    );
  }

  form.addEventListener(
    "submit",
    (event) => {
      const selected =
        selectedCheckboxes().length;

      if (!selected) {
        event.preventDefault();
        updateSelection();
        return;
      }

      if (
        !window.confirm(
          event.submitter === resetButton
            ? (
                `Return ${selected} checked Manual Apply job${selected === 1 ? "" : "s"} to Pending Review?`
              )
            : (
                `Reject ${selected} checked job${selected === 1 ? "" : "s"}?`
              )
        )
      ) {
        event.preventDefault();
      }
    }
  );

  updateSelection();
})();

(() => {
  "use strict";

  const inputs = [
    ...document.querySelectorAll(
      'input[data-jobfinitum-school-search="true"]'
    ),
  ];

  if (
    !inputs.length
  ) {
    return;
  }

  const controllers =
    new WeakMap();

  function schoolStatus(
    input,
    message
  ) {
    const id =
      input.dataset.schoolStatusId;

    if (!id) {
      return;
    }

    const node =
      document.getElementById(
        id
      );

    if (node) {
      node.textContent =
        message;
    }
  }

  function updateDatalist(
    input,
    schools
  ) {
    const listId =
      input.getAttribute(
        "list"
      );

    const list =
      listId
        ? document.getElementById(
            listId
          )
        : null;

    if (!list) {
      return;
    }

    list.replaceChildren();

    for (
      const school
      of schools
    ) {
      const label =
        String(
          school?.label
          || school?.value
          || ""
        ).trim();

      if (!label) {
        continue;
      }

      const option =
        document.createElement(
          "option"
        );

      option.value =
        label;

      list.appendChild(
        option
      );
    }
  }

  async function sendSchoolSearch(
    input,
    query
  ) {
    const previousController =
      controllers.get(input);

    if (previousController) {
      previousController.abort();
    }

    const controller =
      new AbortController();

    controllers.set(
      input,
      controller
    );

    schoolStatus(
      input,
      "Searching schools..."
    );

    try {
      const endpoint = new URL(
        String(
          input.dataset.schoolSearchUrl
          || ""
        ),
        location.href
      );

      endpoint.searchParams.set(
        "q",
        query
      );

      const response = await fetch(
        endpoint,
        {
          method: "GET",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
          },
          signal: controller.signal,
        }
      );

      const payload =
        await response.json();

      if (
        !response.ok
        || !payload.success
      ) {
        throw new Error(
          payload.message
          || "School lookup is unavailable."
        );
      }

      if (
        String(input.value || "").trim()
        !== query
      ) {
        return;
      }

      const schools =
        Array.isArray(payload.items)
          ? payload.items
          : [];

      updateDatalist(
        input,
        schools
      );

      schoolStatus(
        input,
        schools.length
          ? (
              `${schools.length} matching `
              + "schools found."
            )
          : "No matching schools found."
      );
    } catch (error) {
      if (
        error?.name
        === "AbortError"
      ) {
        return;
      }

      updateDatalist(
        input,
        []
      );

      schoolStatus(
        input,
        error?.message
        || "School lookup is unavailable."
      );
    } finally {
      if (
        controllers.get(input)
        === controller
      ) {
        controllers.delete(input);
      }
    }
  }

  function setupJobfinitumSchoolSearch(
    input
  ) {
    let timer = null;
    let lastQuery = "";

    const search = () => {
      const query =
        String(
          input.value
          || ""
        ).trim();

      if (
        query.length < 3
      ) {
        const activeController =
          controllers.get(input);

        if (activeController) {
          activeController.abort();
          controllers.delete(input);
        }

        lastQuery = "";

        schoolStatus(
          input,
          "Type at least 3 characters to search schools."
        );

        return;
      }

      if (
        query === lastQuery
      ) {
        return;
      }

      lastQuery =
        query;

      void sendSchoolSearch(
        input,
        query
      );
    };

    input.addEventListener(
      "input",
      () => {
        if (timer) {
          window.clearTimeout(
            timer
          );
        }

        timer =
          window.setTimeout(
            search,
            300
          );
      }
    );

  }

  for (
    const input
    of inputs
  ) {
    setupJobfinitumSchoolSearch(
      input
    );
  }
})();

(() => {
  "use strict";

  const pickers = [
    ...document.querySelectorAll(
      "[data-jobfinitum-question-multiselect]"
    ),
  ];

  for (const picker of pickers) {
    const summary =
      picker.querySelector(
        "[data-jobfinitum-multiselect-summary]"
      );

    const search =
      picker.querySelector(
        "[data-jobfinitum-multiselect-search]"
      );

    const options = [
      ...picker.querySelectorAll(
        "[data-jobfinitum-multiselect-option]"
      ),
    ];

    const checkboxes = options
      .map(
        (option) => option.querySelector(
          'input[type="checkbox"]'
        )
      )
      .filter(Boolean);

    function updateSummary() {
      if (!summary) {
        return;
      }

      const selected = checkboxes
        .filter(
          (checkbox) => checkbox.checked
        )
        .map(
          (checkbox) => checkbox.value
        );

      if (!selected.length) {
        summary.textContent =
          "Choose one or more answers";
      } else if (selected.length <= 2) {
        summary.textContent =
          selected.join(", ");
      } else {
        summary.textContent =
          `${selected.length} answers selected`;
      }
    }

    for (const checkbox of checkboxes) {
      checkbox.addEventListener(
        "change",
        updateSummary
      );
    }

    search?.addEventListener(
      "input",
      () => {
        const wanted = String(
          search.value || ""
        ).trim().toLowerCase();

        for (const option of options) {
          const label = String(
            option.dataset.choiceLabel
            || option.textContent
            || ""
          ).toLowerCase();

          option.hidden = Boolean(
            wanted
            && !label.includes(wanted)
          );
        }
      }
    );

    updateSummary();
  }
})();
