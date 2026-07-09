
function applyTheme(theme) {
    document.body.classList.remove("theme-dark", "theme-light");
    document.body.classList.add(theme);
    localStorage.setItem("theme", theme);
}

function toggleTheme() {
    const isDark = document.body.classList.contains("theme-dark");
    const nextTheme = isDark ? "theme-light" : "theme-dark";
    applyTheme(nextTheme);
}

document.addEventListener("DOMContentLoaded", function () {
    const savedTheme = localStorage.getItem("theme") || "theme-dark";
    applyTheme(savedTheme);
});
