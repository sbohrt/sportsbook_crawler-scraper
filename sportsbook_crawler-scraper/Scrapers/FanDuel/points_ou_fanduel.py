import csv
import os
import re
import random
import logging
import asyncio
import nodriver as n
import agentql
from playwright.async_api import async_playwright, Geolocation

# --- WINDOWS FIX ---
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

BROWSER_ARGS = [
    "--disable-xss-auditor", "--no-sandbox", "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process", "--disable-infobars",
]

nba_teams = {
    "atlanta-hawks", "boston-celtics", "brooklyn-nets", "charlotte-hornets",
    "chicago-bulls", "cleveland-cavaliers", "dallas-mavericks", "denver-nuggets",
    "detroit-pistons", "golden-state-warriors", "houston-rockets", "indiana-pacers",
    "los-angeles-clippers", "los-angeles-lakers", "memphis-grizzlies", "miami-heat",
    "milwaukee-bucks", "minnesota-timberwolves", "new-orleans-pelicans",
    "new-york-knicks", "philadelphia-76ers", "toronto-raptors", "orlando-magic",
    "washington-wizards", "oklahoma-city-thunder", "portland-trail-blazers",
    "utah-jazz", "phoenix-suns", "sacramento-kings", "san-antonio-spurs"
}

# --- QUERIES ---

DATE_CHECK_QUERY = """
{
    game_header {
        date_or_live_status_text
    }
}
"""

# UPDATED: Specific query to target ONLY the main Assists header
INTERACTION_QUERY = """
{
    assists_accordion_header(name: "Player Assists")
}
"""

BUTTON_QUERY = """
{
    show_more_buttons[](text: "Show more")
}
"""

# UPDATED: Specific query to extract data ONLY from the main Assists section
DATA_QUERY = """
{
    lines_section(name: "Player Assists") {
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

async def handle_press_and_hold(page):
    """Detects and bypasses the 'Press & Hold' CAPTCHA inside the iframe."""
    try:
        iframe = page.frame_locator('iframe[src="about:blank"]')
        captcha_btn = iframe.get_by_role("button", name="Press & Hold").first
        
        if await captcha_btn.is_visible(timeout=3000):
            log.info("⚠️ 'Press & Hold' detected! Engaging...")
            
            box = await captcha_btn.bounding_box()
            if box:
                await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await page.mouse.down()
                log.info("   -> Holding button (10s)...")
                await asyncio.sleep(10)
                await page.mouse.up()
                log.info("   -> Released.")
                await page.wait_for_timeout(3000)
                return True
    except Exception:
        pass
    return False

async def force_click_fallback(page, text_to_find):
    try:
        elements = await page.get_by_text(text_to_find, exact=True).all()
        if not elements: return False
        
        for i, element in enumerate(reversed(elements)):
            if await element.is_visible():
                await element.click()
                await asyncio.sleep(0.2)
        return True
    except Exception:
        return False

def filter_nba_event_links(csv_file_path, nba_teams):
    links_with_prefixes = [] 
    code_prefixes = set() 
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('url', '') or row.get('URL') or row.get('link') or ''
                
                if 'events/' in url or 'nba' in url:
                    url_lower = url.lower()
                    for team in nba_teams:
                        if team in url_lower:
                            match = re.search(r'-(\d{6,})$', url)
                            if match:
                                six_digit_code = match.group(1)[-8:]
                                first_5_digits = six_digit_code[:5]
                                code_prefixes.add(first_5_digits)
                                links_with_prefixes.append((url, first_5_digits))
                            break
    except Exception as e:
        log.error(f"Error reading CSV: {e}")
        return [], set(), None
    
    if code_prefixes:
        target_prefix = max(code_prefixes, key=int)
        filtered_links = [url for url, prefix in links_with_prefixes if prefix == target_prefix]
        return list(set(filtered_links)), code_prefixes, target_prefix
    else:
        return [], set(), None

async def scrape_single_game(page, base_url):
    """Scrapes a single game."""
    
    if "?" in base_url:
        URL = f"{base_url}&tab=player-assists"
    else:
        URL = f"{base_url}?tab=player-assists"

    game_name = "unknown"
    try:
        match = re.search(r'/nba/([^/?]+)', URL) or re.search(r'/events/([^/?]+)', URL)
        if match: game_name = match.group(1)
    except: pass

    results = [] 
    log.info(f"Scraping: {game_name}")

    try:
        # Navigate
        await page.goto(URL)
        
        # Bot Check
        await handle_press_and_hold(page)
        
        # Hydration
        await asyncio.sleep(random.uniform(2, 4))
        await page.wait_for_timeout(2000)

        # Date Check
        try:
            aql = agentql.wrap(page)
            date_data = await aql.query_data(DATE_CHECK_QUERY)
            status_text = date_data.get("game_header", {}).get("date_or_live_status_text", "").lower()
            if "tomorrow" in status_text or "mon" in status_text or "tue" in status_text or "wed" in status_text:
                log.info(f"Skipping {game_name} (Not Today: {status_text})")
                return []
        except: pass

        # Interaction: Open Specific Accordion
        try:
            aql = agentql.wrap(page)
            # UPDATED: Use the specific query provided
            resp = await aql.query_elements(INTERACTION_QUERY)
            
            # Access the specific field directly
            if resp.assists_accordion_header:
                log.info("Found 'Player Assists' header. Clicking...")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                await resp.assists_accordion_header.click()
                await page.wait_for_timeout(200)
            else:
                log.warning("AgentQL could not find specific 'Player Assists' header.")
                
        except Exception as e:
            # log.warning(f"Accordion interaction warning: {e}")
            pass

        # Interaction: Show More
        await asyncio.sleep(0.5)
        await force_click_fallback(page, "Show more")
        await asyncio.sleep(1.5)

        # Data Extraction
        aql = agentql.wrap(page)
        # UPDATED: Use the specific data query
        data = await aql.query_data(DATA_QUERY)
        
        # Access the specific section directly (no loop needed)
        lines_section = data.get("lines_section")
        
        if lines_section:
            rows = lines_section.get("rows", [])
            for r in rows:
                p_name = r.get("player_name")
                line_val = clean_line(r.get("over_line_label"))
                
                if p_name and line_val:
                    results.append({
                        "game": game_name,
                        "market": "player assists",
                        "player": p_name,
                        "line": line_val,
                        "odds_over": r.get("over_price"),
                        "odds_under": r.get("under_price")
                    })
        else:
            log.warning("No data found in 'Player Assists' section.")
        
        log.info(f" -> Found {len(results)} rows.")

    except Exception as e:
        log.error(f"Error on {game_name}: {e}")

    return results

# --- ASYNC MAIN ---
async def async_main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    links_path = os.path.join(script_dir, '..', '..', 'Links', 'betting_links_fanduel.csv')
    if not os.path.exists(links_path):
        links_path = os.path.join(script_dir, 'Links', 'betting_links_fanduel.csv')

    filtered_links, _, _ = filter_nba_event_links(links_path, nba_teams)
    log.info(f"Filtered to {len(filtered_links)} games for today.")

    if not filtered_links:
        return

    all_data = []

    log.info("Starting Nodriver (Chrome)...")
    browser_obj = None
    try:
        browser_obj = await n.start(browser_args=BROWSER_ARGS, headless=False)
        cdp_url = browser_obj.connection.websocket_url
        log.info(f"Connected to Nodriver at: {cdp_url}")

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            page = context.pages[0] 

            for i, link in enumerate(filtered_links):
                log.info(f"Processing {i+1}/{len(filtered_links)}: {link}")
                
                game_data = await scrape_single_game(page, link)
                all_data.extend(game_data)
                
                if i < len(filtered_links) - 1:
                    sleep_sec = random.uniform(2.0, 4.0)
                    log.info(f"Sleeping {sleep_sec:.2f}s...")
                    await asyncio.sleep(sleep_sec)
            
            await browser.close()

    except Exception as e:
        log.error(f"Execution Error: {e}")
    finally:
        if browser_obj:
            try:
                browser_obj.stop()
            except: pass

    # Save Data
    output_dir = os.path.join(script_dir, '..', '..', 'Odds')
    if not os.path.exists(output_dir): output_dir = os.path.join(script_dir, 'Odds')
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, 'fanduel_odds.csv')
    fieldnames = ["game", "market", "player", "line", "odds_over", "odds_under"]
    
    final_rows = []
    if os.path.exists(output_path):
        with open(output_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('market') != 'player assists':
                    final_rows.append(row)
    
    final_rows.extend(all_data)
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final_rows)

    log.info(f"Done. Saved {len(final_rows)} total rows.")

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()