import os
import shutil
import time
import re
import asyncio
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


NSE_BASE_URL = "https://www.nseindia.com"
EVENT_CAL_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-event-calendar"
BOARD_MEETINGS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-board-meetings"
CORP_ACTIONS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-actions"
ANNOUNCEMENTS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-announcements"
CORP_FILING_API = NSE_BASE_URL + "/api/corporate-filing"
CORP_ACTIONS_API = NSE_BASE_URL + "/api/corporate-actions"
USE_SELENIUM_FALLBACK = os.environ.get("USE_SELENIUM_FALLBACK", "true").lower() == "true"

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "pragma": "no-cache",
}


def _build_driver(headless: bool = True) -> webdriver.Chrome:
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )

    # Explicitly set Chromium binary if provided (Render needs this)
    chrome_bin = os.environ.get("CHROME_BIN")
    if not chrome_bin:
        for candidate in (
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
        ):
            if os.path.exists(candidate):
                chrome_bin = candidate
                break
        if not chrome_bin:
            chrome_bin = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if chrome_bin:
        chrome_options.binary_location = chrome_bin

    # Prefer preinstalled chromedriver if available
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    if chromedriver_path:
        service = Service(chromedriver_path)
    else:
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(30)
    return driver


def _init_nse_session() -> requests.Session:
    """
    Prepare a requests session with headers and cookies primed by hitting the base URL.
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update(
        {
            "referer": NSE_BASE_URL,
            "accept": "application/json,text/html;q=0.9",
            "accept-encoding": "gzip, deflate, br",
        }
    )
    # Prime cookies
    resp = session.get(NSE_BASE_URL, timeout=5)
    resp.raise_for_status()
    return session


def _pick(item: Dict, keys, default="") -> str:
    for key in keys:
        val = item.get(key)
        if val is not None and val != "":
            return str(val).strip()
    return default


def _fetch_corporate_actions_api(symbol: str) -> List[Dict]:
    session = _init_nse_session()
    resp = session.get(
        CORP_ACTIONS_API,
        params={"index": "equities", "symbol": symbol},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data") or payload.get("rows") or payload or []
    rows: List[Dict] = []
    for item in items:
        rows.append(
            {
                "symbol": _pick(item, ["symbol", "SYMBOL"], symbol),
                "company": _pick(item, ["company", "comp", "companyName"], ""),
                "series": _pick(item, ["series"], ""),
                "purpose": _pick(item, ["subject", "purpose"], ""),
                "face_value": _pick(item, ["faceVal", "face_value"], ""),
                "ex_date": _pick(item, ["exDate", "ex_date"], ""),
                "record_date": _pick(item, ["recDate", "recordDate", "rec_date"], ""),
                "book_closure_start": _pick(item, ["bcStartDate", "bc_start_date"], ""),
                "book_closure_end": _pick(item, ["bcEndDate", "bc_end_date"], ""),
            }
        )
    return rows


def _fetch_board_meetings_api(symbol: str) -> List[Dict]:
    session = _init_nse_session()
    resp = session.get(
        CORP_FILING_API,
        params={"index": "equities", "symbol": symbol, "type": "Board Meeting"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data") or payload.get("rows") or payload or []
    rows: List[Dict] = []
    for item in items:
        rows.append(
            {
                "symbol": _pick(item, ["symbol", "SYMBOL"], symbol),
                "company": _pick(item, ["sm_name", "company", "companyName"], ""),
                "purpose": _pick(item, ["bm_purpose", "purpose", "subject"], ""),
                "details_link": _pick(item, ["detailsUrl", "details_link", "bm_details"], ""),
                "meeting_date": _pick(item, ["bm_date", "meetingDate", "meeting_date"], ""),
                "attachment_link": _pick(
                    item, ["attachment", "attachmentUrl", "pdfUrl", "xmlUrl"], ""
                ),
                "broadcast_datetime": _pick(
                    item, ["bm_timestamp", "broadcastDateTime", "broadcast_time"], ""
                ),
            }
        )
    return rows


def _fetch_event_calendar_api(symbol: str) -> List[Dict]:
    session = _init_nse_session()
    resp = session.get(
        CORP_FILING_API,
        params={"index": "equities", "symbol": symbol, "type": "Event Calendar"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data") or payload.get("rows") or payload or []
    rows: List[Dict] = []
    for item in items:
        rows.append(
            {
                "symbol": _pick(item, ["symbol", "SYMBOL"], symbol),
                "company": _pick(item, ["company", "companyName", "sm_name"], ""),
                "purpose": _pick(item, ["purpose", "subject", "event"], ""),
                "details": _pick(
                    item,
                    ["details", "description", "bmdesc", "eventDescription"],
                    "",
                ),
                "date": _pick(item, ["date", "eventDate", "bm_date"], ""),
            }
        )
    return rows


def _parse_event_calendar_table(html: str) -> List[Dict]:
    """
    Parse the table with id CFeventCalendarTable from HTML and
    return list of dicts: symbol, company, purpose, details, date.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="CFeventCalendarTable")
    if not table:
        return []

    rows = []
    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        # 0: symbol
        symbol_cell = tds[0]
        symbol_link = symbol_cell.find("a")
        symbol = (symbol_link.get_text(strip=True) if symbol_link else symbol_cell.get_text(strip=True))

        # 1: company
        company = tds[1].get_text(strip=True)

        # 2: purpose
        purpose = tds[2].get_text(strip=True)

        # 3: details
        details_cell = tds[3]
        # full text is usually in data-ws-symbol-col="SYMBOL-bmdesc" or span.content
        full_desc_attr = details_cell.get("data-ws-symbol-col-prev") or details_cell.get("data-ws-symbol-col")
        if full_desc_attr:
            details = full_desc_attr.strip()
        else:
            content_span = details_cell.find("span", class_="content")
            if content_span:
                details = content_span.get_text(strip=True)
            else:
                details = details_cell.get_text(strip=True)

        # 4: date (may be in 5th td)
        date_str = ""
        if len(tds) >= 5:
            date_str = tds[4].get_text(strip=True)

        rows.append(
            {
                "symbol": symbol,
                "company": company,
                "purpose": purpose,
                "details": details,
                "date": date_str,
            }
        )
    return rows


def _parse_board_meetings_table(html: str) -> List[Dict]:
    """
    Parse the board meetings equity table and return a list of dicts.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="CFboardmeetingEquityTable")
    if not table:
        return []

    rows: List[Dict] = []
    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue

        # 0: symbol
        symbol_cell = tds[0]
        symbol_link = symbol_cell.find("a")
        symbol = (symbol_link.get_text(strip=True) if symbol_link else symbol_cell.get_text(strip=True))

        # 1: company
        company = tds[1].get_text(strip=True)

        # 2: purpose
        purpose = tds[2].get_text(strip=True)

        # 3: details link (optional)
        details_cell = tds[3]
        details_anchor = details_cell.find("a")
        details_link = details_anchor["href"] if details_anchor and details_anchor.has_attr("href") else ""

        # 4: meeting date
        meeting_date = tds[4].get_text(strip=True)

        # 5: attachment link (optional)
        attachment_cell = tds[5]
        attachment_anchor = attachment_cell.find("a")
        attachment_link = attachment_anchor["href"] if attachment_anchor and attachment_anchor.has_attr("href") else ""

        # 6: broadcast date/time
        broadcast_datetime = tds[6].get_text(strip=True)

        rows.append(
            {
                "symbol": symbol,
                "company": company,
                "purpose": purpose,
                "details_link": details_link,
                "meeting_date": meeting_date,
                "attachment_link": attachment_link,
                "broadcast_datetime": broadcast_datetime,
            }
        )
    return rows


def _parse_corporate_actions_table(html: str) -> List[Dict]:
    """
    Parse the corporate actions equity table and return a list of dicts.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="CFcorpactionsEquityTable")
    if not table:
        return []

    rows: List[Dict] = []
    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 9:
            continue

        symbol_cell = tds[0]
        symbol_link = symbol_cell.find("a")
        symbol = (symbol_link.get_text(strip=True) if symbol_link else symbol_cell.get_text(strip=True))

        company = tds[1].get_text(strip=True)
        series = tds[2].get_text(strip=True)
        purpose = tds[3].get_text(strip=True)
        face_value = tds[4].get_text(strip=True)
        ex_date = tds[5].get_text(strip=True)
        record_date = tds[6].get_text(strip=True)
        bc_start_date = tds[7].get_text(strip=True)
        bc_end_date = tds[8].get_text(strip=True)

        rows.append(
            {
                "symbol": symbol,
                "company": company,
                "series": series,
                "purpose": purpose,
                "face_value": face_value,
                "ex_date": ex_date,
                "record_date": record_date,
                "book_closure_start": bc_start_date,
                "book_closure_end": bc_end_date,
            }
        )

    return rows


def _parse_announcements_table(html: str) -> List[Dict]:
    """
    Parse the announcements equity table (id="CFanncEquityTable") and return a list of dicts.
    Columns: SYMBOL, COMPANY NAME, SUBJECT, DETAILS, ATTACHMENT, XBRL, BROADCAST DATE/TIME
    """
    soup = BeautifulSoup(html, "lxml")
    
    # Try multiple table ID variations
    table = soup.find("table", id="CFanncEquityTable")
    if not table:
        # Try alternative IDs
        table = soup.find("table", id="CFanncEquity")
        if not table:
            table = soup.find("table", class_=lambda x: x and "annc" in x.lower())
    
    if not table:
        return []

    rows: List[Dict] = []
    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        # Skip rows with insufficient columns (headers, empty rows, etc.)
        if len(tds) < 7:
            continue

        # 0: symbol
        symbol_cell = tds[0]
        symbol_link = symbol_cell.find("a")
        symbol = (symbol_link.get_text(strip=True) if symbol_link else symbol_cell.get_text(strip=True))

        # 1: company name
        company = tds[1].get_text(strip=True)

        # 2: subject
        subject = tds[2].get_text(strip=True)

        # 3: details
        details_cell = tds[3]
        # Try to get full text from data attributes or content
        full_desc_attr = details_cell.get("data-ws-symbol-col-prev") or details_cell.get("data-ws-symbol-col")
        if full_desc_attr:
            details = full_desc_attr.strip()
        else:
            content_span = details_cell.find("span", class_="content")
            if content_span:
                details = content_span.get_text(strip=True)
            else:
                details = details_cell.get_text(strip=True)

        # 4: attachment link (optional)
        attachment_cell = tds[4]
        attachment_anchor = attachment_cell.find("a")
        attachment_link = attachment_anchor["href"] if attachment_anchor and attachment_anchor.has_attr("href") else ""

        # 5: XBRL link (optional)
        xbrl_cell = tds[5]
        xbrl_anchor = xbrl_cell.find("a")
        xbrl_link = xbrl_anchor["href"] if xbrl_anchor and xbrl_anchor.has_attr("href") else ""

        # 6: broadcast date/time
        broadcast_datetime = tds[6].get_text(strip=True)

        rows.append(
            {
                "symbol": symbol,
                "company": company,
                "subject": subject,
                "details": details,
                "attachment_link": attachment_link,
                "xbrl_link": xbrl_link,
                "broadcast_datetime": broadcast_datetime,
            }
        )
    
    return rows


def get_event_calendar_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Fetch event calendar via NSE JSON API; fallback to Selenium if needed.
    """
    symbol = symbol.upper().strip()

    # Fast path: API
    try:
        rows = _fetch_event_calendar_api(symbol)
        if rows:
            return rows
    except Exception:
        pass

    if not USE_SELENIUM_FALLBACK:
        raise RuntimeError("API fetch failed and Selenium fallback disabled")

    driver = _build_driver(headless=headless)
    try:
        driver.get(NSE_BASE_URL)
        url = f"{EVENT_CAL_URL}?symbol={symbol}"
        driver.get(url)

        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.ID, "CFeventCalendarTable")))

        html = driver.page_source
        return _parse_event_calendar_table(html)
    finally:
        driver.quit()


def get_board_meetings_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Open the NSE board meetings for the given symbol using API, fallback to Selenium.
    """
    symbol = symbol.upper().strip()

    try:
        rows = _fetch_board_meetings_api(symbol)
        if rows:
            return rows
    except Exception:
        pass

    if not USE_SELENIUM_FALLBACK:
        raise RuntimeError("API fetch failed and Selenium fallback disabled")

    driver = _build_driver(headless=headless)
    try:
        driver.get(NSE_BASE_URL)

        url = f"{BOARD_MEETINGS_URL}?symbol={symbol}"
        driver.get(url)

        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.ID, "CFboardmeetingEquityTable")))

        html = driver.page_source
        return _parse_board_meetings_table(html)
    finally:
        driver.quit()


def get_corporate_actions_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Open the NSE corporate actions for the given symbol via API, fallback to Selenium.
    """
    symbol = symbol.upper().strip()

    try:
        rows = _fetch_corporate_actions_api(symbol)
        if rows:
            return rows
    except Exception:
        pass

    if not USE_SELENIUM_FALLBACK:
        raise RuntimeError("API fetch failed and Selenium fallback disabled")

    driver = _build_driver(headless=headless)
    try:
        driver.get(NSE_BASE_URL)

        url = f"{CORP_ACTIONS_URL}?symbol={symbol}"
        driver.get(url)

        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.ID, "CFcorpactionsEquityTable")))

        html = driver.page_source
        return _parse_corporate_actions_table(html)
    finally:
        driver.quit()


def _fetch_announcements_api(symbol: str) -> List[Dict]:
    """
    Try to fetch announcements via API endpoint (if available).
    """
    session = _init_nse_session()
    try:
        resp = session.get(
            CORP_FILING_API,
            params={"index": "equities", "symbol": symbol, "type": "Announcement"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data") or payload.get("rows") or payload or []
        rows: List[Dict] = []
        for item in items:
            rows.append(
                {
                    "symbol": _pick(item, ["symbol", "SYMBOL"], symbol),
                    "company": _pick(item, ["sm_name", "company", "companyName"], ""),
                    "subject": _pick(item, ["desc", "subject", "purpose"], ""),
                    "details": _pick(item, ["details", "description", "attchmntText"], ""),
                    "attachment_link": _pick(item, ["attachment", "attachmentUrl", "attchmntFile"], ""),
                    "xbrl_link": _pick(item, ["xbrl", "xbrlUrl", "seq_id"], ""),
                    "broadcast_datetime": _pick(item, ["an_dt", "broadcastDateTime", "broadcast_datetime"], ""),
                }
            )
        return rows
    except Exception:
        # API endpoint might not exist or might use different params
        return []


def get_announcements_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Fetch announcements for the given symbol via API (if available), fallback to Selenium scraping.
    """
    symbol = symbol.upper().strip()

    # Try API first - but always fall back to Selenium if empty or fails
    try:
        rows = _fetch_announcements_api(symbol)
        # Only use API results if we got actual data
        if rows and len(rows) > 0:
            return rows
    except Exception:
        # API failed, continue to Selenium
        pass

    if not USE_SELENIUM_FALLBACK:
        raise RuntimeError("API fetch failed and Selenium fallback disabled")

    driver = _build_driver(headless=headless)
    try:
        print(f"[DEBUG] Loading NSE base URL...")
        driver.get(NSE_BASE_URL)
        time.sleep(2)  # Wait for cookies/session

        url = f"{ANNOUNCEMENTS_URL}?symbol={symbol}"
        print(f"[DEBUG] Loading announcements URL: {url}")
        driver.get(url)
        
        # Wait longer for table to load - try multiple strategies
        wait = WebDriverWait(driver, 25)
        table_found = False
        
        # Strategy 1: Wait for table by ID
        try:
            wait.until(EC.presence_of_element_located((By.ID, "CFanncEquityTable")))
            # Also wait for it to be visible and have rows
            wait.until(EC.visibility_of_element_located((By.ID, "CFanncEquityTable")))
            time.sleep(2)  # Additional wait for dynamic content
            table_found = True
            print(f"[DEBUG] Table CFanncEquityTable found and visible")
        except Exception as e:
            print(f"[DEBUG] Table not found with ID CFanncEquityTable: {str(e)}")
        
        # Strategy 2: Try alternative selectors
        if not table_found:
            try:
                # Wait for any table with 'annc' in ID
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table[id*='annc']")))
                time.sleep(2)
                table_found = True
                print(f"[DEBUG] Found table with alternative selector")
            except:
                pass
        
        # Strategy 3: Wait for tbody with rows
        if not table_found:
            try:
                wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "table#CFanncEquityTable tbody tr")) > 0)
                time.sleep(2)
                table_found = True
                print(f"[DEBUG] Found table rows")
            except:
                pass
        
        # Final wait for any dynamic loading
        if table_found:
            time.sleep(3)
        else:
            time.sleep(5)

        html = driver.page_source
        rows = _parse_announcements_table(html)
        return rows
    finally:
        driver.quit()


# ============================================================================
# Equity Quote Scraping Functions (using Playwright)
# ============================================================================

def _extract_value_after_label(text: str, label: str) -> Optional[str]:
    """Extract numeric value that appears immediately after a label in text."""
    pattern = label + r'([0-9,.\-]+)'
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def _parse_nse_quote_html(html_content: str) -> dict:
    """Parse the rendered NSE equity quote HTML and extract all data."""
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
                data['prev_close'] = _extract_value_after_label(text, 'Prev. Close')
            elif text.startswith('Open'):
                data['open'] = _extract_value_after_label(text, 'Open')
            elif text.startswith('High'):
                data['high'] = _extract_value_after_label(text, 'High')
            elif text.startswith('Low'):
                data['low'] = _extract_value_after_label(text, 'Low')
            elif text.startswith('VWAP'):
                data['vwap'] = _extract_value_after_label(text, 'VWAP')
            elif text.startswith('Close'):
                close_val = _extract_value_after_label(text, 'Close')
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
        
        # Look for buy/sell quantities in the main text
        buy_qty_match = re.search(r'Total Buy Quantity([0-9,.]+)', body_text)
        if buy_qty_match:
            data['total_buy_qty'] = buy_qty_match.group(1)
        
        sell_qty_match = re.search(r'Total Sell Quantity([0-9,.]+)', body_text)
        if sell_qty_match:
            data['total_sell_qty'] = sell_qty_match.group(1)
        
        # Extract returns data (YTD, 1M, 3M, 6M, 1Y, 3Y, 5Y)
        data['returns'] = {}
        percent_texts = soup.find_all(string=lambda t: t and '%' in t and len(t.strip()) < 50)
        
        for text in percent_texts:
            text_stripped = text.strip()
            parent = text.find_parent()
            if not parent or parent.name in ['style', 'script']:
                continue
            
            parent_text = parent.get_text(strip=True)
            for period in ['YTD', '1M', '3M', '6M', '1Y', '3Y', '5Y', '10Y', '15Y', '20Y', '25Y', '30Y']:
                if period in parent_text:
                    period_match = re.search(period + r'\s*([0-9.]+%)', parent_text)
                    if period_match:
                        data['returns'][period] = period_match.group(1)
        
    except Exception as e:
        data['parse_error'] = str(e)
    
    return data


async def _scrape_equity_quote_async(symbol: str, headless: bool = True) -> dict:
    """Async function to scrape equity quote page using Playwright - EXACT copy of equity_quote_run.py."""
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed. Install it with: pip install playwright && playwright install")
    
    symbol = symbol.upper().strip()
    url = f"{NSE_BASE_URL}/get-quote/equity/{symbol}"
    
    async def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
        import random
        await asyncio.sleep(random.uniform(min_sec, max_sec))
    
    async with async_playwright() as p:
        # EXACTLY match equity_quote_run.py - only this arg
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        
        # EXACTLY match equity_quote_run.py - no extra settings
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        
        page = await context.new_page()
        
        # EXACTLY match equity_quote_run.py
        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """
        )
        
        # EXACTLY match equity_quote_run.py
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
            # EXACTLY match equity_quote_run.py - direct goto, no retries
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            await human_delay(2, 4)
            
            # EXACTLY match equity_quote_run.py
            import random
            await page.mouse.move(random.randint(200, 600), random.randint(200, 600))
            await human_delay(0.5, 1.0)
            
            # Scroll a bit
            await page.mouse.wheel(0, random.randint(200, 600))
            await human_delay(0.5, 1.0)
            
            # Extra wait for dynamic content to fully load
            await human_delay(3, 5)
            
            html_content = await page.content()
            parsed_data = _parse_nse_quote_html(html_content)
            
            await context.close()
            await browser.close()
            
            return parsed_data
            
        except Exception as e:
            await context.close()
            await browser.close()
            raise


def get_equity_quote_for_symbol(symbol: str, headless: bool = True) -> dict:
    """
    Fetch equity quote data for the given symbol.
    Synchronous wrapper around async Playwright scraper.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "Playwright is not installed. Install it with: pip install playwright && playwright install"}
    
    try:
        # Try asyncio.run() first (works in standalone scripts)
        # If that fails (event loop already running), use get_event_loop()
        try:
            result = asyncio.run(_scrape_equity_quote_async(symbol, headless))
            return result
        except RuntimeError:
            # Event loop already running (Flask/Gunicorn case)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Need to run in executor or use nest_asyncio
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _scrape_equity_quote_async(symbol, headless))
                    result = future.result()
                    return result
            else:
                result = loop.run_until_complete(_scrape_equity_quote_async(symbol, headless))
                return result
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# Financial Results Scraping Functions (using Playwright)
# ============================================================================

def _parse_financial_results(html_content: str) -> dict:
    """Parse the financial results comparison HTML and extract structured data."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    company_name = "N/A"
    company_symbol = "N/A"
    
    line1_elem = soup.find('p', class_='line1')
    if line1_elem:
        spans = line1_elem.find_all('span')
        if len(spans) >= 2:
            company_name = spans[0].get_text(strip=True)
            company_symbol = spans[1].get_text(strip=True)
    
    results_compare_div = soup.find('div', id='resultsCompare')
    if not results_compare_div:
        return {
            "status": "error",
            "message": "Financial results container (div#resultsCompare) not found",
            "company": {"name": company_name, "symbol": company_symbol}
        }
    
    table = results_compare_div.find('table', class_='common_table')
    if not table:
        return {
            "status": "error",
            "message": "Financial results table not found",
            "company": {"name": company_name, "symbol": company_symbol}
        }
    
    thead = table.find('thead')
    if not thead:
        return {"status": "error", "message": "Table header not found"}
    
    header_rows = thead.find_all('tr')
    quarters = []
    audit_status = []
    
    if len(header_rows) >= 2:
        quarter_cells = header_rows[0].find_all('th')[1:]
        quarters = [cell.get_text(strip=True) for cell in quarter_cells]
        status_cells = header_rows[1].find_all('th')[1:]
        audit_status = [cell.get_text(strip=True) for cell in status_cells]
    
    tbody = table.find('tbody')
    if not tbody:
        return {
            "status": "error",
            "message": "Table body (tbody) not found",
            "company": {"name": company_name, "symbol": company_symbol}
        }
    
    rows = tbody.find_all('tr')
    if not rows or len(rows) < 3:
        return {
            "status": "error",
            "message": f"Insufficient data rows found (found {len(rows) if rows else 0} rows)",
            "company": {"name": company_name, "symbol": company_symbol}
        }
    
    sections = []
    current_section = None
    
    for row in rows:
        section_header = row.find('td', class_='sectionCol')
        if section_header:
            if current_section:
                sections.append(current_section)
            current_section = {
                "section_name": section_header.get_text(strip=True),
                "line_items": []
            }
            continue
        
        cells = row.find_all('td')
        if len(cells) > 1 and current_section:
            line_item_name = cells[0].get_text(strip=True)
            values = []
            for cell in cells[1:]:
                value_text = cell.get_text(strip=True)
                if value_text in ['-', '']:
                    value_text = None
                values.append(value_text)
            
            is_total = 'text-bold' in str(row) or 'highlightRow' in str(row)
            current_section["line_items"].append({
                "name": line_item_name,
                "values": values,
                "is_total": is_total
            })
    
    if current_section:
        sections.append(current_section)
    
    return {
        "status": "success",
        "company": {"name": company_name, "symbol": company_symbol},
        "quarters": quarters,
        "audit_status": audit_status,
        "currency": "₹ Lakhs",
        "sections": sections,
        "metadata": {
            "total_quarters": len(quarters),
            "total_sections": len(sections),
            "note": "For comparison purposes the last 5 quarters of Standalone Results are considered. All Values are in ₹ Lakhs."
        }
    }


async def _scrape_financial_results_async(symbol: str, headless: bool = True) -> dict:
    """Async function to scrape financial results using Playwright with form interaction."""
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed. Install it with: pip install playwright && playwright install")
    
    symbol = symbol.upper().strip()
    url = f"{NSE_BASE_URL}/companies-listing/corporate-filings-financial-results-comparision"
    
    async def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
        import random
        await asyncio.sleep(random.uniform(min_sec, max_sec))
    
    async with async_playwright() as p:
        # EXACTLY match finiancialReport.py - only this arg, headless parameter respected
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        
        # EXACTLY match finiancialReport.py - no extra settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        
        page = await context.new_page()
        
        # EXACTLY match finiancialReport.py
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
        """)
        
        # EXACTLY match finiancialReport.py
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
        })
        
        try:
            # EXACTLY match finiancialReport.py - direct goto, no retries
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            await human_delay(2, 4)
            
            # EXACTLY match finiancialReport.py - mouse movement first
            import random
            await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
            await human_delay(0.5, 1)
            
            # Find input field - EXACTLY match finiancialReport.py
            input_selectors = [
                'input[placeholder*="Company name or symbol"]',
                'input[placeholder*="Company"]',
                'input[class*="search"]',
                'input[id*="company"]',
                'input[type="text"]',
                'input',
            ]
            
            input_field = None
            for selector in input_selectors:
                try:
                    elements = page.locator(selector)
                    count = await elements.count()
                    if count > 0:
                        input_field = elements.first
                        if await input_field.is_visible():
                            break
                except:
                    continue
            
            if not input_field:
                await context.close()
                await browser.close()
                return {"status": "error", "message": "Could not find search input field"}
            
            # EXACTLY match finiancialReport.py
            await input_field.scroll_into_view_if_needed()
            await human_delay(1, 2)
            
            # Move mouse to input field - EXACTLY match finiancialReport.py
            box = await input_field.bounding_box()
            if box:
                await page.mouse.move(int(box['x'] + box['width'] / 2), int(box['y'] + box['height'] / 2))
            await human_delay(0.5, 1.5)
            
            await input_field.click()
            await human_delay(1, 2)
            
            # EXACTLY match finiancialReport.py
            await input_field.press("Control+A")
            await human_delay(0.2, 0.4)
            await input_field.press("Backspace")
            await human_delay(0.3, 0.7)
            
            # Type with realistic delays - EXACTLY match finiancialReport.py
            for char in symbol:
                await input_field.type(char, delay=random.randint(50, 150))
                await human_delay(0.05, 0.2)
            
            await human_delay(3, 5)
            
            # Find and click suggestion - EXACTLY match finiancialReport.py
            suggestion_selectors = [
                '.tt-suggestion',
                '.autocompleteList',
                'div.autocompleteList',
                '.ng-option',
                'a.ng-option',
                '[role="option"]',
                '.ng-option-label',
                'div.ng-option',
            ]
            suggestion_found = False
            
            for selector in suggestion_selectors:
                try:
                    suggestions = page.locator(selector)
                    count = await suggestions.count()
                    if count > 0:
                        for i in range(count):
                            suggestion = suggestions.nth(i)
                            try:
                                suggestion_text = await suggestion.inner_text()
                                suggestion_text = suggestion_text.strip()
                                
                                search_upper = symbol.upper()
                                suggestion_upper = suggestion_text.upper()
                                
                                if search_upper in suggestion_upper:
                                    is_visible = await suggestion.is_visible(timeout=2000)
                                    if is_visible:
                                        await suggestion.scroll_into_view_if_needed()
                                        await human_delay(0.3, 0.8)
                                        await suggestion.click(force=True, timeout=10000)
                                        await human_delay(1, 2)
                                        suggestion_found = True
                                        break
                            except:
                                continue
                        if suggestion_found:
                            break
                except:
                    continue
            
            if not suggestion_found:
                # Try first suggestion fallback - EXACTLY match finiancialReport.py
                for fallback_selector in ['.tt-suggestion', '.autocompleteList', '.ng-option']:
                    try:
                        first_suggestion = page.locator(fallback_selector).first
                        if await first_suggestion.is_visible(timeout=2000):
                            await first_suggestion.click(force=True, timeout=10000)
                            await human_delay(1, 2)
                            suggestion_found = True
                            break
                    except:
                        continue
            
            if not suggestion_found:
                await input_field.press("ArrowDown")
                await human_delay(0.3, 0.8)
                await input_field.press("Enter")
            
            await human_delay(2, 4)
            
            # Find and click search button - EXACTLY match finiancialReport.py
            button_selectors = [
                'button[type="submit"]',
                'button[class*="search"]',
                'button[id*="search"]',
                'button:has-text("Search")',
                'input[type="submit"]',
                'button',
            ]
            button_found = False
            
            for selector in button_selectors:
                try:
                    buttons = page.locator(selector)
                    count = await buttons.count()
                    if count > 0:
                        button = buttons.first
                        if await button.is_visible():
                            # Move mouse to button - EXACTLY match finiancialReport.py
                            box = await button.bounding_box()
                            if box:
                                await page.mouse.move(int(box['x'] + box['width'] / 2), int(box['y'] + box['height'] / 2))
                            await human_delay(0.5, 1.5)
                            await button.click()
                            button_found = True
                            break
                except:
                    continue
            
            if not button_found:
                await input_field.press("Enter")
            
            await human_delay(8, 12)
            
            # Wait for table - EXACTLY match finiancialReport.py
            try:
                table_selector = 'table.common_table'
                table_locator = page.locator(table_selector)
                await table_locator.wait_for(state='visible', timeout=15000)
            except Exception as e:
                await human_delay(5, 7)
            
            html_content = await page.content()
            parsed_data = _parse_financial_results(html_content)
            
            await context.close()
            await browser.close()
            
            return parsed_data
            
        except Exception as e:
            await context.close()
            await browser.close()
            raise


def get_financial_results_for_symbol(symbol: str, headless: bool = True) -> dict:
    """
    Fetch financial results comparison data for the given symbol.
    Synchronous wrapper around async Playwright scraper.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"status": "error", "message": "Playwright is not installed. Install it with: pip install playwright && playwright install"}
    
    try:
        # Try asyncio.run() first (works in standalone scripts)
        # If that fails (event loop already running), use get_event_loop()
        try:
            result = asyncio.run(_scrape_financial_results_async(symbol, headless))
            return result
        except RuntimeError:
            # Event loop already running (Flask/Gunicorn case)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Need to run in executor or use nest_asyncio
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _scrape_financial_results_async(symbol, headless))
                    result = future.result()
                    return result
            else:
                result = loop.run_until_complete(_scrape_financial_results_async(symbol, headless))
                return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
