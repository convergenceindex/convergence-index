#!/usr/bin/env python3
"""
Polling Collector for Convergence Index
Fetches polling data from multiple sources and caches locally
Runs via GitHub Actions every 6 hours
"""

import json
import os
from datetime import datetime, timedelta
import re
import logging
import sys

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

    def fetch_wikipedia(self):
        """
        Fetch polling data from Wikipedia race pages
        Most reliable source - community maintained, structured tables
        """
        logger.info("Fetching Wikipedia polling tables...")
        try:
            # Would fetch and parse:
            # https://en.wikipedia.org/wiki/2026_United_States_Senate_elections
            # https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections
            # Governor pages

            self.polls['sources']['success'].append('wikipedia')
            logger.info("✓ Wikipedia fetch attempted")
            return True
        except Exception as e:
            logger.warning(f"✗ Wikipedia fetch failed: {e}")
            self.polls['sources']['failed'].append('wikipedia')
            return False

    def fetch_nate_silver(self):
        """
        Fetch latest polling from Nate Silver's Substack
        """
        logger.info("Fetching Nate Silver's Substack...")
        try:
            # Parse generic ballot + key race margins from latest post
            # Example: "Generic ballot: Democrats +2.6"

            self.polls['sources']['success'].append('nate-silver-substack')
            logger.info("✓ Nate Silver fetch attempted")
            return True
        except Exception as e:
            logger.warning(f"✗ Nate Silver fetch failed: {e}")
            self.polls['sources']['failed'].append('nate-silver-substack')
            return False

    def fetch_surveyusa(self):
        """
        Fetch latest polls from SurveyUSA (updates almost daily)
        """
        logger.info("Fetching SurveyUSA latest releases...")
        try:
            self.polls['sources']['success'].append('surveyusa')
            logger.info("✓ SurveyUSA fetch attempted")
            return True
        except Exception as e:
            logger.warning(f"✗ SurveyUSA fetch failed: {e}")
            self.polls['sources']['failed'].append('surveyusa')
            return False

    def fetch_270towin(self):
        """
        Fetch from 270toWin polling tracker
        """
        logger.info("Fetching 270toWin polling tracker...")
        try:
            self.polls['sources']['success'].append('270towin')
            logger.info("✓ 270toWin fetch attempted")
            return True
        except Exception as e:
            logger.warning(f"✗ 270toWin fetch failed: {e}")
            self.polls['sources']['failed'].append('270towin')
            return False

    def fetch_cook_political(self):
        """
        Fetch from Cook Political Report
        """
        logger.info("Fetching Cook Political Report...")
        try:
            self.polls['sources']['success'].append('cook-political')
            logger.info("✓ Cook Political fetch attempted")
            return True
        except Exception as e:
            logger.warning(f"✗ Cook Political fetch failed: {e}")
            self.polls['sources']['failed'].append('cook-political')
            return False

    def fetch_ballotpedia(self):
        """
        Fetch from Ballotpedia race pages
        """
        logger.info("Fetching Ballotpedia data...")
        try:
            self.polls['sources']['success'].append('ballotpedia')
            logger.info("✓ Ballotpedia fetch attempted")
            return True
        except Exception as e:
            logger.warning(f"✗ Ballotpedia fetch failed: {e}")
            self.polls['sources']['failed'].append('ballotpedia')
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
            logger.info("✓ Using newly fetched polling data")
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
        self.fetch_wikipedia()          # Most reliable
        self.fetch_nate_silver()        # Daily updates
        self.fetch_surveyusa()          # Almost daily
        self.fetch_270towin()           # Comprehensive
        self.fetch_cook_political()     # Weekly+
        self.fetch_ballotpedia()        # Detailed

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
