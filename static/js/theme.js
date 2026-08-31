const JOBFINITUM_THEME_STORAGE_KEY = "jobfinitum-theme-v2";
const JOBFINITUM_THEME_TRANSITION_CLASS = "jobfinitum-theme-transition";
const JOBFINITUM_THEME_TO_DARK_CLASS = "jobfinitum-theme-to-dark";
const JOBFINITUM_THEME_TO_LIGHT_CLASS = "jobfinitum-theme-to-light";
let jobfinitumThemeTransitionActive = false;

function normalizeTheme(theme) {
    return theme === "theme-dark" ? "theme-dark" : "theme-light";
}

function updateThemeToggleAccessibility(theme) {
    const nextThemeName = theme === "theme-dark" ? "light" : "dark";

    document.querySelectorAll(
        ".app-utility-button, .public-theme-toggle"
    ).forEach(function (toggle) {
        toggle.setAttribute("aria-label", "Switch to " + nextThemeName + " mode");
        toggle.setAttribute("title", "Switch to " + nextThemeName + " mode");
        toggle.setAttribute("aria-pressed", String(theme === "theme-dark"));
    });
}

function applyTheme(theme) {
    const normalizedTheme = normalizeTheme(theme);

    document.documentElement.dataset.jobfinitumTheme = normalizedTheme;
    document.body.classList.remove("theme-dark", "theme-light");
    document.body.classList.add(normalizedTheme);
    updateThemeToggleAccessibility(normalizedTheme);

    try {
        localStorage.setItem(JOBFINITUM_THEME_STORAGE_KEY, normalizedTheme);
    } catch (error) {
        // The active page still receives the theme when storage is unavailable.
    }
}

function isPublicSplashPage() {
    return Boolean(document.querySelector("[data-public-home]"));
}

function isThemeToggleElement(element) {
    return Boolean(
        element
        && element.nodeType === 1
        && element.matches(".app-utility-button, .public-theme-toggle")
    );
}

function findThemeToggle(toggleElement) {
    if (isThemeToggleElement(toggleElement)) {
        return toggleElement;
    }

    if (isThemeToggleElement(document.activeElement)) {
        return document.activeElement;
    }

    return document.querySelector(
        document.body.classList.contains("app-authenticated")
            ? ".app-utility-button"
            : ".public-theme-toggle"
    );
}

function getThemeTransitionGeometry(toggleElement) {
    const toggle = findThemeToggle(toggleElement);
    const rect = toggle ? toggle.getBoundingClientRect() : null;
    const originX = rect
        ? rect.left + rect.width / 2
        : window.innerWidth / 2;
    const originY = rect
        ? rect.top + rect.height / 2
        : window.innerHeight / 2;
    const farthestX = Math.max(originX, window.innerWidth - originX);
    const farthestY = Math.max(originY, window.innerHeight - originY);

    return {
        x: originX,
        y: originY,
        radius: Math.ceil(Math.hypot(farthestX, farthestY)) + 2,
    };
}

function finishThemeTransition(scrollPosition) {
    const root = document.documentElement;

    root.classList.remove(
        JOBFINITUM_THEME_TRANSITION_CLASS,
        JOBFINITUM_THEME_TO_DARK_CLASS,
        JOBFINITUM_THEME_TO_LIGHT_CLASS
    );
    root.style.removeProperty("--jf-theme-transition-x");
    root.style.removeProperty("--jf-theme-transition-y");
    root.style.removeProperty("--jf-theme-transition-radius");
    jobfinitumThemeTransitionActive = false;

    if (
        scrollPosition
        && (
            window.scrollX !== scrollPosition.x
            || window.scrollY !== scrollPosition.y
        )
    ) {
        window.scrollTo(scrollPosition.x, scrollPosition.y);
    }
}

function toggleTheme(toggleElement) {
    if (jobfinitumThemeTransitionActive) {
        return;
    }

    const isDark = document.body.classList.contains("theme-dark");
    const goingDark = !isDark;
    const nextTheme = isDark ? "theme-light" : "theme-dark";
    const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
    ).matches;

    if (
        isPublicSplashPage()
        || reduceMotion
        || typeof document.startViewTransition !== "function"
    ) {
        applyTheme(nextTheme);
        return;
    }

    const geometry = getThemeTransitionGeometry(toggleElement);
    const root = document.documentElement;
    const scrollPosition = {
        x: window.scrollX,
        y: window.scrollY,
    };

    root.style.setProperty("--jf-theme-transition-x", geometry.x + "px");
    root.style.setProperty("--jf-theme-transition-y", geometry.y + "px");
    root.style.setProperty(
        "--jf-theme-transition-radius",
        geometry.radius + "px"
    );
    root.classList.add(
        JOBFINITUM_THEME_TRANSITION_CLASS,
        goingDark
            ? JOBFINITUM_THEME_TO_DARK_CLASS
            : JOBFINITUM_THEME_TO_LIGHT_CLASS
    );
    jobfinitumThemeTransitionActive = true;

    try {
        const transition = document.startViewTransition(function () {
            applyTheme(nextTheme);

            if (
                window.scrollX !== scrollPosition.x
                || window.scrollY !== scrollPosition.y
            ) {
                window.scrollTo(scrollPosition.x, scrollPosition.y);
            }
        });

        transition.finished.then(
            function () {
                finishThemeTransition(scrollPosition);
            },
            function () {
                finishThemeTransition(scrollPosition);
            }
        );
    } catch (error) {
        applyTheme(nextTheme);
        finishThemeTransition(scrollPosition);
    }
}

document.addEventListener("DOMContentLoaded", function () {
    let storedTheme = "theme-light";

    try {
        storedTheme = localStorage.getItem(JOBFINITUM_THEME_STORAGE_KEY)
            || storedTheme;
    } catch (error) {
        storedTheme = "theme-light";
    }

    const savedTheme = (
        document.documentElement.dataset.jobfinitumTheme
        || storedTheme
    );

    applyTheme(savedTheme);
});
