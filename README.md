# Bus Charging Scheduler

**Electric bus charging scheduler for fixed routes, built with Python + Streamlit.**

Live demo: `https://electric-bus-charging-scheduler-amak4suerf4rmtzced8akj.streamlit.app/`  
GitHub: `https://github.com/Mdsehran/electric-bus-charging-scheduler`

---

## Running locally

```bash
# 1. Clone
git clone https://github.com/Mdsehran/electric-bus-charging-scheduler.git
cd bus-charging-scheduler

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## How to change a weight

Weights live in each scenario's JSON file. Open e.g. `scenarios/scenario_1.json` and edit:

```json
"weights": {
  "individual": 1.0,
  "operator": 1.0,
  "overall": 1.0
}
```

That's it. No code changes. The scheduler reads weights from the file at runtime.

**Example — boost operator fairness in Scenario 4:**
```json
"weights": {
  "individual": 1.0,
  "operator": 3.0,
  "overall": 1.0
}
```

Reload the app → pick Scenario 4 → the schedule changes to more aggressively favour KPN buses (the dominant operator).

---

## How to add a new rule

### Soft rule (affects priority when multiple buses compete)

1. Open `scheduler/engine.py`, find `score_plan()`.
2. Add a new cost component:

```python
# Example: penalise buses that have been waiting longest network-wide
age_penalty = (current_time - bus.departure_min) * weights.get("age", 0.0)
cost += age_penalty
```

3. Add the weight to `Weights` dataclass and to scenario JSON files:
```json
"weights": { "individual": 1.0, "operator": 1.0, "overall": 1.0, "age": 0.5 }
```

That's the entire change. The engine loops over `score_plan()` output — it doesn't need to know what the rule is.

### Hard rule (must always hold, like range constraint)

Add it to `generate_charging_plans()` or as a post-filter on valid plans:

```python
# Example: bus must charge at station B (e.g. mandatory inspection stop)
if "B" not in chosen_stations and bus.mandatory_stop == "B":
    continue  # skip this plan
```

---

## How to add a new scenario

1. Copy `scenarios/scenario_1.json` to `scenarios/scenario_6.json`.
2. Edit: `id`, `name`, `description`, `buses[]`, and optionally `weights`.
3. Restart app → new scenario appears in the dropdown automatically.

---

## How to add a new station

In the scenario JSON, add to `route.stations`, `route.segments`, and `stations_config`:

```json
"stations": ["A", "B", "B2", "C", "D"],
"segments": [
  {"from": "Bengaluru", "to": "A",  "distance_km": 100},
  {"from": "A",         "to": "B",  "distance_km": 80},
  {"from": "B",         "to": "B2", "distance_km": 40},
  {"from": "B2",        "to": "C",  "distance_km": 100},
  {"from": "C",         "to": "D",  "distance_km": 120},
  {"from": "D",         "to": "Kochi", "distance_km": 100}
],
"stations_config": {
  "A": {"chargers": 1}, "B": {"chargers": 1},
  "B2": {"chargers": 2}, "C": {"chargers": 1}, "D": {"chargers": 1}
}
```

No code changes required.

---

## How to add a new operator

Add buses with the new operator name in the scenario JSON:

```json
{"id": "bus-BK-11", "operator": "greenbus", "direction": "BK", "departure": "22:00"}
```

No code changes. The scheduler treats operators as string keys — any new string is automatically tracked.

---

## Project structure

```
bus-charging-scheduler/
├── app.py                    # Streamlit UI
├── requirements.txt
├── README.md
├── ARCHITECTURE.md
├── scheduler/
│   ├── __init__.py
│   ├── engine.py             # Core scheduling logic
│   └── loader.py             # Scenario JSON → domain models
└── scenarios/
    ├── scenario_1.json       # Even spacing
    ├── scenario_2.json       # Bunched start
    ├── scenario_3.json       # Asymmetric load
    ├── scenario_4.json       # Operator heavy (operator weight = 2.0)
    └── scenario_5.json       # Worst case convergence
```
