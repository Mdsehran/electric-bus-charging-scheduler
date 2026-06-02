"""
app.py - Bus Charging Scheduler
Python + Streamlit. One file, one process.

Dropdown -> Scenario Input -> Per-Bus Timetable -> Per-Station View
"""

import streamlit as st
from pathlib import Path
import pandas as pd
from scheduler import run_scheduler, load_all_scenarios, minutes_to_hhmm

st.set_page_config(
    page_title="Bus Charging Scheduler",
    page_icon="⚡",
    layout="wide",
)

st.markdown("""
<style>
  .block-container { padding-top: 1.5rem; }
  .section-header {
    font-size: 1.3rem; font-weight: 700; color: #1e3a5f;
    border-left: 4px solid #2563eb; padding-left: 10px;
    margin: 1.2rem 0 0.6rem 0;
  }
  .station-box {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 12px 14px; margin-bottom: 6px;
  }
  .station-title {
    font-size: 1.1rem; font-weight: 800; color: #2563eb;
    border-bottom: 2px solid #bfdbfe; padding-bottom: 4px; margin-bottom: 8px;
  }
  .charge-slot {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 5px;
    padding: 8px 10px; margin-bottom: 5px; font-size: 0.82rem;
  }
  .wait-badge-none { color: #16a34a; font-weight: 700; }
  .wait-badge-some { color: #d97706; font-weight: 700; }
  .wait-badge-high { color: #dc2626; font-weight: 700; }
  .tag { display:inline-block; padding:1px 6px; border-radius:3px; font-size:0.7rem; font-weight:700; margin-right:3px; }
  .t-kpn      { background:#dcfce7; color:#15803d; }
  .t-freshbus { background:#fce7f3; color:#be185d; }
  .t-flixbus  { background:#ede9fe; color:#7c3aed; }
  .t-bk       { background:#dbeafe; color:#1d4ed8; }
  .t-kb       { background:#ffedd5; color:#c2410c; }
  .summary-box {
    background:#eff6ff; border:1px solid #bfdbfe;
    border-radius:8px; padding:10px 14px; text-align:center;
  }
  .summary-val { font-size:1.6rem; font-weight:800; color:#1e3a5f; }
  .summary-lbl { font-size:0.72rem; color:#64748b; text-transform:uppercase; letter-spacing:.05em; }
</style>
""", unsafe_allow_html=True)


# ── helpers ──────────────────────────────────────────────────────────────────
def fmt_min(m):
    h = int(m) // 60
    mn = int(m) % 60
    return f"{h}h {mn}m"

def op_tag(op):
    cls = {"kpn":"t-kpn","freshbus":"t-freshbus","flixbus":"t-flixbus"}.get(op,"t-kpn")
    return f'<span class="tag {cls}">{op}</span>'

def dir_tag(d):
    cls = "t-bk" if d == "BK" else "t-kb"
    lbl = "BLR→Kochi" if d == "BK" else "Kochi→BLR"
    return f'<span class="tag {cls}">{lbl}</span>'

def wait_badge(w):
    if w == 0:
        cls, txt = "wait-badge-none", "no wait"
    elif w <= 30:
        cls, txt = "wait-badge-some", f"wait {w:.0f} min"
    else:
        cls, txt = "wait-badge-high", f"wait {w:.0f} min"
    return f'<span class="{cls}">{txt}</span>'


# ── load scenarios ────────────────────────────────────────────────────────────
@st.cache_data
def load_all():
    return load_all_scenarios(Path(__file__).parent / "scenarios")

scenarios = load_all()


# ── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("# ⚡ Bus Charging Scheduler")
st.caption("Weighted greedy simulation · Weights tunable per scenario · Extensible rule engine")
st.divider()


# ── SCENARIO PICKER ───────────────────────────────────────────────────────────
col_dd, col_w = st.columns([3, 1])
with col_dd:
    scenario_name = st.selectbox(
        "**Pick a Scenario**",
        list(scenarios.keys()),
        help="Each scenario is a self-contained JSON file with buses, route, physics, and weights."
    )

data    = scenarios[scenario_name]
route   = data["route"]
physics = data["physics"]
weights = data["weights"]
buses   = data["buses"]
meta    = data["meta"]

with col_w:
    st.markdown("**Weights**")
    wc1, wc2, wc3 = st.columns(3)
    wc1.metric("Individual", weights.individual)
    wc2.metric("Operator",   weights.operator)
    wc3.metric("Overall",    weights.overall)

st.divider()


# ── RUN SCHEDULER ─────────────────────────────────────────────────────────────
@st.cache_data
def get_results(name):
    d = scenarios[name]
    return run_scheduler(d["buses"], d["route"], d["physics"], d["weights"])

results = get_results(scenario_name)


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 1 — SCENARIO INPUT
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-header">📋 Scenario Input</div>', unsafe_allow_html=True)
st.markdown(f"**{meta['name']}** — {meta['description']}")

with st.expander("Route & Physics", expanded=False):
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Segments**")
        seg_data = []
        cum = 0
        for seg in route.segments:
            cum += seg.distance_km
            seg_data.append({
                "From":     seg.from_stop,
                "To":       seg.to_stop,
                "Dist (km)": int(seg.distance_km),
                "Cumul (km)": int(cum),
                "Travel (min)": int(physics.travel_time_min(seg.distance_km)),
            })
        st.dataframe(pd.DataFrame(seg_data), hide_index=True, use_container_width=True)
    with cc2:
        st.markdown("**Physics & Constraints**")
        st.table({
            "Parameter": ["Battery range","Charge time","Speed","Chargers/station"],
            "Value":     [
                str(int(physics.battery_range_km)) + " km",
                str(int(physics.charge_duration_min)) + " min (always to full)",
                str(int(physics.speed_kmh)) + " km/h",
                "1 per station",
            ],
        })

st.markdown("**Departure Schedule**")
rows = []
for b in buses:
    rows.append({
        "Bus ID":    b.id,
        "Operator":  b.operator.upper(),
        "Direction": "Bengaluru → Kochi" if b.direction == "BK" else "Kochi → Bengaluru",
        "Departure": minutes_to_hhmm(b.departure_min),
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=min(400, 36*len(buses)+40))
st.divider()


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PER-BUS TIMETABLE
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-header">🚌 Per-Bus Timetable</div>', unsafe_allow_html=True)
st.caption("Full timeline for every bus: which stations it charges at, exact times, wait at each, final arrival.")

# Summary table
tbl = []
for r in results:
    stations_used = " → ".join(e.station for e in r.charge_events) if r.charge_events else "none"
    tbl.append({
        "Bus ID":          r.bus.id,
        "Operator":        r.bus.operator.upper(),
        "Direction":       "BLR→Kochi" if r.bus.direction == "BK" else "Kochi→BLR",
        "Departs":         minutes_to_hhmm(r.departure_min),
        "Charges At":      stations_used,
        "Total Wait (min)": round(r.total_wait_min, 1),
        "Arrives":         minutes_to_hhmm(r.arrival_min),
        "Trip Duration":   fmt_min(r.trip_duration_min),
    })
st.dataframe(pd.DataFrame(tbl), hide_index=True, use_container_width=True, height=min(600, 36*len(results)+40))

# Detailed per-bus expandable
st.markdown("#### Charge Event Detail")
st.caption("Expand each bus to see exact charging timeline.")

for r in results:
    b = r.bus
    dl = "BLR→Kochi" if b.direction == "BK" else "Kochi→BLR"
    label = (
        b.id + "  |  " + b.operator.upper()
        + "  |  " + dl
        + "  |  dep " + minutes_to_hhmm(r.departure_min)
        + "  →  arr " + minutes_to_hhmm(r.arrival_min)
        + "  |  wait: " + str(round(r.total_wait_min, 1)) + " min"
    )
    with st.expander(label):
        if not r.charge_events:
            st.info("No charging stops — trip within battery range.")
        else:
            ev_rows = []
            for ev in r.charge_events:
                ev_rows.append({
                    "Station":       ev.station,
                    "Arrive":        minutes_to_hhmm(ev.arrive_min),
                    "Charge Start":  minutes_to_hhmm(ev.charge_start),
                    "Charge End":    minutes_to_hhmm(ev.charge_end),
                    "Wait (min)":    round(ev.wait_min, 1),
                })
            st.dataframe(pd.DataFrame(ev_rows), hide_index=True, use_container_width=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Departs",       minutes_to_hhmm(r.departure_min))
        m2.metric("Arrives",       minutes_to_hhmm(r.arrival_min))
        m3.metric("Total Wait",    str(round(r.total_wait_min, 1)) + " min")
        m4.metric("Trip Duration", fmt_min(r.trip_duration_min))

st.divider()


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 3 — PER-STATION VIEW
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-header">🏁 Per-Station Charging Queue</div>', unsafe_allow_html=True)
st.caption("For each of A, B, C, D: the order buses charged, slot times, and wait time.")

# Build per-station event lists
station_events = {s: [] for s in route.stations}
for r in results:
    for ev in r.charge_events:
        station_events[ev.station].append({
            "charge_start": ev.charge_start,
            "charge_end":   ev.charge_end,
            "arrive":       ev.arrive_min,
            "wait":         ev.wait_min,
            "bus_id":       r.bus.id,
            "operator":     r.bus.operator,
            "direction":    r.bus.direction,
        })

cols = st.columns(len(route.stations))

for i, station in enumerate(route.stations):
    with cols[i]:
        events = sorted(station_events[station], key=lambda x: x["charge_start"])
        n_buses = len(events)
        total_wait_here = sum(e["wait"] for e in events)

        st.markdown(
            f'<div class="station-title">Station {station} &nbsp; '
            f'<small style="font-weight:400;font-size:0.8rem;color:#64748b">'
            f'{n_buses} buses · {round(total_wait_here,1)} min wait</small></div>',
            unsafe_allow_html=True
        )

        if not events:
            st.caption("No buses charged here")
        else:
            for slot, ev in enumerate(events, 1):
                oc  = {"kpn":"t-kpn","freshbus":"t-freshbus","flixbus":"t-flixbus"}.get(ev["operator"],"t-kpn")
                dc  = "t-bk" if ev["direction"] == "BK" else "t-kb"
                dl  = "→Kochi" if ev["direction"] == "BK" else "→BLR"
                w   = ev["wait"]
                if w == 0:
                    wb = '<span class="wait-badge-none">no wait</span>'
                elif w <= 30:
                    wb = f'<span class="wait-badge-some">wait {w:.0f} min</span>'
                else:
                    wb = f'<span class="wait-badge-high">wait {w:.0f} min</span>'

                html = (
                    '<div class="charge-slot">'
                    + f"<b>#{slot}</b> "
                    + f'<span class="tag {oc}">{ev["operator"]}</span>'
                    + f'<span class="tag {dc}">{dl}</span> '
                    + f"<code>{ev['bus_id']}</code><br>"
                    + f"Arrive <b>{minutes_to_hhmm(ev['arrive'])}</b> · "
                    + f"Start <b>{minutes_to_hhmm(ev['charge_start'])}</b> · "
                    + f"Done <b>{minutes_to_hhmm(ev['charge_end'])}</b><br>"
                    + wb
                    + "</div>"
                )
                st.markdown(html, unsafe_allow_html=True)

            if events:
                st.caption(
                    "Active: "
                    + minutes_to_hhmm(events[0]["charge_start"])
                    + " – "
                    + minutes_to_hhmm(events[-1]["charge_end"])
                )

st.divider()


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SUMMARY
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-header">📊 Schedule Summary</div>', unsafe_allow_html=True)

total_wait  = sum(r.total_wait_min for r in results)
avg_wait    = total_wait / len(results)
max_wait    = max(r.total_wait_min for r in results)
avg_trip    = sum(r.trip_duration_min for r in results) / len(results)
n_buses     = len(results)

sc1, sc2, sc3, sc4 = st.columns(4)
sc1.metric("Total Network Wait",  str(round(total_wait, 1)) + " min")
sc2.metric("Avg Wait / Bus",      str(round(avg_wait, 1))   + " min")
sc3.metric("Max Wait (any bus)",  str(round(max_wait, 1))   + " min")
sc4.metric("Avg Trip Duration",   fmt_min(avg_trip))

st.markdown("#### Per-Operator Breakdown")
op_stats = {}
for r in results:
    op = r.bus.operator
    if op not in op_stats:
        op_stats[op] = {"count": 0, "total_wait": 0.0, "total_trip": 0.0, "max_wait": 0.0}
    op_stats[op]["count"]      += 1
    op_stats[op]["total_wait"] += r.total_wait_min
    op_stats[op]["total_trip"] += r.trip_duration_min
    op_stats[op]["max_wait"]    = max(op_stats[op]["max_wait"], r.total_wait_min)

op_rows = []
for op, s in sorted(op_stats.items()):
    op_rows.append({
        "Operator":           op.upper(),
        "Buses":              s["count"],
        "Total Wait (min)":   round(s["total_wait"], 1),
        "Avg Wait (min)":     round(s["total_wait"] / s["count"], 1),
        "Max Wait (min)":     round(s["max_wait"], 1),
        "Avg Trip":           fmt_min(s["total_trip"] / s["count"]),
    })
st.dataframe(pd.DataFrame(op_rows), hide_index=True, use_container_width=True)

# Weight impact callout
st.markdown("#### Weight Configuration Impact")
st.info(
    f"**Active weights:** Individual = {weights.individual} · "
    f"Operator = {weights.operator} · Overall = {weights.overall}\n\n"
    "These control how the scheduler trades off between minimising per-bus wait, "
    "ensuring operator fairness, and minimising total network trip time. "
    "Edit the `weights` block in the scenario JSON to change them — no code change required."
)

st.divider()
st.caption("Bus Charging Scheduler · Python + Streamlit · Weighted Greedy Simulation · All range constraints validated ✓")