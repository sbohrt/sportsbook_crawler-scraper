import agentql
import csv
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

URL = "https://sportsbook.fanduel.com/basketball/nba/dallas-mavericks-@-oklahoma-city-thunder-35024521?tab=player-rebounds"

ACCORDION_QUERY = """
{
    rebounds_accordion_header(name: "Player Rebounds")
}
"""

# Updated to look for a LIST of buttons, not just one
SHOW_MORE_QUERY = """
{
    show_more_buttons[](text: "Show more")
}
"""

DATA_QUERY = """
{
    lines_section(name: "Player Rebounds") {
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

def clean_line(text):
    if not text: 
        return ""
    return text.replace("O ", "").replace("U ", "").strip()

def force_click_fallback(page, text_to_find):
    try:
        # We find ALL elements matching the text
        elements = page.get_by_text(text_to_find, exact=True).all()
        if not elements:
            return False
            
        log.info(f"FALLBACK: Found {len(elements)} instances of '{text_to_find}'. Clicking them all...")
        
        # Click them in reverse order (bottom up) to avoid layout shifts messing up the top ones
        for i, element in enumerate(reversed(elements)):
            if element.is_visible():
                element.click()
                log.info(f"Clicked instance {i+1}")
                page.wait_for_timeout(500) # Small pause between clicks
        return True
    except Exception as e:
        log.warning(f"Fallback click failed: {e}")
        return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        page = context.new_page()
        aql_page = agentql.wrap(page)

        log.info(f"Opening {URL}")
        aql_page.goto(URL)

        print("\n" + "="*50)
        print("CHECKPOINT: If you see 'Press & Hold', click it manually.")
        input("Press ENTER once the Page is loaded (Bot check passed)...")
        print("="*50 + "\n")

        # --- STEP 1: OPEN ACCORDION ---
        log.info("Attempting to open Accordion...")
        try:
            response = aql_page.query_elements(ACCORDION_QUERY)
            if response.rebounds_accordion_header:
                response.rebounds_accordion_header.click()
            else:
                raise Exception("AgentQL header miss")
        except Exception:
            # Fallback will click the generic "Player Rebounds" text
            # We use .last inside the helper to target the bottom accordion
            try:
                page.get_by_text("Player Rebounds", exact=True).last.click()
            except:
                pass
        
        aql_page.wait_for_timeout(2000)

        # --- STEP 2: CLICK *ALL* SHOW MORE BUTTONS ---
        log.info("Checking for multiple 'Show more' buttons...")
        
        clicked_any = False
        
        # Method A: AgentQL (Smart find)
        try:
            response = aql_page.query_elements(SHOW_MORE_QUERY)
            buttons = response.show_more_buttons
            if buttons:
                log.info(f"AgentQL found {len(buttons)} 'Show more' buttons.")
                for btn in buttons:
                    btn.click()
                    aql_page.wait_for_timeout(500)
                clicked_any = True
        except Exception:
            pass
            
        # Method B: Fallback (Dumb text search)
        # Always run this just in case AgentQL missed one
        if force_click_fallback(page, "Show more"):
            clicked_any = True

        if clicked_any:
            log.info("Waiting 3 seconds for lists to expand...")
            aql_page.wait_for_timeout(3000)

        # --- STEP 3: EXTRACT DATA ---
        log.info("Querying data...")
        result = aql_page.query_data(DATA_QUERY)
        
        section = result.get("lines_section")
        rows = section.get("rows", []) if section else []

        csv_rows = []
        for row in rows:
            p_name = row.get("player_name")
            line_val = clean_line(row.get("over_line_label"))
            o_odds = row.get("over_price")
            u_odds = row.get("under_price")

            if p_name and line_val:
                csv_rows.append({
                    "player_name": p_name,
                    "rebounds_line": line_val,
                    "odds_over": o_odds,
                    "odds_under": u_odds
                })

        output_file = "fanduel_rebounds.csv"
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["player_name", "rebounds_line", "odds_over", "odds_under"]
            )
            writer.writeheader()
            writer.writerows(csv_rows)

        log.info(f"Successfully saved {len(csv_rows)} rows to {output_file}")
        browser.close()

if __name__ == "__main__":
    main()