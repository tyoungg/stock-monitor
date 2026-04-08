import yfinance as yf
import json

def test_burry_data(symbol):
    print(f"--- {symbol} ---")
    t = yf.Ticker(symbol)

    print("Cashflow columns:")
    print(t.cashflow.index.tolist())

    # Try to find RSU tax related keys
    rsu_keys = [
        'Payments for tax related to settlement of equity awards',
        'Cash Paid for Tax Related to Settlement of Equity Awards',
        'Taxes Paid Related to Settlement of Equity Awards',
        'Common Stock Payments',
        'Other Cash Payments from Financing Activities'
    ]

    for k in rsu_keys:
        if k in t.cashflow.index:
            print(f"{k}: {t.cashflow.loc[k].tolist()}")

    print("Net Income:")
    if 'Net Income' in t.financials.index:
        print(t.financials.loc['Net Income'].tolist())

    print("Stock Based Compensation:")
    if 'Stock Based Compensation' in t.cashflow.index:
        print(t.cashflow.loc['Stock Based Compensation'].tolist())

    print("Repurchase Of Capital Stock:")
    if 'Repurchase Of Capital Stock' in t.cashflow.index:
        print(t.cashflow.loc['Repurchase Of Capital Stock'].tolist())

test_burry_data("NVDA")
test_burry_data("MSFT")
