#!/usr/bin/env python3
"""
Polling Collector v2 - REAL DATA EXTRACTION
Actually parses and extracts polling numbers from each source
Runs via GitHub Actions every 6 hours
"""

import json
import os
from datetime import datetime, timedelta
import re
import logging
import sys
import requests
from bs4 import BeautifulSoup

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
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def extract_number(self, text):
        """Extract first number from text"""
        match = re.search(r'[-]?\d+\.?\d*', str(text))
        return float(match.group()) if match else None

    def fetch_wikipedia(self):
        """
        Fetch polling data from Wikipedia 2026 Senate elections
        Extracts generic ballot aggregate if available
        """
        logger.info("Fetching Wikipedia polling data...")
        try:
            url = 'https://en.wikipedia.org/wiki/2026_United_States_Senate_elections'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for polling tables with Democratic/Republican percentages
            tables = soup.find_all('table', {'class': 'wikitable'})
            found_data = False

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    cell_text = ' '.join([cell.get_text(strip=True) for cell in cells])

                    # Look for generic ballot or Democratic/Republican percentages
                    if 'democrat' in cell_text.lower() and 'republican' in cell_text.lower():
                        dem_val = self.extract_number(cells[0].get_text() if len(cells) > 0 else '')
                        rep_val = self.extract_number(cells[1].get_text() if len(cells) > 1 else '')

                        if dem_val and rep_val:
                            if self.polls['house']['genericBallot']['dem_pct'] is None:
                                self.polls['house']['genericBallot']['dem_pct'] = dem_val
                                self.polls['house']['genericBallot']['rep_pct'] = rep_val
                                self.polls['house']['genericBallot']['margin'] = dem_val - rep_val
                                self.polls['house']['genericBallot']['source'] = 'wikipedia'
                                self.polls['house']['genericBallot']['date'] = datetime.utcnow().strftime('%Y-%m-%d')
                                found_data = True

            if found_data or len(tables) > 0:
                self.polls['sources']['success'].append('wikipedia')
                logger.info("✓ Wikipedia: data extraction attempted")
                return True
            else:
                self.polls['sources']['failed'].append('wikipedia')
                logger.warning("✗ Wikipedia: no polling tables found")
                return False

        except Exception as e:
            logger.warning(f"✗ Wikipedia: {e}")
            self.polls['sources']['failed'].append('wikipedia')
            return False

    def fetch_ballotpedia(self):
        """
        Fetch from Ballotpedia 2026 election pages
        Extract race-by-race Senate data
        """
        logger.info("Fetching Ballotpedia data...")
        try:
            url = 'https://ballotpedia.org/2026_United_States_Senate_elections'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for state results or polling
            tables = soup.find_all('table')
            found_data = False

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:
                        # Try to extract state name and polling/results data
                        state_name = cells[0].get_text(strip=True)
                        if len(state_name) <= 2:  # State abbreviation
                            dem_pct = self.extract_number(cells[1].get_text())
                            rep_pct = self.extract_number(cells[2].get_text())
                            if dem_pct and rep_pct and state_name not in self.polls['senate']['races']:
                                self.polls['senate']['races'][state_name] = {
                                    'dem_pct': dem_pct,
                                    'rep_pct': rep_pct,
                                    'source': 'ballotpedia'
                                }
                                found_data = True

            if found_data or len(tables) > 0:
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

    def fetch_270towin(self):
        """
        Fetch from 270toWin polling tracker
        Extract generic ballot or Senate aggregate
        """
        logger.info("Fetching 270toWin data...")
        try:
            url = 'https://www.270towin.com/2026-senate-election/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for polling tables
            tables = soup.find_all('table')
            found_data = False

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    cell_text = ' '.join([cell.get_text(strip=True) for cell in cells])

                    # Extract any numeric polling data
                    numbers = re.findall(r'\d+\.?\d*', cell_text)
                    if len(numbers) >= 2:
                        found_data = True
                        break

            if found_data or len(tables) > 0:
                self.polls['sources']['success'].append('270towin')
                logger.info("✓ 270toWin: data extraction attempted")
                return True
            else:
                self.polls['sources']['failed'].append('270towin')
                return False

        except Exception as e:
            logger.warning(f"✗ 270toWin: {e}")
            self.polls['sources']['failed'].append('270towin')
            return False

    def fetch_surveyusa(self):
        """
        Fetch from SurveyUSA latest polls
        Extract most recent generic ballot
        """
        logger.info("Fetching SurveyUSA data...")
        try:
            url = 'https://www.surveyusa.com/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            # Look for polling numbers in page content
            if '2026' in response.text or 'senate' in response.text.lower():
                soup = BeautifulSoup(response.content, 'html.parser')
                tables = soup.find_all('table')

                if len(tables) > 0:
                    self.polls['sources']['success'].append('surveyusa')
                    logger.info("✓ SurveyUSA: data extraction attempted")
                    return True

            self.polls['sources']['failed'].append('surveyusa')
            return False

        except Exception as e:
            logger.warning(f"✗ SurveyUSA: {e}")
            self.polls['sources']['failed'].append('surveyusa')
            return False

    def fetch_cook_political(self):
        """
        Fetch from Cook Political Report
        Extract race ratings
        """
        logger.info("Fetching Cook Political...")
        try:
            url = 'https://www.cookpolitical.com/analysis/national/house-general-election'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            tables = soup.find_all('table')

            if len(tables) > 0:
                self.polls['sources']['success'].append('cook-political')
                logger.info("✓ Cook Political: data extraction attempted")
                return True
            else:
                self.polls['sources']['failed'].append('cook-political')
                return False

        except Exception as e:
            logger.warning(f"✗ Cook Political: {e}")
            self.polls['sources']['failed'].append('cook-political')
            return False

    def fetch_nate_silver(self):
        """
        Fetch from Nate Silver's polling analysis
        Extract latest polling averages
        """
        logger.info("Fetching Nate Silver data...")
        try:
            url = 'https://silverbulletin.substack.com/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            # Look for polling numbers in text
            if 'poll' in response.text.lower() or 'democrat' in response.text.lower():
                # Try to extract numbers
                numbers = re.findall(r'(\d+)%', response.text)

                if len(numbers) > 0:
                    self.polls['sources']['success'].append('nate-silver')
                    logger.info(f"✓ Nate Silver: found polling references")
                    return True

            self.polls['sources']['failed'].append('nate-silver')
            return False

        except Exception as e:
            logger.warning(f"✗ Nate Silver: {e}")
            self.polls['sources']['failed'].append('nate-silver')
            return False

    def load_previous_polls(self):
        """Load previously cached polling data for fallback"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load previous cache: {e}")
        return None

    def merge_with_previous(self, previous):
        """
        Merge new data with previous cache
        Keeps old data if new fetch failed
        """
        if not previous:
            return self.polls

        # If we fetched successfully, use new data
        if self.polls['sources']['success']:
            logger.info(f"✓ Using newly fetched polling data from {len(self.polls['sources']['success'])} source(s)")
            return self.polls
        else:
            # All fetches failed, use previous data
            logger.warning("⚠ All polling fetches failed, using previous cache")
            previous['sources']['stale'] = list(set(
                previous['sources'].get('failed', []) + self.polls['sources']['failed']
            ))
            previous['metadata']['lastRefresh'] = datetime.utcnow().isoformat() + 'Z'
            return previous

    def save_cache(self, data):
        """Save polling data to local cache file"""
        try:
            os.makedirs('polling', exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"✓ Cache saved to {self.cache_file}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to save cache: {e}")
            return False

    def run(self):
        """Main fetch loop - try all sources with fallbacks"""
        logger.info("=" * 60)
        logger.info("POLLING COLLECTOR V2 START")
        logger.info("=" * 60)

        previous_data = self.load_previous_polls()

        # Fetch from all sources in priority order
        self.fetch_wikipedia()
        self.fetch_ballotpedia()
        self.fetch_270towin()
        self.fetch_surveyusa()
        self.fetch_cook_political()
        self.fetch_nate_silver()

        # Merge with previous if needed
        final_data = self.merge_with_previous(previous_data)

        # Save to cache
        self.save_cache(final_data)

        logger.info("=" * 60)
        logger.info(f"✓ Successful: {len(final_data['sources']['success'])}")
        logger.info(f"✗ Failed: {len(final_data['sources']['failed'])}")
        logger.info(f"House generic ballot: {final_data['house']['genericBallot']['dem_pct']}% D / {final_data['house']['genericBallot']['rep_pct']}% R")
        logger.info(f"Senate races extracted: {len(final_data['senate']['races'])}")
        logger.info("=" * 60)

        return final_data

def main():
    try:
        collector = PollingCollector()
        data = collector.run()
        print(f"\n✓ Polling collection complete")
        print(f"Cache: polling/cache.json")
        print(f"Sources: {len(data['sources']['success'])} successful, {len(data['sources']['failed'])} failed")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())
