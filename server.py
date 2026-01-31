from flask import Flask, render_template, request, redirect, url_for
import csv
import json
import os

app = Flask(__name__)

RULES_FILE = 'rules.csv'
ALERT_STATE_FILE = 'alert_state.json'

def read_rules():
    if not os.path.exists(RULES_FILE):
        return []
    with open(RULES_FILE, 'r') as f:
        reader = csv.DictReader(f)
        return list(reader)

def write_rules(rules):
    with open(RULES_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['symbol', 'low', 'high', 'pct_up', 'pct_down', 'webhook'])
        writer.writeheader()
        writer.writerows(rules)

def read_alert_state():
    if not os.path.exists(ALERT_STATE_FILE):
        return {}
    with open(ALERT_STATE_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def write_alert_state(alert_state):
    with open(ALERT_STATE_FILE, 'w') as f:
        json.dump(alert_state, f, indent=4)

@app.route('/')
def index():
    rules = read_rules()
    alert_state = read_alert_state()
    return render_template('index.html', rules=rules, alert_state=alert_state)

@app.route('/save', methods=['POST'])
def save_rules():
    rules = []
    symbols = request.form.getlist('symbol')
    lows = request.form.getlist('low')
    highs = request.form.getlist('high')
    pct_ups = request.form.getlist('pct_up')
    pct_downs = request.form.getlist('pct_down')
    webhooks = request.form.getlist('webhook')

    for i in range(len(symbols)):
        if symbols[i]:
            rules.append({
                'symbol': symbols[i],
                'low': lows[i],
                'high': highs[i],
                'pct_up': pct_ups[i],
                'pct_down': pct_downs[i],
                'webhook': webhooks[i]
            })

    write_rules(rules)
    return redirect(url_for('index'))

@app.route('/reenable', methods=['POST'])
def reenable_alert():
    symbol = request.form.get('symbol')
    alert_type = request.form.get('alert_type')
    alert_state = read_alert_state()
    if symbol in alert_state and alert_type in alert_state[symbol]:
        alert_state[symbol].remove(alert_type)
        if not alert_state[symbol]:
            del alert_state[symbol]
        write_alert_state(alert_state)
    return redirect(url_for('index'))

@app.route('/clear_all', methods=['POST'])
def clear_all_alerts():
    write_alert_state({})
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0')