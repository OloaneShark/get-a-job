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
(() => {
  "use strict";

  const EXTENSION_SOURCE =
    "jobfinitum-chrome-agent";

  const SITE_SOURCE =
    "jobfinitum-site";

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
    return Boolean(agentVersion());
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

    const form =
      document.createElement("form");

    form.method = "POST";
    form.action = next.action_url;
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
    scheduleBatchWatchdog(state);
  }

  async function stopBatch({
    closeRunner = true,
    recoverCurrent = true,
  } = {}) {
    const state = loadState();

    clearBatchWatchdog();
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

      if (
        !FINAL_STATUSES.has(
          String(result.status || "")
        )
      ) {
        return;
      }

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

      state.completed += 1;
      state.current = null;
      state.current_started_at = null;
      clearBatchWatchdog();

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

  const EXTENSION_SOURCE =
    "jobfinitum-chrome-agent";

  const SITE_SOURCE =
    "jobfinitum-site";

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

  const pending =
    new Map();

  let requestCounter = 0;

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

  function sendSchoolSearch(
    input,
    query
  ) {
    requestCounter += 1;

    const requestId = (
      `school-${Date.now()}-`
      + requestCounter
    );

    pending.set(
      requestId,
      {
        input,
        query,
      }
    );

    schoolStatus(
      input,
      "Searching the actual Greenhouse school list..."
    );

    window.postMessage(
      {
        source:
          SITE_SOURCE,
        type:
          "jobfinitum-school-search-request",
        request_id:
          requestId,
        query,
        greenhouse_url:
          String(
            input.dataset.greenhouseUrl
            || ""
          ),
      },
      location.origin
    );
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
        query.length < 2
      ) {
        lastQuery = "";
        updateDatalist(
          input,
          []
        );

        schoolStatus(
          input,
          "Type at least 2 characters to search the actual Greenhouse school list."
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

      sendSchoolSearch(
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

    // If a remembered value already exists, leave it alone.
    // The user can edit it and live search will start.
  }

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window
        || event.origin
          !== location.origin
        || !event.data
        || event.data.source
          !== EXTENSION_SOURCE
        || event.data.type
          !== "school-search-result"
      ) {
        return;
      }

      const requestId =
        String(
          event.data.request_id
          || ""
        );

      const request =
        pending.get(
          requestId
        );

      if (!request) {
        return;
      }

      pending.delete(
        requestId
      );

      const currentValue =
        String(
          request.input.value
          || ""
        ).trim();

      // Ignore stale results if the user has typed more since
      // this request was sent.
      if (
        currentValue
        !== request.query
      ) {
        return;
      }

      if (
        !event.data.ok
      ) {
        updateDatalist(
          request.input,
          []
        );

        schoolStatus(
          request.input,
          event.data.error
            ? (
                "School lookup unavailable: "
                + event.data.error
              )
            : (
                "School lookup is unavailable."
              )
        );

        return;
      }

      const schools =
        Array.isArray(
          event.data.schools
        )
          ? event.data.schools
          : [];

      updateDatalist(
        request.input,
        schools
      );

      schoolStatus(
        request.input,
        schools.length
          ? (
              `${schools.length} matching `
              + "Greenhouse schools found."
            )
          : (
              "No matching Greenhouse schools found."
            )
      );
    }
  );

  for (
    const input
    of inputs
  ) {
    setupJobfinitumSchoolSearch(
      input
    );
  }
})();
