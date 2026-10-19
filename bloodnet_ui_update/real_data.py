"""
real_data.py - run the blood balancer against exported hospital data.

Two modes:
  recommend  Read TODAY'S inventory snapshot + recent usage and print/save
             PROPOSED transfers. Nothing is executed; a technologist must
             approve each one.
  backtest   Replay historical receipts and usage with and without sharing
             to estimate what the network would have saved.

Quick start (synthetic sample data, to see the file formats):
  python real_data.py make-sample sample_data
  python real_data.py recommend --data sample_data
  python real_data.py backtest  --data sample_data

Input files (CSV, header row required, column names case-insensitive).
Only inventory-level data is accepted; files with patient-identifying
columns are rejected.

  hospitals.csv   hospital_id, name, lat, lon                [reserve_days]
  inventory.csv   hospital_id, unit_id, abo_rh, expiry_date  [product, status]
  usage.csv       date, hospital_id, abo_rh, units           [product]
  receipts.csv    date, hospital_id, abo_rh, units, and expiry_date OR
                  shelf_life_days                            [product]
  routes.csv      (optional) from_id, to_id, minutes   door-to-door courier time

Notes
  * abo_rh accepts O-, O NEG, o_neg, AB+, "A POS", etc.
  * Dates: YYYY-MM-DD (also MM/DD/YYYY).
  * Only red cells (product RBC/PRBC/"red ...") are balanced. Other products
    (platelets, plasma) are skipped and reported.
  * inventory.csv `status`: only AVAILABLE / IN STOCK / READY units are
    considered. Quarantined, reserved, crossmatched or temperature-excursion
    units are excluded. If the column is missing, ALL units are assumed
    available, so export it if you can.
"""
import argparse
import csv
import math
import os
import random
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import blood_balancer as bb

TYPES = bb.TYPES
DETOUR = 1.3        # road distance ~ 1.3 x straight line
SPEED_KMH = 50
HANDOFF_H = 0.75    # packing + handoff time
AVAILABLE_STATUSES = {"AVAILABLE", "IN STOCK", "IN_STOCK", "INSTOCK", "READY"}
PHI_WORDS = ("patient", "mrn", "dob", "birth", "ssn", "medical_record")


class DataError(Exception):
    pass


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def read_csv(path, required, optional=()):
    if not os.path.exists(path):
        raise DataError(f"Missing file: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        bad = [h for h in fields if any(w in h for w in PHI_WORDS)]
        if bad:
            raise DataError(
                f"{path}: columns {bad} look like patient identifiers. Remove "
                "them; this tool only needs inventory-level data.")
        missing = [c for c in required if c not in fields]
        if missing:
            raise DataError(f"{path}: missing required column(s) {missing}. "
                            f"Found: {fields}")
        rows = []
        for i, raw in enumerate(reader, start=2):
            row = {}
            for k, v in raw.items():
                if k is None:
                    continue
                row[k.strip().lower()] = (v or "").strip()
            row["_line"] = i
            rows.append(row)
    return rows, fields


def parse_date(s, where):
    s = s.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise DataError(f"{where}: cannot parse date '{s}' (use YYYY-MM-DD)")


def parse_num(s, where, integer=False, minimum=None):
    try:
        v = float(s)
    except ValueError:
        raise DataError(f"{where}: '{s}' is not a number")
    if integer:
        if v != int(v):
            raise DataError(f"{where}: '{s}' must be a whole number")
        v = int(v)
    if minimum is not None and v < minimum:
        raise DataError(f"{where}: {v} is below the minimum of {minimum}")
    return v


_TYPE_RE = re.compile(
    r"^(AB|A|B|O)\s*[-_ ]?\s*(\+|-|POS|NEG|POSITIVE|NEGATIVE|PLUS|MINUS)$")


def norm_type(s, where):
    t = s.strip().upper().replace("\u2212", "-").replace("\u2013", "-")
    m = _TYPE_RE.match(t)
    if not m:
        raise DataError(f"{where}: unrecognised blood type '{s}' "
                        "(expected e.g. O-, A+, 'AB NEG')")
    rh = "+" if m.group(2) in ("+", "POS", "POSITIVE", "PLUS") else "-"
    return m.group(1) + rh


def is_rbc(product):
    p = product.strip().upper()
    return p == "" or "RBC" in p or p.startswith("RED")


def haversine_km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi, dl = p2 - p1, math.radians(lo2 - lo1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------
def load_hospitals(d):
    rows, _ = read_csv(os.path.join(d, "hospitals.csv"),
                       ["hospital_id", "name", "lat", "lon"], ["reserve_days"])
    hospitals, id2h, reserve, names = [], {}, {}, set()
    for r in rows:
        w = f"hospitals.csv line {r['_line']}"
        hid, name = r["hospital_id"], r["name"]
        if hid in id2h:
            raise DataError(f"{w}: duplicate hospital_id '{hid}'")
        if name in names:
            raise DataError(f"{w}: duplicate hospital name '{name}'")
        lat = parse_num(r["lat"], w + " lat")
        lon = parse_num(r["lon"], w + " lon")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise DataError(f"{w}: lat/lon out of range")
        h = bb.Hospital(name=name, demand_rate=0.0, supply_rate=0.0, pos=(lat, lon))
        hospitals.append(h)
        id2h[hid] = h
        names.add(name)
        if r.get("reserve_days"):
            reserve[name] = parse_num(r["reserve_days"], w + " reserve_days", minimum=0)
    if len(hospitals) < 2:
        raise DataError("hospitals.csv needs at least 2 hospitals")

    minutes = {}
    rpath = os.path.join(d, "routes.csv")
    if os.path.exists(rpath):
        for r in read_csv(rpath, ["from_id", "to_id", "minutes"])[0]:
            w = f"routes.csv line {r['_line']}"
            for k in ("from_id", "to_id"):
                if r[k] not in id2h:
                    raise DataError(f"{w}: unknown hospital_id '{r[k]}'")
            m = parse_num(r["minutes"], w, minimum=1)
            a, b = "hospital:" + id2h[r["from_id"]].name, "hospital:" + id2h[r["to_id"]].name
            minutes[(a, b)] = m
            minutes.setdefault((b, a), m)
    return hospitals, reserve, minutes, id2h


def load_inventory(d, as_of, id2h):
    rows, fields = read_csv(os.path.join(d, "inventory.csv"),
                            ["hospital_id", "unit_id", "abo_rh", "expiry_date"],
                            ["product", "status"])
    has_status = "status" in fields
    skipped = defaultdict(int)
    meta, seen, uid = {}, set(), 0
    for r in rows:
        w = f"inventory.csv line {r['_line']}"
        if r["hospital_id"] not in id2h:
            raise DataError(f"{w}: unknown hospital_id '{r['hospital_id']}'")
        if not is_rbc(r.get("product", "")):
            skipped[f"non-RBC product ({r['product'].upper()})"] += 1
            continue
        status = r.get("status", "").upper()
        if has_status and status not in AVAILABLE_STATUSES:
            skipped[f"status {status or 'blank'}"] += 1
            continue
        key = (r["hospital_id"], r["unit_id"])
        if key in seen:
            skipped["duplicate unit_id"] += 1
            continue
        seen.add(key)
        exp = parse_date(r["expiry_date"], w)
        if exp <= as_of:
            skipped["already expired"] += 1
            continue
        uid += 1
        id2h[r["hospital_id"]].inventory.append(
            bb.Unit(uid, norm_type(r["abo_rh"], w), (exp - as_of).days))
        meta[uid] = (r["unit_id"], exp)
    return meta, skipped, has_status


def load_usage_receipts(d, id2h, need_receipts):
    usage = defaultdict(int)  # (date, hospital name, type) -> units
    rows, _ = read_csv(os.path.join(d, "usage.csv"),
                       ["date", "hospital_id", "abo_rh", "units"], ["product"])
    for r in rows:
        w = f"usage.csv line {r['_line']}"
        if r["hospital_id"] not in id2h:
            raise DataError(f"{w}: unknown hospital_id '{r['hospital_id']}'")
        if not is_rbc(r.get("product", "")):
            continue
        usage[(parse_date(r["date"], w), id2h[r["hospital_id"]].name,
               norm_type(r["abo_rh"], w))] += parse_num(r["units"], w, True, 0)

    receipts = defaultdict(list)  # date -> [(name, type, qty, expiry_date)]
    if need_receipts:
        rows, fields = read_csv(os.path.join(d, "receipts.csv"),
                                ["date", "hospital_id", "abo_rh", "units"],
                                ["product", "expiry_date", "shelf_life_days"])
        if "expiry_date" not in fields and "shelf_life_days" not in fields:
            raise DataError("receipts.csv needs expiry_date or shelf_life_days")
        for r in rows:
            w = f"receipts.csv line {r['_line']}"
            if r["hospital_id"] not in id2h:
                raise DataError(f"{w}: unknown hospital_id '{r['hospital_id']}'")
            if not is_rbc(r.get("product", "")):
                continue
            rd = parse_date(r["date"], w)
            if r.get("expiry_date"):
                exp = parse_date(r["expiry_date"], w)
            elif r.get("shelf_life_days"):
                exp = rd + timedelta(days=parse_num(r["shelf_life_days"], w, True, 1))
            else:
                raise DataError(f"{w}: no expiry_date or shelf_life_days")
            receipts[rd].append((id2h[r["hospital_id"]].name,
                                 norm_type(r["abo_rh"], w),
                                 parse_num(r["units"], w, True, 0), exp))
    return usage, receipts


def forecasts_from_usage(usage, hospitals, start, end):
    """Mean units/day per hospital and type over [start, end)."""
    days = max((end - start).days, 1)
    totals = defaultdict(float)
    for (dt, name, t), u in usage.items():
        if start <= dt < end:
            totals[(name, t)] += u
    out = {}
    for h in hospitals:
        if not any(k[0] == h.name for k in totals):
            raise DataError(f"No usage history for '{h.name}' in {start}..{end}")
        out[h.name] = {t: totals[(h.name, t)] / days for t in TYPES}
    return out


# --------------------------------------------------------------------------
# Real-world agents
# --------------------------------------------------------------------------
class RealLogistics(bb.LogisticsAgent):
    """Haversine x detour distance, or measured courier minutes if provided."""

    def __init__(self, hospitals, bus, minutes=None):
        super().__init__(hospitals, bus)
        self.minutes = minutes or {}

    def distance(self, a, b):
        return haversine_km(self.pos[a], self.pos[b]) * DETOUR

    def handle(self, msg_type, p):
        if msg_type == "ASSESS_ROUTE":
            km = self.distance(p["from"], p["to"])
            mins = self.minutes.get((p["from"], p["to"]))
            hours = mins / 60 if mins is not None else km / SPEED_KMH + HANDOFF_H
            return {"km": km, "hours": hours,
                    "feasible": hours <= bb.MAX_TRANSIT_HOURS}


class AlwaysApprove:
    """Recommend mode never executes anything; humans approve later."""

    def random(self):
        return 0.0


def build_network(hospitals, forecasts, reserve, minutes, rng):
    bus = bb.Bus()
    agents = [bb.HospitalAgent(h, bus) for h in hospitals]
    for a in agents:
        a.forecast = dict(forecasts[a.h.name])
        a.reserve_days = reserve.get(a.h.name, bb.RESERVE_DAYS)
    logistics = RealLogistics(hospitals, bus, minutes)
    compliance = bb.ComplianceAgent(bus)
    matchmaker = bb.MatchmakerAgent(bus, rng)
    return bus, agents, logistics, compliance, matchmaker


# --------------------------------------------------------------------------
# Mode 1: recommend
# --------------------------------------------------------------------------
def recommend(args):
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else date.today()
    hospitals, reserve, minutes, id2h = load_hospitals(args.data)
    meta, skipped, has_status = load_inventory(args.data, as_of, id2h)
    usage, _ = load_usage_receipts(args.data, id2h, need_receipts=False)

    window_start = as_of - timedelta(days=args.window)
    forecasts = forecasts_from_usage(usage, hospitals, window_start, as_of)
    first = min((k[0] for k in usage), default=as_of)

    bus, agents, logistics, comp, mm = build_network(
        hospitals, forecasts, reserve, minutes, AlwaysApprove())

    print(f"\nSNAPSHOT {as_of}: {len(hospitals)} hospitals, "
          f"{sum(len(h.inventory) for h in hospitals)} usable RBC units")
    if first > window_start:
        print(f"  WARNING: usage history starts {first}; forecast window of "
              f"{args.window} days is only partly covered.")
    if not has_status:
        print("  WARNING: inventory.csv has no 'status' column; assuming every "
              "unit is available (quarantined/reserved units may be included).")
    for reason, n in sorted(skipped.items()):
        print(f"  Excluded {n} unit(s): {reason}")

    print("\nCURRENT POSITION (days on hand, O-neg / O-pos / A-pos):")
    for a in agents:
        d = {t: a.days_on_hand(t, 0) for t in ("O-", "O+", "A+")}
        print(f"  {a.h.name:<24}" + "".join(f"{t}: {d[t]:>5.1f}d   " for t in d))

    reqs = []
    for a in agents:
        for r in a.detect_shortfalls(0):
            r["doh"] = a.days_on_hand(r["btype"], 0)
            reqs.append(r)
    reqs.sort(key=lambda r: r["doh"])  # most urgent first

    unmet = []
    for r in reqs:
        moved = mm.fulfil(r, 0)
        if moved < r["qty"]:
            unmet.append((r, r["qty"] - moved))

    rows = []
    for i, e in enumerate(comp.log, start=1):
        route = logistics.handle("ASSESS_ROUTE", {"from": e["from"], "to": e["to"]})
        exps = [meta[u][1] for u in e["units"]]
        arrive_days = min((x - as_of).days for x in exps) - route["hours"] / 24
        rows.append({
            "priority": i,
            "recipient": e["to"].split(":", 1)[1],
            "donor": e["from"].split(":", 1)[1],
            "abo_rh": e["btype"],
            "units": len(e["units"]),
            "unit_ids": ";".join(meta[u][0] for u in e["units"]),
            "earliest_expiry": min(exps).isoformat(),
            "shelf_days_on_arrival": round(arrive_days, 1),
            "distance_km": round(route["km"], 1),
            "transit_hours": round(route["hours"], 1),
            "status": "PROPOSED - requires blood bank approval",
        })

    print(f"\nPROPOSED TRANSFERS ({len(rows)}), most urgent first")
    if not rows:
        print("  None. No hospital is below threshold with an eligible donor.")
    for r in rows:
        print(f"  {r['priority']:>2}. {r['donor']} -> {r['recipient']}: "
              f"{r['units']} x {r['abo_rh']}  (earliest expiry {r['earliest_expiry']}, "
              f"{r['shelf_days_on_arrival']}d left on arrival, "
              f"{r['distance_km']} km, ~{r['transit_hours']} h)")

    if unmet:
        print("\nSHORTFALLS WITH NO ELIGIBLE DONOR (consider supplier order or "
              "ABO substitution):")
        for r, short in unmet:
            print(f"  {r['hospital'].split(':', 1)[1]:<24} {r['btype']:<3} "
                  f"short {short} unit(s), {r['doh']:.1f} days on hand")

    risk = defaultdict(int)
    for h in hospitals:
        for u in h.inventory:
            if u.expiry <= args.risk_days:
                risk[(h.name, u.btype)] += 1
    if risk:
        print(f"\nSTILL AT RISK OF EXPIRING within {args.risk_days} days "
              "(no transfer proposed; consider manual outreach):")
        for (name, t), n in sorted(risk.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {name:<24} {t:<3} {n} unit(s)")

    if args.out and rows:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\nSaved proposals to {args.out}")
    print("\nNothing has been executed. Each transfer needs sign-off under "
          "your facility's SOPs.")


# --------------------------------------------------------------------------
# Mode 2: backtest
# --------------------------------------------------------------------------
def backtest(args):
    hospitals, reserve, minutes, id2h = load_hospitals(args.data)
    usage, receipts = load_usage_receipts(args.data, id2h, need_receipts=True)
    if not usage:
        raise DataError("usage.csv has no RBC rows")
    start = min(k[0] for k in usage)
    end = max(k[0] for k in usage)
    n = (end - start).days + 1
    if n < args.warmup + 14:
        raise DataError(f"Need at least {args.warmup + 14} days of usage "
                        f"(found {n}).")
    init_fc = forecasts_from_usage(usage, hospitals, start, end + timedelta(days=1))

    def replay(sharing):
        hs = [bb.Hospital(h.name, 0.0, 0.0, h.pos) for h in hospitals]
        rng = random.Random(args.seed)
        srng = random.Random(args.seed + 99)
        bus, agents, _, comp, mm = build_network(
            hs, init_fc, reserve, minutes, rng)
        by_name = {a.h.name: a for a in agents}
        uid = 0
        for a in agents:  # assumed opening stock: ~4 days of usage
            for t in TYPES:
                for _ in range(math.ceil(4 * a.forecast[t])):
                    uid += 1
                    a.h.inventory.append(bb.Unit(uid, t, srng.randint(10, 30)))
        snap = {}
        for di in range(n):
            day = start + timedelta(days=di)
            for name, t, qty, exp in receipts.get(day, []):
                for _ in range(qty):
                    uid += 1
                    by_name[name].h.inventory.append(
                        bb.Unit(uid, t, (exp - start).days))
            if sharing:
                reqs = []
                for a in agents:
                    for r in a.detect_shortfalls(di):
                        r["doh"] = a.days_on_hand(r["btype"], di)
                        reqs.append(r)
                reqs.sort(key=lambda r: r["doh"])
                for r in reqs:
                    mm.fulfil(r, di)
            for a in agents:
                h = a.h
                for t in TYPES:
                    dem = usage.get((day, h.name, t), 0)
                    a.observe_demand(t, dem)
                    stock = sorted(h.stock(t), key=lambda u: u.expiry)
                    for _ in range(dem):
                        if stock:
                            h.inventory.remove(stock.pop(0))
                            h.served += 1
                        else:
                            h.stockouts += 1
            for h in hs:
                dead = [u for u in h.inventory if u.expiry <= di + 1]
                h.wasted += len(dead)
                h.inventory = [u for u in h.inventory if u.expiry > di + 1]
            if di == args.warmup - 1:
                snap = {h.name: (h.wasted, h.stockouts, h.served) for h in hs}
        res = {h.name: (h.wasted - snap[h.name][0], h.stockouts - snap[h.name][1],
                        h.served - snap[h.name][2]) for h in hs}
        return res, mm

    base, _ = replay(False)
    shared, mm = replay(True)

    print(f"\nBACKTEST {start} .. {end} ({n} days; first {args.warmup} days "
          "excluded as warm-up)")
    print(f"  {'Hospital':<24}{'Wasted':>14}{'Shortage events':>20}")
    print(f"  {'':<24}{'alone -> net':>14}{'alone -> net':>20}")
    tw = [0, 0]; ts = [0, 0]
    for h in hospitals:
        bw, bs, _ = base[h.name]
        sw, ss, _ = shared[h.name]
        tw[0] += bw; tw[1] += sw; ts[0] += bs; ts[1] += ss
        print(f"  {h.name:<24}{f'{bw} -> {sw}':>14}{f'{bs} -> {ss}':>20}")
    print(f"  {'TOTAL':<24}{f'{tw[0]} -> {tw[1]}':>14}{f'{ts[0]} -> {ts[1]}':>20}")
    pct = lambda a, b: f"{(a - b) / a:.0%}" if a else "n/a"
    print(f"\n  Waste change: {pct(tw[0], tw[1])} | shortage change: "
          f"{pct(ts[0], ts[1])} | transfers: {mm.transfers} | units moved: "
          f"{mm.units_moved}")
    print("\nHOW TO READ THIS")
    print("  * Both columns come from the same replay model, so compare them to "
          "each other, not to your actual discard/shortage records.")
    print("  * A 'shortage event' means recorded usage the modeled shelf could not "
          "cover. In reality some of these were met by emergency supplier orders.")
    print("  * Opening stock is assumed (~4 days of usage) because history lacks it.")
    print("  * Approvals are simulated at "
          f"{args.approval_rate:.0%}; same-day transfers assumed.")


# --------------------------------------------------------------------------
# Sample data generator (SYNTHETIC - for trying the pipeline only)
# --------------------------------------------------------------------------
def make_sample(outdir):
    os.makedirs(outdir, exist_ok=True)
    sched = bb.make_schedule()
    base_h = bb.run(False, sched)[0]
    today = date.today()
    start = today - timedelta(days=bb.DAYS)
    ids = {name: f"H{i + 1}" for i, (name, *_) in enumerate(bb.HOSPITALS)}

    def write(name, header, rows):
        with open(os.path.join(outdir, name), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    rows = []
    for name, _, _, (x, y) in bb.HOSPITALS:
        lat = 40.0 + y / 111.0
        lon = -75.0 + x / (111.0 * math.cos(math.radians(40.0)))
        rows.append([ids[name], name, round(lat, 5), round(lon, 5),
                     2 if "Rural" in name else 3])
    write("hospitals.csv", ["hospital_id", "name", "lat", "lon", "reserve_days"], rows)

    urows, rrows, agg = [], [], defaultdict(int)
    for (d, name, t), (demand, shelf) in sched.items():
        day = start + timedelta(days=d)
        if demand:
            urows.append([day, ids[name], t, demand])
        for s in shelf:
            agg[(d, name, t, s)] += 1
    for (d, name, t, s), q in sorted(agg.items()):
        day = start + timedelta(days=d)
        rrows.append([day, ids[name], t, q, day + timedelta(days=s)])
    write("usage.csv", ["date", "hospital_id", "abo_rh", "units"], urows)
    write("receipts.csv", ["date", "hospital_id", "abo_rh", "units", "expiry_date"], rrows)

    rng = random.Random(1)
    irows = []
    for h in base_h:
        for u in h.inventory:
            irows.append([ids[h.name], f"U{u.uid:06d}", u.btype, "RBC",
                          start + timedelta(days=u.expiry), "AVAILABLE"])
    for r in rng.sample(irows, 3):          # demo: cold-chain excursions
        r[5] = "QUARANTINE"
    for i in range(4):                       # demo: non-RBC product
        irows.append(["H1", f"P{i:04d}", "A+", "PLT",
                      today + timedelta(days=3), "AVAILABLE"])
    write("inventory.csv",
          ["hospital_id", "unit_id", "abo_rh", "product", "expiry_date", "status"],
          irows)
    print(f"Wrote SYNTHETIC sample data to {outdir}/ "
          "(hospitals, inventory, usage, receipts).")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("make-sample", help="write synthetic example CSVs")
    s.add_argument("outdir")

    def common(p):
        p.add_argument("--data", required=True, help="folder with the CSV files")
        p.add_argument("--threshold-days", type=float,
                       help=f"request when days-on-hand below this "
                            f"(default {bb.REQUEST_THRESHOLD_DAYS})")
        p.add_argument("--target-days", type=float,
                       help=f"restock target (default {bb.TARGET_DAYS})")
        p.add_argument("--min-arrival-days", type=int,
                       help="minimum shelf life on arrival "
                            f"(default {bb.MIN_ARRIVAL_SHELF_DAYS})")

    r = sub.add_parser("recommend", help="propose transfers from today's snapshot")
    common(r)
    r.add_argument("--as-of", help="snapshot date YYYY-MM-DD (default today)")
    r.add_argument("--window", type=int, default=28,
                   help="days of usage history for forecasting (default 28)")
    r.add_argument("--risk-days", type=int, default=7)
    r.add_argument("--out", help="write proposals to this CSV")

    b = sub.add_parser("backtest", help="replay history with vs without sharing")
    common(b)
    b.add_argument("--warmup", type=int, default=14)
    b.add_argument("--approval-rate", type=float, default=0.9)
    b.add_argument("--seed", type=int, default=7)

    args = ap.parse_args()
    if args.cmd != "make-sample":
        if args.threshold_days is not None:
            bb.REQUEST_THRESHOLD_DAYS = args.threshold_days
        if args.target_days is not None:
            bb.TARGET_DAYS = args.target_days
        if args.min_arrival_days is not None:
            bb.MIN_ARRIVAL_SHELF_DAYS = args.min_arrival_days
        if args.cmd == "backtest":
            bb.APPROVAL_RATE = args.approval_rate
    try:
        if args.cmd == "make-sample":
            make_sample(args.outdir)
        elif args.cmd == "recommend":
            recommend(args)
        else:
            backtest(args)
    except DataError as e:
        print(f"\nDATA ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
