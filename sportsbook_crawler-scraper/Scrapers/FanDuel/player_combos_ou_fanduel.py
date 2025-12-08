import csv
import logging
import agentql
from playwright.sync_api import sync_playwright

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

URL = "https://sportsbook.fanduel.com/basketball/nba/phoenix-suns-@-minnesota-timberwolves-35036256?tab=player-combos"

# QUERY 1: HEADERS ONLY (To open the accordions)
HEADER_QUERY = """
{
    market_accordions[] {
        header_text
        header_element
    }
}
"""

# QUERY 2: GLOBAL BUTTON SEARCH (Find ALL "Show more" buttons anywhere)
BUTTON_QUERY = """
{
    show_more_buttons[](text: "Show more")
}
"""

# QUERY 3: DATA EXTRACTION
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

def clean_line(text):
    if not text: 
        return ""
    return text.replace("O ", "").replace("U ", "").strip()

def force_click_fallback(page):
    """Hard fallback: Finds any element with text 'Show more' and clicks it."""
    try:
        # Get all elements with exact text "Show more"
        elements = page.get_by_text("Show more", exact=True).all()
        if not elements:
            return False
            
        log.info(f"FALLBACK: Found {len(elements)} 'Show more' buttons via text. Clicking...")
        
        # Click in reverse order (bottom to top) to prevent layout shifts hiding top buttons
        for i, element in enumerate(reversed(elements)):
            if element.is_visible():
                try:
                    element.click(timeout=1000)
                    page.wait_for_timeout(300)
                except Exception:
                    pass
        return True
    except Exception as e:
        log.warning(f"Fallback click failed: {e}")
        return False

def save_rows_to_csv(rows, filename, line_col_name):
    if not rows:
        return

    csv_rows = []
    for row in rows:
        p_name = row.get("player_name")
        line_val = clean_line(row.get("over_line_label"))
        o_odds = row.get("over_price")
        u_odds = row.get("under_price")

        if p_name and line_val:
            csv_rows.append({
                "player_name": p_name,
                line_col_name: line_val,
                "odds_over": o_odds,
                "odds_under": u_odds
            })

    if csv_rows:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["player_name", line_col_name, "odds_over", "odds_under"]
            )
            writer.writeheader()
            writer.writerows(csv_rows)
        log.info(f"Saved {len(csv_rows)} rows to {filename}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        aql_page = agentql.wrap(page)

        log.info(f"Opening URL: {URL}")
        aql_page.goto(URL)
        
        log.info("Waiting 8 seconds for page load...")
        page.wait_for_timeout(8000)

        # --- STEP 1: OPEN ACCORDION HEADERS ---
        log.info("Opening Accordions...")
        try:
            response = aql_page.query_elements(HEADER_QUERY)
            accordions = getattr(response, 'market_accordions', [])
            
            for acc in accordions:
                # Get text safely
                try:
                    raw_text = acc.header_text.text_content() if acc.header_text else ""
                    text = raw_text.lower()
                except:
                    text = ""

                # If it's a target combo header, click it
                if "pts" in text or "reb" in text or "ast" in text:
                    if acc.header_element:
                        try:
                            acc.header_element.click()
                            page.wait_for_timeout(300)
                        except:
                            pass
        except Exception as e:
            log.warning(f"Header step issue: {e}")

        # --- STEP 2: CLICK ALL 'SHOW MORE' BUTTONS (GLOBAL) ---
        log.info("Hunting for 'Show more' buttons...")
        page.wait_for_timeout(1000) # Wait for accordions to animate open
        
        clicked_any = False

        # Attempt A: AgentQL Global Query
        try:
            response = aql_page.query_elements(BUTTON_QUERY)
            buttons = getattr(response, 'show_more_buttons', [])
            if buttons:
                log.info(f"AgentQL found {len(buttons)} buttons. Clicking...")
                for btn in buttons:
                    try:
                        btn.click()
                        page.wait_for_timeout(500)
                        clicked_any = True
                    except:
                        pass
        except Exception:
            pass

        # Attempt B: Playwright Fallback (Most Reliable)
        if force_click_fallback(page):
            clicked_any = True

        if clicked_any:
            log.info("Buttons clicked. Waiting 4 seconds for lists to expand...")
            page.wait_for_timeout(4000)
        else:
            log.info("No 'Show more' buttons found/clicked (Lists might be short).")

        # --- STEP 3: EXTRACT DATA ---
        log.info("Extracting data...")
        data = aql_page.query_data(DATA_QUERY)
        
        market_accordions = data.get("market_accordions", [])
        
        for section in market_accordions:
            header = section.get("header_text", "")
            rows = section.get("rows", [])

            if not header:
                continue

            # Route based on header text
            if "Pts + Reb + Ast" in header:
                save_rows_to_csv(rows, "fanduel_pts_reb_ast.csv", "pra_line")
            elif "Pts + Reb" in header:
                save_rows_to_csv(rows, "fanduel_pts_reb.csv", "pr_line")
            elif "Pts + Ast" in header:
                save_rows_to_csv(rows, "fanduel_pts_ast.csv", "pa_line")
            elif "Reb + Ast" in header:
                save_rows_to_csv(rows, "fanduel_reb_ast.csv", "ra_line")
        
        log.info("Processing complete.")
        browser.close()

if __name__ == "__main__":
    main()