"""
Travel Cost Optimizer — Streamlit Web Application
==================================================
A visual interface for finding the cheapest flight + hotel combinations
within a flexible date window, powered by the Amadeus API.

Setup
-----
    pip install streamlit amadeus pandas plotly

    export AMADEUS_API_KEY="your_key"
    export AMADEUS_API_SECRET="your_secret"

    streamlit run streamlit_travel_app.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import product
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from amadeus import Client, ResponseError, NetworkError


# Constants

MAX_TRIP_DAYS = 14
REQUEST_COOLDOWN = 1.2
MAX_HOTEL_IDS_PER_SEARCH = 20
CURRENCY = "USD"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
log = logging.getLogger(__name__)



# DATA MODEL

@dataclass(order=True)
class TripQuote:
    total_cost: float
    departure: date = field(compare=False)
    return_date: date = field(compare=False)
    nights: int = field(compare=False)
    flight_price: float = field(compare=False)
    hotel_avg_night: float = field(compare=False)
    hotel_total: float = field(compare=False)


# AMADEUS CLIENT & API HELPERS

def build_client() -> Client:
    api_key = os.environ.get("AMADEUS_API_KEY")
    api_secret = os.environ.get("AMADEUS_API_SECRET")

    if not api_key or not api_secret:
        st.error(
            "**Missing API credentials.** Set `AMADEUS_API_KEY` and "
            "`AMADEUS_API_SECRET` as environment variables before launching."
        )
        st.stop()

    hostname = "production" if os.environ.get("AMADEUS_ENV") == "production" else "test"

    return Client(
        client_id=api_key,
        client_secret=api_secret,
        hostname=hostname,
        log_level="warn",
    )


def _error_detail(err: ResponseError) -> str:
    resp = getattr(err, "response", None)
    if resp is None:
        return str(err)
    status = getattr(resp, "status_code", "?")
    body = getattr(resp, "result", None) or getattr(resp, "body", None)
    return f"HTTP {status} — {body}"


def get_cheapest_flight(
    client: Client, origin: str, dest: str, dep: date, ret: date,
) -> Optional[float]:
    try:
        resp = client.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=dest,
            departureDate=dep.isoformat(),
            returnDate=ret.isoformat(),
            adults=1,
            currencyCode=CURRENCY,
            max=1,
        )
        offers = resp.data
        return float(offers[0]["price"]["grandTotal"]) if offers else None
    except (ResponseError, NetworkError) as err:
        log.warning("Flight error (%s→%s %s/%s): %s", origin, dest, dep, ret, _error_detail(err))
        return None


def _fetch_hotel_ids(client: Client, city_code: str) -> list[str]:
    try:
        resp = client.reference_data.locations.hotels.by_city.get(cityCode=city_code)
        return [h["hotelId"] for h in (resp.data or [])[:MAX_HOTEL_IDS_PER_SEARCH]]
    except (ResponseError, NetworkError) as err:
        log.warning("Hotel ID error for %s: %s", city_code, _error_detail(err))
        return []


def get_avg_hotel_price(
    client: Client, city_code: str, check_in: date, check_out: date,
    hotel_cache: dict[str, list[str]],
) -> Optional[float]:
    if city_code not in hotel_cache:
        hotel_cache[city_code] = _fetch_hotel_ids(client, city_code)
        time.sleep(REQUEST_COOLDOWN)

    ids = hotel_cache[city_code]
    if not ids:
        return None

    try:
        resp = client.shopping.hotel_offers_search.get(
            hotelIds=ids,
            checkInDate=check_in.isoformat(),
            checkOutDate=check_out.isoformat(),
            adults=1,
            currency=CURRENCY,
        )
        prices: list[float] = []
        for hotel in resp.data or []:
            for offer in hotel.get("offers", []):
                pi = offer.get("price", {})
                total = pi.get("total") or pi.get("base")
                if total is not None:
                    nights = max((check_out - check_in).days, 1)
                    prices.append(float(total) / nights)
        return round(sum(prices) / len(prices), 2) if prices else None
    except (ResponseError, NetworkError) as err:
        log.warning("Hotel offer error for %s: %s", city_code, _error_detail(err))
        return None


# DATE GRID & PIPELINE

def generate_date_pairs(ideal_dep: date, ideal_ret: date, n: int) -> list[tuple[date, date]]:
    deps = [ideal_dep + timedelta(days=d) for d in range(-n, n + 1)]
    rets = [ideal_ret + timedelta(days=d) for d in range(-n, n + 1)]
    return [(d, r) for d, r in product(deps, rets) if 1 <= (r - d).days <= MAX_TRIP_DAYS]


@st.cache_data(show_spinner=False)
def fetch_all_quotes(
    origin: str, destination: str,
    ideal_dep_iso: str, ideal_ret_iso: str,
    n: int,
) -> tuple[list[dict], Optional[dict]]:
    """Fetch all quotes. Returns (all_records, ideal_record | None).

    Dates are passed as ISO strings so Streamlit can hash them for caching.
    """
    ideal_dep = date.fromisoformat(ideal_dep_iso)
    ideal_ret = date.fromisoformat(ideal_ret_iso)

    client = build_client()
    pairs = generate_date_pairs(ideal_dep, ideal_ret, n)
    total_pairs = len(pairs)

    hotel_cache: dict[str, list[str]] = {}
    quotes: list[TripQuote] = []

    # --- Progress UI ---
    progress_bar = st.progress(0, text="Preparing search…")
    status = st.status(f"Searching {total_pairs} date combinations…", expanded=True)

    for idx, (dep, ret) in enumerate(pairs, start=1):
        nights = (ret - dep).days
        pct = idx / total_pairs
        label = f"Querying combo {idx}/{total_pairs}:  {dep} → {ret}  ({nights}n)"
        progress_bar.progress(pct, text=label)
        status.write(f"✈️  `{dep}` → `{ret}`  ({nights} nights)")

        flight = get_cheapest_flight(client, origin, destination, dep, ret)
        time.sleep(REQUEST_COOLDOWN)

        if flight is None:
            status.write("   ↳ no flight offers — skipped")
            continue

        hotel_avg = get_avg_hotel_price(client, destination, dep, ret, hotel_cache)
        time.sleep(REQUEST_COOLDOWN)

        if hotel_avg is None:
            status.write("   ↳ no hotel offers — skipped")
            continue

        ht = round(hotel_avg * nights, 2)
        total = round(flight + ht, 2)
        quotes.append(TripQuote(total, dep, ret, nights, flight, hotel_avg, ht))
        status.write(f"   ↳ **${total:,.2f}**  (flight ${flight:,.2f} + hotel ${ht:,.2f})")

    progress_bar.progress(1.0, text="Done!")
    status.update(label=f"Finished — {len(quotes)} quotes found", state="complete")

    # --- Build records ---
    quotes.sort()
    records = [
        {
            "Dep_Date": q.departure.isoformat(),
            "Ret_Date": q.return_date.isoformat(),
            "Nights": q.nights,
            "Flight_Price": q.flight_price,
            "Hotel_Avg_Night": q.hotel_avg_night,
            "Hotel_Total": q.hotel_total,
            "Total_Cost": q.total_cost,
        }
        for q in quotes
    ]

    ideal_record = None
    for r in records:
        if r["Dep_Date"] == ideal_dep_iso and r["Ret_Date"] == ideal_ret_iso:
            ideal_record = r
            break

    return records, ideal_record


# VISUALISATION HELPERS

def build_heatmap(df: pd.DataFrame) -> go.Figure:
    """Create a Departure × Return cost heatmap."""
    pivot = df.pivot_table(
        index="Ret_Date", columns="Dep_Date", values="Total_Cost", aggfunc="min",
    )
    # Sort axes chronologically
    pivot = pivot.sort_index(ascending=False)
    pivot = pivot[sorted(pivot.columns)]

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=[
            [0.0, "#10b981"],   # cheapest  — green
            [0.5, "#fbbf24"],   # mid       — amber
            [1.0, "#ef4444"],   # expensive — red
        ],
        hovertemplate=(
            "Depart: %{x}<br>Return: %{y}<br>"
            "Total: $%{z:,.2f}<extra></extra>"
        ),
        colorbar=dict(title="Total ($)", tickprefix="$"),
    ))

    fig.update_layout(
        title="Total Trip Cost by Date Combination",
        xaxis_title="Departure Date",
        yaxis_title="Return Date",
        height=500,
        margin=dict(l=80, r=40, t=60, b=80),
    )
    return fig


# STREAMLIT UI

def main() -> None:
    st.set_page_config(page_title="Travel Cost Optimizer", page_icon="✈️", layout="wide")
    st.title("✈️ Travel Cost Optimizer")
    st.caption("Find the cheapest flight + hotel combo within your flexible date window.")

    # Sidebar inputs:
    with st.sidebar:
        st.header("Search Parameters")

        origin = st.text_input("Origin (IATA code)", value="BOS", max_chars=3).upper()
        destination = st.text_input("Destination (IATA code)", value="CDG", max_chars=3).upper()

        st.divider()

        today = date.today()
        default_dep = today + timedelta(days=30)
        default_ret = today + timedelta(days=37)

        ideal_dep = st.date_input("Ideal Departure", value=default_dep)
        ideal_ret = st.date_input("Ideal Return", value=default_ret)

        n = st.slider("Flexibility (± days)", min_value=0, max_value=7, value=3)

        st.divider()
        top_k = st.slider("Show Top K results", min_value=3, max_value=20, value=5)

        search = st.button("🔍  Search Best Deals", use_container_width=True, type="primary")

    # Validation:
    if search:
        if len(origin) != 3 or len(destination) != 3:
            st.error("Origin and Destination must be 3-letter IATA codes.")
            return
        if ideal_ret <= ideal_dep:
            st.error("Return date must be after departure date.")
            return
        if (ideal_ret - ideal_dep).days > MAX_TRIP_DAYS:
            st.error(f"Trip duration cannot exceed {MAX_TRIP_DAYS} days.")
            return

        # Fetch data:
        records, ideal_record = fetch_all_quotes(
            origin, destination,
            ideal_dep.isoformat(), ideal_ret.isoformat(), n,
        )

        if not records:
            st.warning("No complete quotes were found. Try different dates or routes.")
            return

        df_all = pd.DataFrame(records)
        df_top = df_all.head(top_k).copy()
        df_top.insert(0, "Rank", range(1, len(df_top) + 1))

        # Metric cards:
        best = records[0]

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("🏆 Best Total", f"${best['Total_Cost']:,.2f}")
        with col2:
            st.metric("Best Departure", best["Dep_Date"])
        with col3:
            st.metric("Best Return", best["Ret_Date"])
        with col4:
            if ideal_record:
                saving = ideal_record["Total_Cost"] - best["Total_Cost"]
                st.metric(
                    "Savings vs Ideal Dates",
                    f"${saving:,.2f}",
                    delta=f"-${saving:,.2f}" if saving > 0 else "$0",
                    delta_color="inverse",
                )
            else:
                st.metric("Savings vs Ideal Dates", "N/A",
                           help="Ideal date combo had no available offers.")

        st.divider()

        # Results table:
        st.subheader(f"Top {len(df_top)} Cheapest Combinations")

        st.dataframe(
            df_top.style.format({
                "Flight_Price": "${:,.2f}",
                "Hotel_Avg_Night": "${:,.2f}",
                "Hotel_Total": "${:,.2f}",
                "Total_Cost": "${:,.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # CSV download:
        csv = df_all.to_csv(index=False)
        st.download_button(
            "📥  Download all results as CSV",
            data=csv,
            file_name=f"travel_quotes_{origin}_{destination}.csv",
            mime="text/csv",
        )

        st.divider()

        # Heatmap:
        st.subheader("Cost Heatmap")
        if len(df_all) >= 2:
            fig = build_heatmap(df_all)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough data points to generate a heatmap.")

    else:
        # Landing state:
        st.info("👈  Configure your search in the sidebar and click **Search Best Deals**.")


if __name__ == "__main__":
    main()
    