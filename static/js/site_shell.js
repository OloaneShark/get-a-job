document.addEventListener("DOMContentLoaded", function () {
    const menus = Array.from(document.querySelectorAll(".app-nav-menu"));

    menus.forEach(function (menu) {
        menu.addEventListener("toggle", function () {
            if (!menu.open) {
                return;
            }

            menus.forEach(function (otherMenu) {
                if (otherMenu !== menu) {
                    otherMenu.open = false;
                }
            });
        });
    });

    document.addEventListener("click", function (event) {
        if (event.target.closest(".app-nav-menu")) {
            return;
        }

        menus.forEach(function (menu) {
            menu.open = false;
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") {
            return;
        }

        menus.forEach(function (menu) {
            menu.open = false;
        });
    });
});
