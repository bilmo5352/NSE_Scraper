import asyncio
import os
import random
import sys
import argparse
import json
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


async def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Add random delay to simulate human behavior"""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


def parse_financial_results(html_content: str) -> dict:
    """
    Parse the financial results comparison HTML and extract structured data.
    
    Args:
        html_content: Raw HTML content from the scraped page
    
    Returns:
        dict: Structured financial data with quarters, sections, and line items
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract company name and symbol (appears before the table)
    company_name = "N/A"
    company_symbol = "N/A"
    
    # Find the <p class="line1"> which contains company info
    line1_elem = soup.find('p', class_='line1')
    if line1_elem:
        spans = line1_elem.find_all('span')
        if len(spans) >= 2:
            # First span (class="lt") has company name
            company_name = spans[0].get_text(strip=True)
            # Second span has symbol
            company_symbol = spans[1].get_text(strip=True)
    
    # Find the financial results table (it's inside div#resultsCompare)
    results_compare_div = soup.find('div', id='resultsCompare')
    if not results_compare_div:
        return {
            "status": "error",
            "message": "Financial results container (div#resultsCompare) not found - data may not have loaded",
            "company": {
                "name": company_name,
                "symbol": company_symbol
            }
        }
    
    table = results_compare_div.find('table', class_='common_table')
    
    if not table:
        return {
            "status": "error",
            "message": "Financial results table not found inside resultsCompare div",
            "company": {
                "name": company_name,
                "symbol": company_symbol
            }
        }
    
    # Extract quarter headers
    thead = table.find('thead')
    if not thead:
        return {
            "status": "error",
            "message": "Table header not found"
        }
    
    header_rows = thead.find_all('tr')
    quarters = []
    audit_status = []
    
    if len(header_rows) >= 2:
        # First row has quarter dates
        quarter_cells = header_rows[0].find_all('th')[1:]  # Skip first cell (QUARTER ENDED)
        quarters = [cell.get_text(strip=True) for cell in quarter_cells]
        
        # Second row has audit status
        status_cells = header_rows[1].find_all('th')[1:]  # Skip first cell (PARTICULARS)
        audit_status = [cell.get_text(strip=True) for cell in status_cells]
    
    # Extract data rows from tbody
    tbody = table.find('tbody')
    if not tbody:
        return {
            "status": "error",
            "message": "Table body (tbody) not found - data may not have loaded",
            "company": {
                "name": company_name,
                "symbol": company_symbol
            }
        }
    
    rows = tbody.find_all('tr')
    if not rows or len(rows) < 3:
        return {
            "status": "error",
            "message": f"Insufficient data rows found (found {len(rows) if rows else 0} rows)",
            "company": {
                "name": company_name,
                "symbol": company_symbol
            }
        }
    
    sections = []
    current_section = None
    
    for row in rows:
        # Check if it's a section header
        section_header = row.find('td', class_='sectionCol')
        if section_header:
            # Save previous section if exists
            if current_section:
                sections.append(current_section)
            
            # Start new section
            current_section = {
                "section_name": section_header.get_text(strip=True),
                "line_items": []
            }
            continue
        
        # Extract data rows
        cells = row.find_all('td')
        if len(cells) > 1 and current_section:
            # First cell is the line item name
            line_item_name = cells[0].get_text(strip=True)
            
            # Rest are values for each quarter
            values = []
            for cell in cells[1:]:
                value_text = cell.get_text(strip=True)
                # Clean up value (remove commas, handle dash/empty)
                if value_text in ['-', '']:
                    value_text = None
                values.append(value_text)
            
            # Check if this is a highlighted/total row
            is_total = 'text-bold' in str(row) or 'highlightRow' in str(row)
            
            current_section["line_items"].append({
                "name": line_item_name,
                "values": values,
                "is_total": is_total
            })
    
    # Add the last section
    if current_section:
        sections.append(current_section)
    
    # Build the final structured response
    result = {
        "status": "success",
        "company": {
            "name": company_name,
            "symbol": company_symbol
        },
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
    
    return result


async def scrape_with_search(url: str, search_term: str, output_dir: str = "output") -> dict:
    """
    Scrape a webpage with form interaction - search for a company and click first suggestion.
    Uses human-like behavior to avoid bot detection.
    
    Args:
        url: The URL of the page to scrape
        search_term: Company name or symbol to search (e.g., "RELIANCE")
        output_dir: Directory to save outputs (screenshots and HTML)
    
    Returns:
        dict: Contains paths to saved screenshot and HTML file
    """
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate timestamp for unique filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = url.split("//")[-1].split("/")[0].replace(".", "_")
    
    screenshot_path = os.path.join(output_dir, f"{domain}_screenshot_{timestamp}.png")
    html_path = os.path.join(output_dir, f"{domain}_page_{timestamp}.html")
    json_path = os.path.join(output_dir, f"{domain}_data_{timestamp}.json")
    
    async with async_playwright() as p:
        # Launch browser with visible window - disable blink features to appear more human
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        
        page = await context.new_page()
        
        # Inject script to hide automation indicators
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
        """)
        
        # Set browser headers
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
        })
        
        try:
            print(f"[INFO] Opening page: {url}")
            # Navigate to the page
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            print(f"[INFO] Waiting for page to fully load...")
            await human_delay(2, 4)
            
            # Move mouse around to simulate human activity
            await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
            await human_delay(0.5, 1)
            
            print(f"[INFO] Looking for company search input field...")
            # Find the input field - try multiple selectors
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
                            print(f"[SUCCESS] Found input field with selector: {selector}")
                            break
                except:
                    continue
            
            if not input_field:
                print(f"[ERROR] Could not find company search input field")
                await context.close()
                await browser.close()
                return {
                    "status": "error",
                    "url": url,
                    "error": "Could not find search input field"
                }
            
            # Scroll to input field
            await input_field.scroll_into_view_if_needed()
            await human_delay(1, 2)
            
            # Move mouse to input field
            box = await input_field.bounding_box()
            if box:
                await page.mouse.move(int(box['x'] + box['width'] / 2), int(box['y'] + box['height'] / 2))
            await human_delay(0.5, 1.5)
            
            # Click the input field
            print(f"[INFO] Clicking on input field...")
            await input_field.click()
            await human_delay(1, 2)
            
            # Clear any existing text using Ctrl+A and Delete
            await input_field.press("Control+A")
            await human_delay(0.2, 0.4)
            await input_field.press("Backspace")
            await human_delay(0.3, 0.7)
            
            # Type with realistic delays (character by character)
            print(f"[INFO] Typing '{search_term}' in search field with realistic delays...")
            for char in search_term:
                await input_field.type(char, delay=random.randint(50, 150))
                await human_delay(0.05, 0.2)
            
            print(f"[INFO] Waiting for suggestions to appear...")
            await human_delay(3, 5)
            
            # Try to find and click the correct suggestion
            print(f"[INFO] Looking for suggestion matching '{search_term}'...")
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
                        print(f"[SUCCESS] Found {count} suggestions with selector: {selector}")
                        
                        # Loop through suggestions to find the one matching our search term
                        for i in range(count):
                            suggestion = suggestions.nth(i)
                            try:
                                suggestion_text = await suggestion.inner_text()
                                suggestion_text = suggestion_text.strip()
                                print(f"[DEBUG] Suggestion {i+1}: '{suggestion_text}'")
                                
                                # Match if search term appears anywhere in the suggestion
                                search_upper = search_term.upper()
                                suggestion_upper = suggestion_text.upper()
                                
                                # Check if search term is in the suggestion text
                                if search_upper in suggestion_upper:
                                        print(f"[INFO] ✓ Found matching suggestion: {suggestion_text}")
                                        
                                        try:
                                            is_visible = await suggestion.is_visible(timeout=2000)
                                            if is_visible:
                                                await suggestion.scroll_into_view_if_needed()
                                                await human_delay(0.3, 0.8)
                                                
                                                print(f"[INFO] Clicking on: {suggestion_text}")
                                                await suggestion.click(force=True, timeout=10000)
                                                print(f"[SUCCESS] Clicked successfully")
                                                await human_delay(1, 2)
                                                suggestion_found = True
                                                break
                                        except Exception as e:
                                            print(f"[WARN] Error clicking suggestion: {str(e)}")
                                            continue
                            except Exception as e:
                                print(f"[DEBUG] Error processing suggestion {i+1}: {str(e)}")
                                continue
                        
                        if suggestion_found:
                            break
                except Exception as e:
                    print(f"[DEBUG] Failed with selector '{selector}': {str(e)}")
                    continue
            
            if not suggestion_found:
                print(f"[WARN] Could not find exact match, trying first suggestion as fallback...")
                try:
                    # Try to click the first suggestion as last resort
                    # Try multiple selectors
                    for fallback_selector in ['.tt-suggestion', '.autocompleteList', '.ng-option']:
                        try:
                            first_suggestion = page.locator(fallback_selector).first
                            if await first_suggestion.is_visible(timeout=2000):
                                suggestion_text = await first_suggestion.inner_text()
                                print(f"[INFO] Clicking first suggestion: {suggestion_text}")
                                await first_suggestion.click(force=True, timeout=10000)
                                print(f"[SUCCESS] Clicked first suggestion")
                                await human_delay(1, 2)
                                suggestion_found = True
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"[WARN] Fallback also failed: {str(e)}")
            
            if not suggestion_found:
                print(f"[WARN] Could not find suggestion dropdown, trying keyboard navigation...")
                await human_delay(0.5, 1)
                await input_field.press("ArrowDown")
                await human_delay(0.3, 0.8)
                await input_field.press("Enter")
            
            print(f"[INFO] Waiting after selecting suggestion...")
            await human_delay(2, 4)
            
            print(f"[INFO] Looking for search button...")
            # Find and click search button
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
                            print(f"[SUCCESS] Found search button with selector: {selector}")
                            
                            # Move mouse to button
                            box = await button.bounding_box()
                            if box:
                                await page.mouse.move(int(box['x'] + box['width'] / 2), int(box['y'] + box['height'] / 2))
                            await human_delay(0.5, 1.5)
                            
                            # Click button
                            await button.click()
                            button_found = True
                            break
                except:
                    continue
            
            if not button_found:
                print(f"[WARN] Could not find search button, pressing Enter instead...")
                await input_field.press("Enter")
            
            print(f"[INFO] Waiting for results to load and JavaScript to render...")
            await human_delay(8, 12)
            
            # Check if table loaded by looking for the results table
            print(f"[INFO] Checking if financial results table loaded...")
            try:
                table_selector = 'table.common_table'
                table_locator = page.locator(table_selector)
                await table_locator.wait_for(state='visible', timeout=15000)
                print(f"[SUCCESS] Financial results table is visible")
            except Exception as e:
                print(f"[WARN] Table may not have loaded: {str(e)}")
                print(f"[INFO] Waiting additional 5 seconds...")
                await human_delay(5, 7)
            
            print(f"[INFO] Taking screenshot...")
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"[SUCCESS] Screenshot saved to: {screenshot_path}")
            
            print(f"[INFO] Saving HTML content...")
            html_content = await page.content()
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"[SUCCESS] HTML saved to: {html_path}")
            
            print(f"[INFO] Parsing financial data from HTML...")
            parsed_data = parse_financial_results(html_content)
            
            if parsed_data.get("status") == "success":
                print(f"[SUCCESS] Extracted {parsed_data['metadata']['total_sections']} sections with {parsed_data['metadata']['total_quarters']} quarters")
                
                # Save parsed data as JSON
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(parsed_data, f, indent=2, ensure_ascii=False)
                print(f"[SUCCESS] Parsed data saved to: {json_path}")
            else:
                print(f"[WARN] Failed to parse financial data: {parsed_data.get('message')}")
            
            await context.close()
            await browser.close()
            
            return {
                "status": "success",
                "url": url,
                "search_term": search_term,
                "screenshot": screenshot_path,
                "html": html_path,
                "json": json_path,
                "parsed_data": parsed_data,
                "timestamp": timestamp
            }
            
        except Exception as e:
            print(f"[ERROR] Failed to scrape: {str(e)}")
            await context.close()
            await browser.close()
            return {
                "status": "error",
                "url": url,
                "search_term": search_term,
                "error": str(e)
            }


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Web scraper for NSE financial results comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python interactive_scraper.py -s RELIANCE
  python interactive_scraper.py -s TCS
  python interactive_scraper.py -s INFY -o ./custom_output
        """
    )
    
    parser.add_argument(
        '-s', '--symbol',
        required=True,
        help='Stock symbol to search (e.g., RELIANCE, TCS, INFY, HDFC, ICICI)'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='../output',
        help='Output directory for screenshots and HTML files (default: ../output)'
    )
    
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run in headless mode (no browser window)'
    )
    
    args = parser.parse_args()
    
    # Print header
    print("[START] Interactive Web Scraper with Playwright")
    print(f"Mode: JavaScript Rendering Enabled | Headless: {args.headless} | Wait Time: 10s")
    print(f"Stock Symbol: {args.symbol}\n")
    
    url = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results-comparision"
    search_term = args.symbol.upper()
    
    result = asyncio.run(scrape_with_search(url, search_term, output_dir=args.output))
    
    if result.get("status") == "success":
        print(f"\n[FINAL] ✓ Scraping completed successfully!")
        print(f"  Stock Symbol: {result['search_term']}")
        print(f"  Screenshot: {result['screenshot']}")
        print(f"  HTML: {result['html']}")
        print(f"  JSON: {result.get('json', 'N/A')}")
        
        # Print summary of parsed data
        parsed_data = result.get('parsed_data', {})
        if parsed_data.get('status') == 'success':
            print(f"\n[DATA SUMMARY]")
            print(f"  Company: {parsed_data['company']['name']} ({parsed_data['company']['symbol']})")
            print(f"  Quarters: {', '.join(parsed_data['quarters'])}")
            print(f"  Total Sections: {parsed_data['metadata']['total_sections']}")
            print(f"  Currency: {parsed_data['currency']}")
            
            # Print section names
            print(f"\n[SECTIONS EXTRACTED]")
            for i, section in enumerate(parsed_data['sections'], 1):
                print(f"  {i}. {section['section_name']} ({len(section['line_items'])} line items)")
    else:
        print(f"\n[FINAL] ✗ Scraping failed: {result.get('error')}")
