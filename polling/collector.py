#!/usr/bin/env python3
"""
Aggregated Polling & Markets Collector
Fetches published polling averages from multiple sources + PredictIt markets
Combines into single blended forecast
Sustainable: falls back to cache if any source fails
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

class AggregatedCollector:
    def __init__(self):
        self.cache_file = 'polling/cache.json'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.polling_sources = []
        self.market_sources = []

    # ============================================================================
    # POLLING SOURCES - Fetch Published Averages
    # ============================================================================

    def fetch_realclearpolls_average(self):
        """
        Fetch RealClearPolitics generic ballot average
        RCP publishes their polling average on the main page
        """
        logger.info("Fetching RealClearPolitics polling average...")
        try:
            url = 'https://www.realclearpolling.com/latest-polls/2026'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()

            # Look for generic ballot percentages
            # RCP format: "Democrats X% Republicans Y%"
            matches = re.findall(r'Democrats?\s+(\d+\.?\d*)%.*?Republicans?\s+(\d+\.?\d*)%', text, re.IGNORECASE)

            if matches:
                dem_pct = float(matches[0][0])
                rep_pct = float(matches[0][1])
                logger.info(f"✓ RCP Average: D {dem_pct}% R {rep_pct}%")
                self.polling_sources.append({
                    'source': 'realclearpolitics',
                    'dem_pct': dem_pct,
                    'rep_pct': rep_pct,
                    'margin': dem_pct - rep_pct
                })
                return True
            else:
                logger.warning("✗ RCP: Could not extract average")
                return False
        except Exception as e:
            logger.warning(f"✗ RCP: {e}")
            return False

    def fetch_270towin_average(self):
        """
        Fetch 270toWin polling average
        """
        logger.info("Fetching 270toWin polling average...")
        try:
            url = 'https://www.270towin.com/2026-generic-ballot/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()

            # Look for polling average numbers
            if '2026' in text and '%' in text:
                numbers = re.findall(r'(\d+\.?\d*)%', text)
                if len(numbers) >= 2:
                    dem_pct = float(numbers[0])
                    rep_pct = float(numbers[1])
                    logger.info(f"✓ 270toWin Average: D {dem_pct}% R {rep_pct}%")
                    self.polling_sources.append({
                        'source': '270towin',
                        'dem_pct': dem_pct,
                        'rep_pct': rep_pct,
                        'margin': dem_pct - rep_pct
                    })
                    return True

            logger.warning("✗ 270toWin: Could not extract average")
            return False
        except Exception as e:
            logger.warning(f"✗ 270toWin: {e}")
            return False

    def fetch_deciskhq_average(self):
        """
        Fetch Decision Desk HQ polling average/forecast
        """
        logger.info("Fetching Decision Desk HQ average...")
        try:
            url = 'https://votes.decisiondeskhq.com/forecast/2026'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()

            # Look for percentage data in forecast
            if 'house' in text.lower() and '%' in text:
                numbers = re.findall(r'(\d+\.?\d*)%', text)
                if len(numbers) >= 2:
                    dem_pct = float(numbers[0])
                    rep_pct = float(numbers[1])
                    logger.info(f"✓ Decision Desk HQ: D {dem_pct}% R {rep_pct}%")
                    self.polling_sources.append({
                        'source': 'deciskhq',
                        'dem_pct': dem_pct,
                        'rep_pct': rep_pct,
                        'margin': dem_pct - rep_pct
                    })
                    return True

            logger.warning("✗ Decision Desk HQ: Could not extract data")
            return False
        except Exception as e:
            logger.warning(f"✗ Decision Desk HQ: {e}")
            return False

    def fetch_us_polling_data(self):
        """
        Fetch from US Polling Data aggregator
        """
        logger.info("Fetching US Polling Data aggregator...")
        try:
            url = 'https://uspollingdata.com/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()

            # Look for generic ballot aggregate
            if '2026' in text or 'generic' in text.lower():
                numbers = re.findall(r'(\d+\.?\d*)%', text)
                if len(numbers) >= 2:
                    dem_pct = float(numbers[0])
                    rep_pct = float(numbers[1])
                    logger.info(f"✓ US Polling Data: D {dem_pct}% R {rep_pct}%")
                    self.polling_sources.append({
                        'source': 'uspollingdata',
                        'dem_pct': dem_pct,
                        'rep_pct': rep_pct,
                        'margin': dem_pct - rep_pct
                    })
                    return True

            logger.warning("✗ US Polling Data: Could not extract")
            return False
        except Exception as e:
            logger.warning(f"✗ US Polling Data: {e}")
            return False

    # ============================================================================
    # MARKET SOURCES
    # ============================================================================

    def fetch_predictit_markets(self):
        """
        Fetch PredictIt market odds for House/Senate control
        """
        logger.info("Fetching PredictIt market odds...")
        try:
            url = 'https://www.predictit.org/api/marketdata/all/'
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data or 'markets' not in data:
                logger.warning("✗ PredictIt: Invalid response")
                return False

            markets = data.get('markets', [])

            # Look for 2026 House/Senate control markets
            for market in markets:
                name = market.get('name', '').lower()
                if '2026' not in name:
                    continue

                contracts = market.get('contracts', [])
                for contract in contracts:
                    c_name = contract.get('name', '').lower()
                    if 'democrat' in c_name or 'republican' in c_name:
                        price = contract.get('lastTradePrice')

                        if price and 'house' in name and 'control' in name:
                            if 'democrat' in c_name:
                                logger.info(f"✓ PredictIt House Dem control: {price*100:.1f}%")
                                self.market_sources.append({
                                    'source': 'predictit',
                                    'chamber': 'house',
                                    'dem_prob': price * 100
                                })

                        elif price and 'senate' in name and 'control' in name:
                            if 'democrat' in c_name:
                                logger.info(f"✓ PredictIt Senate Dem control: {price*100:.1f}%")
                                self.market_sources.append({
                                    'source': 'predictit',
                                    'chamber': 'senate',
                                    'dem_prob': price * 100
                                })

            if self.market_sources:
                logger.info(f"✓ PredictIt: Extracted {len(self.market_sources)} market odds")
                return True
            else:
                logger.warning("✗ PredictIt: No 2026 markets found")
                return False

        except Exception as e:
            logger.warning(f"✗ PredictIt: {e}")
            return False

    # ============================================================================
    # AGGREGATION
    # ============================================================================

    def aggregate_polling(self):
        """Average all polling sources"""
        if not self.polling_sources:
            logger.warning("No polling sources to aggregate")
            return None

        avg_dem = sum(s['dem_pct'] for s in self.polling_sources) / len(self.polling_sources)
        avg_rep = sum(s['rep_pct'] for s in self.polling_sources) / len(self.polling_sources)

        logger.info(f"✓ Polling aggregate: D {avg_dem:.1f}% R {avg_rep:.1f}% ({len(self.polling_sources)} sources)")

        return {
            'dem_pct': round(avg_dem, 1),
            'rep_pct': round(avg_rep, 1),
            'margin': round(avg_dem - avg_rep, 1),
            'sources_count': len(self.polling_sources),
            'sources': [s['source'] for s in self.polling_sources]
        }

    def aggregate_markets(self):
        """Average market odds by chamber"""
        if not self.market_sources:
            logger.warning("No market sources to aggregate")
            return None

        house_odds = [s['dem_prob'] for s in self.market_sources if s.get('chamber') == 'house']
        senate_odds = [s['dem_prob'] for s in self.market_sources if s.get('chamber') == 'senate']

        result = {}
        if house_odds:
            result['house_dem_prob'] = round(sum(house_odds) / len(house_odds), 1)
        if senate_odds:
            result['senate_dem_prob'] = round(sum(senate_odds) / len(senate_odds), 1)

        logger.info(f"✓ Markets aggregate: {result}")
        return result

    def build_cache(self, polling_agg, markets_agg):
        """Build final cache with both signals"""
        cache = {
            'asOf': datetime.utcnow().isoformat() + 'Z',
            'polling': polling_agg or {},
            'markets': markets_agg or {},
            'blended': {},
            'metadata': {
                'fetchedAt': datetime.utcnow().isoformat() + 'Z',
                'nextUpdate': (datetime.utcnow() + timedelta(hours=6)).isoformat() + 'Z',
                'pollingSources': len(self.polling_sources),
                'marketSources': len(self.market_sources),
            }
        }

        # Blend if both available
        if polling_agg and markets_agg:
            if polling_agg.get('dem_pct') and markets_agg.get('house_dem_prob'):
                blended_dem = (polling_agg['dem_pct'] * 0.5) + (markets_agg['house_dem_prob'] * 0.5)
                cache['blended']['house_dem_pct'] = round(blended_dem, 1)

            if polling_agg.get('dem_pct') and markets_agg.get('senate_dem_prob'):
                blended_dem = (polling_agg['dem_pct'] * 0.5) + (markets_agg['senate_dem_prob'] * 0.5)
                cache['blended']['senate_dem_pct'] = round(blended_dem, 1)

        return cache

    def load_cache(self):
        """Load previous cache as fallback"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load cache: {e}")
        return None

    def save_cache(self, cache_data):
        """Save cache"""
        try:
            os.makedirs('polling', exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"✓ Cache saved")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to save cache: {e}")
            return False

    def run(self):
        """Main collection and aggregation loop"""
        logger.info("=" * 70)
        logger.info("AGGREGATED POLLING & MARKETS COLLECTOR")
        logger.info("=" * 70)

        # Fetch all sources (continue even if some fail)
        self.fetch_realclearpolls_average()
        self.fetch_270towin_average()
        self.fetch_deciskhq_average()
        self.fetch_us_polling_data()
        self.fetch_predictit_markets()

        # Aggregate what we got
        polling_agg = self.aggregate_polling()
        markets_agg = self.aggregate_markets()

        # Build cache
        cache = self.build_cache(polling_agg, markets_agg)

        # If we have new data, save it
        if polling_agg or markets_agg:
            self.save_cache(cache)
            logger.info("✓ New data collected and cached")
            return cache
        else:
            # Use previous cache as fallback
            logger.info("⚠ No new data, using cache...")
            previous = self.load_cache()
            if previous:
                logger.info("✓ Using cached data")
                previous['metadata']['usedCache'] = True
                return previous
            else:
                logger.error("✗ No data available")
                return cache

def main():
    try:
        collector = AggregatedCollector()
        data = collector.run()

        print(f"\n✓ Collection complete")
        print(f"Polling: {data.get('polling')}")
        print(f"Markets: {data.get('markets')}")
        print(f"Blended: {data.get('blended')}")
        print(f"Cache: polling/cache.json")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())
