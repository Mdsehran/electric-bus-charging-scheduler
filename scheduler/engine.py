"""
scheduler/engine.py

Bus Charging Scheduler - Core Engine
Architecture: Priority-Queue Weighted Greedy Simulation

Key insight: The scheduler must DISTRIBUTE buses across valid station plans
to minimize contention. It does this by scoring each valid plan using a
weighted cost function that considers:
  1. individual  - how long THIS bus will wait
  2. operator    - how much THIS operator's fleet has already waited (fairness)  
  3. overall     - total trip duration impact on the network

Weights are read from scenario files - changing a weight is one JSON edit.
Adding a new rule = adding one cost term to score_plan(). Engine unchanged.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------

@dataclass
class RouteSegment:
    from_stop: str
    to_stop: str
    distance_km: float


@dataclass
class Route:
    id: str
    endpoints: List[str]       # [origin, destination] in BK order
    stations: List[str]        # charging stations in BK order: [A, B, C, D]
    segments: List[RouteSegment]  # ordered BK segments

    def stations_for_direction(self, direction: str) -> List[str]:
        """Stations in travel order for this direction."""
        return list(self.stations) if direction == "BK" else list(reversed(self.stations))

    def cumulative_distances(self, direction: str) -> Dict[str, float]:
        """
        Distance from origin to each stop for the given direction.
        BK: BLR=0, A=100, B=220, C=320, D=440, Kochi=540
        KB: Kochi=0, D=100, C=220, B=320, A=440, BLR=540
        """
        segs = self.segments if direction == "BK" else list(reversed(self.segments))
        cum = {}
        d = 0.0
        for seg in segs:
            stop = seg.to_stop if direction == "BK" else seg.from_stop
            d += seg.distance_km
            cum[stop] = d
        return cum

    def total_distance(self) -> float:
        return sum(s.distance_km for s in self.segments)


@dataclass
class Physics:
    battery_range_km: float
    charge_duration_min: float
    speed_kmh: float

    def travel_time_min(self, distance_km: float) -> float:
        return (distance_km / self.speed_kmh) * 60.0


@dataclass
class Weights:
    individual: float   # penalise per-bus waiting
    operator: float     # penalise operator-level avg waiting
    overall: float      # penalise total network trip time


@dataclass
class BusInput:
    id: str
    operator: str
    direction: str        # 'BK' or 'KB'
    departure_min: float  # minutes since midnight


@dataclass
class ChargeEvent:
    station: str
    arrive_min: float     # when bus physically arrives at station
    charge_start: float   # when charging actually begins (>= arrive if waiting)
    charge_end: float     # charge_start + charge_duration_min
    wait_min: float       # charge_start - arrive_min


@dataclass
class BusResult:
    bus: BusInput
    charge_events: List[ChargeEvent]
    departure_min: float
    arrival_min: float
    total_wait_min: float

    @property
    def trip_duration_min(self) -> float:
        return self.arrival_min - self.departure_min


# ---------------------------------------------------------------------------
# Plan Generator: all valid charging station subsets
# ---------------------------------------------------------------------------

def generate_valid_plans(
    bus: BusInput,
    route: Route,
    physics: Physics,
) -> List[List[str]]:
    """
    Enumerate all valid charging plans for a bus.
    A plan is a list of stations (in travel order) where the bus charges.
    Valid = no gap between consecutive charge points exceeds battery_range_km.

    For 4 stations: 2^4 = 16 subsets to check. Fast even for 20 stations.
    """
    stations = route.stations_for_direction(bus.direction)
    cum = route.cumulative_distances(bus.direction)
    total = route.total_distance()
    rng = physics.battery_range_km
    n = len(stations)

    valid = []
    for mask in range(1 << n):
        chosen = [stations[i] for i in range(n) if mask & (1 << i)]
        # Build sequence: origin(0) -> chosen stations -> destination(total)
        seq = [0.0] + [cum[s] for s in chosen] + [total]
        if all(seq[i+1] - seq[i] <= rng + 1e-9 for i in range(len(seq) - 1)):
            valid.append(chosen)

    return valid


# ---------------------------------------------------------------------------
# Cost function: estimate cost of a plan given current system state
# ---------------------------------------------------------------------------

def estimate_plan_cost(
    plan: List[str],
    bus: BusInput,
    route: Route,
    physics: Physics,
    station_free_at: Dict[str, float],
    op_avg_wait: Dict[str, float],
    weights: Weights,
) -> float:
    """
    Estimate the weighted cost of executing a charging plan for a bus.
    Lower = better. This is the ONLY place weights are used.

    Cost = w_individual * (total wait this bus incurs)
         + w_operator   * (avg wait already accumulated by this operator)
         + w_overall    * (total trip duration)

    To add a new soft rule: add one term here + one weight field.
    Nothing else changes.
    """
    cum = route.cumulative_distances(bus.direction)
    total = route.total_distance()

    current_time = bus.departure_min
    current_dist = 0.0
    total_wait = 0.0

    for station in plan:
        dist = cum[station]
        travel = physics.travel_time_min(dist - current_dist)
        arrive = current_time + travel
        free_at = station_free_at.get(station, 0.0)
        charge_start = max(arrive, free_at)
        wait = charge_start - arrive
        total_wait += wait
        current_time = charge_start + physics.charge_duration_min
        current_dist = dist

    # Time to reach destination after last charge
    remaining = total - current_dist
    current_time += physics.travel_time_min(remaining)
    trip_duration = current_time - bus.departure_min

    # Operator fairness: how much has this operator's fleet waited so far
    op_wait = op_avg_wait.get(bus.operator, 0.0)

    cost = (
        weights.individual * total_wait
        + weights.operator  * op_wait
        + weights.overall   * trip_duration
    )
    return cost


# ---------------------------------------------------------------------------
# Main Scheduler
# ---------------------------------------------------------------------------

def run_scheduler(
    buses: List[BusInput],
    route: Route,
    physics: Physics,
    weights: Weights,
) -> List[BusResult]:
    """
    Weighted greedy scheduling simulation.

    For each bus (in departure order):
      1. Generate all valid charging plans
      2. Score each plan with the weighted cost function
         (sees current station congestion + operator fairness state)
      3. Pick lowest-cost plan — this naturally distributes buses across
         stations to avoid congestion
      4. Book charger slots, update system state
      5. Update operator wait statistics for subsequent buses

    This means bus-BK-02 will pick [B,D] if station A is already backed up,
    because [A,C] will score higher (more wait) than [B,D] (no wait).
    The weight values control exactly how aggressively this happens.

    Complexity: O(n * 2^s) plan generation + O(n * s) simulation
    Scales to hundreds of buses and dozens of stations without rewrite.
    """
    # Station charger availability: when is each charger next free?
    # Future extension: list per station for multiple chargers
    station_free_at: Dict[str, float] = {s: 0.0 for s in route.stations}

    # Operator wait tracking for fairness weight
    op_total_wait: Dict[str, float] = {}
    op_bus_count:  Dict[str, int]   = {}

    results: List[BusResult] = []

    # Process buses in departure order (first-come-first-served baseline)
    sorted_buses = sorted(buses, key=lambda b: b.departure_min)

    for bus in sorted_buses:
        # 1. Generate all valid plans
        plans = generate_valid_plans(bus, route, physics)
        if not plans:
            raise ValueError(
                f"No valid plan for {bus.id}! "
                f"Check battery_range_km vs route segment distances."
            )

        # 2. Compute operator avg wait for cost function
        op_avg_wait = {
            op: op_total_wait.get(op, 0.0) / max(op_bus_count.get(op, 1), 1)
            for op in set(b.operator for b in buses)
        }

        # 3. Score every plan, pick the lowest-cost one
        best_plan = min(
            plans,
            key=lambda p: estimate_plan_cost(
                p, bus, route, physics,
                station_free_at, op_avg_wait, weights
            )
        )

        # 4. Simulate the chosen plan and book charger slots
        cum = route.cumulative_distances(bus.direction)
        total = route.total_distance()

        charge_events: List[ChargeEvent] = []
        current_time = bus.departure_min
        current_dist = 0.0

        for station in best_plan:
            dist = cum[station]
            travel = physics.travel_time_min(dist - current_dist)
            arrive = current_time + travel

            free_at = station_free_at.get(station, 0.0)
            charge_start = max(arrive, free_at)
            wait = charge_start - arrive
            charge_end = charge_start + physics.charge_duration_min

            # Book this charger slot
            station_free_at[station] = charge_end

            charge_events.append(ChargeEvent(
                station=station,
                arrive_min=arrive,
                charge_start=charge_start,
                charge_end=charge_end,
                wait_min=wait,
            ))

            current_time = charge_end
            current_dist = dist

        # Final leg to destination
        remaining = total - current_dist
        arrival_min = current_time + physics.travel_time_min(remaining)
        total_wait = sum(e.wait_min for e in charge_events)

        # 5. Update operator stats
        op_total_wait[bus.operator] = op_total_wait.get(bus.operator, 0.0) + total_wait
        op_bus_count[bus.operator]  = op_bus_count.get(bus.operator, 0) + 1

        results.append(BusResult(
            bus=bus,
            charge_events=charge_events,
            departure_min=bus.departure_min,
            arrival_min=arrival_min,
            total_wait_min=total_wait,
        ))

    return results