import os

from services.auto_apply_submission.browsers.playwright_browser import (
    PlaywrightBrowserSession,
)
from services.auto_apply_submission.browsers.persistent_playwright_browser import (
    PersistentPlaywrightBrowserSession,
)


def normalized_bool(
    value,
    *,
    default=False,
):
    if value is None:
        return bool(
            default
        )

    return (
        str(value)
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def create_browser_session(
    *,
    headless=None,
    default_timeout_ms=15000,
):
    mode = (
        os.getenv(
            "AUTO_APPLY_BROWSER_MODE",
            "ephemeral",
        )
        .strip()
        .lower()
    )

    if headless is None:
        headless = normalized_bool(
            os.getenv(
                "AUTO_APPLY_BROWSER_HEADLESS"
            ),
            default=(
                mode != "persistent"
            ),
        )

    if mode in {
        "",
        "ephemeral",
        "playwright",
    }:
        return PlaywrightBrowserSession(
            headless=headless,
            default_timeout_ms=(
                default_timeout_ms
            ),
        )

    if mode == "persistent":
        channel = (
            os.getenv(
                "AUTO_APPLY_BROWSER_CHANNEL",
                "chrome",
            )
            .strip()
            .lower()
        )

        profile_dir = (
            os.getenv(
                "AUTO_APPLY_BROWSER_PROFILE_DIR"
            )
            or None
        )

        return (
            PersistentPlaywrightBrowserSession(
                headless=headless,
                default_timeout_ms=(
                    default_timeout_ms
                ),
                channel=channel,
                user_data_dir=profile_dir,
            )
        )

    raise ValueError(
        "Unsupported AUTO_APPLY_BROWSER_MODE: "
        f"{mode}"
    )
