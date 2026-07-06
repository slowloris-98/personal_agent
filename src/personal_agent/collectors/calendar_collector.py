"""Collect today's calendar events from the primary account."""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..config import CollectConfig
from ..google_auth import get_service
from ..models import CalendarEvent

log = logging.getLogger(__name__)


def _day_bounds(tz_name: str, on_date: date | None = None) -> tuple[str, str]:
    """RFC3339 start/end of a day (default *today*) in the configured timezone."""
    tz = ZoneInfo(tz_name)
    day = on_date or datetime.now(tz).date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day, time.max, tzinfo=tz)
    return start.isoformat(), end.isoformat()


def collect(
    primary_label: str,
    collect_cfg: CollectConfig,
    warnings: list[str],
    on_date: date | None = None,
) -> list[CalendarEvent]:
    try:
        service = get_service(primary_label, "calendar", "v3")
        time_min, time_max = _day_bounds(collect_cfg.timezone, on_date)
        resp = (
            service.events()
            .list(
                calendarId=collect_cfg.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events: list[CalendarEvent] = []
        for ev in resp.get("items", []):
            start = ev.get("start", {})
            end = ev.get("end", {})
            all_day = "date" in start
            events.append(
                CalendarEvent(
                    summary=ev.get("summary", "(no title)"),
                    start=start.get("dateTime") or start.get("date", ""),
                    end=end.get("dateTime") or end.get("date", ""),
                    location=ev.get("location", ""),
                    all_day=all_day,
                )
            )
        day_label = (on_date or "today")
        log.info("Calendar[%s]: %d events (%s)", primary_label, len(events), day_label)
        return events
    except Exception as exc:  # noqa: BLE001
        msg = f"Calendar collection failed: {exc}"
        log.warning(msg)
        warnings.append(msg)
        return []
