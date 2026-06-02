"""
scheduler/loader.py

Loads scenario JSON files and converts them into the domain models
used by the scheduling engine.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from scheduler.engine import (
    Route, RouteSegment, Physics, Weights, BusInput
)


def parse_time_to_minutes(t: str) -> float:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def minutes_to_hhmm(minutes: float) -> str:
    """Convert minutes since midnight to 'HH:MM' string."""
    total = int(round(minutes))
    h = (total // 60) % 24
    m = total % 60
    return f"{h:02d}:{m:02d}"


def load_scenario(path: str | Path) -> dict[str, Any]:
    """
    Load a scenario JSON file and return a dict with parsed domain objects:
    {
        'raw': <original json dict>,
        'route': Route,
        'physics': Physics,
        'weights': Weights,
        'buses': list[BusInput],
        'meta': {'id', 'name', 'description'},
    }
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Parse route
    route_data = raw["route"]
    segments = [
        RouteSegment(
            from_stop=seg["from"],
            to_stop=seg["to"],
            distance_km=seg["distance_km"],
        )
        for seg in route_data["segments"]
    ]
    route = Route(
        id=route_data["id"],
        endpoints=route_data["endpoints"],
        stations=route_data["stations"],
        segments=segments,
    )

    # Parse physics
    phys_data = raw["physics"]
    physics = Physics(
        battery_range_km=phys_data["battery_range_km"],
        charge_duration_min=phys_data["charge_duration_min"],
        speed_kmh=phys_data["speed_kmh"],
    )

    # Parse weights
    w_data = raw["weights"]
    weights = Weights(
        individual=w_data["individual"],
        operator=w_data["operator"],
        overall=w_data["overall"],
    )

    # Parse buses
    buses = [
        BusInput(
            id=b["id"],
            operator=b["operator"],
            direction=b["direction"],
            departure_min=parse_time_to_minutes(b["departure"]),
        )
        for b in raw["buses"]
    ]

    return {
        "raw": raw,
        "route": route,
        "physics": physics,
        "weights": weights,
        "buses": buses,
        "meta": {
            "id": raw["id"],
            "name": raw["name"],
            "description": raw["description"],
        },
        "stations_config": raw.get("stations_config", {}),
    }


def load_all_scenarios(scenarios_dir: str | Path) -> dict[str, dict]:
    """Load all scenario_*.json files from a directory, sorted by filename."""
    scenarios_dir = Path(scenarios_dir)
    files = sorted(scenarios_dir.glob("scenario_*.json"))
    result = {}
    for f in files:
        data = load_scenario(f)
        result[data["meta"]["name"]] = data
    return result