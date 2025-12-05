import agentql
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

URL = "https://sportsbook.fanduel.com/basketball/nba/dallas-mavericks-@-oklahoma-city-thunder-35024521?tab=player-rebounds"


INTERACTION_QUERY = """
{
    player_rebounds_header(name: "Player Rebounds")
}
"""

STRUCTURE_QUERY = """
{
    player_rebounds_section {
        section_title
        all_text_elements[] {
            text_content
        }
    }
}
"""

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        page = context.new_page()
        aql_page = agentql.wrap(page)

        log.info(f"Opening {URL}")
        aql_page.goto(URL)

        # --- MANUAL CHECKPOINT ---
        print("\n" + "="*50)
        print("ACTION REQUIRED:")
        print("1. Clear the 'Press & Hold' check.")
        print("2. Navigate to the specific game page.")
        print("3. Ensure you see the 'Player Rebounds' header (even if collapsed).")
        input("Press ENTER to execute the toggle and scrape...")
        print("="*50 + "\n")

        # 1. TOGGLE ACCORDION
        log.info("Toggling 'Player Rebounds'...")
        try:
            interaction = aql_page.query_elements(INTERACTION_QUERY)
            if interaction.player_rebounds_header:
                interaction.player_rebounds_header.click()
                log.info("Clicked header. Waiting 4 seconds for DOM update...")
                # Generous wait time to ensure the new HTML nodes are fully mounted
                aql_page.wait_for_timeout(4000) 
            else:
                log.warning("Header not found via AgentQL. Proceeding assuming it might be open...")
        except Exception as e:
            log.error(f"Interaction failed: {e}")

        # 2. GRAB STRUCTURE
        log.info("Capturing section structure...")
        data = aql_page.query_data(STRUCTURE_QUERY)

        with open('structure_dump.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        log.info("Saved structure to 'structure_dump.json'.")
        browser.close()

if __name__ == "__main__":
    main()