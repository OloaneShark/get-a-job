import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from services.auto_apply_submission.browsers.base import (
    BrowserSession,
)


SUPPORTED_BROWSERS = {
    "chromium",
    "chrome",
    "msedge",
    "firefox",
}


def default_profile_dir(
    browser_name,
):
    browser_name = str(
        browser_name or "chrome"
    ).strip().lower()

    local_app_data = os.getenv(
        "LOCALAPPDATA"
    )

    if local_app_data:
        return (
            Path(local_app_data)
            / "Jobfinitum"
            / "browser-profiles"
            / browser_name
        )

    xdg_data_home = os.getenv(
        "XDG_DATA_HOME"
    )

    if xdg_data_home:
        return (
            Path(xdg_data_home)
            / "jobfinitum"
            / "browser-profiles"
            / browser_name
        )

    return (
        Path.home()
        / ".local"
        / "share"
        / "jobfinitum"
        / "browser-profiles"
        / browser_name
    )


class PersistentPlaywrightBrowserSession(
    BrowserSession
):
    engine_name = "playwright_persistent"

    def __init__(
        self,
        *,
        headless=False,
        default_timeout_ms=15000,
        channel="chrome",
        user_data_dir=None,
    ):
        normalized_channel = str(
            channel or "chrome"
        ).strip().lower()

        if (
            normalized_channel
            not in SUPPORTED_BROWSERS
        ):
            raise ValueError(
                "Unsupported persistent browser "
                f"channel: {normalized_channel}"
            )

        self.headless = bool(
            headless
        )
        self.default_timeout_ms = int(
            default_timeout_ms
        )
        self.channel = normalized_channel

        self.user_data_dir = Path(
            user_data_dir
            or default_profile_dir(
                normalized_channel
            )
        ).expanduser().resolve()

        self._playwright = None
        self._context = None
        self._page = None

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError(
                "Browser session has not been started."
            )

        return self._page

    @property
    def human_handoff_available(self):
        return not self.headless

    def __enter__(self):
        self.user_data_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._playwright = (
            sync_playwright().start()
        )

        try:
            if self.channel == "firefox":
                self._context = (
                    self._playwright
                    .firefox
                    .launch_persistent_context(
                        str(
                            self.user_data_dir
                        ),
                        headless=self.headless,
                    )
                )

            else:
                launch_kwargs = {
                    "headless": self.headless,
                    "chromium_sandbox": True,
                }

                if self.channel in {
                    "chrome",
                    "msedge",
                }:
                    launch_kwargs[
                        "channel"
                    ] = self.channel

                self._context = (
                    self._playwright
                    .chromium
                    .launch_persistent_context(
                        str(
                            self.user_data_dir
                        ),
                        **launch_kwargs,
                    )
                )

            pages = list(
                self._context.pages
            )

            if pages:
                self._page = pages[0]
            else:
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
