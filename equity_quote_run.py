"""
One-shot runner to scrape an NSE equity quote page with human-like behavior.

Edit the URL/OUTPUT_DIR/HEADLESS/TAKE_SCREENSHOT constants below and run:
    python equity_quote_run.py

Outputs:
    - Screenshot (optional)
    - Rendered HTML
    - Parsed JSON with all quote data
"""

import asyncio
import os
import random
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --------- CONFIG ---------
URL = "https://www.nseindia.com/get-quote/equity/RELIANCE/Reliance-Industries-Limited"
OUTPUT_DIR = "output"
HEADLESS = False           # Set True to hide browser
TAKE_SCREENSHOT = True     # Set False to skip screenshot
# ---------------------------


async def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Add random delay to simulate human behavior."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def extract_value_after_label(text: str, label: str) -> str:
    """
    Extract numeric value that appears immediately after a label in text.
    Example: "Open1,534.00" with label "Open" returns "1,534.00"
    """
    pattern = label + r'([0-9,.\-]+)'
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def parse_nse_quote_html(html_content: str) -> dict:
    """
    Parse the rendered NSE equity quote HTML and extract all data.
    
    NSE stores data in specific div structures with continuous text
    (no spaces between labels and values).
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    data = {}
    
    try:
        # Get main body text for pattern matching
        main_body = soup.find('main', id='midBody')
        if not main_body:
            return {"error": "Main body not found"}
        
        body_text = main_body.get_text()
        
        # Extract symbol from header
        symbol_elem = soup.find('span', class_='symbol-text')
        if symbol_elem:
            data['symbol'] = symbol_elem.get_text(strip=True)
        
        # Extract current price from index-highlight
        ltp_div = soup.find('div', class_='index-highlight')
        if ltp_div:
            spans = ltp_div.find_all('span', class_='value')
            if not spans:
                spans = ltp_div.find_all('span')
            price_text = ''.join([span.get_text(strip=True) for span in spans])
            data['last_price'] = price_text.strip()
        
        # Extract change and percent change
        change_divs = soup.find_all('div', class_='index-change-highlight')
        if len(change_divs) >= 2:
            change_spans = change_divs[0].find_all('span')
            pct_spans = change_divs[1].find_all('span')
            data['change'] = ''.join([s.get_text(strip=True) for s in change_spans]).strip()
            data['percent_change'] = ''.join([s.get_text(strip=True) for s in pct_spans]).strip()
        
        # Extract OHLC and VWAP from symbol-item divs
        symbol_items = soup.find_all('div', class_='symbol-item')
        for item in symbol_items:
            text = item.get_text(strip=True)
            
            if text.startswith('Prev. Close'):
                data['prev_close'] = extract_value_after_label(text, 'Prev. Close')
            elif text.startswith('Open'):
                data['open'] = extract_value_after_label(text, 'Open')
            elif text.startswith('High'):
                data['high'] = extract_value_after_label(text, 'High')
            elif text.startswith('Low'):
                data['low'] = extract_value_after_label(text, 'Low')
            elif text.startswith('VWAP'):
                data['vwap'] = extract_value_after_label(text, 'VWAP')
            elif text.startswith('Close'):
                close_val = extract_value_after_label(text, 'Close')
                if close_val and close_val != '-':
                    data['close'] = close_val
        
        # Extract volume and value from body text
        vol_match = re.search(r'Traded Volume \(Lakhs\)([0-9,.]+)', body_text)
        if vol_match:
            data['traded_volume_lakhs'] = vol_match.group(1)
        
        val_match = re.search(r'Traded Value \(₹ Cr\.\)([0-9,.]+)', body_text)
        if val_match:
            data['traded_value_cr'] = val_match.group(1)
        
        # Extract market cap
        mcap_match = re.search(r'Total Market Cap \(₹ Cr\.\)([0-9,.]+)', body_text)
        if mcap_match:
            data['total_market_cap_cr'] = mcap_match.group(1)
        
        ffmc_match = re.search(r'Free Float Market Cap \(₹ Cr\.\)([0-9,.]+)', body_text)
        if ffmc_match:
            data['free_float_market_cap_cr'] = ffmc_match.group(1)
        
        # Extract impact cost and face value
        impact_match = re.search(r'Impact cost([0-9,.]+)', body_text)
        if impact_match:
            data['impact_cost'] = impact_match.group(1)
        
        fv_match = re.search(r'Face Value([0-9,.]+)', body_text)
        if fv_match:
            data['face_value'] = fv_match.group(1)
        
        # Extract 52-week high and low
        high52_match = re.search(r'52 Week High \([^)]+\)([0-9,.]+)', body_text)
        if high52_match:
            data['52_week_high'] = high52_match.group(1)
        
        low52_match = re.search(r'52 Week Low \([^)]+\)([0-9,.]+)', body_text)
        if low52_match:
            data['52_week_low'] = low52_match.group(1)
        
        # Extract upper and lower bands
        upper_match = re.search(r'Upper Band([0-9,.]+)', body_text)
        if upper_match:
            data['upper_band'] = upper_match.group(1)
        
        lower_match = re.search(r'Lower Band([0-9,.]+)', body_text)
        if lower_match:
            data['lower_band'] = lower_match.group(1)
        
        # Extract delivery data
        del_qty_match = re.search(r'Deliverable / Traded Quantity([0-9,.]+)%', body_text)
        if del_qty_match:
            data['delivery_qty_pct'] = del_qty_match.group(1) + '%'
        
        # Extract volatility
        daily_vol_match = re.search(r'Daily Volatility([0-9,.]+)', body_text)
        if daily_vol_match:
            data['daily_volatility'] = daily_vol_match.group(1)
        
        annual_vol_match = re.search(r'Annualised Volatility([0-9,.]+)', body_text)
        if annual_vol_match:
            data['annualised_volatility'] = annual_vol_match.group(1)
        
        # Extract P/E and other ratios
        pe_match = re.search(r'Symbol P/E([0-9,.]+)', body_text)
        if pe_match:
            data['pe'] = pe_match.group(1)
        
        adj_pe_match = re.search(r'Adjusted P/E([0-9,.]+)', body_text)
        if adj_pe_match:
            data['adjusted_pe'] = adj_pe_match.group(1)
        
        # Extract security info
        isin_match = re.search(r'\(([A-Z]{2}[A-Z0-9]{10})\)', body_text)
        if isin_match:
            data['isin'] = isin_match.group(1)
        
        listing_match = re.search(r'Date of Listing([0-9]{2}-[A-Za-z]{3}-[0-9]{4})', body_text)
        if listing_match:
            data['listing_date'] = listing_match.group(1)
        
        # Extract industry
        industry_match = re.search(r'Basic Industry([A-Za-z &]+)Dashboard', body_text)
        if industry_match:
            data['industry'] = industry_match.group(1).strip()
        
        # Extract order book data (Total Buy/Sell Quantity)
        order_data = soup.find('div', class_='OrderData')
        if order_data:
            order_text = order_data.get_text()
            # The order book shows individual bids/asks, not total quantities
            # We need to find total buy/sell elsewhere
        
        # Look for buy/sell quantities in the main text
        buy_qty_match = re.search(r'Total Buy Quantity([0-9,.]+)', body_text)
        if buy_qty_match:
            data['total_buy_qty'] = buy_qty_match.group(1)
        
        sell_qty_match = re.search(r'Total Sell Quantity([0-9,.]+)', body_text)
        if sell_qty_match:
            data['total_sell_qty'] = sell_qty_match.group(1)
        
        # Extract returns data (YTD, 1M, 3M, 6M, 1Y, 3Y, 5Y)
        # These are typically shown as percentages in specific sections
        data['returns'] = {}
        
        # Find all text elements containing percentages
        percent_texts = soup.find_all(string=lambda t: t and '%' in t and len(t.strip()) < 50)
        
        for text in percent_texts:
            text_stripped = text.strip()
            parent = text.find_parent()
            if not parent or parent.name in ['style', 'script']:
                continue
            
            # Get the context around this percentage
            parent_text = parent.get_text(strip=True)
            
            # Look for return period indicators
            # Patterns like "YTD26.26%" or "1M3.54%"
            for period in ['YTD', '1M', '3M', '6M', '1Y', '3Y', '5Y', '10Y', '15Y', '20Y', '25Y', '30Y']:
                if period in parent_text:
                    # Extract the percentage near this period
                    period_match = re.search(period + r'\s*([0-9.]+%)', parent_text)
                    if period_match:
                        data['returns'][period] = period_match.group(1)
        
    except Exception as e:
        data['parse_error'] = str(e)
    
    return data


async def scrape_equity_quote(
    url: str,
    output_dir: str = "output",
    headless: bool = False,
    take_screenshot: bool = True,
) -> dict:
    """Scrape the NSE equity quote page; save screenshot, HTML, and extract data."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = url.split("//")[-1].split("/")[0].replace(".", "_")
    screenshot_path = os.path.join(output_dir, f"{domain}_quote_{timestamp}.png")
    html_path = os.path.join(output_dir, f"{domain}_quote_{timestamp}.html")
    json_path = os.path.join(output_dir, f"{domain}_quote_{timestamp}.json")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        # Hide automation flags
        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """
        )

        # Extra headers
        await page.set_extra_http_headers(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://www.google.com/",
            }
        )

        try:
            print(f"[INFO] Opening page: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            print("[INFO] Waiting for page to settle...")
            await human_delay(2, 4)

            # Move mouse to simulate activity
            await page.mouse.move(random.randint(200, 600), random.randint(200, 600))
            await human_delay(0.5, 1.0)

            # Scroll a bit
            await page.mouse.wheel(0, random.randint(200, 600))
            await human_delay(0.5, 1.0)

            # Extra wait for dynamic content to fully load
            await human_delay(3, 5)

            if take_screenshot:
                print("[INFO] Taking screenshot...")
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"[SUCCESS] Screenshot saved: {screenshot_path}")

            print("[INFO] Saving HTML content...")
            html_content = await page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"[SUCCESS] HTML saved: {html_path}")

            print("[INFO] Parsing HTML to extract data...")
            parsed_data = parse_nse_quote_html(html_content)
            
            # Save parsed JSON
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(parsed_data, f, indent=2, ensure_ascii=False)
            print(f"[SUCCESS] Parsed JSON saved: {json_path}")

            await context.close()
            await browser.close()

            return {
                "status": "success",
                "url": url,
                "screenshot": screenshot_path if take_screenshot else None,
                "html": html_path,
                "json": json_path,
                "data": parsed_data,
                "timestamp": timestamp,
            }

        except Exception as e:
            print(f"[ERROR] Failed to scrape: {e}")
            await context.close()
            await browser.close()
            return {
                "status": "error",
                "url": url,
                "error": str(e),
            }


def run():
    result = asyncio.run(
        scrape_equity_quote(
            url=URL,
            output_dir=OUTPUT_DIR,
            headless=HEADLESS,
            take_screenshot=TAKE_SCREENSHOT,
        )
    )
    if result.get("status") == "success":
        print("\n" + "="*60)
        print("[FINAL] ✓ Scrape completed successfully")
        print("="*60)
        print(f"  URL:        {result['url']}")
        print(f"  Screenshot: {result.get('screenshot')}")
        print(f"  HTML:       {result['html']}")
        print(f"  JSON:       {result['json']}")
        print("\n[FINAL] Parsed JSON:")
        print(json.dumps(result['data'], indent=2, ensure_ascii=False))
    else:
        print("[FINAL] ✗ Scrape failed")
        print(f"  Error: {result.get('error')}")


if __name__ == "__main__":
    run()
