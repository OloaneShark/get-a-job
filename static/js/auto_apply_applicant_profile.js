
document.addEventListener("DOMContentLoaded", () => {
    const picker = document.getElementById("applicant-location-picker");
    if (!picker) return;

    const country = document.getElementById("applicant-location-country");
    const state = document.getElementById("applicant-location-state");
    const city = document.getElementById("applicant-location-city");
    const countryValue = document.getElementById("applicant-country-value");
    const stateValue = document.getElementById("applicant-state-value");
    const cityValue = document.getElementById("applicant-city-value");

    const oldCountry = picker.dataset.currentCountry || "";
    const oldState = picker.dataset.currentState || "";
    const oldCity = picker.dataset.currentCity || "";

    function reset(select, placeholder, disabled = false) {
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
            if (value) target.searchParams.set(key, value);
        });

        const response = await fetch(target, {
            headers: {"Accept": "application/json"},
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data.message || "Location data could not be loaded."
            );
        }

        return data.items || [];
    }

    function fill(select, items, placeholder) {
        reset(select, placeholder);

        items.forEach(item => {
            const option = document.createElement("option");
            option.value = item.code || item.name;
            option.textContent = item.name;
            option.dataset.name = item.name;
            select.appendChild(option);
        });
    }

    function nameOf(select) {
        if (!select.value) return "";
        const option = select.options[select.selectedIndex];
        return (option.dataset.name || option.textContent || "").trim();
    }

    function chooseByName(select, expected) {
        const wanted = String(expected || "").trim().toLowerCase();
        if (!wanted) return false;

        for (const option of select.options) {
            const value = String(
                option.dataset.name || option.textContent || ""
            ).trim().toLowerCase();

            if (value === wanted) {
                select.value = option.value;
                return true;
            }
        }

        return false;
    }

    async function loadStates() {
        reset(state, "Choose a state / region", true);
        reset(city, "Choose a city", true);
        stateValue.value = "";
        cityValue.value = "";

        if (!country.value) return;

        const items = await fetchItems(
            picker.dataset.statesUrl,
            {country: country.value}
        );

        if (items.length) {
            fill(state, items, "Choose a state / region");
        }
    }

    async function loadCities() {
        reset(city, "Choose a city", true);
        cityValue.value = "";

        if (!country.value || !state.value) return;

        const items = await fetchItems(
            picker.dataset.citiesUrl,
            {
                country: country.value,
                state: state.value,
            }
        );

        if (items.length) {
            fill(city, items, "Choose a city");
        }
    }

    country.addEventListener("change", async () => {
        countryValue.value = nameOf(country);
        try {
            await loadStates();
        } catch (error) {
            console.error(error);
        }
    });

    state.addEventListener("change", async () => {
        stateValue.value = nameOf(state);
        try {
            await loadCities();
        } catch (error) {
            console.error(error);
        }
    });

    city.addEventListener("change", () => {
        cityValue.value = nameOf(city);
    });

    async function initialize() {
        try {
            const countries = await fetchItems(
                picker.dataset.countriesUrl
            );

            fill(country, countries, "Choose a country");

            if (chooseByName(country, oldCountry)) {
                countryValue.value = nameOf(country);
                await loadStates();

                if (chooseByName(state, oldState)) {
                    stateValue.value = nameOf(state);
                    await loadCities();

                    if (chooseByName(city, oldCity)) {
                        cityValue.value = nameOf(city);
                    }
                }
            }
        } catch (error) {
            reset(country, "Location data unavailable", true);
            console.error(error);
        }
    }

    initialize();

    const phoneCountry = document.getElementById("phone-country-select");
    const phone = document.getElementById("phone-number-input");
    const preview = document.getElementById("phone-number-preview");

    function updatePhonePreview() {
        if (!phoneCountry || !phone || !preview) return;

        const text = (
            phoneCountry.options[phoneCountry.selectedIndex]?.textContent
            || ""
        );
        const match = text.match(/\(\+(\d+)\)/);
        const number = String(phone.value || "").trim();

        if (!number) {
            preview.textContent =
                "Stored in international E.164 format after saving.";
        } else if (number.startsWith("+")) {
            preview.textContent = `International number: ${number}`;
        } else if (match) {
            preview.textContent =
                `International form: +${match[1]} ${number}`;
        } else {
            preview.textContent =
                "Choose the phone number's country.";
        }
    }

    if (phoneCountry && phone) {
        phoneCountry.addEventListener("change", updatePhonePreview);
        phone.addEventListener("input", updatePhonePreview);
        updatePhonePreview();
    }
});
