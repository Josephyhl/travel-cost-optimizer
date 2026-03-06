# ✈️ Travel Cost Optimizer

Find the cheapest flight + hotel combo by searching across flexible travel dates — powered by the [Amadeus API](https://developers.amadeus.com/).

## Features

- **Flexible Date Grid** — Generates all valid departure/return combinations within ±N days of your ideal dates
- **Real-time Price Fetching** — Pulls live flight and hotel prices from Amadeus
- **Smart Ranking** — Calculates total trip cost and surfaces the Top K cheapest options
- **Interactive Dashboard** — Streamlit web UI with sidebar controls, progress tracking, and CSV export
- **Cost Heatmap** — Plotly-powered visualization showing price by date combination (green = cheap, red = expensive)
- **Savings Metric** — Shows how much you save vs. your original ideal dates

## Tech Stack

- **Python 3.13** / Pandas / Dataclasses
- **Amadeus SDK** — Flight Offers Search + Hotel Offers Search
- **Streamlit** — Web UI with caching (`st.cache_data`)
- **Plotly** — Interactive heatmap visualization

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/travel-cost-optimizer.git
cd travel-cost-optimizer

# Install dependencies
pip install amadeus pandas streamlit plotly

# Set API credentials
export AMADEUS_API_KEY="your_key"
export AMADEUS_API_SECRET="your_secret"

# Run the web app
streamlit run streamlit_travel_app.py

# Or run the CLI version
python Travel.py
```

## Getting API Keys

1. Sign up at [developers.amadeus.com](https://developers.amadeus.com/)
2. Create an app in the dashboard
3. Copy your API Key and API Secret

## Screenshot

> *Add a screenshot of your Streamlit dashboard here*

## License

MIT
