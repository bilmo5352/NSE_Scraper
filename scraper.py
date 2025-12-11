import os
import shutil
import time
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.utils import ChromeType
from bs4 import BeautifulSoup


NSE_BASE_URL = "https://www.nseindia.com"
EVENT_CAL_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-event-calendar"
BOARD_MEETINGS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-board-meetings"
CORP_ACTIONS_URL = NSE_BASE_URL + "/companies-listing/corporate-filings-actions"


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
        # fallbacks common across distros
        for candidate in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
            if os.path.exists(candidate):
                chrome_bin = candidate
                break
        if not chrome_bin:
            # last resort: search PATH
            chrome_bin = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if chrome_bin:
        chrome_options.binary_location = chrome_bin

    service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(30)
    return driver


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
    Open the NSE event calendar for the given symbol and return table JSON.
    """
    symbol = symbol.upper().strip()
    driver = _build_driver(headless=headless)

    try:
        # 1. Hit base to set cookies (NSE sometimes rejects direct deep links)
        driver.get(NSE_BASE_URL)
        time.sleep(2)

        # 2. Now open event calendar with query param symbol
        url = f"{EVENT_CAL_URL}?symbol={symbol}"
        driver.get(url)

        wait = WebDriverWait(driver, 25)

        # The Equity tab's table gets populated via JS into div#CFeventCalendar
        # Ultimately, the table we care about has id="CFeventCalendarTable"
        wait.until(
            EC.presence_of_element_located((By.ID, "CFeventCalendarTable"))
        )

        # Optional: small extra wait to let all rows render
        time.sleep(1.5)

        html = driver.page_source
        return _parse_event_calendar_table(html)
    finally:
        driver.quit()


def get_board_meetings_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Open the NSE board meetings page for the given symbol and return table JSON.
    """
    symbol = symbol.upper().strip()
    driver = _build_driver(headless=headless)

    try:
        driver.get(NSE_BASE_URL)
        time.sleep(2)

        url = f"{BOARD_MEETINGS_URL}?symbol={symbol}"
        driver.get(url)

        wait = WebDriverWait(driver, 25)
        wait.until(EC.presence_of_element_located((By.ID, "CFboardmeetingEquityTable")))
        time.sleep(1.5)

        html = driver.page_source
        return _parse_board_meetings_table(html)
    finally:
        driver.quit()


def get_corporate_actions_for_symbol(symbol: str, headless: bool = True) -> List[Dict]:
    """
    Open the NSE corporate actions page for the given symbol and return table JSON.
    """
    symbol = symbol.upper().strip()
    driver = _build_driver(headless=headless)

    try:
        driver.get(NSE_BASE_URL)
        time.sleep(2)

        url = f"{CORP_ACTIONS_URL}?symbol={symbol}"
        driver.get(url)

        wait = WebDriverWait(driver, 25)
        wait.until(EC.presence_of_element_located((By.ID, "CFcorpactionsEquityTable")))
        time.sleep(1.5)

        html = driver.page_source
        return _parse_corporate_actions_table(html)
    finally:
        driver.quit()
