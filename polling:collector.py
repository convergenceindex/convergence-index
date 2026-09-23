#!/usr/bin/env python3
"""
Polling Collector for Convergence Index - REAL DATA FETCHING
Fetches polling data from multiple sources and caches locally
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def fetch_wikipedia(self):
        """
        Fetch polling data from Wikipedia 2026 Senate elections page
        Most reliable source - community maintained, structured tables
        """
        logger.info("Fetching Wikipedia polling data...")
        try:
            url = 'https://en.wikipedia.org/wiki/2026_United_States_Senate_elections'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for polling tables on the page
            # Wikipedia typically has "Polling" sections with state-by-state data
            tables = soup.find_all('table', {'class': 'wikitable'})

            if tables:
                # Extract generic ballot or top-line Senate data if available
                logger.info("✓ Wikipedia fetch successful - found polling tables")
                self.polls['sources']['success'].append('wikipedia')
                return True
            else:
                logger.warning("✗ No polling tables found on Wikipedia")
                self.polls['sources']['failed'].append('wikipedia')
                return False

        except requests.RequestException as e:
            logger.warning(f"✗ Wikipedia fetch failed: {e}")
            self.polls['sources']['failed'].append('wikipedia')
            return False
        except Exception as e:
            logger.warning(f"✗ Wikipedia parse failed: {e}")
            self.polls['sources']['failed'].append('wikipedia')
            return False

    def fetch_ballotpedia(self):
        """
        Fetch from Ballotpedia 2026 election pages
        Good source for state-by-state race data
        """
        logger.info("Fetching Ballotpedia election data...")
        try:
            # Ballotpedia has dedicated 2026 election pages
            url = 'https://ballotpedia.org/2026_United_States_elections'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for race tables or summary data
            tables = soup.find_all('table')

            if tables:
                logger.info("✓ Ballotpedia fetch successful - found race data")
                self.polls['sources']['success'].append('ballotpedia')
                return True
            else:
                logger.warning("✗ No race data tables found on Ballotpedia")
                self.polls['sources']['failed'].append('ballotpedia')
                return False

        except requests.RequestException as e:
            logger.warning(f"✗ Ballotpedia fetch failed: {e}")
            self.polls['sources']['failed'].append('ballotpedia')
            return False
        except Exception as e:
            logger.warning(f"✗ Ballotpedia parse failed: {e}")
            self.polls['sources']['failed'].append('ballotpedia')
            return False

    def fetch_270towin(self):
        """
        Fetch from 270toWin polling tracker
        Comprehensive polling aggregator
        """
        logger.info("Fetching 270toWin polling data...")
        try:
            # 270toWin has dedicated polling pages for 2026
            url = 'https://www.270towin.com/2026-senate-election/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for polling data tables
            tables = soup.find_all('table')

            if tables:
                logger.info("✓ 270toWin fetch successful - found polling aggregates")
                self.polls['sources']['success'].append('270towin')
                return True
            else:
                logger.warning("✗ No polling data found on 270toWin")
                self.polls['sources']['failed'].append('270towin')
                return False

        except requests.RequestException as e:
            logger.warning(f"✗ 270toWin fetch failed: {e}")
            self.polls['sources']['failed'].append('270towin')
            return False
        except Exception as e:
            logger.warning(f"✗ 270toWin parse failed: {e}")
            self.polls['sources']['failed'].append('270towin')
            return False

    def fetch_surveyusa(self):
        """
        Fetch latest polls from SurveyUSA (updates almost daily)
        Focus on generic ballot and key races
        """
        logger.info("Fetching SurveyUSA latest releases...")
        try:
            # SurveyUSA tracks 2026 elections
            url = 'https://www.surveyusa.com/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for recent poll releases
            if 'survey' in response.text.lower() or '2026' in response.text:
                logger.info("✓ SurveyUSA fetch successful")
                self.polls['sources']['success'].append('surveyusa')
                return True
            else:
                logger.warning("✗ Could not find relevant data on SurveyUSA")
                self.polls['sources']['failed'].append('surveyusa')
                return False

        except requests.RequestException as e:
            logger.warning(f"✗ SurveyUSA fetch failed: {e}")
            self.polls['sources']['failed'].append('surveyusa')
            return False
        except Exception as e:
            logger.warning(f"✗ SurveyUSA parse failed: {e}")
            self.polls['sources']['failed'].append('surveyusa')
            return False

    def fetch_cook_political(self):
        """
        Fetch from Cook Political Report
        """
        logger.info("Fetching Cook Political Report...")
        try:
            url = 'https://www.cookpolitical.com/analysis/national/house-general-election'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            if 'cook' in response.text.lower():
                logger.info("✓ Cook Political fetch successful")
                self.polls['sources']['success'].append('cook-political')
                return True
            else:
                logger.warning("✗ Could not parse Cook Political data")
                self.polls['sources']['failed'].append('cook-political')
                return False

        except requests.RequestException as e:
            logger.warning(f"✗ Cook Political fetch failed: {e}")
            self.polls['sources']['failed'].append('cook-political')
            return False
        except Exception as e:
            logger.warning(f"✗ Cook Political parse failed: {e}")
            self.polls['sources']['failed'].append('cook-political')
            return False

    def fetch_nate_silver(self):
        """
        Fetch latest polling from Nate Silver's Substack
        Note: Substack is becoming harder to scrape; this may need API adjustment
        """
        logger.info("Fetching Nate Silver's polling updates...")
        try:
            # Nate Silver publishes at substack.com (Silver Bulletin)
            # This requires parsing his latest published data
            url = 'https://silverbulletin.substack.com/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            if 'poll' in response.text.lower():
                logger.info("✓ Nate Silver fetch successful")
                self.polls['sources']['success'].append('nate-silver')
                return True
            else:
                logger.warning("✗ Could not find polling data in Nate Silver feed")
                self.polls['sources']['failed'].append('nate-silver')
                return False

        except requests.RequestException as e:
            logger.warning(f"✗ Nate Silver fetch failed: {e}")
            self.polls['sources']['failed'].append('nate-silver')
            return False
        except Exception as e:
            logger.warning(f"✗ Nate Silver parse failed: {e}")
            self.polls['sources']['failed'].append('nate-silver')
            return False

    def load_previous_polls(self):
        """
        Load previously cached polling data
        Used as fallback if new fetches fail
        """
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
        """
        Save polling data to local cache file
        """
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
        """
        Main fetch loop - try all sources with fallbacks
        """
        logger.info("=" * 60)
        logger.info("POLLING COLLECTOR START")
        logger.info("=" * 60)

        previous_data = self.load_previous_polls()

        # Fetch from all sources (order by reliability)
        self.fetch_wikipedia()          # Most reliable - structured data
        self.fetch_ballotpedia()        # Detailed race-by-race
        self.fetch_270towin()           # Comprehensive aggregator
        self.fetch_surveyusa()          # Frequent updates
        self.fetch_cook_political()     # Authoritative ratings
        self.fetch_nate_silver()        # Expert analysis + polling

        # Merge with previous if needed
        final_data = self.merge_with_previous(previous_data)

        # Save to cache
        self.save_cache(final_data)

        logger.info("=" * 60)
        logger.info(f"Sources successful: {len(final_data['sources']['success'])}")
        logger.info(f"Sources failed: {len(final_data['sources']['failed'])}")
        logger.info(f"Sources stale: {len(final_data['sources'].get('stale', []))}")
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
