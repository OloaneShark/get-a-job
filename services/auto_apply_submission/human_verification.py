import os
import time


DEFAULT_HANDOFF_TIMEOUT_SECONDS = 300
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


def handoff_timeout_seconds():
    raw = os.getenv(
        "AUTO_APPLY_HUMAN_HANDOFF_TIMEOUT_SECONDS",
        str(
            DEFAULT_HANDOFF_TIMEOUT_SECONDS
        ),
    )

    try:
        value = int(
            str(raw).strip()
        )
    except (TypeError, ValueError):
        return DEFAULT_HANDOFF_TIMEOUT_SECONDS

    return max(
        30,
        min(
            value,
            1800,
        ),
    )


def wait_for_user_condition(
    page,
    condition_is_still_blocking,
    *,
    label,
    timeout_seconds=None,
    poll_interval_seconds=(
        DEFAULT_POLL_INTERVAL_SECONDS
    ),
):
    timeout_seconds = (
        timeout_seconds
        if timeout_seconds is not None
        else handoff_timeout_seconds()
    )

    timeout_seconds = max(
        1,
        int(
            timeout_seconds
        ),
    )

    poll_interval_seconds = max(
        0.25,
        float(
            poll_interval_seconds
        ),
    )

    try:
        page.bring_to_front()
    except Exception:
        pass

    started = time.monotonic()
    deadline = (
        started
        + timeout_seconds
    )

    print(
        "AUTO APPLY HUMAN HANDOFF | "
        f"Waiting for user: {label}"
    )

    while time.monotonic() < deadline:
        # If the user closes the visible browser/tab, stop
        # waiting immediately. Otherwise the background
        # handoff worker remains registered as active until
        # the full timeout expires.
        browser_closed = False

        try:
            browser_closed = bool(
                page.is_closed()
            )
        except Exception:
            # A TargetClosed-style failure also means the
            # interactive page is no longer usable.
            browser_closed = True

        if not browser_closed:
            try:
                context_pages = list(
                    page.context.pages
                )

                if not context_pages:
                    browser_closed = True
            except Exception:
                browser_closed = True

        if browser_closed:
            elapsed = round(
                time.monotonic()
                - started,
                2,
            )

            print(
                "AUTO APPLY HUMAN HANDOFF | "
                f"Browser closed after "
                f"{elapsed} seconds: {label}"
            )

            return {
                "cleared": False,
                "browser_closed": True,
                "elapsed_seconds": elapsed,
                "error": (
                    "Interactive browser was closed "
                    "before the handoff completed."
                ),
            }

        try:
            if not condition_is_still_blocking(
                page
            ):
                elapsed = round(
                    time.monotonic()
                    - started,
                    2,
                )

                print(
                    "AUTO APPLY HUMAN HANDOFF | "
                    f"Human step cleared after "
                    f"{elapsed} seconds: {label}"
                )

                return {
                    "cleared": True,
                    "elapsed_seconds": elapsed,
                }

        except Exception as error:
            return {
                "cleared": False,
                "elapsed_seconds": round(
                    time.monotonic()
                    - started,
                    2,
                ),
                "error": (
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            }

        wait_ms = int(
            poll_interval_seconds
            * 1000
        )

        try:
            page.wait_for_timeout(
                wait_ms
            )
        except Exception:
            time.sleep(
                poll_interval_seconds
            )

    elapsed = round(
        time.monotonic()
        - started,
        2,
    )

    print(
        "AUTO APPLY HUMAN HANDOFF | "
        f"Resume session timed out after "
        f"{elapsed} seconds: {label}"
    )

    return {
        "cleared": False,
        "elapsed_seconds": elapsed,
        "timed_out": True,
    }
