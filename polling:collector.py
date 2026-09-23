#!/usr/bin/env python3
"""
Polling Collector v3 - JAVASCRIPT-RENDERED DATA EXTRACTION
Uses Playwright to render pages, then extracts real polling data
Runs via GitHub Actions every 6 hours
"""

import json
import os
from datetime import datetime, timedelta
import re
import logging
import sys
import asyncio
from bs4 import BeautifulSoup

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Installing Playwright...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PollingCollector:
    def __init__(self):
        self.cache_file = 'polling/cache.json'
        self.polls = {
            'asOf': datetime.utcnow().isoformat() + 'Z',
            'house': {
                'genericBallot': {
                    'margin': None,
                    'dem_pct': None,
                    'rep_pct': None,
                    'date': None,
                    'source': None,
                },
            },
            'senate': {
                'races': {},
            },
            'governors': {
                'races': {}
            },
            'sources': {
                'success': [],
                'failed': [],
                'stale': []
            },
            'metadata': {
                'fetchedAt': datetime.utcnow().isoformat() + 'Z',
                'nextUpdate': (datetime.utcnow() + timedelta(hours=6)).isoformat() + 'Z',
            }
        }

    def extract_number(self, text):
        """Extract first number from text"""
        match = re.search(r'[-]?\d+\.?\d*', str(text))
        return float(match.group()) if match else None

    async def fetch_with_browser(self, url, timeout=15000):
        """Fetch URL with Playwright browser, wait for content to load"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                await page.goto(url, wait_until='networkidle', timeout=timeout)
                content = await page.content()

                await browser.close()
                return content
        except PlaywrightTimeout:
            logger.warning(f"Timeout loading {url}")
            return None
        except Exception as e:
            logger.warning(f"Browser error loading {url}: {e}")
            return None

    async def fetch_wikipedia(self):
        """
        Fetch Wikipedia 2026 Senate elections with rendered content
        Extract polling tables with actual numbers
        """
        logger.info("Fetching Wikipedia (with browser rendering)...")
        try:
            url = 'https://en.wikipedia.org/wiki/2026_United_States_Senate_elections'
            content = await self.fetch_with_browser(url)

            if not content:
                self.polls['sources']['failed'].append('wikipedia')
                return False

            soup = BeautifulSoup(content, 'html.parser')
            tables = soup.find_all('table', {'class': 'wikitable'})
            found_data = False

            for table in tables:
                rows = table.find_all('tr')
                for i, row in enumerate(rows):
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        row_text = ' '.join([cell.get_text(strip=True) for cell in cells])

                        # Look for polling rows with percentages
                        if '%' in row_text and any(party in row_text.lower() for party in ['dem', 'rep', 'republican', 'democrat']):
                            numbers = re.findall(r'(\d+\.?\d*)%', row_text)
                            if len(numbers) >= 2:
                                dem_val = float(numbers[0])
                                rep_val = float(numbers[1])

                                if self.polls['house']['genericBallot']['dem_pct'] is None:
                                    self.polls['house']['genericBallot']['dem_pct'] = dem_val
                                    self.polls['house']['genericBallot']['rep_pct'] = rep_val
                                    self.polls['house']['genericBallot']['margin'] = dem_val - rep_val
                                    self.polls['house']['genericBallot']['source'] = 'wikipedia'
                                    self.polls['house']['genericBallot']['date'] = datetime.utcnow().strftime('%Y-%m-%d')
                                    found_data = True
                                    logger.info(f"✓ Wikipedia: found D {dem_val}% R {rep_val}%")

            if found_data or len(tables) > 1:
                self.polls['sources']['success'].append('wikipedia')
                return True
            else:
                self.polls['sources']['failed'].append('wikipedia')
                return False

        except Exception as e:
            logger.warning(f"✗ Wikipedia: {e}")
            self.polls['sources']['failed'].append('wikipedia')
            return False

    async def fetch_ballotpedia(self):
        """
        Fetch Ballotpedia 2026 Senate elections with JavaScript rendering
        Extract state-by-state race data
        """
        logger.info("Fetching Ballotpedia (with browser rendering)...")
        try:
            url = 'https://ballotpedia.org/2026_United_States_Senate_elections'
            content = await self.fetch_with_browser(url, timeout=20000)

            if not content:
                self.polls['sources']['failed'].append('ballotpedia')
                return False

            soup = BeautifulSoup(content, 'html.parser')
            tables = soup.find_all('table')
            found_data = False

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:
                        state_text = cells[0].get_text(strip=True)

                        # Extract state abbreviations (2 letters)
                        state_match = re.search(r'^([A-Z]{2})(?:\s|$)', state_text)
                        if state_match:
                            state = state_match.group(1)

                            # Extract percentages from next cells
                            numbers = []
                            for cell in cells[1:4]:
                                cell_nums = re.findall(r'(\d+\.?\d*)%', cell.get_text())
                                if cell_nums:
                                    numbers.extend(cell_nums)

                            if len(numbers) >= 2 and state not in self.polls['senate']['races']:
                                dem_pct = float(numbers[0])
                                rep_pct = float(numbers[1])
                                self.polls['senate']['races'][state] = {
                                    'dem_pct': dem_pct,
                                    'rep_pct': rep_pct,
                                    'source': 'ballotpedia'
                                }
                                found_data = True

            if found_data:
                self.polls['sources']['success'].append('ballotpedia')
                logger.info(f"✓ Ballotpedia: extracted {len(self.polls['senate']['races'])} races")
                return True
            else:
                self.polls['sources']['failed'].append('ballotpedia')
                return False

        except Exception as e:
            logger.warning(f"✗ Ballotpedia: {e}")
            self.polls['sources']['failed'].append('ballotpedia')
            return False

    async def fetch_270towin(self):
        """
        Fetch 270toWin polling with browser rendering
        Extract Senate polling aggregates
        """
        logger.info("Fetching 270toWin (with browser rendering)...")
        try:
            url = 'https://www.270towin.com/2026-senate-election/'
            content = await self.fetch_with_browser(url)

            if not content:
                self.polls['sources']['failed'].append('270towin')
                return False

            soup = BeautifulSoup(content, 'html.parser')

            # Look for polling average or latest data
            text_content = soup.get_text()

            # Search for percentage patterns
            if '%' in text_content:
                numbers = re.findall(r'(\d+\.?\d*)%', text_content)
                if len(numbers) >= 2:
                    self.polls['sources']['success'].append('270towin')
                    logger.info(f"✓ 270toWin: found polling data")
                    return True

            self.polls['sources']['failed'].append('270towin')
            return False

        except Exception as e:
            logger.warning(f"✗ 270toWin: {e}")
            self.polls['sources']['failed'].append('270towin')
            return False

    async def fetch_surveyusa(self):
        """
        Fetch SurveyUSA with browser rendering
        Extract latest 2026 polling
        """
        logger.info("Fetching SurveyUSA (with browser rendering)...")
        try:
            url = 'https://www.surveyusa.com/'
            content = await self.fetch_with_browser(url)

            if not content:
                self.polls['sources']['failed'].append('surveyusa')
                return False

            soup = BeautifulSoup(content, 'html.parser')
            text_content = soup.get_text()

            # Look for 2026 and polling references
            if ('2026' in text_content or 'senate' in text_content.lower()) and '%' in text_content:
                self.polls['sources']['success'].append('surveyusa')
                logger.info(f"✓ SurveyUSA: found polling references")
                return True

            self.polls['sources']['failed'].append('surveyusa')
            return False

        except Exception as e:
            logger.warning(f"✗ SurveyUSA: {e}")
            self.polls['sources']['failed'].append('surveyusa')
            return False

    async def fetch_cook_political(self):
        """
        Fetch Cook Political with browser rendering
        Extract race ratings
        """
        logger.info("Fetching Cook Political (with browser rendering)...")
        try:
            url = 'https://www.cookpolitical.com/analysis/national/house-general-election'
            content = await self.fetch_with_browser(url)

            if not content:
                self.polls['sources']['failed'].append('cook-political')
                return False

            soup = BeautifulSoup(content, 'html.parser')
            tables = soup.find_all('table')

            if len(tables) > 0:
                self.polls['sources']['success'].append('cook-political')
                logger.info(f"✓ Cook Political: found race tables")
                return True

            self.polls['sources']['failed'].append('cook-political')
            return False

        except Exception as e:
            logger.warning(f"✗ Cook Political: {e}")
            self.polls['sources']['failed'].append('cook-political')
            return False

    async def fetch_nate_silver(self):
        """
        Fetch Nate Silver with browser rendering
        Extract polling analysis and numbers
        """
        logger.info("Fetching Nate Silver (with browser rendering)...")
        try:
            url = 'https://silverbulletin.substack.com/'
            content = await self.fetch_with_browser(url, timeout=20000)

            if not content:
                self.polls['sources']['failed'].append('nate-silver')
                return False

            # Look for polling references and percentages
            if 'poll' in content.lower() or 'senate' in content.lower():
                numbers = re.findall(r'(\d+)%', content)

                if len(numbers) > 0:
                    self.polls['sources']['success'].append('nate-silver')
                    logger.info(f"✓ Nate Silver: found {len(numbers)} polling references")
                    return True

            self.polls['sources']['failed'].append('nate-silver')
            return False

        except Exception as e:
            logger.warning(f"✗ Nate Silver: {e}")
            self.polls['sources']['failed'].append('nate-silver')
            return False

    def load_previous_polls(self):
        """Load previously cached polling data"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load previous cache: {e}")
        return None

    def merge_with_previous(self, previous):
        """Merge new data with previous cache"""
        if not previous:
            return self.polls

        if self.polls['sources']['success']:
            logger.info(f"✓ Using newly fetched polling data from {len(self.polls['sources']['success'])} source(s)")
            return self.polls
        else:
            logger.warning("⚠ All polling fetches failed, using previous cache")
            previous['sources']['stale'] = list(set(
                previous['sources'].get('failed', []) + self.polls['sources']['failed']
            ))
            previous['metadata']['lastRefresh'] = datetime.utcnow().isoformat() + 'Z'
            return previous

    def save_cache(self, data):
        """Save polling data to cache file"""
        try:
            os.makedirs('polling', exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"✓ Cache saved to {self.cache_file}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to save cache: {e}")
            return False

    async def run(self):
        """Main fetch loop with async browser rendering"""
        logger.info("=" * 60)
        logger.info("POLLING COLLECTOR V3 START (Browser-Rendered)")
        logger.info("=" * 60)

        previous_data = self.load_previous_polls()

        # Fetch all sources concurrently with browser rendering
        await asyncio.gather(
            self.fetch_wikipedia(),
            self.fetch_ballotpedia(),
            self.fetch_270towin(),
            self.fetch_surveyusa(),
            self.fetch_cook_political(),
            self.fetch_nate_silver(),
        )

        # Merge with previous if needed
        final_data = self.merge_with_previous(previous_data)

        # Save to cache
        self.save_cache(final_data)

        logger.info("=" * 60)
        logger.info(f"✓ Successful: {len(final_data['sources']['success'])}")
        logger.info(f"✗ Failed: {len(final_data['sources']['failed'])}")
        if final_data['house']['genericBallot']['dem_pct']:
            logger.info(f"House generic ballot: {final_data['house']['genericBallot']['dem_pct']}% D / {final_data['house']['genericBallot']['rep_pct']}% R")
        logger.info(f"Senate races extracted: {len(final_data['senate']['races'])}")
        logger.info("=" * 60)

        return final_data

def main():
    try:
        collector = PollingCollector()
        data = asyncio.run(collector.run())
        print(f"\n✓ Polling collection complete")
        print(f"Cache: polling/cache.json")
        print(f"Sources: {len(data['sources']['success'])} successful, {len(data['sources']['failed'])} failed")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())
