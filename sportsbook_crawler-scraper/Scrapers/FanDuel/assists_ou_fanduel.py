import csv
import os
import re
import random
import logging
import asyncio
import nodriver as n
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
                await page.wait_for_timeout(5000)
                return True
    except Exception:
        pass
    return False

async def open_assists_accordion(page):
    """Finds and clicks the 'Player Assists' header using Pure Playwright."""
    try:
        # 1. Look for specific button role with exact text
        header = page.get_by_role("button", name="Player Assists", exact=True).first
        
        if await header.is_visible():
            expanded = await header.get_attribute("aria-expanded")
            if expanded == "true":
                log.info("Header already open.")
                return True # It is open, we can proceed
            
            log.info("Found 'Player Assists' header. Clicking...")
            await header.click()
            await page.wait_for_timeout(1000)
            return True

        # 2. Fallback
        text_header = page.get_by_text("Player Assists", exact=True).first
        if await text_header.is_visible():
            log.info("Found 'Player Assists' text. Clicking...")
            await text_header.click()
            await page.wait_for_timeout(1000)
            return True
            
    except Exception as e:
        log.warning(f"Accordion interaction issue: {e}")
    return False

async def click_show_more(page):
    """Clicks 'Show more' buttons."""
    try:
        show_mores = await page.get_by_text("Show more", exact=True).all()
        if show_mores:
            log.info(f"Found {len(show_mores)} 'Show more' buttons. Clicking...")
            for btn in reversed(show_mores):
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
    except Exception:
        pass

async def extract_data_pure_playwright(page, game_name):
    """
    Extracts betting rows by scanning the entire Player Assists container text.
    This is more robust than looking for specific list items.
    """
    results = []
    try:
        # 1. Locate the header again to find the container
        header = page.get_by_role("button", name="Player Assists", exact=True).first
        
        if not await header.is_visible():
            # Fallback text locator
            header = page.get_by_text("Player Assists", exact=True).first
            if not await header.is_visible():
                return []

        # 2. Get the parent/sibling container that holds the data
        # We assume the data is in a div following the header.
        # A robust way is to get the bounding box of the header and look below it,
        # OR simply scrape ALL visible text on the page and parse it (safest).
        
        # We will try to find the specific market container first
        # Usually it's a sibling div or inside a list
        
        # Let's try grabbing the text of the *entire* relevant section
        # We look for the container that has "Player Assists" and likely "Show less" (since we expanded it)
        # or simply scan for the pattern on the whole page content.
        
        page_text = await page.content() # Get raw HTML
        
        # We can use regex on the raw HTML or text content to find the patterns
        # Pattern: Player Name ... O [Line] [Odds] ... U [Line] [Odds]
        # This regex is designed to find:
        # >Name< ... >O 5.5< ... >-110< ... >U 5.5< ... >-110<
        
        # However, Playwright's locator list strategy is better if we target the right elements.
        # Let's try a very broad locator: Any element containing "O " followed by a number
        
        potential_rows = await page.locator('div, li').filter(has_text=re.compile(r'^O\s+\d+\.?\d*')).all()
        
        # Deduplicate elements (nested divs might match multiple times)
        unique_texts = set()
        
        log.info(f"Scanning {len(potential_rows)} potential row elements...")

        for row in potential_rows:
            text = await row.inner_text()
            if not text or text in unique_texts: continue
            unique_texts.add(text)
            
            lines = text.split('\n')
            # Look for the specific structure:
            # 1. Player Name
            # 2. O [Line]
            # 3. [Odds]
            # 4. U [Line]
            # 5. [Odds]
            
            # Simple Parser
            if "O " in text and "U " in text:
                player_name = lines[0].strip()
                
                # Filter out headers
                if "Player" in player_name or "Assists" in player_name or len(player_name) > 40: continue
                
                # Find Over Line/Odds
                o_line = None
                o_odds = None
                u_odds = None
                
                for i, line in enumerate(lines):
                    if line.startswith("O ") and not o_line:
                        o_line = line.replace("O ", "").strip()
                        if i+1 < len(lines): o_odds = lines[i+1]
                    
                    if line.startswith("U ") and not u_odds:
                        # u_line = line.replace("U ", "").strip() # Usually same as O line
                        if i+1 < len(lines): u_odds = lines[i+1]
                
                if player_name and o_line and o_odds and u_odds:
                    results.append({
                        "game": game_name,
                        "market": "player assists",
                        "player": player_name,
                        "line": o_line,
                        "odds_over": o_odds,
                        "odds_under": u_odds
                    })

    except Exception as e:
        log.warning(f"Manual extraction issue: {e}")
        
    return results

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
    except Exception:
        return [], set(), None
    
    if code_prefixes:
        target_prefix = max(code_prefixes, key=int)
        filtered_links = [url for url, prefix in links_with_prefixes if prefix == target_prefix]
        return list(set(filtered_links)), code_prefixes, target_prefix
    else:
        return [], set(), None

async def scrape_single_game(page, base_url, is_first_game=False):
    if "?" in base_url:
        URL = f"{base_url}&tab=player-assists"
    else:
        URL = f"{base_url}?tab=player-assists"

    game_name = "unknown"
    try:
        match = re.search(r'/nba/([^/?]+)', URL) or re.search(r'/events/([^/?]+)', URL)
        if match: game_name = match.group(1)
    except: pass

    log.info(f"Scraping: {game_name}")

    try:
        await page.goto(URL)
        await handle_press_and_hold(page)
        
        # Warmup sleep
        wait_time = 6 if is_first_game else random.uniform(2, 4)
        log.info(f"Waiting {wait_time:.1f}s for page load...")
        await asyncio.sleep(wait_time)
        
        # --- INTERACTION ---
        await open_assists_accordion(page)
        await asyncio.sleep(1)
        await click_show_more(page)
        await asyncio.sleep(2)

        # --- EXTRACTION ---
        results = await extract_data_pure_playwright(page, game_name)
        log.info(f" -> Found {len(results)} rows.")
        return results

    except Exception as e:
        log.error(f"Error on {game_name}: {e}")
        return []

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
                is_first = (i == 0)
                game_data = await scrape_single_game(page, link, is_first_game=is_first)
                all_data.extend(game_data)
                
                if i < len(filtered_links) - 1:
                    await asyncio.sleep(random.uniform(2.0, 4.0))
            
            await browser.close()

    except Exception as e:
        log.error(f"Execution Error: {e}")
    finally:
        if browser_obj:
            try: browser_obj.stop()
            except: pass

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