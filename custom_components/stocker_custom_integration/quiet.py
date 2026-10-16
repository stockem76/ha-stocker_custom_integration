"""Per-camera quiet times, e.g. ``Garden=22:00-07:00; doorbell=23:30-06:30``.

No Home Assistant imports, so it can be unit tested on its own. Camera names
match case-insensitively; ``*`` applies to every camera. A camera may have
several comma-separated windows, and windows may cross midnight.
"""

from __future__ import annotations

import re
from datetime import time

Window = tuple[time, time]
QuietTimes = dict[str, list[Window]]

_RANGE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def _clock(hours: str, minutes: str) -> time:
    h, m = int(hours), int(minutes)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"{hours}:{minutes} is not a valid time")
    return time(h, m)


def parse_quiet_times(text: str | None) -> QuietTimes:
    """Parse the option text; raises ValueError with a readable message."""
    result: QuietTimes = {}
    if not text or not text.strip():
        return result
    for part in re.split(r"[;\n]+", text):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"'{part.strip()}' needs camera=HH:MM-HH:MM")
        camera, ranges = part.split("=", 1)
        camera = camera.strip().lower()
        if not camera:
            raise ValueError(f"'{part.strip()}' is missing a camera name")
        for item in ranges.split(","):
            match = _RANGE.match(item)
            if not match:
                raise ValueError(f"'{item.strip()}' should look like 22:00-07:00")
            start = _clock(match.group(1), match.group(2))
            end = _clock(match.group(3), match.group(4))
            if start == end:
                raise ValueError(f"'{item.strip()}' starts and ends at the same time")
            result.setdefault(camera, []).append((start, end))
    return result


def in_window(window: Window, now: time) -> bool:
    start, end = window
    if start < end:
        return start <= now < end
    return now >= start or now < end  # crosses midnight


def is_quiet(quiet: QuietTimes, camera: str, now: time) -> bool:
    """True if ``camera`` (or ``*``) has a quiet window covering ``now``."""
    for key in (camera.lower(), "*"):
        if any(in_window(w, now) for w in quiet.get(key, [])):
            return True
    return False
