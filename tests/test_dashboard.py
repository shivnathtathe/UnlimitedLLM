from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest

import main
from app.config import Settings
from app.proxy import DASHBOARD_LINES, _dashboard_loop, _render_dashboard


def _status(window_count=8, in_flight=3, queue_depth=5, total_fired=21):
    return {
        "max_rpm": 40,
        "window_count": window_count,
        "in_flight": in_flight,
        "queue_depth": queue_depth,
        "total_fired": total_fired,
        "window_resets_in": 12.34,
    }


def test_dashboard_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DASHBOARD_ENABLED", raising=False)
    assert Settings().dashboard_enabled is False


def test_dashboard_enabled_from_environment(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    assert Settings().dashboard_enabled is True


def test_render_dashboard_contains_live_limiter_values():
    dashboard = _render_dashboard(_status())
    lines = dashboard.splitlines()
    assert len(lines) == DASHBOARD_LINES
    assert "8/40" in lines[0]
    assert lines[1].endswith("3")
    assert lines[2].endswith("5")
    assert lines[3].endswith("21")
    assert lines[4].endswith("12.3s")


@pytest.mark.asyncio
async def test_dashboard_redraws_in_place(monkeypatch):
    output = io.StringIO()
    statuses = iter((_status(), _status(window_count=9, total_fired=22)))

    class Limiter:
        def status(self):
            return next(statuses)

    sleeps = 0

    async def stop_after_second_frame(delay):
        nonlocal sleeps
        assert delay == 1
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("app.proxy.sys.stdout", output)
    monkeypatch.setattr("app.proxy.asyncio.sleep", stop_after_second_frame)

    with pytest.raises(asyncio.CancelledError):
        await _dashboard_loop(Limiter())

    rendered = output.getvalue()
    assert "8/40" in rendered
    assert "9/40" in rendered
    assert f"\033[{DASHBOARD_LINES}A" in rendered
    assert rendered.count("\033[2K\r") == DASHBOARD_LINES * 2


@pytest.mark.parametrize(
    ("dashboard_enabled", "expected_access_log"), [(False, True), (True, False)]
)
def test_main_toggles_uvicorn_access_logs(
    monkeypatch, dashboard_enabled, expected_access_log
):
    settings = SimpleNamespace(
        host="127.0.0.1", port=8000, max_rpm=40, dashboard_enabled=dashboard_enabled
    )
    app = object()
    calls: list[dict] = []
    disabled_levels: list[int] = []

    monkeypatch.setattr(main, "Settings", lambda: settings)
    monkeypatch.setattr(main.logging, "disable", disabled_levels.append)
    monkeypatch.setattr(main, "print_banner", lambda value: None)
    monkeypatch.setattr(main, "create_app", lambda value: app)
    monkeypatch.setattr(
        main.uvicorn,
        "run",
        lambda passed_app, **kwargs: calls.append({"app": passed_app, **kwargs}),
    )

    main.main()

    assert calls == [
        {
            "app": app,
            "host": "127.0.0.1",
            "port": 8000,
            "log_level": "info",
            "access_log": expected_access_log,
        }
    ]
    expected_level = main.logging.CRITICAL if dashboard_enabled else main.logging.NOTSET
    assert disabled_levels == [expected_level]
