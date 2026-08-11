(() => {
    "use strict";

    const statusElement = document.getElementById(
        "candidate-action-status"
    );
    const getTableContainer = () => (
        document.getElementById(
            "candidate-table-container"
        )
    );
    const getEmptyState = () => (
        document.getElementById(
            "candidate-empty-state"
        )
    );
    const discoveryForm = document.getElementById(
        "automatic-discovery-form"
    );
    const discoveryButton = document.getElementById(
        "automatic-discovery-button"
    );
    let discoveryPollTimer = null;

    if (!statusElement) {
        return;
    }

    const categoryClass = (category) => {
        const mapping = {
            success: "alert-success",
            info: "alert-info",
            warning: "alert-warning",
            danger: "alert-danger",
        };

        return mapping[category] || "alert-info";
    };

    const showStatus = (message, category = "info") => {
        statusElement.className = (
            `alert ${categoryClass(category)}`
        );
        statusElement.textContent = message;
        statusElement.classList.remove("d-none");
    };

    const updateEmptyState = () => {
        const remainingRows = document.querySelectorAll(
            "[data-candidate-row]"
        ).length;

        if (remainingRows > 0) {
            return;
        }

        const tableContainer = getTableContainer();
        const emptyState = getEmptyState();

        if (tableContainer) {
            tableContainer.classList.add("d-none");
        }

        if (emptyState) {
            emptyState.classList.remove("d-none");
        }
    };

    const setFormBusy = (form, busy) => {
        form.querySelectorAll(
            "button, input[type='submit']"
        ).forEach((control) => {
            control.disabled = busy;
        });
    };

    const removeRow = (row) => {
        if (!row) {
            return;
        }

        row.style.transition = (
            "opacity 160ms ease, transform 160ms ease"
        );
        row.style.opacity = "0";
        row.style.transform = "translateX(10px)";

        window.setTimeout(() => {
            row.remove();
            updateEmptyState();
        }, 170);
    };

    const setDiscoveryButtonState = (running) => {
        if (!discoveryButton) {
            return;
        }

        discoveryButton.disabled = running;
        discoveryButton.textContent = running
            ? "Discovery Running..."
            : "Run Automatic Discovery";
    };

    const scheduleDiscoveryPoll = () => {
        window.clearTimeout(discoveryPollTimer);
        discoveryPollTimer = window.setTimeout(
            checkDiscoveryStatus,
            3000
        );
    };

    const handleCompletedDiscovery = (payload) => {
        setDiscoveryButtonState(false);
        showStatus(payload.message, "success");

        const storageKey = "completed-source-discovery-run";
        const previousRun = window.sessionStorage.getItem(storageKey);

        if (payload.run_id && payload.run_id !== previousRun) {
            window.sessionStorage.setItem(storageKey, payload.run_id);
            window.setTimeout(() => {
                window.location.reload();
            }, 700);
        }
    };

    const checkDiscoveryStatus = async () => {
        if (!discoveryForm) {
            return;
        }

        try {
            const response = await fetch(
                discoveryForm.dataset.statusUrl,
                {
                    headers: {"Accept": "application/json"},
                    credentials: "same-origin",
                    cache: "no-store",
                }
            );
            const payload = await response.json();

            if (!response.ok || !payload.success) {
                throw new Error(
                    payload.message || "Discovery status failed."
                );
            }

            if (payload.state === "queued" || payload.state === "running") {
                setDiscoveryButtonState(true);
                showStatus(payload.message, "info");
                scheduleDiscoveryPoll();
                return;
            }

            if (payload.state === "completed") {
                handleCompletedDiscovery(payload);
                return;
            }

            if (payload.state === "failed") {
                setDiscoveryButtonState(false);
                showStatus(payload.message, "danger");
                return;
            }

            setDiscoveryButtonState(false);

        } catch (error) {
            setDiscoveryButtonState(false);
            showStatus(
                error.message || "Discovery status could not be checked.",
                "danger"
            );
        }
    };

    if (discoveryForm) {
        discoveryForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            if (discoveryButton && discoveryButton.disabled) {
                return;
            }

            setDiscoveryButtonState(true);
            showStatus("Starting automatic discovery...", "info");

            try {
                const response = await fetch(
                    discoveryForm.action,
                    {
                        method: "POST",
                        body: new FormData(discoveryForm),
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json",
                        },
                        credentials: "same-origin",
                    }
                );
                const payload = await response.json();

                if (!response.ok || !payload.success) {
                    throw new Error(
                        payload.message || "Discovery could not be started."
                    );
                }

                showStatus(payload.message, payload.category || "info");
                scheduleDiscoveryPoll();

            } catch (error) {
                setDiscoveryButtonState(false);
                showStatus(
                    error.message || "Discovery could not be started.",
                    "danger"
                );
            }
        });

        checkDiscoveryStatus();
    }


    const loadCandidateSource = async (
        url,
        updateHistory = true
    ) => {
        const currentFilter = document.getElementById(
            "candidate-source-filter"
        );
        const currentResults = document.getElementById(
            "candidate-results-card"
        );

        if (!currentFilter || !currentResults) {
            return;
        }

        currentFilter.setAttribute("aria-busy", "true");
        currentResults.setAttribute("aria-busy", "true");
        currentFilter.style.opacity = "0.65";
        currentResults.style.opacity = "0.65";

        try {
            const response = await fetch(
                url,
                {
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "text/html",
                    },
                    credentials: "same-origin",
                    cache: "no-store",
                }
            );

            if (!response.ok) {
                throw new Error(
                    "The source filter could not be loaded."
                );
            }

            const html = await response.text();
            const parsedDocument = new DOMParser().parseFromString(
                html,
                "text/html"
            );

            const nextFilter = parsedDocument.getElementById(
                "candidate-source-filter"
            );
            const nextResults = parsedDocument.getElementById(
                "candidate-results-card"
            );

            if (!nextFilter || !nextResults) {
                throw new Error(
                    "The filtered candidate view was incomplete."
                );
            }

            currentFilter.replaceWith(nextFilter);
            currentResults.replaceWith(nextResults);

            if (updateHistory) {
                window.history.pushState(
                    {
                        discoverySourceFilter: true,
                    },
                    "",
                    url
                );
            }
        } catch (error) {
            currentFilter.removeAttribute("aria-busy");
            currentResults.removeAttribute("aria-busy");
            currentFilter.style.opacity = "";
            currentResults.style.opacity = "";

            showStatus(
                error.message
                || "The source filter could not be loaded.",
                "danger"
            );
        }
    };

    document.addEventListener(
        "click",
        (event) => {
            const filterLink = event.target.closest(
                "#candidate-source-filter a"
            );

            if (!filterLink) {
                return;
            }

            if (
                event.defaultPrevented
                || event.button !== 0
                || event.metaKey
                || event.ctrlKey
                || event.shiftKey
                || event.altKey
            ) {
                return;
            }

            event.preventDefault();

            loadCandidateSource(
                filterLink.href,
                true
            );
        }
    );

    window.addEventListener(
        "popstate",
        () => {
            loadCandidateSource(
                window.location.href,
                false
            );
        }
    );

    document.addEventListener(
        "submit",
        async (event) => {
            const form = event.target.closest(
                ".candidate-action-form"
            );

            if (!form) {
                return;
            }

            event.preventDefault();

            if (form.dataset.busy === "true") {
                return;
            }

            form.dataset.busy = "true";
            setFormBusy(form, true);

            const row = form.closest(
                "[data-candidate-row]"
            );

            try {
                const response = await fetch(
                    form.action,
                    {
                        method: "POST",
                        body: new FormData(form),
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json",
                        },
                        credentials: "same-origin",
                    }
                );

                const contentType = (
                    response.headers.get("content-type")
                    || ""
                );

                if (!contentType.includes("application/json")) {
                    throw new Error(
                        "The server returned an unexpected response."
                    );
                }

                const payload = await response.json();

                if (!response.ok || !payload.success) {
                    throw new Error(
                        payload.message || "The action failed."
                    );
                }

                showStatus(
                    payload.message,
                    payload.category
                );

                if (payload.remove_row) {
                    removeRow(row);
                }

            } catch (error) {
                showStatus(
                    error.message
                    || "The action could not be completed.",
                    "danger"
                );
                setFormBusy(form, false);
                form.dataset.busy = "false";
            }
        }
    );

    const scopedBulkActions = [
        {
            path: "/admin/job-source-candidates/cleanup-invalid",
            label: "Clear Invalid",
            confirmText: "Clear invalid and rejected candidates",
        },
        {
            path: "/admin/job-source-candidates/cleanup-approved",
            label: "Clear Approved",
            confirmText: "Clear approved candidates",
        },
        {
            path: "/admin/job-source-candidates/approve-all-valid",
            label: "Approve All Valid",
            confirmText: "Approve all valid candidates",
        },
    ];

    const getScopedBulkAction = (form) => {
        if (!form || !form.action) {
            return null;
        }

        const actionUrl = new URL(
            form.action,
            window.location.origin
        );

        return (
            scopedBulkActions.find(
                (action) => (
                    action.path
                    === actionUrl.pathname
                )
            )
            || null
        );
    };

    const sourceDisplayName = (source) => {
        return String(source || "")
            .split("_")
            .filter(Boolean)
            .map((part) => (
                part.charAt(0).toUpperCase()
                + part.slice(1)
            ))
            .join(" ");
    };

    const syncScopedBulkActions = (url) => {
        const pageUrl = new URL(
            url || window.location.href,
            window.location.origin
        );
        const source = (
            pageUrl.searchParams.get("source")
            || ""
        ).trim().toLowerCase();
        const displaySource = sourceDisplayName(
            source
        );

        document.querySelectorAll(
            "form"
        ).forEach((form) => {
            const action = getScopedBulkAction(
                form
            );

            if (!action) {
                return;
            }

            form.onsubmit = null;

            let sourceInput = form.querySelector(
                'input[name="source"]'
            );

            if (!sourceInput) {
                sourceInput = (
                    document.createElement("input")
                );
                sourceInput.type = "hidden";
                sourceInput.name = "source";
                form.appendChild(
                    sourceInput
                );
            }

            sourceInput.value = source;

            const button = form.querySelector(
                'button[type="submit"], '
                + 'input[type="submit"]'
            );

            if (button) {
                const buttonLabel = (
                    displaySource
                    ? (
                        `${action.label} — `
                        + displaySource
                    )
                    : action.label
                );

                if (
                    button.tagName.toLowerCase()
                    === "input"
                ) {
                    button.value = buttonLabel;
                } else {
                    button.textContent = (
                        buttonLabel
                    );
                }
            }

            form.dataset.scopedBulkConfirm = (
                displaySource
                ? (
                    `${action.confirmText} for `
                    + `${displaySource} only?`
                )
                : (
                    `${action.confirmText} `
                    + "across ALL sources?"
                )
            );
        });
    };

    syncScopedBulkActions(
        window.location.href
    );

    document.addEventListener(
        "click",
        (event) => {
            const filterLink = (
                event.target.closest(
                    "#candidate-source-filter a"
                )
            );

            if (!filterLink) {
                return;
            }

            syncScopedBulkActions(
                filterLink.href
            );
        }
    );

    window.addEventListener(
        "popstate",
        () => {
            syncScopedBulkActions(
                window.location.href
            );
        }
    );

    document.addEventListener(
        "submit",
        (event) => {
            const form = event.target;
            const action = getScopedBulkAction(
                form
            );

            if (!action) {
                return;
            }

            syncScopedBulkActions(
                window.location.href
            );

            if (
                !window.confirm(
                    form.dataset.scopedBulkConfirm
                )
            ) {
                event.preventDefault();
            }
        },
        true
    );


})();
