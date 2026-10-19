"""
Inter-Hospital Blood Bank Inventory Balancer
Multi-agent simulation: Hospital, Matchmaker, Logistics, Compliance agents
plus a simulated human-approval step. Standard library only.

Run:  python blood_balancer.py
"""
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
TYPES = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]
SHARE = {"O-": .07, "O+": .38, "A-": .06, "A+": .34,
         "B-": .02, "B+": .09, "AB-": .01, "AB+": .03}
DAYS = 120
SEED = 7

REQUEST_THRESHOLD_DAYS = 2.0   # requester if days-on-hand below this
TARGET_DAYS = 4.0              # restock target
RESERVE_DAYS = 3.0             # donor must keep this much (hard constraint)
MIN_ARRIVAL_SHELF_DAYS = 3     # units must have this much life on arrival
MAX_TRANSIT_HOURS = 24         # validated-shipper limit for RBC
APPROVAL_RATE = 0.90           # simulated technologist approves 90%

HOSPITALS = [
    # name, demand/day, supply/day, (x_km, y_km)
    ("Central General",      22, 20, (0, 0)),
    ("Northside Medical",    10, 14, (12, 25)),
    ("Eastgate Community",    6,  8, (30, 5)),
    ("St. Mary's",           14, 14, (-15, 10)),
    ("Riverside Children's",  8,  6, (5, -20)),
    ("Westfield Rural",       4,  5, (-45, -10)),
]


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Unit:
    uid: int
    btype: str
    expiry: int  # absolute day number


@dataclass
class Hospital:
    name: str
    demand_rate: float
    supply_rate: float
    pos: tuple
    inventory: list = field(default_factory=list)
    wasted: int = 0
    stockouts: int = 0
    served: int = 0

    def stock(self, btype):
        return [u for u in self.inventory if u.btype == btype]


# --------------------------------------------------------------------------
# Message bus
# --------------------------------------------------------------------------
class Bus:
    """Typed request/response bus. Each agent registers handlers by name."""

    def __init__(self):
        self.handlers = {}
        self.msg_count = defaultdict(int)

    def register(self, agent_name, handler):
        self.handlers[agent_name] = handler

    def request(self, to, msg_type, payload):
        self.msg_count[msg_type] += 1
        return self.handlers[to](msg_type, payload)

    def broadcast(self, sender, msg_type, payload):
        out = {}
        for name, h in self.handlers.items():
            if name.startswith("hospital:") and name != sender:
                self.msg_count[msg_type] += 1
                out[name] = h(msg_type, payload)
        return out


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------
class HospitalAgent:
    """Owns one hospital's inventory view, demand forecast, and offer logic."""

    def __init__(self, hospital, bus):
        self.h = hospital
        self.bus = bus
        self.name = f"hospital:{hospital.name}"
        self.forecast = {t: hospital.demand_rate * SHARE[t] for t in TYPES}
        self.times_donated = 0
        bus.register(self.name, self.handle)

    # -- forecasting ------------------------------------------------------
    def observe_demand(self, btype, qty, alpha=0.15):
        self.forecast[btype] = (1 - alpha) * self.forecast[btype] + alpha * qty

    def days_on_hand(self, btype, today):
        usable = [u for u in self.h.stock(btype) if u.expiry > today]
        f = max(self.forecast[btype], 0.05)
        return len(usable) / f

    # -- requester side ---------------------------------------------------
    def detect_shortfalls(self, today):
        reqs = []
        for t in TYPES:
            if self.days_on_hand(t, today) < REQUEST_THRESHOLD_DAYS:
                need = math.ceil(TARGET_DAYS * self.forecast[t]) - len(self.h.stock(t))
                if need > 0:
                    reqs.append({"hospital": self.name, "btype": t, "qty": need})
        return reqs

    # -- donor side -------------------------------------------------------
    def offerable_units(self, btype, today):
        """Units unlikely to be consumed locally before expiry,
        while keeping a hard safety reserve."""
        units = sorted(self.h.stock(btype), key=lambda u: u.expiry)
        reserve = math.ceil(RESERVE_DAYS * self.forecast[btype])
        f = self.forecast[btype]
        offers = []
        for i, u in enumerate(units):  # FIFO position i
            days_left = u.expiry - today
            expected_use = f * days_left
            at_risk = i >= expected_use * 0.85
            remaining_after = len(units) - len(offers) - 1
            if at_risk and remaining_after >= reserve:
                offers.append(u)
        return offers

    def handle(self, msg_type, p):
        if msg_type == "QUERY_SURPLUS":
            units = self.offerable_units(p["btype"], p["today"])
            return {"donor": self.name, "units": units,
                    "times_donated": self.times_donated}
        if msg_type == "APPROVAL_REQUEST":
            # Simulated human blood-bank technologist sign-off
            return {"approved": p["rng"].random() < APPROVAL_RATE}
        if msg_type == "SHIP":
            ids = {u.uid for u in p["units"]}
            self.h.inventory = [u for u in self.h.inventory if u.uid not in ids]
            self.times_donated += len(ids)
            return {"ok": True}
        if msg_type == "RECEIVE":
            self.h.inventory.extend(p["units"])
            return {"ok": True}


class LogisticsAgent:
    """Transit time and cold-chain feasibility."""

    def __init__(self, hospitals, bus):
        self.pos = {f"hospital:{h.name}": h.pos for h in hospitals}
        bus.register("logistics", self.handle)

    def distance(self, a, b):
        (x1, y1), (x2, y2) = self.pos[a], self.pos[b]
        return math.hypot(x1 - x2, y1 - y2)

    def handle(self, msg_type, p):
        if msg_type == "ASSESS_ROUTE":
            km = self.distance(p["from"], p["to"])
            hours = km / 50 + 0.75  # 50 km/h + 45 min packing/handoff
            return {"km": km, "hours": hours,
                    "feasible": hours <= MAX_TRANSIT_HOURS}


class ComplianceAgent:
    """Hard-constraint checks and append-only chain-of-custody log."""

    def __init__(self, bus):
        self.log = []
        bus.register("compliance", self.handle)

    def handle(self, msg_type, p):
        if msg_type == "VALIDATE":
            # exact ABO/Rh match, enough shelf life on arrival
            transit_days = p["hours"] / 24
            ok_units = [u for u in p["units"]
                        if u.btype == p["btype"]
                        and (u.expiry - p["today"] - transit_days) >= MIN_ARRIVAL_SHELF_DAYS]
            return {"units": ok_units}
        if msg_type == "LOG":
            self.log.append(p)
            return {"ok": True}


class MatchmakerAgent:
    """Regional coordinator: finds, scores, and negotiates transfers."""

    def __init__(self, bus, rng):
        self.bus = bus
        self.rng = rng
        self.transfers = 0
        self.units_moved = 0
        self.declined = 0
        self.unfilled = 0
        bus.register("matchmaker", lambda *_: None)

    def score(self, offer, route, max_km):
        units = offer["units"]
        today = offer["today"]
        # expiry risk: fewer days remaining => higher score
        risk = sum(1 - min(1, (u.expiry - today) / 30) for u in units) / len(units)
        proximity = 1 - route["km"] / max(max_km, 1)
        fairness = 1 / (1 + offer["times_donated"] / 10)
        return 0.5 * risk + 0.3 * proximity + 0.2 * fairness

    def fulfil(self, req, today):
        responses = self.bus.broadcast(req["hospital"], "QUERY_SURPLUS",
                                       {"btype": req["btype"], "today": today})
        candidates = []
        for donor, offer in responses.items():
            if not offer["units"]:
                continue
            route = self.bus.request("logistics", "ASSESS_ROUTE",
                                     {"from": donor, "to": req["hospital"]})
            if not route["feasible"]:
                continue
            valid = self.bus.request("compliance", "VALIDATE", {
                "units": offer["units"], "btype": req["btype"],
                "today": today, "hours": route["hours"]})["units"]
            if not valid:
                continue
            candidates.append({**offer, "units": valid, "today": today,
                               "route": route, "donor": donor})
        if not candidates:
            self.unfilled += 1
            return 0

        max_km = max(c["route"]["km"] for c in candidates)
        candidates.sort(key=lambda c: -self.score(c, c["route"], max_km))

        remaining = req["qty"]
        moved_total = 0
        for c in candidates:                       # escalate down the ranking
            if remaining <= 0:
                break
            batch = c["units"][:remaining]
            appr = self.bus.request(c["donor"], "APPROVAL_REQUEST",
                                    {"rng": self.rng, "qty": len(batch)})
            if not appr["approved"]:
                self.declined += 1
                continue
            self.bus.request(c["donor"], "SHIP", {"units": batch})
            self.bus.request(req["hospital"], "RECEIVE", {"units": batch})
            self.bus.request("compliance", "LOG", {
                "day": today, "from": c["donor"], "to": req["hospital"],
                "btype": req["btype"], "units": [u.uid for u in batch],
                "km": round(c["route"]["km"], 1)})
            moved_total += len(batch)
            remaining -= len(batch)
            self.transfers += 1
        self.units_moved += moved_total
        return moved_total


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------
def poisson(rng, lam):
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def make_schedule():
    """Shared demand/delivery schedule so both runs see identical conditions."""
    rng = random.Random(SEED)
    sched = {}
    for d in range(DAYS):
        for name, dem, sup, _ in HOSPITALS:
            for t in TYPES:
                demand = poisson(rng, dem * SHARE[t])
                shelf = [rng.randint(18, 35) for _ in range(poisson(rng, sup * SHARE[t]))]
                sched[(d, name, t)] = (demand, shelf)
    return sched


def run(sharing, sched):
    hospitals = [Hospital(n, dem, sup, pos) for n, dem, sup, pos in HOSPITALS]
    bus = Bus()
    rng = random.Random(SEED + 1)
    agents = [HospitalAgent(h, bus) for h in hospitals]
    LogisticsAgent(hospitals, bus)
    compliance = ComplianceAgent(bus)
    matchmaker = MatchmakerAgent(bus, rng)
    uid = 0

    # initial stock: ~4 days on hand
    for h in hospitals:
        for t in TYPES:
            for _ in range(math.ceil(4 * h.demand_rate * SHARE[t])):
                uid += 1
                h.inventory.append(Unit(uid, t, rng.randint(10, 30)))

    for day in range(DAYS):
        # 1. supplier deliveries
        for h in hospitals:
            for t in TYPES:
                _, shelf = sched[(day, h.name, t)]
                for s in shelf:
                    uid += 1
                    h.inventory.append(Unit(uid, t, day + s))

        # 2. agent coordination
        if sharing:
            for a in agents:
                for req in a.detect_shortfalls(day):
                    matchmaker.fulfil(req, day)

        # 3. clinical demand (FIFO: oldest first)
        for a in agents:
            h = a.h
            for t in TYPES:
                demand, _ = sched[(day, h.name, t)]
                a.observe_demand(t, demand)
                stock = sorted(h.stock(t), key=lambda u: u.expiry)
                for _ in range(demand):
                    if stock:
                        used = stock.pop(0)
                        h.inventory.remove(used)
                        h.served += 1
                    else:
                        h.stockouts += 1

        # 4. expiry
        for h in hospitals:
            expired = [u for u in h.inventory if u.expiry <= day + 1]
            h.wasted += len(expired)
            h.inventory = [u for u in h.inventory if u.expiry > day + 1]

    return hospitals, matchmaker, compliance, bus


def summarize(label, hospitals):
    print(f"\n{label}")
    print(f"  {'Hospital':<22}{'Served':>8}{'Stockouts':>11}{'Wasted':>8}")
    for h in hospitals:
        print(f"  {h.name:<22}{h.served:>8}{h.stockouts:>11}{h.wasted:>8}")
    print(f"  {'TOTAL':<22}{sum(h.served for h in hospitals):>8}"
          f"{sum(h.stockouts for h in hospitals):>11}"
          f"{sum(h.wasted for h in hospitals):>8}")


def main():
    sched = make_schedule()
    base_h, *_ = run(False, sched)
    shared_h, mm, comp, bus = run(True, sched)

    print(f"Simulated {len(HOSPITALS)} hospitals over {DAYS} days, "
          f"identical demand and supply in both runs.")
    summarize("BASELINE (no sharing)", base_h)
    summarize("WITH AGENT NETWORK", shared_h)

    bw, sw = sum(h.wasted for h in base_h), sum(h.wasted for h in shared_h)
    bs, ss = sum(h.stockouts for h in base_h), sum(h.stockouts for h in shared_h)
    print("\nIMPACT")
    print(f"  Waste reduced:     {bw} -> {sw}  ({(bw - sw) / max(bw, 1):.0%})")
    print(f"  Stockouts reduced: {bs} -> {ss}  ({(bs - ss) / max(bs, 1):.0%})")
    print(f"  Transfers: {mm.transfers}  | units moved: {mm.units_moved}"
          f"  | declined: {mm.declined}  | unfilled requests: {mm.unfilled}")
    print(f"  Messages on bus: {dict(bus.msg_count)}")
    print("\nSAMPLE CHAIN-OF-CUSTODY LOG")
    for e in comp.log[:5]:
        print(f"  day {e['day']:>3}  {e['btype']:<3} x{len(e['units'])}  "
              f"{e['from'].split(':')[1]} -> {e['to'].split(':')[1]} ({e['km']} km)")


if __name__ == "__main__":
    main()
