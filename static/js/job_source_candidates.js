(() => {
    "use strict";

    const statusElement = document.getElementById(
        "candidate-action-status"
    );
    const tableContainer = document.getElementById(
        "candidate-table-container"
    );
    const emptyState = document.getElementById(
        "candidate-empty-state"
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
})();
