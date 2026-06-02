# ARCHITECTURE.md

## Scheduling Framework: Weighted-Cost Event-Driven Greedy Simulation

---

### Why this approach?

The problem is a **contention scheduling problem**: multiple buses arrive at shared chargers at overlapping times, and we need to decide who goes first using tunable soft rules.

I evaluated three approaches:

| Approach | Pros | Cons |
|---|---|---|
| Rule-based priority queues | Simple, fast | Hard to tune, rules conflict |
| Integer Linear Programming (ILP) | Globally optimal | Slow, opaque, hard to extend |
| **Weighted-Cost Greedy Simulation** | Fast, transparent, tunable, extensible | Locally greedy (not globally optimal) |

I chose **Weighted-Cost Greedy Simulation** because:

1. **Tuning is trivial** — weights are a single dict. Change a number → behaviour changes. Nothing else touches weights.
2. **New rules = new cost terms** — add a line to `score_plan()`. The engine loop doesn't change.
3. **Scales naturally** — time complexity is O(n × 2^s) for plan generation (n buses, s ≤ 4 stations = 16 plans max) plus O(n × s) for simulation. 1000 buses, 10 stations = still fast.
4. **Transparent** — every decision is a deterministic function of weights + state. You can explain exactly why bus X went before bus Y.
5. **Field-learning friendly** — when operators learn what weights actually matter, it's a one-line change in a JSON file.

The key insight: **global optimality is not the goal**. The spec says to weigh three soft rules — that's exactly a cost function. A greedy simulation with a cost function is the natural fit.

---

### How the scheduler works

```
For each bus (sorted by departure time):
  1. Generate all valid charging plans (subsets of stations satisfying range constraint)
  2. Score each plan using weighted cost function:
       cost = w_individual × estimated_wait_this_bus
            + w_operator   × avg_wait_already_accumulated_by_this_operator
            + w_overall    × estimated_trip_duration
  3. Choose the lowest-cost plan
  4. Book charger slots: if charger free → charge immediately; if busy → wait
  5. Update operator statistics for subsequent buses
```

The cost function runs on **current system state** — it sees how backed-up each station is, how much each operator's fleet has already waited, and picks the plan that best balances the three objectives.

---

### Data Structure Design

Every scenario is a self-contained JSON file. I designed it to be a **world description**, not just a schedule — everything the scheduler needs lives in one file.

```json
{
  "id": "scenario_1",
  "name": "...",
  "description": "...",
  "route": {
    "id": "blr_kochi",
    "endpoints": ["Bengaluru", "Kochi"],
    "stations": ["A", "B", "C", "D"],
    "segments": [
      {"from": "Bengaluru", "to": "A", "distance_km": 100},
      ...
    ]
  },
  "physics": {
    "battery_range_km": 240,
    "charge_duration_min": 25,
    "speed_kmh": 60
  },
  "stations_config": {
    "A": {"chargers": 1},
    ...
  },
  "weights": {
    "individual": 1.0,
    "operator": 1.0,
    "overall": 1.0
  },
  "buses": [
    {"id": "bus-BK-01", "operator": "kpn", "direction": "BK", "departure": "19:00"},
    ...
  ]
}
```

Key design decisions:

- **Route is data, not code.** Segments, distances, station names — all in JSON. Add a station = edit JSON.
- **Physics is data, not constants.** Battery range, charge time, speed — all overridable per scenario. A future scenario with faster buses or larger batteries just changes these values.
- **Weights are per-scenario.** Scenario 4 has `operator: 2.0` baked in. Reviewers and operators can see and override weights per scenario.
- **Direction is a string.** "BK" / "KB" today. Could be "BK1", "express", "night" tomorrow — no code change.
- **Operator is a string.** Any new operator name in the JSON is automatically tracked, no enum to update.
- **`stations_config` is separate from `route.stations`.** Stations are an ordered list for routing; config holds per-station properties (chargers, pricing, capacity). Decoupled intentionally.

---

### Changes I anticipated and how the design handles them

| Future change | What changes | Code change? |
|---|---|---|
| Add a 5th or 6th station mid-route | Add to `route.stations`, `route.segments`, `stations_config` | ❌ None |
| Increase chargers at station B to 2 | Edit `stations_config.B.chargers` | Minimal — engine needs to track per-charger slots (one dict → list of slots) |
| Add a new operator (e.g. "greenbus") | Add buses with `"operator": "greenbus"` | ❌ None — operator is a string key |
| Change segment distances | Edit `route.segments[i].distance_km` | ❌ None |
| Change travel speed | Edit `physics.speed_kmh` | ❌ None |
| Different battery range | Edit `physics.battery_range_km` | ❌ None |
| Different charging time | Edit `physics.charge_duration_min` | ❌ None |
| Add a new weight dimension (e.g. "priority") | Add field to `weights` + one line in `score_plan()` | ~3 lines |
| Priority buses (e.g. medical, express) | Add `"priority": true` to bus entry, add cost term | ~5 lines in engine |
| Time-of-day electricity pricing | Add `"peak_hours": [...]` to `stations_config`, add cost term | ~5 lines |
| Multiple routes sharing stations | Each scenario has its own `route.id`; scheduler already works per-scenario | Trivial |
| Driver shift constraints | Add `"shift_end": "23:00"` to bus entry, add hard constraint in plan validation | ~8 lines |
| More than 20 buses | Add more entries to `buses[]` | ❌ None |
| Partial charging (not always full) | Add `physics.charge_to_pct` field, update energy tracking | ~15 lines |
| Buses with different battery sizes | Add `battery_range_km` per bus (overrides physics default) | ~5 lines |
| A new scenario | Copy JSON, edit departure times | ❌ No code |
| Encode a fresh schedule in the interview | Fill `buses[]` array | ❌ No code |

---

### How to change a weight

Find the scenario file. Change the number. Done.

```json
// Before
"weights": { "individual": 1.0, "operator": 1.0, "overall": 1.0 }

// After — emphasise operator fairness
"weights": { "individual": 1.0, "operator": 3.0, "overall": 1.0 }
```

The scheduler reads `weights` from the file at runtime. No code touched.

---

### How to add a new soft rule

**Example: penalise buses that are behind their scheduled arrival (lateness penalty)**

1. In `scheduler/engine.py`, add to the `Weights` dataclass:
```python
@dataclass
class Weights:
    individual: float
    operator: float
    overall: float
    lateness: float = 0.0   # ← add this
```

2. In `score_plan()`, add one cost term:
```python
scheduled_arrival = bus.departure_min + physics.travel_time_min(total_distance)
lateness = max(0, trip_duration - (scheduled_arrival - bus.departure_min))
cost += weights.lateness * lateness
```

3. In scenario JSON:
```json
"weights": { "individual": 1.0, "operator": 1.0, "overall": 1.0, "lateness": 0.5 }
```

That's it. The engine loop is untouched. No rewrite.

---

### How to add a hard rule

**Example: mandatory stop at station B for all buses (e.g. safety inspection)**

In `generate_charging_plans()`, add a filter:

```python
# After generating chosen subset
if bus.get("mandatory_stop") and bus["mandatory_stop"] not in [s for s, _ in chosen]:
    continue  # skip this plan — violates hard constraint
```

Add to bus JSON: `"mandatory_stop": "B"`

---

### Assumptions made

1. **All buses leave their origin with full charge** (spec states this explicitly — Bengaluru and Kochi have slow chargers).

2. **Buses process in departure order** for the greedy pass. This is fair because earlier-departing buses encounter stations first. Ties (simultaneous departures) are broken by arrival order at the station.

3. **Charging always fills to 100%** — the spec says "always to full, takes 25 minutes." No partial charging.

4. **No bus can skip past a station it needs** — buses visit stations in route order only.

5. **A bus may charge 0, 1, 2, 3, or 4 times** depending on the range constraint. The scheduler picks the number that minimises cost, not always the minimum required. (Example: a bus could charge 2 times at non-contended stations rather than 2 times at heavily contended ones.)

6. **Station charger is atomic** — a bus either occupies the charger or waits. No pre-emption.

7. **Speed is constant** — no traffic modelling. This is per spec.

8. **The endpoints (Bengaluru, Kochi) are not scheduling concerns** — per spec. Slow chargers there are outside scope.

9. **A plan with 0 charging stops is valid if total route ≤ battery range.** The BLR-Kochi route is 540 km vs 240 km range, so this never happens in practice, but the engine handles it correctly.

10. **`direction: "BK"` = Bengaluru → Kochi; `"KB"` = reverse.** Stations are traversed in opposite order.

---

### What I'd improve given more time

- **Multiple chargers per station**: extend `station_free_at` to a list of slot end-times per station, pick earliest available.
- **Global re-optimisation pass**: after the greedy pass, run a local search (swap two buses at a contended station) to escape greedy local optima.
- **Streaming/live simulation**: extend the event model to handle buses arriving mid-run (useful for real-time ops).
- **Conflict validation layer**: explicit validator that checks all hard rules after scheduling, logs any violations.
