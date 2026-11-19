from __future__ import annotations

import asyncio

import pytest

import load_test
from load_test import RequestSpec, partition_waves, run_waves


def _spec(label: str) -> RequestSpec:
    return RequestSpec(priority=3, payload={"label": label})


@pytest.mark.asyncio
async def test_wave_two_starts_before_wave_one_completes(monkeypatch):
    wave1_started = asyncio.Event()
    wave2_started = asyncio.Event()
    release_wave1 = asyncio.Event()
    wave1_completed = False

    async def fake_run_wave(client, base_url, api_key, specs):
        nonlocal wave1_completed
        if specs[0].payload["label"] == "wave1":
            wave1_started.set()
            await release_wave1.wait()
            wave1_completed = True
            return ["wave1-result"]
        assert wave1_started.is_set()
        assert not wave1_completed
        wave2_started.set()
        release_wave1.set()
        return ["wave2-result"]

    monkeypatch.setattr(load_test, "run_wave", fake_run_wave)
    wave1, wave2 = await run_waves(
        object(), "http://proxy", "key", [_spec("wave1")], [_spec("wave2")]
    )

    assert wave2_started.is_set()
    assert wave1 == ["wave1-result"]
    assert wave2 == ["wave2-result"]


def test_partition_waves_uses_both_requested_sizes():
    specs = [_spec(str(i)) for i in range(5)]
    wave1, wave2 = partition_waves(specs, wave1=2, wave2=3)
    assert wave1 == specs[:2]
    assert wave2 == specs[2:]


@pytest.mark.parametrize(
    ("total", "wave1", "wave2"),
    [(5, 2, 2), (5, -1, 6), (5, 6, -1)],
)
def test_partition_waves_rejects_invalid_sizes(total, wave1, wave2):
    with pytest.raises(ValueError, match="wave1 \\+ wave2 must equal total"):
        partition_waves([_spec(str(i)) for i in range(total)], wave1, wave2)
