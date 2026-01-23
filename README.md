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

### Editing Rules and Managing Alerts with the Web Interface

To make it easier to add, remove, or update rules, this project includes a local web server that provides a simple editor for the `rules.csv` file. The web interface also allows you to view and manage silenced alerts.

**To run the editor:**

1.  Make sure you have installed the dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Start the local server:
    ```bash
    python server.py
    ```
3.  Open your web browser and navigate to `http://127.0.0.1:5000`.

You will see a table with all the current rules. You can edit the values, add new rows, or clear out rows to remove them. Click "Save Rules" to update the `rules.csv` file.

Below the rules editor, you will find a section for "Silenced Alerts". This table shows you which alerts have been triggered and are currently silenced. You can re-enable individual alerts or clear all silenced alerts using the buttons provided.

**Note on Debug Mode:** For security, the Flask server runs with debug mode disabled by default. If you are developing the tool and need more detailed error messages, you can temporarily enable it by changing `app.run(debug=False)` to `app.run(debug=True)` at the end of the `server.py` file.

---

### ✅ CI validation & artifacts
A small CI workflow (`.github/workflows/ci.yml`) is included which installs dependencies and runs `monitor.py` with a test rule to ensure the environment and script run correctly. It now uploads `alerts.json` as an artifact (name: `ci-alerts-json`).

### 🎨 Discord embeds
`monitor.py` now writes structured `alerts.json` (array of objects: `symbol`, `triggers`, `price`, `prev_close`, `change`, `text`, `severity`). The workflow prepares Discord *embeds* from these alerts and posts them to your webhook — this produces nicer messages using the Discord embeds API.


Happy monitoring! 🎯

---

### 📧 Email Alerts
You can receive a single email with all alerts. To do so, you will need to configure the following secrets in your GitHub repository:
- `ALERT_EMAIL_RECIPIENT`: The email address to send the alerts to.
- `MAIL_SERVER`: The SMTP server address.
- `MAIL_PORT`: The SMTP server port.
- `MAIL_USERNAME`: The username for the SMTP server.
- `MAIL_PASSWORD`: The password for the SMTP server.

### 📊 Market Recap Email
In addition to alerts, a daily market recap email is sent shortly after the market closes. This email provides a summary of the day's performance for all monitored stocks in a formatted HTML table.

### 🤫 Permanent Alert Silencing
To prevent repeat notifications, once a stock triggers an alert, it is permanently silenced. The symbol of the triggered stock is added to the `alert_state.json` file.

**To re-enable an alert for a stock**, you can now use the web interface as described above, or you can manually edit the `alert_state.json` file in the repository.
