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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IndeedScraper:
    """Scrape job listings from Indeed.com"""
    
    def __init__(self):
        """Initialize the scraper."""
        self.base_url = "https://www.indeed.com/jobs"
        self.jobs = []
        
    def scrape_jobs(self, keywords: List[str], locations: List[str], max_jobs: int = 25) -> List[Dict]:
        """
        Scrape job listings from Indeed.
        
        Args:
            keywords: List of job title keywords to search
            locations: List of locations (e.g., "Denver, CO", "remote")
            max_jobs: Maximum number of jobs to scrape PER KEYWORD
            
        Returns:
            List of job dictionaries with title, company, location, salary, link, description
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("Playwright not installed. Run: pip install playwright")
        
        all_jobs = []
        # Collect max_jobs per keyword (not total)
        jobs_per_keyword = max_jobs
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            for keyword in keywords:
                logger.info(f"Searching for: {keyword}")
                
                for location in locations:
                    logger.info(f"  Location: {location}")
                    
                    try:
                        jobs = self._scrape_keyword_location(
                            browser, keyword, location, jobs_per_keyword
                        )
                        all_jobs.extend(jobs)
                    except Exception as e:
                        logger.warning(f"Error scraping {keyword} in {location}: {e}")
                        continue
                    
                    # Rate limiting to avoid blocking
                    time.sleep(2)
            
            browser.close()
        
        # Remove duplicates by job title + company
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = (job.get('title', ''), job.get('company', ''))
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)
        
        return unique_jobs[:max_jobs]
    
    def _scrape_keyword_location(self, browser, keyword: str, location: str, limit: int) -> List[Dict]:
        """Scrape jobs for a specific keyword and location."""
        page = browser.new_page()
        page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        
        try:
            # Build URL with date filter for last 7 days
            if location.lower() == 'remote':
                url = f"{self.base_url}?q={quote(keyword)}&l=&sc=0kf%3Aattr%28DSQF7%29%3B&date=7&vjk"
            else:
                url = f"{self.base_url}?q={quote(keyword)}&l={quote(location)}&date=7&vjk"
            
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
    
    def _parse_job_card(self, card) -> Optional[Dict]:
        """Parse individual job card HTML."""
        try:
            # Extract title and link from title element
            title_elem = card.find('h2', class_='jobTitle')
            if not title_elem:
                return None
            title = title_elem.get_text(strip=True)
            
            # Try to get link from the title anchor tag first
            link = ""
            title_link = title_elem.find('a')
            if title_link:
                link = title_link.get('href', '')
            
            # If not found in title, look for any link in the card
            if not link:
                # Try to find a data-jk attribute (job key) that can be used to construct the link
                jk_attr = card.get('data-jk')
                if jk_attr:
                    link = f"https://www.indeed.com/viewjob?jk={jk_attr}"
            
            # If still not found, try common link classes
            if not link:
                link_elem = card.find('a', {'class': lambda x: x and 'jcs' in x})
                if link_elem:
                    link = link_elem.get('href', '')
            
            # Ensure link is absolute URL
            if link and not link.startswith('http'):
                link = f"https://www.indeed.com{link}"
            
            # Extract company
            company_elem = card.find('span', {'class': lambda x: x and 'companyName' in x})
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            
            # Extract location
            location_elem = card.find('div', {'class': lambda x: x and 'companyLocation' in x})
            location = location_elem.get_text(strip=True) if location_elem else "Location not specified"
            
            # Extract salary (may not be present)
            salary = ""
            salary_elem = card.find('div', {'class': lambda x: x and 'salary' in x})
            if salary_elem:
                salary = salary_elem.get_text(strip=True)
            
            # Extract job description snippet
            description = ""
            desc_elem = card.find('div', {'class': lambda x: x and 'snippet' in x})
            if desc_elem:
                description = desc_elem.get_text(strip=True)
            
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


def scrape_indeed(keywords: List[str], locations: List[str], max_jobs: int = 25) -> List[Dict]:
    """
    Convenience function to scrape Indeed.
    
    Args:
        keywords: List of job keywords
        locations: List of locations
        max_jobs: Max jobs to collect per keyword
        
    Returns:
        List of job dictionaries (deduplicated)
    """
    scraper = IndeedScraper()
    return scraper.scrape_jobs(keywords, locations, max_jobs)


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
