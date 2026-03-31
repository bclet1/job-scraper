"""
Glassdoor job scraper using Playwright for JavaScript rendering.

Glassdoor is a React SPA with Cloudflare anti-bot protection. This scraper
uses realistic browser fingerprinting via Playwright and conservative delays.

Note: Glassdoor may intermittently block headless browsers. If 0 jobs are
returned consistently, try:
  - Increasing _DELAY_BETWEEN_REQUESTS
  - Running with headless=False to inspect what the page renders
  - Checking whether Glassdoor requires login for your region
"""

import random
import re
import time
from typing import Dict, List
from urllib.parse import urlencode

from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

# Glassdoor fromAge param: number of days (1, 3, 7, 14, 30)
_SUPPORTED_AGES = [1, 3, 7, 14, 30]

# Seconds to sleep between keyword/location combinations
_DELAY_BETWEEN_REQUESTS = (3, 6)


def _days_to_from_age(days: int) -> int:
    """Round days_old up to the nearest Glassdoor-supported fromAge bucket."""
    for bucket in _SUPPORTED_AGES:
        if days <= bucket:
            return bucket
    return 30


class GlassdoorScraper:
    """Scrape job listings from Glassdoor's public job search (no account required)."""

    BASE_URL = "https://www.glassdoor.com/Job/jobs.htm"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

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
        Scrape job listings from Glassdoor.

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
            raise ImportError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        all_jobs: List[Dict] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent=self.HEADERS["User-Agent"],
                locale="en-US",
                timezone_id="America/Denver",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            # Hide webdriver flag
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            for keyword in keywords:
                logger.info(f"Searching Glassdoor for: {keyword}")

                for location in locations:
                    logger.info(f"  Location: {location}")

                    try:
                        jobs = self._scrape_keyword_location(
                            context, keyword, location, max_jobs, days_old
                        )
                        all_jobs.extend(jobs)
                    except Exception as exc:
                        logger.warning(
                            f"Error scraping Glassdoor for '{keyword}' in '{location}': {exc}"
                        )
                        continue

                    time.sleep(random.uniform(*_DELAY_BETWEEN_REQUESTS))

            browser.close()

        # De-duplicate by (title, company) — case-insensitive
        seen: set = set()
        unique_jobs: List[Dict] = []
        for job in all_jobs:
            key = (
                job.get("title", "").strip().lower(),
                job.get("company", "").strip().lower(),
            )
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        return unique_jobs[:max_jobs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_search_url(self, keyword: str, location: str, page_cursor: int, days_old: int) -> str:
        """Build a Glassdoor job-search URL."""
        normalized_location = location.strip().lower()

        params: Dict[str, str] = {
            "sc.keyword": keyword,
            "fromAge": str(_days_to_from_age(days_old)),
            "pgc": str(page_cursor),          # page cursor (0-based, increments by ~30)
        }

        if normalized_location == "remote":
            params["remoteWorkType"] = "1"
            # National scope for remote
            params["locT"] = "N"
            params["locId"] = "1"
        else:
            # Embed location in keyword for broadest compatibility (no location-ID lookup needed)
            params["sc.keyword"] = f"{keyword} {location}"

        return f"{self.BASE_URL}?{urlencode(params)}"

    def _scrape_keyword_location(
        self,
        context,
        keyword: str,
        location: str,
        limit: int,
        days_old: int,
    ) -> List[Dict]:
        jobs: List[Dict] = []
        page_cursor = 0
        max_pages = 5

        page = context.new_page()
        try:
            for _ in range(max_pages):
                if len(jobs) >= limit:
                    break

                url = self._build_search_url(keyword, location, page_cursor, days_old)
                logger.info(f"    Fetching: {url}")

                try:
                    page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    # Give React time to hydrate
                    page.wait_for_timeout(random.randint(2500, 4000))
                except Exception as exc:
                    logger.warning(f"    Page load failed: {exc}")
                    break

                html = page.content()
                page_jobs = self._parse_search_results(html)

                if not page_jobs:
                    logger.info("    No jobs found on page — stopping pagination")
                    break

                for job in page_jobs:
                    if len(jobs) >= limit:
                        break
                    # Fetch description from detail page when we have a link
                    if job.get("link") and not job.get("description"):
                        job["description"] = self._fetch_description(context, job["link"])
                    jobs.append(job)

                # Glassdoor paginates with a cursor that jumps by ~30 results
                page_cursor += 30
                time.sleep(random.uniform(2, 4))

        finally:
            page.close()

        return jobs

    def _parse_search_results(self, html: str) -> List[Dict]:
        """Parse job cards from a Glassdoor search results page."""
        soup = BeautifulSoup(html, "html.parser")
        jobs: List[Dict] = []

        # Glassdoor job cards — selector may need updating if they redesign
        # Try multiple known selectors in order of preference
        card_selectors = [
            "li[data-test='jobListing']",
            "li.JobsList_jobListItem__wjTHv",
            "div[data-jobid]",
            "article.job-search-result",
        ]

        cards = []
        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                break

        if not cards:
            logger.warning("    Could not find job cards — page structure may have changed or bot was detected")
            return []

        for card in cards:
            try:
                job = self._parse_card(card)
                if job and job.get("title") and job.get("link"):
                    jobs.append(job)
            except Exception as exc:
                logger.debug(f"    Error parsing card: {exc}")
                continue

        return jobs

    def _parse_card(self, card) -> Dict:
        """Extract fields from a single job card element."""
        # Title — try multiple selectors
        title_el = (
            card.select_one("a[data-test='job-title']")
            or card.select_one("a.JobCard_seoLink__WdqHZ")
            or card.select_one("a[class*='jobTitle']")
            or card.select_one("a[class*='JobCard']")
        )
        title = title_el.get_text(strip=True) if title_el else ""

        # Link
        link = ""
        if title_el and title_el.get("href"):
            href = title_el["href"]
            link = href if href.startswith("http") else f"https://www.glassdoor.com{href}"

        # Company
        company_el = (
            card.select_one("span[data-test='employer-name']")
            or card.select_one("div[data-test='employer-name']")
            or card.select_one("span[class*='EmployerProfile']")
            or card.select_one("[class*='employerName']")
        )
        company = company_el.get_text(strip=True) if company_el else ""

        # Location
        location_el = (
            card.select_one("div[data-test='emp-location']")
            or card.select_one("span[class*='location']")
            or card.select_one("[class*='Location']")
        )
        location = location_el.get_text(strip=True) if location_el else ""

        # Salary (often only shown on detail page; capture if present on card)
        salary_el = (
            card.select_one("div[data-test='detailSalary']")
            or card.select_one("span[class*='salary']")
            or card.select_one("[class*='Salary']")
        )
        salary = salary_el.get_text(strip=True) if salary_el else ""
        # Clean up salary
        salary = re.sub(r'\s+', ' ', salary).strip()

        # Description snippet (card-level — usually a short excerpt)
        desc_el = (
            card.select_one("div[data-test='descSnippet']")
            or card.select_one("[class*='description']")
            or card.select_one("[class*='Description']")
        )
        description = desc_el.get_text(strip=True) if desc_el else ""

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "link": link,
            "description": description,
        }

    def _fetch_description(self, context, url: str) -> str:
        """Fetch full job description from the detail page."""
        page = context.new_page()
        try:
            page.goto(url, timeout=25_000, wait_until="domcontentloaded")
            page.wait_for_timeout(random.randint(1500, 3000))
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            desc_el = (
                soup.select_one("div[class*='jobDescriptionContent']")
                or soup.select_one("div[data-test='jobDescriptionContent']")
                or soup.select_one("div[id='JobDescriptionContainer']")
                or soup.select_one("[class*='JobDescription']")
            )
            if desc_el:
                return re.sub(r'\s+', ' ', desc_el.get_text(separator=' ', strip=True))
            return ""
        except Exception as exc:
            logger.debug(f"Failed to fetch description from {url}: {exc}")
            return ""
        finally:
            page.close()


# ---------------------------------------------------------------------------
# Module-level contract function (required by multi_job_scraper.py)
# ---------------------------------------------------------------------------

def scrape_glassdoor(
    keywords: List[str],
    locations: List[str],
    max_jobs: int = 25,
    days_old: int = 1,
) -> List[Dict]:
    """Scrape Glassdoor jobs — entry point for the pipeline."""
    scraper = GlassdoorScraper()
    return scraper.scrape_jobs(keywords, locations, max_jobs, days_old)


# ---------------------------------------------------------------------------
# Isolation smoke test (see CLAUDE.md — Testing a New Scraper in Isolation)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from logging_setup import configure_logging
    configure_logging()
    logging.getLogger(__name__).setLevel(logging.INFO)
    logging.getLogger().setLevel(logging.INFO)

    keywords = sys.argv[1:] or ["DevOps Engineer"]
    print(f"Smoke test: scraping Glassdoor for {keywords} / remote / max_jobs=3 / days_old=7\n")

    jobs = scrape_glassdoor(
        keywords=keywords,
        locations=["remote"],
        max_jobs=3,
        days_old=7,
    )

    print(f"Returned {len(jobs)} job(s)")
    for job in jobs:
        print(f"  {job.get('title')} | {job.get('company')} | {job.get('salary') or 'no salary'}")
        print(f"    link: {job.get('link')}")
        print(f"    desc chars: {len(job.get('description', ''))}")
        print()

    # Validate contract fields
    required = {"title", "company", "location", "salary", "link", "description"}
    issues = []
    for i, job in enumerate(jobs):
        for field in required:
            if job.get(field) is None:
                issues.append(f"Job {i}: '{field}' is None (must be empty string)")
        if job.get("link") and not job["link"].startswith("https://"):
            issues.append(f"Job {i}: link doesn't start with https://")
        if len(job.get("description", "")) < 100:
            issues.append(f"Job {i}: description is short ({len(job.get('description',''))} chars) — may hurt match scores")

    if issues:
        print("⚠ Contract issues:")
        for issue in issues:
            print(f"  • {issue}")
    elif jobs:
        print("✓ All contract fields OK")
    else:
        print("⚠ No jobs returned — site may have blocked the scraper or selectors need updating")
