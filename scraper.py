import os
import shutil
import time
import logging
from typing import List, Dict

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# Set up logging
logger = logging.getLogger(__name__)


NSE_BASE_URL = "https://www.nseindia.com"
EVENT_CAL_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-event-calendar"
BOARD_MEETINGS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-board-meetings"
CORP_ACTIONS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-actions"
ANNOUNCEMENTS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-announcements"
CORP_FILING_API = NSE_BASE_URL + "/api/corporate-filing"
CORP_ACTIONS_API = NSE_BASE_URL + "/api/corporate-actions"
USE_SELENIUM_FALLBACK = os.environ.get("USE_SELENIUM_FALLBACK", "true").lower() == "true"
# Disable Selenium for announcements in production if API returns empty
DISABLE_ANNOUNCEMENTS_SELENIUM = os.environ.get("DISABLE_ANNOUNCEMENTS_SELENIUM", "false").lower() == "true"

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
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--window-size=1280,720")
    chrome_options.add_argument("--memory-pressure-off")
    chrome_options.add_argument("--max_old_space_size=512")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--disable-impl-side-painting")
    chrome_options.add_argument("--disable-accelerated-2d-canvas")
    chrome_options.add_argument("--disable-accelerated-video-decode")
    chrome_options.add_argument("--js-flags=--max-old-space-size=512")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--ignore-ssl-errors")
    chrome_options.add_argument("--ignore-certificate-errors-spki-list")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-breakpad")
    chrome_options.add_argument("--disable-client-side-phishing-detection")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-features=TranslateUI")
    chrome_options.add_argument("--disable-hang-monitor")
    chrome_options.add_argument("--disable-ipc-flooding-protection")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-prompt-on-repost")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-translate")
    chrome_options.add_argument("--metrics-recording-only")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--safebrowsing-disable-auto-update")
    chrome_options.add_argument("--enable-automation")
    chrome_options.add_argument("--password-store=basic")
    chrome_options.add_argument("--use-mock-keychain")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )

    # Explicitly set Chromium binary if provided (Render/Railway needs this)
    chrome_bin = os.environ.get("CHROME_BIN")
    if not chrome_bin:
        for candidate in (
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium/chromium",
        ):
            if os.path.exists(candidate):
                chrome_bin = candidate
                break
        if not chrome_bin:
            chrome_bin = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    
    if chrome_bin:
        if not os.path.exists(chrome_bin):
            error_msg = f"Chrome binary not found at {chrome_bin}"
            logger.error(f"_build_driver: {error_msg}")
            raise RuntimeError(error_msg)
        chrome_options.binary_location = chrome_bin
    else:
        # Try to find it anyway
        found = shutil.which("chromium") or shutil.which("chromium-browser")
        if found:
            chrome_bin = found
            chrome_options.binary_location = found

    # Prefer preinstalled chromedriver if available
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    if chromedriver_path:
        if not os.path.exists(chromedriver_path):
            error_msg = f"ChromeDriver not found at {chromedriver_path}"
            logger.error(f"_build_driver: {error_msg}")
            raise RuntimeError(error_msg)
        service = Service(chromedriver_path)
    else:
        # Try to find chromedriver in common locations
        for candidate in ("/usr/bin/chromedriver", "/usr/local/bin/chromedriver"):
            if os.path.exists(candidate):
                chromedriver_path = candidate
                service = Service(chromedriver_path)
                break
        else:
            # Last resort: use ChromeDriverManager
            chromedriver_path = "ChromeDriverManager"
            service = Service(ChromeDriverManager().install())

    # Log Chrome binary and ChromeDriver paths
    logger.info(f"_build_driver: Chrome binary: {chrome_bin}, ChromeDriver: {chromedriver_path}")

    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)
        return driver
    except Exception as e:
        error_msg = f"Failed to start Chrome: {str(e)}"
        if chrome_bin:
            error_msg += f" (Chrome binary: {chrome_bin})"
        if chromedriver_path:
            error_msg += f" (ChromeDriver: {chromedriver_path})"
        logger.error(f"_build_driver: {error_msg}")
        raise RuntimeError(error_msg) from e


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


def _fetch_announcements_api(symbol: str) -> List[Dict]:
    """
    Try to fetch announcements via API. 
    Returns immediately if any type returns data (strict API-first approach).
    """
    session = _init_nse_session()
    # Try different possible type values
    for api_type in ["Announcement", "Corporate Announcement", "Announcements"]:
        try:
            logger.info(f"_fetch_announcements_api: Trying API type '{api_type}' for symbol {symbol}")
            resp = session.get(
                CORP_FILING_API,
                params={"index": "equities", "symbol": symbol, "type": api_type},
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("data") or payload.get("rows") or payload or []
            
            # If we got items, process them and return immediately
            if items and len(items) > 0:
                logger.info(f"_fetch_announcements_api: Found {len(items)} items for type '{api_type}'")
                rows: List[Dict] = []
                for item in items:
                    rows.append(
                        {
                            "symbol": _pick(item, ["symbol", "SYMBOL"], symbol),
                            "company": _pick(item, ["sm_name", "company", "companyName"], ""),
                            "subject": _pick(item, ["desc", "subject", "purpose"], ""),
                            "details": _pick(item, ["attchmntText", "details", "description"], ""),
                            "attachment_link": _pick(item, ["attachment", "attachmentUrl", "pdfUrl"], ""),
                            "attachment_size": _pick(item, ["attachmentSize", "size"], ""),
                            "xbrl_link": _pick(item, ["xbrlUrl", "xbrl_link", "xmlUrl"], ""),
                            "broadcast_datetime": _pick(item, ["an_dt", "broadcastDateTime", "broadcast_time"], ""),
                        }
                    )
                if rows:
                    logger.info(f"_fetch_announcements_api: Returning {len(rows)} rows from API")
                    return rows
        except Exception as e:
            logger.debug(f"_fetch_announcements_api: API type '{api_type}' failed: {str(e)}")
            continue
    
    # No API type worked, return empty
    logger.info(f"_fetch_announcements_api: No API data found for symbol {symbol}")
    return []


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


def _parse_announcements_table(html: str) -> List[Dict]:
    """
    Parse the announcements equity table and return a list of dicts.
    Table ID: CFanncEquityTable
    Columns: SYMBOL, COMPANY NAME, SUBJECT, DETAILS, ATTACHMENT, XBRL, BROADCAST DATE/TIME
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="CFanncEquityTable")
    if not table:
        # Try alternative table IDs or class names
        table = soup.find("table", class_=lambda x: x and "CFannc" in str(x))
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

        try:
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
            # Try to get full text from data attribute first (data-ws-symbol-col-prev has full text)
            # Check if the td element has the attribute
            full_desc_attr = details_cell.attrs.get("data-ws-symbol-col-prev") or details_cell.get("data-ws-symbol-col-prev")
            if full_desc_attr:
                details = str(full_desc_attr).strip()
            else:
                # Try data-ws-symbol-col attribute
                desc_attr = details_cell.attrs.get("data-ws-symbol-col") or details_cell.get("data-ws-symbol-col")
                if desc_attr:
                    details = str(desc_attr).strip()
                else:
                    # Try content span (truncated text)
                    content_span = details_cell.find("span", class_="content")
                    if content_span:
                        details = content_span.get_text(strip=True)
                    else:
                        # Fallback to all text in the cell
                        details = details_cell.get_text(strip=True, separator=" ")

            # 4: attachment (PDF link and size)
            attachment_cell = tds[4]
            attachment_anchor = attachment_cell.find("a")
            attachment_link = ""
            attachment_size = ""
            if attachment_anchor and attachment_anchor.has_attr("href"):
                attachment_link = attachment_anchor["href"]
                # Get size from the <p> tag that follows
                size_p = attachment_cell.find("p", class_="mt-1")
                if size_p:
                    attachment_size = size_p.get_text(strip=True)

            # 5: XBRL link
            xbrl_cell = tds[5]
            xbrl_anchor = xbrl_cell.find("a")
            xbrl_link = ""
            if xbrl_anchor and xbrl_anchor.has_attr("href"):
                xbrl_link = xbrl_anchor["href"]
                # Make it absolute if relative
                if xbrl_link.startswith("/"):
                    xbrl_link = NSE_BASE_URL + xbrl_link

            # 6: broadcast date/time
            broadcast_datetime_cell = tds[6]
            # The date might be in an <a> tag or directly in the cell
            date_link = broadcast_datetime_cell.find("a")
            if date_link:
                # Get text from the link, but remove the hover table HTML
                broadcast_datetime = date_link.get_text(strip=True)
                # Clean up - remove any extra whitespace/newlines
                broadcast_datetime = " ".join(broadcast_datetime.split())
            else:
                broadcast_datetime = broadcast_datetime_cell.get_text(strip=True)

            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "subject": subject,
                    "details": details,
                    "attachment_link": attachment_link,
                    "attachment_size": attachment_size,
                    "xbrl_link": xbrl_link,
                    "broadcast_datetime": broadcast_datetime,
                }
            )
        except Exception as e:
            # Skip rows that fail to parse
            continue

    return rows


def get_announcements_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Fetch announcements for the given symbol. Prefers API, falls back to Selenium only if needed.
    Uses strengthened waits to properly wait for table rows without crashing Chrome.
    
    Strategy:
    - If API returns any rows, skip Selenium entirely
    - Wait for table element, then wait for at least one row
    - Only scroll after rows exist and only if needed (1-2 iterations max)
    - Fail cleanly on timeout instead of continuing with scrolls/sleeps
    - Always ensure driver.quit() runs in finally block
    """
    symbol = symbol.upper().strip()
    logger.info(f"get_announcements_for_symbol: Starting for symbol {symbol}")

    # Try API first - if it returns data, skip Selenium entirely
    api_rows = []
    api_error = None
    try:
        api_rows = _fetch_announcements_api(symbol)
        # Only return API results if we actually got data
        if api_rows and len(api_rows) > 0:
            logger.info(f"get_announcements_for_symbol: Returning {len(api_rows)} rows from API, skipping Selenium")
            return api_rows
    except Exception as e:
        api_error = str(e)
        logger.warning(f"get_announcements_for_symbol: API fetch failed: {api_error}")
        # API failed, continue to Selenium if enabled

    # Note: Selenium is required for announcements as API returns forbidden/empty
    # Continue to Selenium fallback

    # API returned empty or failed, use Selenium (if enabled)
    if not USE_SELENIUM_FALLBACK:
        raise RuntimeError("API fetch failed and Selenium fallback disabled")

    logger.info(f"get_announcements_for_symbol: Starting Selenium for symbol {symbol}")
    driver = None
    try:
        driver = _build_driver(headless=headless)
        
        # First visit base URL to set cookies and establish session
        base_url = NSE_BASE_URL
        logger.info(f"get_announcements_for_symbol: Navigating to base URL: {base_url}")
        driver.set_page_load_timeout(30)
        driver.get(base_url)
        # Wait for page to be ready
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2)  # Give time for cookies and session to be established
        logger.info(f"get_announcements_for_symbol: Base URL loaded, cookies set")

        # Navigate to announcements page
        url = f"{ANNOUNCEMENTS_URL}?symbol={symbol}"
        logger.info(f"get_announcements_for_symbol: Navigating to announcements URL: {url}")
        driver.set_page_load_timeout(45)
        driver.get(url)
        # Wait for page to be ready
        try:
            WebDriverWait(driver, 25).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            logger.warning(f"get_announcements_for_symbol: Page readyState timeout, continuing anyway")
        logger.info(f"get_announcements_for_symbol: Announcements page loaded")
        
        # Strengthened waits: wait for table, then wait for at least one row
        wait = WebDriverWait(driver, 40)  # Longer timeout just for announcements
        try:
            # 1) Wait for table element
            logger.info(f"get_announcements_for_symbol: Waiting for table CFanncEquityTable")
            table = wait.until(
                EC.presence_of_element_located((By.ID, "CFanncEquityTable"))
            )
            logger.info(f"get_announcements_for_symbol: Table found")
            
            # 2) Wait for at least one row in tbody
            logger.info(f"get_announcements_for_symbol: Waiting for table rows")
            wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "#CFanncEquityTable tbody tr")
                )
            )
            logger.info(f"get_announcements_for_symbol: Table rows found")
            
            # Get HTML and parse immediately after rows appear
            html = driver.page_source
            rows = _parse_announcements_table(html)
            logger.info(f"get_announcements_for_symbol: Parsed {len(rows)} rows from table")
            
            # Only scroll AFTER rows exist and only if needed to trigger lazy loading
            # Limit to 1-2 iterations with condition check
            if rows and len(rows) > 0:
                initial_count = len(rows)
                # Try scrolling once to trigger lazy loading if needed
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)
                    html = driver.page_source
                    rows_after_scroll = _parse_announcements_table(html)
                    # Only use new rows if count increased
                    if len(rows_after_scroll) > initial_count:
                        rows = rows_after_scroll
                        logger.info(f"get_announcements_for_symbol: After scroll, found {len(rows)} rows (was {initial_count})")
                    else:
                        logger.info(f"get_announcements_for_symbol: Scroll did not increase row count, keeping original {initial_count} rows")
                except WebDriverException as e:
                    logger.warning(f"get_announcements_for_symbol: Error during scroll: {str(e)}, using existing rows")
            
            return rows
            
        except TimeoutException as e:
            # Fail cleanly on timeout - return empty list or raise controlled error
            error_msg = f"Timeout waiting for announcements table/rows: {str(e)}"
            logger.error(f"get_announcements_for_symbol: {error_msg}")
            # Try to get page source anyway in case table exists but wait failed
            try:
                html = driver.page_source
                rows = _parse_announcements_table(html)
                if rows and len(rows) > 0:
                    logger.warning(f"get_announcements_for_symbol: Found {len(rows)} rows despite timeout, returning them")
                    return rows
            except Exception:
                pass
            # If no rows found, raise timeout exception
            raise TimeoutException(error_msg) from e
            
    except (WebDriverException, TimeoutException) as e:
        # Catch WebDriverException to prevent multiple Selenium calls after fatal browser error
        logger.error(f"get_announcements_for_symbol: Selenium error: {str(e)}")
        raise
    except Exception as e:
        # Catch any other exceptions
        logger.error(f"get_announcements_for_symbol: Unexpected error: {str(e)}")
        raise
    finally:
        # Always ensure driver is closed, even on timeout or parsing errors
        if driver:
            try:
                driver.quit()
                logger.info(f"get_announcements_for_symbol: Driver closed")
            except Exception as e:
                logger.warning(f"get_announcements_for_symbol: Error closing driver: {str(e)}")