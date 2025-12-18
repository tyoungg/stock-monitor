# stock-monitor- ✅ Stock monitor using GitHub Actions + Python

A small, opinionated setup for running scheduled stock checks and sending alerts when rules trigger.

## What you get

- Runs on a schedule via GitHub Actions (cron)
- Pulls market data via `yfinance`
- Evaluates rules from `rules.csv`
- Sends alerts to a webhook when conditions are met (or prints them when no webhook is configured)

---

## Files

- `monitor.py` - the monitoring script
- `rules.csv` - list of rules (symbol, low, high, pct_up, pct_down, webhook)
- `requirements.txt` - Python dependencies
- `.github/workflows/stock_monitor.yml` - workflow that runs the monitor on a schedule

---

## Quick start

1. Create a repo using these files (or push this repo to GitHub)
2. Add a repository secret named `STOCK_MONITOR_WEBHOOK` with your webhook URL (Slack/Discord/other) if you want alerts to be delivered.
3. The workflow runs on a cron schedule (hourly by default). You can also trigger it manually from the Actions tab; the manual trigger accepts inputs:
   - `stocks` — comma-separated list of symbols to monitor (optional)
   - `default_pct_up` / `default_pct_down` — defaults to apply to symbols provided via `stocks` or `stocks.txt`

> Note: The workflow uses the `Ilshidur/action-discord` action and looks for a secret named `discord_webhook` (fallback: `STOCK_MONITOR_WEBHOOK`). Add your Discord webhook URL as a repository secret with the name `discord_webhook` (or keep using `STOCK_MONITOR_WEBHOOK` if that's already configured). You can modify the workflow to use a different action (Slack, Teams, etc.) or change `monitor.py` to format richer payloads (Discord embeds).

---

### ✅ CI validation & artifacts
A small CI workflow (`.github/workflows/ci.yml`) is included which installs dependencies and runs `monitor.py` with a test rule to ensure the environment and script run correctly. It now uploads `alerts.json` as an artifact (name: `ci-alerts-json`).

### 🎨 Discord embeds
`monitor.py` now writes structured `alerts.json` (array of objects: `symbol`, `triggers`, `price`, `prev_close`, `change`, `text`, `severity`). The workflow prepares Discord *embeds* from these alerts and posts them to your webhook — this produces nicer messages using the Discord embeds API.


Happy monitoring! 🎯
stock monitor try
