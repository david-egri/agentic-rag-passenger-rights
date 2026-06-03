"""Deterministic, LLM-free compensation logic — the factual backbone (CLAUDE.md non-neg #6).

This module is pure: no model calls, no retrieval, no I/O beyond loading the OpenFlights
airport table once. Its output doubles as eval ground truth, so it stays deterministic and
directly testable (`tests/test_calculator.py`). The thin `@tool` wrapper that exposes it to
the agent lives in `src/tools.py`; the law lives here.

Anchored to the **in-force** Reg. (EC) 261/2004 Art. 7 figures (non-neg #2): €250 / €400 /
€600 distance bands and the 3-hour delay threshold (Sturgeon). The 2025 reform is not
enacted — its proposed thresholds are deliberately NOT encoded.

**Eligibility-agnostic** (DECISIONS, 2026-06-03): this computes the *statutory candidate*
amount — what Art. 7 awards for the distance band + delay/rerouting mechanics. It does NOT
apply the extraordinary-circumstances gate (weather/strike); that gate lives at `synthesize`
in Phase 4 as `final = eligible ? candidate_amount : 0`. So `threshold_met` and
`reduction_applied` here are purely mechanical, never the cause-of-disruption judgement.
"""

import math
from functools import lru_cache

import config

# --- Statutory rules (Art. 7) — module constants, not env knobs --------------------------
# These are in-force law, not tunables: keeping them as plain constants (vs a YAML config or
# env override) honors non-neg #2 (anchor to the in-force figures; a wrong euro figure is the
# worst failure mode) and the simplify-p1 decision (plain constants over a rules YAML).
#
# Each band: (exclusive upper distance bound in km, base amount EUR, 50%-reduction arrival
# limit in hours per Art. 7(2)). The reduction limit is the arrival-delay ceiling under which
# an offered re-routing lets the carrier halve the amount: 2 h / 3 h / 4 h by band.
BANDS = (
    (1500, 250, 2),        # ≤ 1500 km
    (3500, 400, 3),        # 1500–3500 km
    (math.inf, 600, 4),    # > 3500 km
)

# Delay (in hours) at the final destination at/above which a *delay* becomes compensable
# (Sturgeon/Nelson). Cancellation and denied boarding are candidates regardless of delay.
DELAY_THRESHOLD_HOURS = 3

DISRUPTION_TYPES = ("delay", "cancellation", "denied_boarding")


class AirportNotFound(ValueError):
    """Raised when an IATA code isn't in the OpenFlights table."""


@lru_cache(maxsize=1)
def load_airports() -> dict[str, tuple[float, float, str]]:
    """Parse OpenFlights `airports.dat` → {IATA: (lat, lon, name)}. Cached for the process.

    Format is headerless CSV; the columns we use are 1=Name, 4=IATA, 6=Lat, 7=Lon. Missing
    IATA codes are the literal `\\N` — skipped. Names/fields are quoted, so we parse with the
    csv module rather than a naive split (airport names contain commas).
    """
    import csv

    airports: dict[str, tuple[float, float, str]] = {}
    with open(config.AIRPORTS_DAT, encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 8:
                continue
            iata = row[4]
            if iata == "\\N" or len(iata) != 3:
                continue
            try:
                lat, lon = float(row[6]), float(row[7])
            except ValueError:
                continue
            # Keep the first occurrence; airports.dat is effectively unique on IATA.
            airports.setdefault(iata.upper(), (lat, lon, row[1]))
    return airports


def resolve_airport(iata: str) -> tuple[float, float, str]:
    """Look up one IATA code → (lat, lon, name); raise AirportNotFound if absent."""
    code = (iata or "").strip().upper()
    airport = load_airports().get(code)
    if airport is None:
        raise AirportNotFound(f"Unknown IATA code: {iata!r}")
    return airport


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points (mean Earth radius 6371 km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _band_for(distance_km: float) -> tuple[int, int]:
    """Distance → (base_amount_eur, reduction_limit_hours) from the Art. 7 band table."""
    for upper, amount, limit in BANDS:
        if distance_km <= upper:
            return amount, limit
    raise AssertionError("unreachable: BANDS ends with math.inf")  # pragma: no cover


def compute_compensation(
    origin_iata: str,
    dest_iata: str,
    delay_hours: float,
    disruption_type: str = "delay",
    rerouting_offered: bool = False,
) -> dict:
    """Compute the statutory candidate compensation for a disrupted flight (Art. 7).

    Steps: resolve both airports → haversine distance → band → base amount → apply the 3 h
    delay threshold and the 50%-reduction (offered re-routing within the band's arrival
    limit). Eligibility-agnostic — see the module docstring.

    Args:
        origin_iata, dest_iata: IATA codes of departure and final destination.
        delay_hours: arrival delay at the final destination, in hours.
        disruption_type: one of "delay", "cancellation", "denied_boarding".
        rerouting_offered: whether the carrier offered re-routing (enables the 50% reduction
            when the arrival delay is within the band limit).

    Returns:
        dict with distance_km, band, base_amount_eur, threshold_met, reduction_applied,
        final_amount_eur, and a human-readable `explanation` (the rest of the inputs echoed).
    """
    dtype = (disruption_type or "delay").strip().lower()
    if dtype not in DISRUPTION_TYPES:
        raise ValueError(f"disruption_type must be one of {DISRUPTION_TYPES}, got {dtype!r}")

    o_lat, o_lon, o_name = resolve_airport(origin_iata)
    d_lat, d_lon, d_name = resolve_airport(dest_iata)
    distance_km = haversine(o_lat, o_lon, d_lat, d_lon)

    base_amount, reduction_limit = _band_for(distance_km)
    band_label = f"≤1500 km" if base_amount == 250 else ("1500–3500 km" if base_amount == 400 else ">3500 km")

    # 3 h threshold applies only to *delays*; cancellation / denied boarding are candidates
    # regardless of delay (subject to the eligibility gate applied later, not here).
    if dtype == "delay":
        threshold_met = delay_hours >= DELAY_THRESHOLD_HOURS
    else:
        threshold_met = True

    # Art. 7(2): an offered re-routing whose arrival is within the band limit lets the carrier
    # halve the amount. Flag-driven for the prototype (the long-haul 3–4 h auto-50% nuance is
    # noted in DECISIONS, not encoded). Only meaningful when something is owed.
    reduction_applied = (
        threshold_met and rerouting_offered and delay_hours <= reduction_limit
    )

    if not threshold_met:
        final_amount = 0
    elif reduction_applied:
        final_amount = base_amount // 2
    else:
        final_amount = base_amount

    explanation = _explain(
        o_name, d_name, distance_km, band_label, base_amount, dtype, delay_hours,
        rerouting_offered, threshold_met, reduction_applied, final_amount, reduction_limit,
    )

    return {
        "origin_iata": origin_iata.strip().upper(),
        "dest_iata": dest_iata.strip().upper(),
        "origin_name": o_name,
        "dest_name": d_name,
        "distance_km": round(distance_km, 1),
        "band": band_label,
        "base_amount_eur": base_amount,
        "disruption_type": dtype,
        "delay_hours": delay_hours,
        "rerouting_offered": rerouting_offered,
        "threshold_met": threshold_met,
        "reduction_applied": reduction_applied,
        "final_amount_eur": final_amount,
        "explanation": explanation,
    }


def _explain(
    o_name, d_name, distance_km, band_label, base_amount, dtype, delay_hours,
    rerouting_offered, threshold_met, reduction_applied, final_amount, reduction_limit,
) -> str:
    """One-line plain-language rationale for the trace/UI (no LLM)."""
    head = (
        f"{o_name} → {d_name} is {distance_km:.0f} km ({band_label}) → base €{base_amount}."
    )
    if not threshold_met:
        return (
            f"{head} A delay of {delay_hours:g} h is under the {DELAY_THRESHOLD_HOURS} h "
            f"threshold, so no compensation is due on delay grounds (candidate €0)."
        )
    if reduction_applied:
        return (
            f"{head} Re-routing was offered with arrival within {reduction_limit} h, so the "
            f"amount is halved (Art. 7(2)) → €{final_amount}."
        )
    return f"{head} Full candidate amount applies → €{final_amount}."
