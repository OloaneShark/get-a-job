(() => {
  "use strict";

  const sectionSelector =
    "#applications-list";

  let activeRequest = null;

  async function loadApplications(
    targetUrl,
    {updateHistory = true} = {}
  ) {
    const currentSection =
      document.querySelector(
        sectionSelector
      );

    if (!currentSection) {
      return;
    }

    if (activeRequest) {
      activeRequest.abort();
    }

    const controller =
      new AbortController();
    activeRequest = controller;

    currentSection.setAttribute(
      "aria-busy",
      "true"
    );

    try {
      const response = await fetch(
        targetUrl.href,
        {
          credentials: "same-origin",
          headers: {
            "X-Requested-With":
              "XMLHttpRequest",
          },
          signal: controller.signal,
        }
      );

      if (!response.ok) {
        throw new Error(
          `Application page request failed with ${response.status}.`
        );
      }

      const documentText =
        await response.text();
      const nextDocument =
        new DOMParser().parseFromString(
          documentText,
          "text/html"
        );
      const nextSection =
        nextDocument.querySelector(
          sectionSelector
        );

      if (!nextSection) {
        throw new Error(
          "The application list was missing from the response."
        );
      }

      currentSection.replaceWith(
        nextSection
      );

      if (updateHistory) {
        window.history.pushState(
          {},
          "",
          targetUrl.href
        );
      }

      nextSection
        .querySelector(
          '[aria-current="page"]'
        )
        ?.focus({preventScroll: true});
    } catch (error) {
      if (error.name !== "AbortError") {
        console.error(
          "Jobfinitum could not update the application page:",
          error
        );
        currentSection.removeAttribute(
          "aria-busy"
        );
      }
    } finally {
      if (activeRequest === controller) {
        activeRequest = null;
      }
    }
  }

  document.addEventListener(
    "click",
    (event) => {
      const link = event.target.closest(
        "[data-applications-page-link]"
      );

      if (!link) {
        return;
      }

      event.preventDefault();

      if (
        link.closest(".page-item")
          ?.classList.contains("disabled")
        || !link.href
      ) {
        return;
      }

      loadApplications(
        new URL(link.href)
      );
    }
  );

  document.addEventListener(
    "change",
    (event) => {
      const select = event.target.closest(
        "[data-applications-per-page]"
      );

      if (!select) {
        return;
      }

      const targetUrl = new URL(
        window.location.href
      );

      targetUrl.searchParams.set(
        "applications_per_page",
        select.value
      );
      targetUrl.searchParams.set(
        "applications_page",
        "1"
      );
      targetUrl.hash = "applications";

      loadApplications(targetUrl);
    }
  );

  window.addEventListener(
    "popstate",
    () => {
      if (
        window.location.pathname
        !== "/dashboard"
      ) {
        return;
      }

      loadApplications(
        new URL(window.location.href),
        {updateHistory: false}
      );
    }
  );
})();
