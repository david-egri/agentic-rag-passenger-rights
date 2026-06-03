"""Direct test set for the deterministic calculator — the one classic-test exception.

The calculator produces the compensation amounts that double as eval ground truth, so a wrong
euro figure is the worst failure mode (CLAUDE.md): it earns a small, direct test set even
though the rest of the app is verified functionally. Expected distances/amounts were
recomputed from the real OpenFlights coordinates (not the proposal's approximations) — e.g.
BUD→LHR is 1489.5 km, just *under* the 1500 km boundary (proposal guessed ~1450).

Run:  pytest tests/test_calculator.py
"""

import math

import pytest

from src.calculator import (
    AirportNotFound,
    compute_compensation,
    haversine,
    resolve_airport,
)


def test_haversine_known_distance():
    """LHR→JFK is ~5540–5560 km by great circle — sanity-check the formula."""
    lhr = resolve_airport("LHR")
    jfk = resolve_airport("JFK")
    d = haversine(lhr[0], lhr[1], jfk[0], jfk[1])
    assert math.isclose(d, 5550, abs_tol=60)


# --- Distance bands → base amount (Art. 7(1)) --------------------------------------------
# Each route's distance is asserted too, so a future airports.dat change that shifts a route
# across a band boundary fails loudly rather than silently changing an amount.
@pytest.mark.parametrize(
    "origin,dest,expected_km,expected_band,expected_base",
    [
        ("CDG", "FCO", 1100.7, "≤1500 km", 250),       # short-haul
        ("BUD", "LHR", 1489.5, "≤1500 km", 250),        # just UNDER the 1500 boundary
        ("LHR", "LIS", 1563.9, "1500–3500 km", 400),    # just OVER the 1500 boundary
        ("FRA", "CAI", 2921.7, "1500–3500 km", 400),    # mid medium-haul
        ("MAD", "JFK", 5762.2, ">3500 km", 600),        # long-haul
    ],
)
def test_distance_bands(origin, dest, expected_km, expected_band, expected_base):
    r = compute_compensation(origin, dest, delay_hours=4)
    assert r["distance_km"] == pytest.approx(expected_km, abs=1.0)
    assert r["band"] == expected_band
    assert r["base_amount_eur"] == expected_base
    assert r["final_amount_eur"] == expected_base  # 4 h delay, no rerouting → full amount


# --- 3-hour delay threshold (Sturgeon) ---------------------------------------------------
@pytest.mark.parametrize(
    "delay_hours,threshold_met,final",
    [
        (2.0, False, 0),     # under 3 h → nothing on delay grounds
        (2.99, False, 0),    # still under
        (3.0, True, 250),    # exactly at threshold → owed
        (5.0, True, 250),    # well over
    ],
)
def test_delay_threshold(delay_hours, threshold_met, final):
    r = compute_compensation("CDG", "FCO", delay_hours, disruption_type="delay")
    assert r["threshold_met"] is threshold_met
    assert r["final_amount_eur"] == final


def test_cancellation_ignores_delay_threshold():
    """Cancellation / denied boarding are candidates regardless of delay (gate applies later)."""
    r = compute_compensation("CDG", "FCO", delay_hours=0, disruption_type="cancellation")
    assert r["threshold_met"] is True
    assert r["final_amount_eur"] == 250

    r2 = compute_compensation("MAD", "JFK", delay_hours=0, disruption_type="denied_boarding")
    assert r2["final_amount_eur"] == 600


# --- 50%-reduction rule (Art. 7(2): re-routing within the band's arrival limit) ----------
def test_reduction_applies_within_band_limit():
    """≤1500 km band: re-routing offered with arrival within 2 h halves €250 → €125."""
    r = compute_compensation("CDG", "FCO", delay_hours=2, disruption_type="cancellation",
                             rerouting_offered=True)
    assert r["reduction_applied"] is True
    assert r["final_amount_eur"] == 125


def test_no_reduction_when_arrival_exceeds_limit():
    """Re-routing offered but arrival delay (6 h) exceeds the 2 h limit → full €250."""
    r = compute_compensation("CDG", "FCO", delay_hours=6, disruption_type="cancellation",
                             rerouting_offered=True)
    assert r["reduction_applied"] is False
    assert r["final_amount_eur"] == 250


def test_reduction_band_limit_scales_with_distance():
    """Long-haul limit is 4 h: re-routing at 4 h halves €600 → €300; at 5 h it's full."""
    halved = compute_compensation("MAD", "JFK", delay_hours=4, disruption_type="cancellation",
                                  rerouting_offered=True)
    assert halved["final_amount_eur"] == 300

    full = compute_compensation("MAD", "JFK", delay_hours=5, disruption_type="cancellation",
                                rerouting_offered=True)
    assert full["final_amount_eur"] == 600


def test_no_reduction_without_offer():
    """No re-routing offered → never reduced, even within the time window."""
    r = compute_compensation("CDG", "FCO", delay_hours=1.5, disruption_type="cancellation",
                             rerouting_offered=False)
    assert r["reduction_applied"] is False
    assert r["final_amount_eur"] == 250


# --- Error handling ----------------------------------------------------------------------
def test_unknown_iata_raises():
    with pytest.raises(AirportNotFound):
        compute_compensation("ZZZ", "LHR", delay_hours=4)


def test_invalid_disruption_type_raises():
    with pytest.raises(ValueError):
        compute_compensation("CDG", "FCO", delay_hours=4, disruption_type="volcano")
