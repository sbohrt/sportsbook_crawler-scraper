import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://www.in.betmgm.com/en/sports/events/indiana-pacers-at-chicago-bulls-18570097")
    await page.get_by_role("button", name="Players").click()
    await page.locator("ds-accordion").filter(has_text="Player points 10+ 15+ 20+ 25").get_by_label("Close Accordion").click()
    await page.locator("ds-accordion-header").filter(has_text="First field goal scorer").click()
    await page.locator("button").filter(has_text="Player points O/U").click()
    await page.locator(".right-icon > vn-icon > .ng-star-inserted > .fast-svg").click()

    # ---------------------
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
