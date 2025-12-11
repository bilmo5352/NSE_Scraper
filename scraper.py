import os
import shutil
import time
from typing import List, Dict

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


NSE_BASE_URL = "https://www.nseindia.com"
EVENT_CAL_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-event-calendar"
BOARD_MEETINGS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-board-meetings"
CORP_ACTIONS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-actions"
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