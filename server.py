from flask import Flask, render_template, request, redirect, url_for
import csv
import os
import json

app = Flask(__name__)

RULES_FILE = 'rules.csv'
ALERT_STATE_FILE = 'alert_state.json'

def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_alert_state(state):
    with open(ALERT_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # This part handles the rules form submission
        symbols = request.form.getlist('symbol')
        lows = request.form.getlist('low')
        highs = request.form.getlist('high')
        pct_ups = request.form.getlist('pct_up')
        pct_downs = request.form.getlist('pct_down')
        webhooks = request.form.getlist('webhook')

        new_rules = []
        for i in range(len(symbols)):
            if symbols[i]:
                new_rules.append({
                    'symbol': symbols[i].upper(),
                    'low': lows[i],
                    'high': highs[i],
                    'pct_up': pct_ups[i],
                    'pct_down': pct_downs[i],
                    'webhook': webhooks[i],
                })

        fieldnames = ['symbol', 'low', 'high', 'pct_up', 'pct_down', 'webhook']
        with open(RULES_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(new_rules)

        return redirect(url_for('index'))

    # Load data for rendering the page
    rules = []
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE, 'r', newline='') as f:
            reader = csv.DictReader(f)
            rules = list(reader)

    alert_state = load_alert_state()

    return render_template('index.html', rules=rules, alert_state=alert_state)

@app.route('/clear-alert', methods=['POST'])
def clear_alert():
    symbol = request.form.get('symbol')
    alert_type = request.form.get('alert_type')
    state = load_alert_state()

    if symbol in state and alert_type in state[symbol]:
        state[symbol].remove(alert_type)
        if not state[symbol]:  # Remove symbol if list is empty
            del state[symbol]
        save_alert_state(state)

    return redirect(url_for('index'))

@app.route('/clear-all-alerts', methods=['POST'])
def clear_all_alerts():
    save_alert_state({})
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=False)
