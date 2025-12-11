import asyncio
import os
import random
from datetime import datetime
from playwright.async_api import async_playwright


async def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Add random delay to simulate human behavior."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def scrape_equity_quote(
    url: str,
    output_dir: str = "output",
    headless: bool = False,
    take_screenshot: bool = True,
) -> dict:
    """
    Scrape the NSE equity quote page with human-like behavior.

    Saves a screenshot and the rendered HTML.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = url.split("//")[-1].split("/")[0].replace(".", "_")
    screenshot_path = os.path.join(output_dir, f"{domain}_quote_{timestamp}.png")
    html_path = os.path.join(output_dir, f"{domain}_quote_{timestamp}.html")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
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

            # Extra wait for dynamic content
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

            await context.close()
            await browser.close()

            return {
                "status": "success",
                "url": url,
                "screenshot": screenshot_path,
                "html": html_path,
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


__all__ = ["scrape_equity_quote"]

