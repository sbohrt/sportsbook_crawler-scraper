import logging
import csv
import agentql
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

URL = "https://www.in.betmgm.com/en/sports/events/golden-state-warriors-at-philadelphia-76ers-18570747?market=Players:Rebound"

QUERY = """
{
    player_rebounds_over_under[] {
        player_name
        rebounds_line
        odds_over
        odds_under
    }
}
"""

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        aql_page = agentql.wrap(page)

        log.info(f"Opening {URL}")
        aql_page.goto(URL)

        # Wait for the page to load dynamic content
        aql_page.wait_for_timeout(6000)

        # Run AgentQL Query
        result = aql_page.query_data(QUERY)

        players = result.get("player_rebounds_over_under", [])

        # Build CSV rows
        rows_out = []
        for player in players:
                rows_out.append({
                    "player_name": player.get("player_name"),
                    "rebounds_line": player.get("rebounds_line"),
                    "odds_over": player.get("odds_over"),
                    "odds_under": player.get("odds_under"), 
                })

        # Save CSV
        output_file = "betmgm_rebounds.csv"
        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["player_name", "rebounds_line", "odds_over", "odds_under"]
            )
            writer.writeheader()
            writer.writerows(rows_out)

        log.info(f"Saved results to {output_file}")

        browser.close()

if __name__ == "__main__":
    main()
