from playwright.sync_api import sync_playwright

from services.auto_apply_submission.browsers.base import (
    BrowserSession,
)


class PlaywrightBrowserSession(BrowserSession):
    engine_name = "playwright"

    def __init__(
        self,
        *,
        headless=True,
        default_timeout_ms=15000,
    ):
        self.headless = bool(
            headless
        )
        self.default_timeout_ms = int(
            default_timeout_ms
        )

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError(
                "Browser session has not been started."
            )

        return self._page

    def __enter__(self):
        self._playwright = (
            sync_playwright().start()
        )

        try:
            self._browser = (
                self._playwright
                .chromium
                .launch(
                    headless=self.headless
                )
            )

            self._context = (
                self._browser.new_context()
            )

            self._page = (
                self._context.new_page()
            )

            self._page.set_default_timeout(
                self.default_timeout_ms
            )

            return self

        except Exception:
            self.close()
            raise

    def close(self):
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            finally:
                self._context = None

        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            finally:
                self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            finally:
                self._playwright = None

        self._page = None

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.close()
        return False
