from flask import Flask, render_template, request, redirect, url_for
import csv
import os

app = Flask(__name__)

RULES_FILE = 'rules.csv'

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        symbols = request.form.getlist('symbol')
        lows = request.form.getlist('low')
        highs = request.form.getlist('high')
        pct_ups = request.form.getlist('pct_up')
        pct_downs = request.form.getlist('pct_down')
        webhooks = request.form.getlist('webhook')

        new_rules = []
        for i in range(len(symbols)):
            # Don't save empty rows where the symbol is missing
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

    rules = []
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE, 'r', newline='') as f:
            reader = csv.DictReader(f)
            rules = list(reader)

    return render_template('index.html', rules=rules)

if __name__ == '__main__':
    app.run(debug=True)
