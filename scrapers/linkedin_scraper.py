"""
LinkedIn job scraper using Playwright for JavaScript rendering.

Uses LinkedIn's public jobs search (no login required) with the f_TPR
time filter and f_WT filter for remote jobs.
"""

import asyncio
import time
import re
import random
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlencode
import logging

logger = logging.getLogger(__name__)

# LinkedIn only supports specific time ranges via f_TPR (seconds since epoch-delta)
# r86400  = past 24 hours
# r259200 = past 3 days
# r604800 = past week
# r2592000 = past month
_DAYS_TO_SECONDS = {
    1:  86400,
    3:  259200,
    7:  604800,
    14: 1209600,
    30: 2592000,
}


def _days_to_tpr(days: int) -> str:
    """Convert a days_old value to LinkedIn's f_TPR=r{seconds} string."""
    # Find the smallest supported bucket that covers the requested days
    for threshold in sorted(_DAYS_TO_SECONDS):
        if days <= threshold:
            return f"r{_DAYS_TO_SECONDS[threshold]}"
    return f"r{_DAYS_TO_SECONDS[30]}"   # cap at 30 days


class LinkedInScraper:
    """Scrape job listings from LinkedIn's public job search (no account required)."""

    BASE_URL = "https://www.linkedin.com/jobs/search/"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    PAGE_SIZE = 25  # LinkedIn returns 25 jobs per page

    def __init__(self):
        self.jobs: List[Dict] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape_jobs(
        self,
        keywords: List[str],
        locations: List[str],
        max_jobs: int = 25,
        days_old: int = 1,
    ) -> List[Dict]:
        """
        Scrape job listings from LinkedIn.

        Args:
            keywords:  List of job-title keywords to search.
            locations: List of locations (e.g. "Denver, CO", "remote").
            max_jobs:  Maximum number of jobs to scrape per keyword.
            days_old:  Only return jobs posted within this many days.

        Returns:
            De-duplicated list of job dicts with standard fields.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("Playwright not installed. Run: pip install playwright")

        all_jobs: List[Dict] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for keyword in keywords:
                logger.info(f"Searching LinkedIn for: {keyword}")

                for location in locations:
                    logger.info(f"  Location: {location}")

                    try:
                        jobs = self._scrape_keyword_location(
                            browser, keyword, location, max_jobs, days_old
                        )
                        all_jobs.extend(jobs)
                    except Exception as exc:
                        logger.warning(
                            f"Error scraping LinkedIn for '{keyword}' in '{location}': {exc}"
                        )
                        continue

                    # Polite delay between searches
                    time.sleep(random.uniform(2, 4))

            browser.close()

        # De-duplicate by (title, company)
        seen: set = set()
        unique_jobs: List[Dict] = []
        for job in all_jobs:
            key = (job.get("title", "").lower(), job.get("company", "").lower())
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        return unique_jobs[:max_jobs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_search_url(
        self, keyword: str, location: str, start: int, days_old: int
    ) -> str:
        """Build a LinkedIn job-search URL."""
        params: Dict[str, str] = {
            "keywords": keyword,
            "f_TPR": _days_to_tpr(days_old),
            "start": str(start),
        }

        normalized = location.strip().lower()
        if normalized == "remote":
            params["f_WT"] = "2"          # LinkedIn work-type=remote
        else:
            params["location"] = location

        return f"{self.BASE_URL}?{urlencode(params)}"

    def _scrape_keyword_location(
        self,
        browser,
        keyword: str,
        location: str,
        limit: int,
        days_old: int,
    ) -> List[Dict]:
        """Scrape one keyword+location combination, paging through results."""
        jobs: List[Dict] = []
        start = 0
        max_pages = 5

        page = browser.new_page()
        page.set_extra_http_headers(self.HEADERS)

        try:
            for page_num in range(max_pages):
                if len(jobs) >= limit:
                    break

                url = self._build_search_url(keyword, location, start, days_old)
                logger.debug(f"Fetching: {url}")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as exc:
                    logger.warning(f"Navigation error on page {page_num + 1}: {exc}")
                    break

                # LinkedIn renders cards asynchronously; give JS time to settle
                time.sleep(random.uniform(2, 3))

                # Try to wait for job cards
                try:
                    page.wait_for_selector(
                        "div.base-card, ul.jobs-search__results-list li",
                        timeout=10000,
                    )
                except Exception:
                    logger.debug("Job card selector timed out – page may be empty")
                    break

                html = page.content()
                page_jobs = self._parse_search_results(html)

                if not page_jobs:
                    logger.debug(f"No jobs parsed on page {page_num + 1}; stopping")
                    break

                for job in page_jobs:
                    key = (job.get("title", "").lower(), job.get("company", "").lower())
                    if key not in {
                        (j.get("title", "").lower(), j.get("company", "").lower())
                        for j in jobs
                    }:
                        jobs.append(job)
                        if len(jobs) >= limit:
                            break

                logger.debug(f"  Page {page_num + 1}: {len(page_jobs)} cards, running total {len(jobs)}")

                start += self.PAGE_SIZE
                time.sleep(random.uniform(1.5, 2.5))

        finally:
            page.close()

        # Enrich with description from the detail page
        enriched: List[Dict] = []
        for job in jobs[:limit]:
            try:
                enriched.append(self._enrich_job_details(job, browser))
            except Exception as exc:
                logger.debug(f"Error enriching LinkedIn job {job.get('link')}: {exc}")
                job.setdefault("description", "")
                enriched.append(job)
            time.sleep(random.uniform(0.8, 1.5))

        logger.info(f"  Found {len(enriched)} LinkedIn jobs for '{keyword}' in '{location}'")
        return enriched

    def _parse_search_results(self, html: str) -> List[Dict]:
        """Parse job cards from a LinkedIn search results page."""
        soup = BeautifulSoup(html, "html.parser")

        # LinkedIn renders cards as <div class="base-card …"> or inside <li> tags
        cards = (
            soup.select("div.base-card")
            or soup.select("ul.jobs-search__results-list li")
        )

        jobs: List[Dict] = []
        for card in cards:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        return jobs

    def _parse_job_card(self, card) -> Optional[Dict]:
        """Extract fields from a single LinkedIn job card."""
        # Title
        title_elem = (
            card.select_one("h3.base-search-card__title")
            or card.select_one("h3.job-search-card__title")
            or card.select_one("h3")
        )
        if not title_elem:
            return None
        title = title_elem.get_text(" ", strip=True)
        if not title:
            return None

        # Company
        company_elem = (
            card.select_one("h4.base-search-card__subtitle a")
            or card.select_one("h4.base-search-card__subtitle")
            or card.select_one("a.hidden-nested-link")
        )
        company = company_elem.get_text(" ", strip=True) if company_elem else "Unknown"

        # Location
        location_elem = (
            card.select_one("span.job-search-card__location")
            or card.select_one("span.base-search-card__metadata")
        )
        location = location_elem.get_text(" ", strip=True) if location_elem else ""

        # Salary (sometimes shown on the card)
        salary_elem = card.select_one("span.job-search-card__salary-info")
        salary = salary_elem.get_text(" ", strip=True) if salary_elem else "Not specified"

        # Link – prefer the full-link anchor
        link_elem = (
            card.select_one("a.base-card__full-link")
            or card.select_one("a[href*='/jobs/view/']")
            or card.select_one("a[data-tracking-id]")
        )
        link = ""
        if link_elem:
            raw = link_elem.get("href", "")
            # Strip tracking query params but keep the clean URL
            link = raw.split("?")[0] if raw else ""

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "link": link,
            "description": "",
        }

    def _enrich_job_details(self, job: Dict, browser) -> Dict:
        """Fetch the LinkedIn job detail page and extract description + salary."""
        link = job.get("link", "")
        if not link:
            return job

        page = browser.new_page()
        page.set_extra_http_headers(self.HEADERS)

        try:
            page.goto(link, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 2.5))

            # Expand "Show more" button if present
            try:
                page.click(
                    "button.show-more-less-html__button--more",
                    timeout=3000,
                )
                time.sleep(0.5)
            except Exception:
                pass

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Description
            desc_elem = (
                soup.select_one("div.show-more-less-html__markup")
                or soup.select_one("div.description__text")
                or soup.select_one("section.description")
            )
            description = desc_elem.get_text(" ", strip=True) if desc_elem else ""
            job["description"] = description

            # Salary refinement from detail page
            if job.get("salary") in ("", "Not specified"):
                salary = self._extract_salary(soup, description)
                job["salary"] = salary

        finally:
            page.close()

        return job

    def _extract_salary(self, soup, description: str) -> str:
        """Extract a salary string from the detail page soup or description text."""
        # Check dedicated salary elements on the detail page
        for selector in [
            "span.compensation__salary",
            "div.compensation",
            "li.description__job-criteria-item",
        ]:
            for elem in soup.select(selector):
                text = elem.get_text(" ", strip=True)
                if re.search(r"\$[\d,]+|\d+[Kk]\s*[-–]\s*\d+[Kk]", text):
                    return text

        # Regex scan across the description text
        patterns = [
            r"\$[\d,]+(?:\.\d+)?\s*[-–—]\s*\$[\d,]+(?:\.\d+)?(?:\s*(?:per year|\/yr|annually|USD))?",
            r"\$[\d,]+(?:\.\d+)?(?:\s*(?:per year|\/yr|annually))",
            r"\d{2,3}[Kk]\s*[-–—]\s*\d{2,3}[Kk](?:\s*(?:per year|annually|USD))?",
            r"USD\s*\$?[\d,]+\s*[-–—]\s*\$?[\d,]+",
        ]
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(0).strip()

        return "Not specified"


# ---------------------------------------------------------------------------
# Module-level convenience wrapper (matches scrape_indeed / scrape_builtin)
# ---------------------------------------------------------------------------

def scrape_linkedin(
    keywords: List[str],
    locations: List[str],
    max_jobs: int = 25,
    days_old: int = 1,
) -> List[Dict]:
    """
    Scrape LinkedIn and return a list of job dicts.

    Signature matches scrape_indeed / scrape_builtin so it can be passed
    directly to run_source() in multi_job_scraper.py.
    """
    scraper = LinkedInScraper()
    return scraper.scrape_jobs(keywords, locations, max_jobs, days_old)
