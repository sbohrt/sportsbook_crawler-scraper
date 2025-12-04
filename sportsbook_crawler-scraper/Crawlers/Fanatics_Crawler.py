#NOTE: UNCHANGED FROM BETMGM FOR NOW, JUST CREATED FILE

import asyncio
import json
import re
import csv
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from collections import defaultdict
from urllib.parse import urljoin, urlparse


class SportsbookLinkScraper:    #Class that contains logic which identifes sportsbook betting links from any sportsbook
    
    BETTING_URL_PATTERNS = [ #common sports book paths indicating betting pages
        r'/event/[\w-]+', #[\w-]+ represents one or more word characters, underscores, or hyphens (nba,lakers,game-12345)
        r'/game/[\w-]+', #d+ represents one or more digits (12345,999)
        r'/match/[\w-]+', #/ url forward slash
        r'/markets/\d+', #\? indicates a query parameter in the URL
        r'/fixtures/\d+',
        r'/competitions/[\w-]+',
        
        
        r'/(nba|nfl|mlb|nhl|ncaab|ncaaf)/[\w-]+/[\w-]+', #two path segments after sport like nba/lakers/celtics-game
        r'/(soccer|football|basketball|baseball|hockey|tennis|mma|ufc|boxing)/[\w-]+/[\w-]+', #same but not abbreviated
        
    
        r'/\d{4}/\d{2}/\d{2}/', #YYYY/MM/DD
        r'/\d{4}-\d{2}-\d{2}/', #{4} is 4 digits, {2} is 2 digits, / is for slashs and - is for hyphens
        
        r'/sports/[\w-]+/betting/', #betmgm specific (/sports/football/betting/)
        r'/en/sports/[\w-]+', #betmgm english sportsbook pages (/en/sports/football)
        
        r'/sportsbook/[\w-]+', #fanduel specific (sportsbook)
        
        
        r'/odds/[\w-]+', #all to cover generic patterns (odds,lines,betting)
        r'/lines/[\w-]+',
        r'/betting/[\w-]+',
    ]
    
    SKIP_PATTERNS = [
        r'/(login|register|account|profile|settings)',
        r'/(help|support|about|contact|careers|press)',
        r'/(terms|privacy|responsible|legal)',
        r'/(promotions|bonus|rewards|offers)',
        r'\.(css|js|json|xml|jpg|jpeg|png|gif|svg|ico|woff|woff2|ttf|eot)', #website resources (images,datafiles) garbage data we dont need
        r'/(api|cdn|static|assets|images|fonts)/',
        r'#',
        r'javascript:',
        r'mailto:',
        r'tel:',
    ]
    
    @classmethod
    def is_betting_link(cls, url):
        if not url or not isinstance(url, str): #checks if url is valid string
            return False
            
        url_lower = url.lower() #case insensitive matching changes to lowercase
        
        # skip non-betting pages
        for pattern in cls.SKIP_PATTERNS: #loops through each skip pattern one by one
            if re.search(pattern, url_lower): #re.search scans through the url for the skip pattern (like control F)
                return False
        
        # check for betting patterns
        for pattern in cls.BETTING_URL_PATTERNS: #loops through each betting pattern one by one
            if re.search(pattern, url_lower): #re.search scans through the url for the betting pattern (like control F)
                return True
        
        #sports keywords so guessing if the link has these keywords probably sports related
        sports = ['nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football', 'basketball', 
                  'baseball', 'hockey', 'tennis', 'mma', 'ufc', 'boxing']
        has_sport = any(sport in url_lower for sport in sports) #check if the url contains any of the sports keywords
        path_segments = len([p for p in urlparse(url_lower).path.split('/') if p]) #url gets parsed and split into segments 
        #only care about path which is the part after the domain (basketball/lakers/warriors)
        #split path into a list and counts how many segments there are (baskebtall,lakers,warriors = 3 segments)
        #so if the url has sports keywords and at least 3 path segments we assume its a betting link)
        if has_sport and path_segments >= 3:
            return True
        
        return False


async def scrape_sportsbook_fast(
    start_url,
    max_pages=50, #crawls 50 pages by default
    max_concurrent=10, #processes 10 urls at a time
    verbose=True #print msg to console
):

    
    if verbose:
        print(f"\n{'='*80}")
        print(f"FAST SCRAPING: {start_url}")
        print(f"Concurrency: {max_concurrent} | Max pages: {max_pages}")
        print(f"{'='*80}\n")
    
    # Minimal browser config for speed
    browser_config = BrowserConfig(  #creaate browser config object tell crawl4ai how to setup the browser
        browser_type="chromium", #use chromium browser
        headless=True, #invisible
        viewport_width=1920,
        viewport_height=1080, #1920x1080 resolution
        java_script_enabled=True, #let java script run on pages
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )#set user agent to mimic real browser so websites think we are regular chrome user not a bot
    
    # config for speed
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS, #fetch real data so skip cache and make real requests
        page_timeout=20000,  # wait max 20 sec per page to load
        wait_for="css:body", #wait until body tag is present, so make sure there is a page strucutre
        delay_before_return_html=1,  # Wait 1 sec for dynamic content
        exclude_external_links=False,  # get all links, we'll filter by domain later
        word_count_threshold=5, #filter out pages with less than 5 words garbage pages
        excluded_tags=["script", "style", "svg"],
        js_code=[
            "window.scrollTo(0, document.body.scrollHeight / 2);",
            "await new Promise(r => setTimeout(r, 500));", #scroll halfway down the page to trigger lazy loading
        ],
    )
    
    betting_links = [] #list to store found betting links
    visited = set() #set to track visited urls
    to_visit = [start_url] #list of urls to visit initialized with start url
    base_domain = urlparse(start_url).netloc # just extract domain name
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        
        while to_visit and len(visited) < max_pages: #start a loop visiting urls until no more to visit or max pages reached
            # Take batch of URLs
            batch = []
            while to_visit and len(batch) < max_concurrent: 
                url = to_visit.pop(0) #pop first url from to_visit list
                if url not in visited:
                    batch.append(url) #add url to batch if not visited
                    visited.add(url) #mark url as visited
            
            if not batch:
                break
            
            if verbose:
                print(f"Processing batch of {len(batch)} URLs (visited: {len(visited)}/{max_pages})")
            
            tasks = [crawler.arun(url=url, config=run_config) for url in batch] #create async tasks for each url in batch
            results = await asyncio.gather(*tasks, return_exceptions=True) #run tasks concurrently, continue even if one fails
            
            # results
            for url, result in zip(batch, results):
                if isinstance(result, Exception): #check if url is an exception object (error during fetch)
                    if verbose:
                        print(f"  Error on {url[:60]}: {str(result)[:50]}") #print error msg if verbose
                    continue
                
                if not result.success:
                    continue
                
                
                found_urls = set() #set to store found urls on this page
                
                
                if hasattr(result, 'links') and result.links: #check if result has links attribute
                    if hasattr(result.links, 'internal'): #hasattr checks if object has specific attribute
                        for link in result.links.internal: #check for internal links
                            href = link.get('href', '') #loop
                            if href:
                                found_urls.add(href)#extract url from link and add to found_urls set
                    if hasattr(result.links, 'external'):
                        for link in result.links.external:
                            href = link.get('href', '') #extract href 
                            if href and base_domain in href: #check if href exists
                                found_urls.add(href)
                
                
                if result.html:
                    for match in re.finditer(r'href=["\']([^"\']+)["\']', result.html): #regex to find all href attributes in html
                        link_url = match.group(1)
                        if link_url.startswith(('http://', 'https://')):
                            if base_domain in link_url:
                                found_urls.add(link_url) #add url to found_urls set
                        elif link_url.startswith('/'):
                            full_url = urljoin(url, link_url) #check if url is relative and convert to absolute (relative starts with /)
                            found_urls.add(full_url)
                
                # Process links
                new_betting = 0
                for found_url in found_urls:
                    # cleans the URL
                    found_url = found_url.split('#')[0].split('?')[0] #remove fragments (after #) and query params (after ?)
                    
                    if not found_url or found_url in visited: #skip url if empty or visited
                        continue
                    
                    
                    if urlparse(found_url).netloc != base_domain: #compare domain of found url to base domain
                        continue
                    
                    if SportsbookLinkScraper.is_betting_link(found_url): #check if found url is a betting link
                        if found_url not in [b['url'] for b in betting_links]: #avoid duplicates
                            betting_links.append({ #add to betting links list and page it was found on
                                'url': found_url,
                                'found_on': url
                            })
                            new_betting += 1
                        
                        if found_url not in visited and found_url not in to_visit: #check for repeats
                            to_visit.append(found_url) #add to to_visit list for future crawling
                
                if verbose and new_betting > 0:
                    print(f"  {url[:60]}: +{new_betting} links (total: {len(betting_links)})") #print new betting links found so it looks cool
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"COMPLETE - Visited {len(visited)} pages, found {len(betting_links)} betting links")
        print(f"{'='*80}\n")
    
    return betting_links


def save_to_csv(betting_links, filename='betting_links.csv'): #save links to csv file
    print(f"\n{'='*80}")
    print(f"FOUND {len(betting_links)} BETTING LINKS")
    print(f"{'='*80}\n")
    
    if not betting_links:
        print("No betting links found!\n") # if no links found just return
        return
    
    # save to CSV with single column
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['url'])  # create hader
        for link in betting_links:
            writer.writerow([link['url']])
    
    print(f"Saved {len(betting_links)} links to: {filename}") #print msg confirming save
    
    # save full data to JSON for reference
    json_filename = filename.replace('.csv', '.json')
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(betting_links, f, indent=2, ensure_ascii=False)
    
    print(f"Full data saved to: {json_filename}\n")
    
    # Print first 10 links as preview for looks
    print("Preview of links:")
    print("-" * 80)
    for i, link in enumerate(betting_links[:10], 1):
        print(f"{i}. {link['url']}")
    
    if len(betting_links) > 10:
        print(f"\n... and {len(betting_links) - 10} more links")
    print()


async def main():
    
    
    print("\nSPORTSBOOK LINK SCRAPER")
    
    
    start_url = "https://www.in.betmgm.com/en/sports"
    
    
    print(f"Target: {start_url}\n") #print which url about to scrape
    
    betting_links = await scrape_sportsbook_fast( #call scrape function wait for it to complete
        start_url=start_url,
        max_pages=50,           # max 50 
        max_concurrent=10,      # 10 requests at the same time
        verbose=True #enable verbose so progress is printed to console
    )
    
    save_to_csv(betting_links, filename='betting_links_fanatics.csv') #save links to csv file


if __name__ == "__main__": #check if script is run directly
    asyncio.run(main())
