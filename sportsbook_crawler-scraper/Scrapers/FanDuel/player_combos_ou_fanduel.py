import csv
import os
import re
import random
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import agentql
from playwright.sync_api import sync_playwright, Geolocation

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Stealth / Browser Config
BROWSER_IGNORED_ARGS = ["--enable-automation", "--disable-extensions"]
BROWSER_ARGS = [
    "--disable-xss-auditor", "--no-sandbox", "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process", "--disable-infobars",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]
LOCATIONS = [
    ("America/New_York", Geolocation(longitude=-74.006, latitude=40.7128)),
    ("America/Chicago", Geolocation(longitude=-87.6298, latitude=41.8781)),
    ("America/Los_Angeles", Geolocation(longitude=-118.2437, latitude=34.0522)),
]

# --- QUERIES ---
INTERACTION_QUERY = """
{
    market_accordions[] {
        header_text
        header_element
    }
}
"""

BUTTON_QUERY = """
{
    show_more_buttons[](text: "Show more")
}
"""

DATA_QUERY = """
{
    market_accordions[] {
        header_text
        rows[] {
            player_name
            over_line_label
            over_price
            under_line_label
            under_price
        }
    }
}
"""

# --- HELPERS ---
def clean_line(text):
    if not text: return ""
    return text.replace("O ", "").replace("U ", "").strip()

def handle_press_and_hold(page):
    """Detects and bypasses the 'Press & Hold' CAPTCHA."""
    try:
        captcha_btn = page.get_by_text("Press & Hold", exact=False).first
        if captcha_btn.is_visible(timeout=3000):
            log.info("⚠️ 'Press & Hold' CAPTCHA detected! Attempting bypass...")
            box = captcha_btn.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                log.info("   -> Mouse DOWN (Holding for 10s)...")
                page.mouse.down()
                page.wait_for_timeout(10000)
                log.info("   -> Mouse UP")
                page.mouse.up()
                page.wait_for_timeout(5000)
                return True
    except Exception:
        pass
    return False

def force_click_fallback(page, text_to_find):
    """Robust fallback to find and click buttons by text."""
    try:
        elements = page.get_by_text(text_to_find, exact=True).all()
        if not elements: return False
        log.info(f"FALLBACK: Found {len(elements)} instances of '{text_to_find}'. Clicking...")
        for i, element in enumerate(reversed(elements)):
            if element.is_visible():
                element.click()
                page.wait_for_timeout(300)
        return True
    except Exception:
        return False

def filter_nba_links(csv_path):
    """Reads CSV and returns valid FanDuel NBA links (nba + numbers)."""
    links = []
    if not os.path.exists(csv_path):
        log.error(f"CSV not found: {csv_path}")
        return []
        
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get('url') or row.get('URL') or row.get('link') or row.get('Link') or ''
            url = url.strip()
            has_nba = 'nba' in url.lower()
            has_numbers = any(char.isdigit() for char in url)
            if has_nba and has_numbers:
                links.append(url)
    
    unique_links = list(set(links))
    log.info(f"Filtered Links: Found {len(unique_links)} URLs containing 'nba' and numbers.")
    return unique_links

# --- WORKER FUNCTION ---
def scrape_single_game(browser_config, base_url):
    """Worker thread: Handles Bot Check -> Nav -> Combo Extraction."""
    
    # Append the Player Combos tab
    if "?" in base_url:
        URL = f"{base_url}&tab=player-combos"
    else:
        URL = f"{base_url}?tab=player-combos"

    game_name = "unknown"
    try:
        match = re.search(r'/nba/([^/?]+)', URL)
        if match: game_name = match.group(1)
    except: pass

    results = [] 
    log.info(f"Starting scrape: {game_name}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=browser_config['args'],
                ignore_default_args=browser_config['ignore_default_args']
            )
            context = browser.new_context(
                locale=browser_config['locale'],
                timezone_id=browser_config['timezone_id'],
                geolocation=browser_config['geolocation'],
                user_agent=browser_config['user_agent'],
                permissions=["geolocation"],
                viewport={"width": 1280, "height": 720}
            )
            page = context.new_page()
            aql_page = agentql.wrap(page)

            # Navigate
            aql_page.goto(URL)
            page.wait_for_timeout(3000)

            # 1. HANDLE BOT CHECK
            handle_press_and_hold(page)

            # Wait for hydration
            log.info("Waiting for page hydration...")
            page.wait_for_timeout(5000)

            # 2. OPEN ACCORDIONS
            try:
                resp = aql_page.query_elements(INTERACTION_QUERY)
                accordions = getattr(resp, 'market_accordions', [])
                for acc in accordions:
                    try:
                        raw_text = acc.header_text.text_content() if acc.header_text else ""
                        text = raw_text.lower()
                    except: text = ""

                    if "pts" in text or "reb" in text or "ast" in text:
                        if acc.header_element:
                            try:
                                acc.header_element.click()
                                page.wait_for_timeout(300)
                            except: pass
            except: pass

            # 3. CLICK SHOW MORE
            try:
                resp = aql_page.query_elements(BUTTON_QUERY)
                if resp.show_more_buttons:
                    for btn in resp.show_more_buttons:
                        btn.click()
                        page.wait_for_timeout(500)
            except: pass
            
            force_click_fallback(page, "Show more")
            page.wait_for_timeout(3000)

            # 4. EXTRACT DATA
            data = aql_page.query_data(DATA_QUERY)
            market_accordions = data.get("market_accordions", [])

            for section in market_accordions:
                header = section.get("header_text", "")
                rows = section.get("rows", [])

                if not header: continue
                
                # Normalize Market Name based on Header
                market_name = None
                
                if "Pts + Reb + Ast" in header:
                    market_name = "points rebounds assists"
                elif "Pts + Reb" in header:
                    market_name = "points rebounds"
                elif "Pts + Ast" in header:
                    market_name = "points assists"
                elif "Reb + Ast" in header:
                    market_name = "rebounds assists"

                # If it's a valid market, extract rows
                if market_name:
                    for r in rows:
                        p_name = r.get("player_name")
                        line_val = clean_line(r.get("over_line_label"))
                        
                        if p_name and line_val:
                            results.append({
                                "game": game_name,
                                "market": market_name,
                                "player": p_name,
                                "line": line_val,
                                "odds_over": r.get("over_price"),
                                "odds_under": r.get("under_price")
                            })
            
            log.info(f" -> Scraped {len(results)} rows from {game_name}")
            browser.close()

    except Exception as e:
        log.error(f"Error scraping {game_name}: {e}")

    return results

# --- MAIN ---
def main():
    # Setup paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fanduel_dir = os.path.dirname(script_dir)
    scraper_dir = os.path.dirname(fanduel_dir)
    
    links_path = os.path.join(scraper_dir, 'Links', 'betting_links_fanduel.csv')
    
    # 1. Get Links
    links = filter_nba_links(links_path)
    log.info(f"Found {len(links)} NBA games to process.")

    # 2. Config
    location = random.choice(LOCATIONS)
    browser_config = {
        'args': BROWSER_ARGS,
        'ignore_default_args': BROWSER_IGNORED_ARGS,
        'locale': "en-US",
        'timezone_id': location[0],
        'geolocation': location[1],
        'user_agent': random.choice(USER_AGENTS)
    }

    # 3. Thread Pool Execution
    all_results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(scrape_single_game, browser_config, url): url for url in links}
        
        for future in as_completed(futures):
            all_results.extend(future.result())

    # 4. Save to Single CSV (fanduel_odds.csv)
    output_dir = os.path.join(script_dir, '..', '..', 'Odds')
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, 'fanduel_odds.csv')

    # Define strict column order requested
    fieldnames = ["game", "market", "player", "line", "odds_over", "odds_under"]
    
    # Write Mode: 'w' overwrites. Change to 'a' if you want to append.
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    log.info(f"Scraping Job Complete. Saved {len(all_results)} rows to {output_path}")

if __name__ == "__main__":
    main()