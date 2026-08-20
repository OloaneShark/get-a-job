document.addEventListener("DOMContentLoaded", () => {
    const picker = document.getElementById("location-picker");
    const hiddenLocations = document.getElementById("locations-field");

    if (!picker || !hiddenLocations) {
        return;
    }

    const countrySelect = document.getElementById("location-country");
    const stateSelect = document.getElementById("location-state");
    const citySelect = document.getElementById("location-city");
    const addButton = document.getElementById("add-location-button");
    const selectedLocations = document.getElementById("selected-locations");

    const employmentCheckboxes = Array.from(
        document.querySelectorAll(".employment-type-checkbox")
    );
    const employmentSummary = document.getElementById(
        "employment-type-summary"
    );

    const splitStoredLocations = value => (
        String(value || "")
            .split(/[\n,]+/)
            .map(item => item.trim())
            .filter(Boolean)
    );

    let locationValues = Array.from(
        new Set(splitStoredLocations(hiddenLocations.value))
    );

    function syncLocationField() {
        hiddenLocations.value = locationValues.join("\n");
    }

    function renderLocationChips() {
        selectedLocations.innerHTML = "";

        if (locationValues.length === 0) {
            const empty = document.createElement("span");
            empty.className = "form-text";
            empty.textContent = "No locations selected yet.";
            selectedLocations.appendChild(empty);
            return;
        }

        locationValues.forEach(location => {
            const chip = document.createElement("span");
            chip.className = "selected-location-chip";

            const text = document.createElement("span");
            text.textContent = location;

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "selected-location-remove";
            remove.setAttribute("aria-label", `Remove ${location}`);
            remove.textContent = "×";

            remove.addEventListener("click", () => {
                locationValues = locationValues.filter(
                    value => value !== location
                );
                syncLocationField();
                renderLocationChips();
            });

            chip.appendChild(text);
            chip.appendChild(remove);
            selectedLocations.appendChild(chip);
        });
    }

    function resetSelect(select, placeholder, disabled = false) {
        select.innerHTML = "";

        const option = document.createElement("option");
        option.value = "";
        option.textContent = placeholder;

        select.appendChild(option);
        select.disabled = disabled;
    }

    async function fetchItems(url, params = {}) {
        const target = new URL(url, window.location.origin);

        Object.entries(params).forEach(([key, value]) => {
            if (value) {
                target.searchParams.set(key, value);
            }
        });

        const response = await fetch(target, {
            headers: {
                "Accept": "application/json",
            },
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data.message || "Location data could not be loaded."
            );
        }

        return data.items || [];
    }

    function populateSelect(select, items, placeholder) {
        resetSelect(select, placeholder, false);

        items.forEach(item => {
            const option = document.createElement("option");
            option.value = item.code || item.name;
            option.textContent = item.name;
            option.dataset.name = item.name;
            select.appendChild(option);
        });
    }

    async function loadCountries() {
        try {
            countrySelect.disabled = true;

            const items = await fetchItems(
                picker.dataset.countriesUrl
            );

            populateSelect(
                countrySelect,
                items,
                "Choose a country"
            );

            addButton.disabled = true;
        } catch (error) {
            resetSelect(
                countrySelect,
                "Location data unavailable",
                true
            );
            console.error(error);
        }
    }

    countrySelect.addEventListener("change", async () => {
        resetSelect(
            stateSelect,
            "Any state / region",
            true
        );
        resetSelect(
            citySelect,
            "Any city",
            true
        );

        addButton.disabled = !countrySelect.value;

        if (!countrySelect.value) {
            return;
        }

        try {
            const items = await fetchItems(
                picker.dataset.statesUrl,
                {
                    country: countrySelect.value,
                }
            );

            if (items.length > 0) {
                populateSelect(
                    stateSelect,
                    items,
                    "Any state / region"
                );
            }
        } catch (error) {
            console.error(error);
        }
    });

    stateSelect.addEventListener("change", async () => {
        resetSelect(
            citySelect,
            "Any city",
            true
        );

        if (!stateSelect.value) {
            return;
        }

        try {
            const items = await fetchItems(
                picker.dataset.citiesUrl,
                {
                    country: countrySelect.value,
                    state: stateSelect.value,
                }
            );

            if (items.length > 0) {
                populateSelect(
                    citySelect,
                    items,
                    "Any city"
                );
            }
        } catch (error) {
            console.error(error);
        }
    });

    addButton.addEventListener("click", () => {
        if (!countrySelect.value) {
            return;
        }

        const selectedCountry = (
            countrySelect.options[
                countrySelect.selectedIndex
            ]?.dataset.name
            || countrySelect.options[
                countrySelect.selectedIndex
            ]?.textContent
            || ""
        ).trim();

        const selectedState = (
            stateSelect.value
            ? (
                stateSelect.options[
                    stateSelect.selectedIndex
                ]?.dataset.name
                || stateSelect.options[
                    stateSelect.selectedIndex
                ]?.textContent
                || ""
            ).trim()
            : ""
        );

        const selectedCity = (
            citySelect.value
            ? (
                citySelect.options[
                    citySelect.selectedIndex
                ]?.dataset.name
                || citySelect.options[
                    citySelect.selectedIndex
                ]?.textContent
                || ""
            ).trim()
            : ""
        );

        // Keep the existing matcher semantics: store only the most-specific
        // selected level (city, otherwise state/region, otherwise country).
        const value = (
            selectedCity
            || selectedState
            || selectedCountry
        );

        if (
            value
            && !locationValues.some(
                item => (
                    item.toLowerCase()
                    === value.toLowerCase()
                )
            )
        ) {
            locationValues.push(value);
            syncLocationField();
            renderLocationChips();
        }
    });

    function updateEmploymentSummary() {
        const checked = employmentCheckboxes.filter(
            checkbox => checkbox.checked
        );

        const labels = checked.map(
            checkbox => (
                checkbox.closest("label")
                    ?.querySelector("span")
                    ?.textContent
                    ?.trim()
                || checkbox.value
            )
        );

        if (
            checked.length === 0
            || checked.some(
                checkbox => checkbox.value === "all"
            )
        ) {
            employmentSummary.textContent =
                "Any employment type";
            return;
        }

        if (labels.length <= 2) {
            employmentSummary.textContent =
                labels.join(", ");
            return;
        }

        employmentSummary.textContent =
            `${labels.length} employment types selected`;
    }

    employmentCheckboxes.forEach(checkbox => {
        checkbox.addEventListener("change", () => {
            if (
                checkbox.value === "all"
                && checkbox.checked
            ) {
                employmentCheckboxes.forEach(other => {
                    if (other !== checkbox) {
                        other.checked = false;
                    }
                });
            } else if (checkbox.checked) {
                const anyCheckbox = employmentCheckboxes.find(
                    item => item.value === "all"
                );

                if (anyCheckbox) {
                    anyCheckbox.checked = false;
                }
            }

            if (
                !employmentCheckboxes.some(
                    item => item.checked
                )
            ) {
                const anyCheckbox = employmentCheckboxes.find(
                    item => item.value === "all"
                );

                if (anyCheckbox) {
                    anyCheckbox.checked = true;
                }
            }

            updateEmploymentSummary();
        });
    });

    syncLocationField();
    renderLocationChips();
    updateEmploymentSummary();
    loadCountries();
});
