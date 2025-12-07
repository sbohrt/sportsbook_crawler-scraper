import logging
import csv
import os
import re
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import agentql
from playwright.sync_api import sync_playwright, Geolocation

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Stealth mode configuration
BROWSER_IGNORED_ARGS = [
    "--enable-automation",
    "--disable-extensions",
]
BROWSER_ARGS = [
    "--disable-xss-auditor",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-infobars",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0",
]

LOCATIONS = [
    ("America/New_York", Geolocation(longitude=-74.006, latitude=40.7128)),  # New York, NY
    ("America/Chicago", Geolocation(longitude=-87.6298, latitude=41.8781)),  # Chicago, IL
    ("America/Los_Angeles", Geolocation(longitude=-118.2437, latitude=34.0522)),  # Los Angeles, CA
    ("America/Denver", Geolocation(longitude=-104.9903, latitude=39.7392)),  # Denver, CO
    ("America/Phoenix", Geolocation(longitude=-112.0740, latitude=33.4484)),  # Phoenix, AZ
]

REFERERS = ["https://www.google.com", "https://www.bing.com", "https://duckduckgo.com"]
ACCEPT_LANGUAGES = ["en-US,en;q=0.9", "en-GB,en;q=0.9", "fr-FR,fr;q=0.9"]

nba_teams = {
    "atlanta-hawks",
    "boston-celtics",
    "brooklyn-nets",
    "charlotte-hornets",
    "chicago-bulls",
    "cleveland-cavaliers",
    "dallas-mavericks",
    "denver-nuggets",
    "detroit-pistons",
    "golden-state-warriors",
    "houston-rockets",
    "indiana-pacers",
    "los-angeles-clippers",
    "memphis-grizzlies",
    "miami-heat",
    "milwaukee-bucks",
    "minnesota-timberwolves",
    "new-orleans-pelicans",
    "new-york-knicks",
    "philadelphia-76ers",
    "toronto-raptors",
    "orlando-magic",
    "washington-wizards",
    "oklahoma-city-thunder",
    "portland-trail-blazers",
    "utah-jazz",
    "phoenix-suns",
    "sacramento-kings",
    "san-antonio-spurs"

}

def filter_nba_event_links(csv_file_path, nba_teams):
    """
    Filter links from CSV that include 'events/' followed by any NBA team name.
    Also extracts and tracks the first 3 digits from the 6-digit code at the end of URLs.
    Returns only links with the lowest code prefix.
    
    Returns:
        tuple: (filtered_links list with lowest prefix, code_prefixes set, lowest_prefix)
    """

    links_with_prefixes = []  # Store (url, prefix) tuples
    code_prefixes = set()  # Track unique first 3 digits of 6-digit codes
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('url', '')
                
                # Check if URL contains "events/"
                if 'events/' in url:
                    # Check if any NBA team name is in the URL
                    url_lower = url.lower()
                    for team in nba_teams:
                        if team in url_lower:
                            # Extract the 6-digit code from the end of the URL
                            # Pattern: ends with a hyphen followed by digits
                            match = re.search(r'-(\d{6,})$', url)
                            if match:
                                six_digit_code = match.group(1)[-8:]  # Get last 8 digits
                                first_3_digits = six_digit_code[:3]  # Get first 3 digits
                                code_prefixes.add(first_3_digits)
                                links_with_prefixes.append((url, first_3_digits))
                            
                            break  # Found a match, no need to check other teams

    
    except FileNotFoundError:
        log.error(f"CSV file not found: {csv_file_path}")
    except Exception as e:
        log.error(f"Error reading CSV file: {e}")
    
    # Find the lowest prefix code
    if code_prefixes:
        lowest_prefix = min(code_prefixes, key=int)
        
        # Filter to only links with the lowest prefix
        filtered_links = [url for url, prefix in links_with_prefixes if prefix == lowest_prefix]
    else:
        lowest_prefix = None
        filtered_links = []
    
    return filtered_links, code_prefixes, lowest_prefix

def scrape_single_game(browser_config, URL, market, POINTS_REBOUNDS_QUERY):
    """
    Scrape a single game and return the rows for CSV.
    Each thread creates its own browser instance for thread safety.
    
    Args:
        browser_config: Dict with browser configuration
        URL: Game URL to scrape
        market: Market name
        POINTS_REBOUNDS_QUERY: AgentQL query
    
    Returns:
        list: Rows of player props data
    """
    # Extract game name from URL
    match = re.search(r'/events/([^/]+)-\d+', URL)
    if match:
        game_name = match.group(1)
        log.info(f"Game: {game_name}")
    else:
        game_name = "unknown"
        log.warning(f"Could not extract game name from URL")
    
    rows = []
    
    try:
        # Each thread creates its own Playwright instance and browser
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=browser_config['args'],
                ignore_default_args=browser_config['ignore_default_args'],
            )
            
            context = browser.new_context(
                locale=browser_config['locale'],
                timezone_id=browser_config['timezone_id'],
                extra_http_headers=browser_config['extra_http_headers'],
                geolocation=browser_config['geolocation'],
                user_agent=browser_config['user_agent'],
                permissions=browser_config['permissions'],
                viewport=browser_config['viewport'],
            )
            
            page = agentql.wrap(context.new_page())
            page.enable_stealth_mode(nav_user_agent=browser_config['user_agent'])
            
            # Navigate to the URL
            page.goto(URL, wait_until="domcontentloaded")
            page.wait_for_page_ready_state()
            
            
            # === EXACT ACTIONS FROM YOUR CODEGEN ===
            
            # Click Player points + rebounds O/U button
            page.locator("button").filter(has_text="Player points + rebounds").nth(1).click()
            page.locator("ms-player-props-option-group").get_by_text("Show More").click()

            # === SCRAPE MARKET USING AGENTQL ===
            data = page.query_data(POINTS_REBOUNDS_QUERY)
            selections = data.get("points_rebounds", [])

            # Build CSV rows for this game
            for sel in selections:
                player_name = sel.get('player_name', '')
                line = sel.get('line', '')
                odds_over = sel.get('odds_over', '')
                odds_under = sel.get('odds_under', '')
                
                rows.append({
                    'game': game_name,
                    'market': market,
                    'player': player_name,
                    'line': line,
                    'odds_over': odds_over,
                    'odds_under': odds_under
                })
            
            log.info(f"  → Scraped {len(selections)} players")
            
            browser.close()
        
    except Exception as e:
        log.error(f"  → Error scraping {game_name}: {str(e)}")
    
    return rows


def main():
    # Get the directory of this script and navigate to parent directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    betmgm_dir = os.path.dirname(script_dir)
    scraper_dir = os.path.dirname(betmgm_dir)
    
    # Path to the betting links CSV file
    csv_file_path = os.path.join(scraper_dir, 'Links', 'betting_links_betmgm.csv')
    
    # Filter NBA event links
    filtered_links, code_prefixes, lowest_prefix = filter_nba_event_links(csv_file_path, nba_teams)
    
    # Add query parameter to filtered links
    filtered_links = [url + "?market=Players" for url in filtered_links]
    
    # log.info(f"Found {len(code_prefixes)} unique code prefixes (first 3 digits): {sorted(code_prefixes)}")
    # log.info(f"Lowest prefix code: {lowest_prefix}")
    # log.info(f"Found {len(filtered_links)} NBA event links with prefix {lowest_prefix}")
    
    # Randomize stealth mode parameters
    user_agent = random.choice(USER_AGENTS)
    header_dnt = random.choice(["0", "1"])
    location = random.choice(LOCATIONS)
    referer = random.choice(REFERERS)
    accept_language = random.choice(ACCEPT_LANGUAGES)
    
    log.info(f"Using stealth mode with location: {location[0]}")
    log.info(f"Processing {len(filtered_links)} NBA games...")
    
    # Define the AgentQL query
    POINTS_REBOUNDS_QUERY = """
    {
        points_rebounds[] {
            player_name
            line
            odds_over
            odds_under
        }
    }
    """
    
    # Extract market name from query (the array field name)
    market_match = re.search(r'(\w+)\[\]', POINTS_REBOUNDS_QUERY)
    market = market_match.group(1).replace('_', ' ') if market_match else "unknown"
    
    # Prepare browser configuration (each thread will create its own browser)
    browser_config = {
        'args': BROWSER_ARGS,
        'ignore_default_args': BROWSER_IGNORED_ARGS,
        'locale': "en-US,en",
        'timezone_id': location[0],
        'extra_http_headers': {
            "Accept-Language": accept_language,
            "Referer": referer,
            "DNT": header_dnt,
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate, br",
        },
        'geolocation': location[1],
        'user_agent': user_agent,
        'permissions': ["geolocation"],
        'viewport': {
            "width": 1920 + random.randint(-50, 50),
            "height": 1080 + random.randint(-50, 50),
        },
    }
    
    # Collect all rows from all games
    all_rows = []
    
    # Start timer
    start_time = time.time()
    
    # Use ThreadPoolExecutor for parallel scraping
    # Each thread will create its own browser instance
    max_workers = min(len(filtered_links), 6)  # Limit to 5 concurrent browsers to avoid resource issues
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all scraping tasks
        futures = {
            executor.submit(scrape_single_game, browser_config, URL, market, POINTS_REBOUNDS_QUERY): URL 
            for URL in filtered_links
        }
        
        # Collect results as they complete
        for future in as_completed(futures):
            try:
                rows = future.result()
                all_rows.extend(rows)
            except Exception as e:
                URL = futures[future]
                log.error(f"  → Thread error for {URL}: {str(e)}")
    
    # Calculate elapsed time
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = elapsed_time % 60
    
    log.info(f"\n{'='*60}")
    log.info(f"Scraping completed in {minutes}m {seconds:.2f}s")
    log.info(f"{'='*60}")
    
    # Save all data to CSV in Odds folder
    odds_dir = os.path.join(scraper_dir, 'Odds')
    os.makedirs(odds_dir, exist_ok=True)
    output_file = os.path.join(odds_dir, 'betmgm_nba.csv')
    
    # Read existing CSV data if file exists
    existing_rows = []
    if os.path.exists(output_file):
        with open(output_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)
    
    # Remove old entries for this market
    filtered_rows = [row for row in existing_rows if row.get('market', '') != market]
    
    # Combine filtered rows with new data
    final_rows = filtered_rows + all_rows
    
    # Write updated data to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['game', 'market', 'player', 'line', 'odds_over', 'odds_under']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final_rows)
    
    log.info(f"\nUpdated {len(all_rows)} player props for market '{market}' from {len(filtered_links)} games")
    log.info(f"Total rows in CSV: {len(final_rows)} (removed {len(existing_rows) - len(filtered_rows)} old entries for this market)")


if __name__ == "__main__":
    main()
