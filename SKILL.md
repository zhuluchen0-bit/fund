---
name: fund-estimator
description: "Estimate daily NAV changes for Chinese equity funds based on their top-10 holdings and real-time stock quotes. Supports querying fund top-10 holdings from East Money, fetching real-time A-share prices from Tencent Finance, calculating weighted estimated fund returns, and managing a watchlist portfolio. Use when the user asks about fund NAV estimates, fund holdings analysis, real-time fund valuation, or portfolio tracking."
---

# Fund NAV Estimator (基金净值估算工具)

Estimates daily NAV changes for Chinese public funds by:
1. Fetching the latest top-10 holdings from 天天基金
2. Getting real-time A-share stock prices from 腾讯行情
3. Calculating a weighted estimated return

## Quick Start

The main script is `scripts/nav_estimator.py` — a Tkinter GUI app.

To launch:
```bash
python3 fund-estimator/scripts/nav_estimator.py
```

Or double-click `启动基金估算工具.command` in the workspace root.

## How It Works

### Data Sources
- **Holdings data**: `https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10&year=&month=`
  Returns HTML with fund name and the latest quarterly top-10 stock holdings with weight percentages.
- **Real-time quotes**: `https://qt.gtimg.cn/q={market_prefix}{stock_code}`
  Returns real-time A-share prices and percentage change via Tencent Finance API.

### Estimation Formula
```
fund_return = sum(stock_weight% × stock_change% / 100)
```

Where `stock_weight%` is the fund's NAV percentage (e.g., 9.69%) and `stock_change%` is the stock's real-time price change percentage.

**Note**: This is an estimate based on the latest disclosed quarterly holdings. The fund manager may have adjusted positions since the report date.

### Portfolio P&L
If the user provides position data:
- **Daily P&L** = position_amount × estimated_return%
- **Updated yield** = 100 × ((1 + current_yield/100) × (1 + estimated_return/100) - 1)

## When to Use

Trigger this skill when the user asks about:
- "Can you estimate today's NAV change for fund XXX?"
- "What are the top holdings of fund XXX?"
- "How much did my fund portfolio gain/lose today?"
- Any Chinese fund valuation or holdings analysis queries

## Scripts

### `scripts/nav_estimator.py`

A standalone Tkinter desktop application that:
- Manages a local fund portfolio (add/edit/delete funds with position data)
- Fetches top-10 holdings data from the internet
- Gets real-time stock quotes
- Displays estimated NAV changes, daily P&L, and updated yield
- Auto-refreshes prices every 15 seconds

Key functions for programmatic use:
```python
# Fetch top-10 holdings for a fund
from nav_estimator import fetch_top10_holdings
name, codes, weights = fetch_top10_holdings("006503")
# Returns: ("基金名称", ["301200", "301377", ...], [9.84, 9.84, ...])

# Get real-time stock quote
from nav_estimator import get_stock_quote
price, change_pct = get_stock_quote("300308")
# Returns: (1103.00, 0.91)

# Full estimate for a fund
from nav_estimator import estimate_fund_return
name, stock_data, estimated_return, coverage = estimate_fund_return("006503")
# estimated_return is in percentage format (e.g., 2.25 = 2.25%)
# coverage is the fraction of NAV covered by top-10 (e.g., 0.863 = 86.3%)
```

### Configuration

The portfolio is saved to `fund_portfolio.json` in the script's directory:
```json
[
  {
    "code": "006503",
    "name": "财通集成电路产业股票C",
    "amount": 100000,
    "shares": 12345.67,
    "yield_pct": 5.0
  }
]
```
