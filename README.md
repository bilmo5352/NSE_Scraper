## NSE Scraping Service

Flask microservice that scrapes NSE corporate filings pages (event calendar, board meetings, corporate actions) for a given symbol using Selenium + BeautifulSoup.

### Endpoints
- `GET /health` – simple health check.
- `GET /event-calendar?symbol=RELIANCE` – returns event calendar rows.
- `GET /board-meetings?symbol=RELIANCE` – returns board meetings rows.
- `GET /corporate-actions?symbol=RELIANCE` – returns corporate action rows.

### Running locally
1) Install deps (Python 3.10+):
```
pip install -r requirements.txt
```
2) Start the server:
```
python app.py
```
3) Hit endpoints, e.g.:
```
curl "http://localhost:8000/corporate-actions?symbol=RELIANCE"
```

### Notes
- Uses `webdriver-manager` to auto-download ChromeDriver; ensures Chrome/Chromium is available.
- Selenium runs headless by default; toggle via function args if needed.
- NSE pages require an initial visit to the base domain to set cookies; scrapers handle this.
