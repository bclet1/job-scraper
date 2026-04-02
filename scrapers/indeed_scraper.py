"""
Indeed.com job scraper using Playwright for JavaScript rendering.
"""

import asyncio
import time
import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import quote
import logging

logger = logging.getLogger(__name__)


class IndeedScraper:
    """Scrape job listings from Indeed.com"""
    
    def __init__(self):
        """Initialize the scraper."""
        self.base_url = "https://www.indeed.com/jobs"
        self.jobs = []
        
    def scrape_jobs(self, keywords: List[str], locations: List[str], max_jobs: int = 25, days_old: int = 1) -> List[Dict]:
        """
        Scrape job listings from Indeed.
        
        Args:
            keywords: List of job title keywords to search
            locations: List of locations (e.g., "Denver, CO", "remote")
            max_jobs: Maximum number of jobs to scrape PER KEYWORD
            days_old: Only return jobs posted within this many days (1 = last 24 hours)
            
        Returns:
            List of job dictionaries with title, company, location, salary, link, description
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("Playwright not installed. Run: pip install playwright")
        
        all_jobs = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for keyword in keywords:
                logger.info(f"Searching for: {keyword}")
                keyword_jobs: List[Dict] = []
                seen_kw: set = set()

                for location in locations:
                    if len(keyword_jobs) >= max_jobs:
                        break
                    remaining = max_jobs - len(keyword_jobs)
                    logger.info(f"  Location: {location} (need {remaining} more)")

                    try:
                        jobs = self._scrape_keyword_location(
                            browser, keyword, location, remaining, days_old
                        )
                        for job in jobs:
                            key = (job.get('title', '').lower(), job.get('company', '').lower())
                            if key not in seen_kw:
                                seen_kw.add(key)
                                keyword_jobs.append(job)
                                if len(keyword_jobs) >= max_jobs:
                                    break
                    except Exception as e:
                        logger.warning(f"Error scraping {keyword} in {location}: {e}")
                        continue

                    # Rate limiting to avoid blocking
                    time.sleep(2)

                logger.info(f"  Collected {len(keyword_jobs)} jobs for '{keyword}' (target {max_jobs})")
                all_jobs.extend(keyword_jobs)

            browser.close()
        
        # Final cross-keyword dedup by (title, company) to remove any jobs
        # that appeared under more than one keyword search.
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = (job.get('title', '').lower(), job.get('company', '').lower())
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        return unique_jobs
    
    def _scrape_keyword_location(self, browser, keyword: str, location: str, limit: int, days_old: int = 1) -> List[Dict]:
        """Scrape jobs for a specific keyword and location."""
        page = browser.new_page()
        page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        
        try:
            # Build URL with date filter using Indeed's fromage parameter (days since posting)
            if location.lower() == 'remote':
                url = f"{self.base_url}?q={quote(keyword)}&l=&sc=0kf%3Aattr%28DSQF7%29%3B&fromage={days_old}"
            else:
                url = f"{self.base_url}?q={quote(keyword)}&l={quote(location)}&fromage={days_old}"
            
            logger.debug(f"Fetching: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for job cards to load
            page.wait_for_selector("div.job_seen_beacon", timeout=10000)
            time.sleep(2)
            
            # Aggressively scroll to load more jobs
            # Keep scrolling until we have enough jobs or reach the end
            jobs = []
            scroll_count = 0
            max_scrolls = 8
            previous_count = 0
            no_change_count = 0
            
            while len(jobs) < limit and scroll_count < max_scrolls:
                try:
                    # Scroll down to trigger lazy loading (more gently)
                    for _ in range(2):
                        page.evaluate("window.scrollBy(0, window.innerHeight)")
                        time.sleep(0.3)
                    
                    time.sleep(0.8)
                    
                    # Parse current jobs - try multiple selectors
                    content = page.content()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Try multiple job card selectors (Indeed changes their structure frequently)
                    job_cards = (
                        soup.find_all('div', class_='job_seen_beacon') or
                        soup.find_all('div', {'data-job-id': True}) or
                        soup.find_all('li', {'data-job-id': True})
                    )
                    
                    new_jobs = []
                    for card in job_cards:
                        try:
                            job = self._parse_job_card(card)
                            if job:
                                # Check if we already have this job
                                job_key = (job.get('title', ''), job.get('company', ''))
                                existing_keys = [(j.get('title', ''), j.get('company', '')) for j in new_jobs]
                                if job_key not in existing_keys and len(new_jobs) < limit:
                                    new_jobs.append(job)
                        except Exception as e:
                            logger.debug(f"Error parsing job card: {e}")
                            continue
                    
                    jobs = new_jobs
                    
                    # Check if we're making progress
                    if len(jobs) == previous_count:
                        no_change_count += 1
                    else:
                        no_change_count = 0
                    
                    # Stop if we found enough or we're not finding new jobs
                    if len(jobs) >= limit or (no_change_count >= 2 and len(jobs) > 0):
                        break
                    
                    previous_count = len(jobs)
                    scroll_count += 1
                    
                except Exception as e:
                    logger.warning(f"Error during scrolling: {e}")
                    break
            
            logger.info(f"  Found {len(jobs)} jobs after {scroll_count} scrolls")
            return jobs[:limit]
        
        finally:
            page.close()

    def _get_text_by_selectors(self, card, selectors: List[str]) -> str:
        """Return first non-empty text from a list of CSS selectors."""
        for selector in selectors:
            elem = card.select_one(selector)
            if elem:
                text = elem.get_text(" ", strip=True)
                if text:
                    return text
        return ""

    def _get_href_by_selectors(self, card, selectors: List[str]) -> str:
        """Return first non-empty href from a list of CSS selectors."""
        for selector in selectors:
            elem = card.select_one(selector)
            if elem:
                href = (elem.get('href') or "").strip()
                if href:
                    return href
        return ""

    def _extract_salary_text(self, text: str) -> str:
        """Extract first salary-like value from free text."""
        if not text:
            return ""

        patterns = [
            r'\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[kKmM])?\s*(?:-|to)\s*\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[kKmM])?\s*(?:per\s+)?(?:year|yr|hour|hr|month|week|day)?',
            r'\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[kKmM])?\s*(?:per\s+)?(?:year|yr|hour|hr|month|week|day)',
            r'\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[kKmM])?\+',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return re.sub(r'\s+', ' ', match.group(0)).strip()

        return ""
    
    def _parse_job_card(self, card) -> Optional[Dict]:
        """Parse individual job card HTML."""
        try:
            title = self._get_text_by_selectors(card, [
                "h2.jobTitle a",
                "h2.jobTitle",
                "h2[data-testid='jobTitle'] a",
                "h2[data-testid='jobTitle']",
                "a[data-testid='job-title']",
                "a.jcs-JobTitle",
            ])
            if not title:
                return None

            link = self._get_href_by_selectors(card, [
                "h2.jobTitle a",
                "h2[data-testid='jobTitle'] a",
                "a[data-testid='job-title']",
                "a.jcs-JobTitle",
                "a[data-jk]",
            ])

            if not link:
                jk_attr = card.get('data-jk') or card.get('data-job-id')
                if jk_attr:
                    link = f"https://www.indeed.com/viewjob?jk={jk_attr}"

            if link and not link.startswith('http'):
                link = f"https://www.indeed.com{link}"

            company = self._get_text_by_selectors(card, [
                "span[data-testid='company-name']",
                "a[data-testid='company-name']",
                "div[data-testid='company-name']",
                "span.companyName",
                "span[class*='companyName']",
            ]) or "Unknown"

            location = self._get_text_by_selectors(card, [
                "div[data-testid='text-location']",
                "span[data-testid='text-location']",
                "div.companyLocation",
                "div[class*='companyLocation']",
            ]) or "Location not specified"

            salary = self._get_text_by_selectors(card, [
                "div[data-testid='attribute_snippet_testid']",
                "div.salary-snippet-container",
                "span.estimated-salary",
                "div[class*='salary']",
                "span[class*='salary']",
            ])

            if not self._extract_salary_text(salary):
                salary_candidates = [
                    elem.get_text(" ", strip=True)
                    for elem in card.select("[data-testid='attribute_snippet_testid'], span.estimated-salary, div.salary-snippet-container")
                ]
                salary = self._extract_salary_text(" | ".join(salary_candidates))

            if not salary:
                salary = self._extract_salary_text(card.get_text(" ", strip=True))

            if not salary:
                salary = "Not specified"

            description = self._get_text_by_selectors(card, [
                "div[data-testid='job-snippet']",
                "div.job-snippet",
                "div.snippet",
                "div[class*='snippet']",
            ])
            
            return {
                'title': title,
                'company': company,
                'location': location,
                'salary': salary,
                'link': link,
                'description': description,
            }
        
        except Exception as e:
            logger.debug(f"Error parsing card: {e}")
            return None


def scrape_indeed(keywords: List[str], locations: List[str], max_jobs: int = 25, days_old: int = 1) -> List[Dict]:
    """
    Convenience function to scrape Indeed.
    
    Args:
        keywords: List of job keywords
        locations: List of locations
        max_jobs: Max jobs to collect per keyword
        days_old: Only return jobs posted within this many days (1 = last 24 hours)
        
    Returns:
        List of job dictionaries (deduplicated)
    """
    scraper = IndeedScraper()
    return scraper.scrape_jobs(keywords, locations, max_jobs, days_old)


if __name__ == "__main__":
    # Test
    test_keywords = ["DevOps Engineer", "Cloud Engineer"]
    test_locations = ["Denver, CO", "remote"]
    
    print("Starting scrape test...")
    jobs = scrape_indeed(test_keywords, test_locations, max_jobs=10)
    
    print(f"\nFound {len(jobs)} jobs:")
    for job in jobs[:3]:
        print(f"\nTitle: {job['title']}")
        print(f"Company: {job['company']}")
        print(f"Location: {job['location']}")
        print(f"Salary: {job['salary']}")
