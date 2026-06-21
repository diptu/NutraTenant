"""Best-effort, dependency-free "<browser> on <OS>" label for a raw User-Agent
string — purely a display convenience for the login session payload, never
used for any security decision (fingerprinting/authorization stays off the
parsed result on purpose; spoofing a UA is trivial).
"""

from __future__ import annotations

import re

_BROWSER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/")),
    ("Opera", re.compile(r"OPR/|Opera/")),
    ("Chrome", re.compile(r"Chrome/")),
    ("Firefox", re.compile(r"Firefox/")),
    ("Safari", re.compile(r"Version/.*Safari/")),
)

_OS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Android", re.compile(r"Android")),
    ("macOS", re.compile(r"Mac OS X")),
    ("Windows", re.compile(r"Windows")),
    ("Linux", re.compile(r"Linux")),
)


def describe_device(user_agent: str | None) -> str:
    if not user_agent:
        return "Unknown device"

    browser = next(
        (name for name, pattern in _BROWSER_PATTERNS if pattern.search(user_agent)),
        None,
    )
    os_name = next((name for name, pattern in _OS_PATTERNS if pattern.search(user_agent)), None)

    if browser and os_name:
        return f"{browser} on {os_name}"
    if browser:
        return browser
    if os_name:
        return os_name
    return "Unknown device"
