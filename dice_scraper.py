"""
Dice.com job scraper using Playwright for JavaScript rendering.

Dice is a tech/IT-focused job board. Their site is a React SPA, so
plain HTTP requests do not return populated job listings.
"""

import random
import re
import time
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

# Dice posted-date filter values (URL query param: filters.postedDate)
_DAYS_TO_FILTER = {
    1:  "ONE_DAY_OR_LESS",
    3:  "THREE_DAYS_OR_LESS",
    7:  "SEVEN_DAYS_OR_LESS",
    30: "THIRTY_DAYS_OR_LESS",
}


def _days_to_filter(days: int) -> str:
    """Map a days_old value to Dice's filters.postedDate string."""
    for threshold in sorted(_DAYS_TO_FILTER):
        if days <= threshold:
            return _DAYS_TO_FILTER[threshold]
    return _DAYS_TO_FILTER[30]


class DiceScraper:
    """Scrape job listings from Dice.com's public job search (no account required)."""

    BASE_URL = "https://www.dice.com/jobs"
    DETAIL_BASE = "https://www.dice.com/job-detail"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
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
        Scrape job listings from Dice.

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
            raise ImportError("Playwright not installed. Run: pip install playwright && playwright install chromium")

        all_jobs: List[Dict] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for keyword in keywords:
                logger.info(f"Searching Dice for: {keyword}")

                for location in locations:
                    logger.info(f"  Location: {location}")

                    try:
                        jobs = self._scrape_keyword_location(
                            browser, keyword, location, max_jobs, days_old
                        )
                        all_jobs.extend(jobs)
                    except Exception as exc:
                        logger.warning(
                            f"Error scraping Dice for '{keyword}' in '{location}': {exc}"
                        )
                        continue

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
        self, keyword: str, location: str, page: int, days_old: int
    ) -> str:
        """Build a Dice job-search URL."""
        params: Dict[str, str] = {
            "q": keyword,
            "page": str(page),
            "pageSize": "20",
            "filters.postedDate": _days_to_filter(days_old),
        }

        normalized = location.strip().lower()
        if normalized == "remote":
            params["filters.workplaceTypes"] = "Remote"
        else:
            params["location"] = location
            params["radius"] = "30"
            params["radiusUnit"] = "mi"

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
        max_pages = 5

        page = browser.new_page()
        page.set_extra_http_headers(self.HEADERS)

        try:
            for page_num in range(1, max_pages + 1):
                if len(jobs) >= limit:
                    break

                url = self._build_search_url(keyword, location, page_num, days_old)
                logger.debug(f"Fetching: {url}")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as exc:
                    logger.warning(f"Navigation error on page {page_num}: {exc}")
                    break

                # Give the React app time to render
                time.sleep(random.uniform(2.5, 4))

                # Wait for job cards to appear
                try:
                    page.wait_for_selector(
                        "div[data-testid='job-card']",
                        timeout=12000,
                    )
                except Exception:
                    logger.debug(f"Job card selector timed out on page {page_num} – may be empty")
                    break

                html = page.content()
                page_jobs = self._parse_search_results(html)

                if not page_jobs:
                    logger.debug(f"No jobs parsed on page {page_num}; stopping")
                    break

                for job in page_jobs:
                    key = (job.get("title", "").lower(), job.get("company", "").lower())
                    existing_keys = {
                        (j.get("title", "").lower(), j.get("company", "").lower())
                        for j in jobs
                    }
                    if key not in existing_keys:
                        jobs.append(job)
                        if len(jobs) >= limit:
                            break

                logger.debug(f"  Page {page_num}: {len(page_jobs)} cards, running total {len(jobs)}")
                time.sleep(random.uniform(1.5, 2.5))

        finally:
            page.close()

        # Enrich with description from the detail page
        enriched: List[Dict] = []
        for job in jobs[:limit]:
            try:
                enriched.append(self._enrich_job_details(job, browser))
            except Exception as exc:
                logger.debug(f"Error enriching Dice job {job.get('link')}: {exc}")
                job.setdefault("description", "")
                enriched.append(job)
            time.sleep(random.uniform(0.8, 1.5))

        logger.info(f"  Found {len(enriched)} Dice jobs for '{keyword}' in '{location}'")
        return enriched

    def _parse_search_results(self, html: str) -> List[Dict]:
        """Parse job cards from a Dice search results page."""
        soup = BeautifulSoup(html, "html.parser")
        # Dice renders each posting as <div data-testid="job-card">
        cards = soup.select("div[data-testid='job-card']")
        jobs: List[Dict] = []
        for card in cards:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)
        return jobs

    def _parse_job_card(self, card) -> Optional[Dict]:
        """Extract fields from a single Dice job card."""
        # --- Link + Title ---
        # The invisible full-card overlay `<a data-testid="job-search-job-card-link">`
        # carries both the href and an aria-label of the form:
        #   "View Details for <title> (<id>)"
        card_link = card.select_one("a[data-testid='job-search-job-card-link']")
        if not card_link:
            return None

        link = card_link.get("href", "").strip()
        aria_label = card_link.get("aria-label", "")
        title_match = re.match(r"View Details for (.+?) \(", aria_label)
        title = title_match.group(1) if title_match else ""

        # Fallback: visible title <a> has 'text-xl' and 'font-semibold' in its class list
        if not title:
            visible_title = next(
                (
                    a for a in card.find_all("a")
                    if a.get("class")
                    and "text-xl" in a["class"]
                    and "font-semibold" in a["class"]
                ),
                None,
            )
            title = visible_title.get_text(" ", strip=True) if visible_title else ""

        if not title:
            return None

        # --- Company ---
        company_p = card.select_one("a[href*='company-profile'] p")
        company = company_p.get_text(" ", strip=True) if company_p else "Unknown"

        # --- Location ---
        # First <p class="text-sm font-normal text-zinc-600"> that isn't a bullet or date.
        # Dice renders: location | "•" | posted-date as three separate <p> elements.
        location = "Location not specified"
        for p in card.find_all("p"):
            cls = p.get("class", [])
            if "text-zinc-600" in cls and "text-sm" in cls:
                text = p.get_text(" ", strip=True)
                if text and text != "•" and not re.match(r'^(Today|Yesterday|\d+ days? ago|\d+[dh] ago)$', text, re.I):
                    location = text
                    break

        # --- Description snippet ---
        desc_p = next(
            (
                p for p in card.find_all("p")
                if "text-zinc-900" in p.get("class", []) and "line-clamp-2" in p.get("class", [])
            ),
            None,
        )
        description = desc_p.get_text(" ", strip=True) if desc_p else ""

        # --- Salary ---
        # Badge <p> elements all share 'text-xs font-medium text-zinc-600'.
        # They appear as: [Easy Apply?] [Employment type] [Salary/experience].
        # Scan them all, prefer any that contain a dollar sign or salary keyword;
        # fall back to the last one.
        salary = "Not specified"
        badge_ps = [
            p for p in card.find_all("p")
            if "text-xs" in p.get("class", []) and "font-medium" in p.get("class", [])
        ]
        SKIP_BADGES = {"easy apply", "full-time", "part-time", "contract", "third party",
                       "internship", "full time", "part time"}
        salary_candidates = [
            p.get_text(" ", strip=True) for p in badge_ps
            if p.get_text(" ", strip=True).lower() not in SKIP_BADGES
        ]
        for candidate in salary_candidates:
            extracted = self._extract_salary(candidate)
            if extracted:
                salary = extracted
                break
        # If nothing was extracted but there's a non-trivial last badge, keep it as-is
        if salary == "Not specified" and salary_candidates:
            last = salary_candidates[-1]
            if last and last.lower() not in SKIP_BADGES:
                salary = last

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "link": link,
            "description": description,
            "source": "dice",
        }

    def _enrich_job_details(self, job: Dict, browser) -> Dict:
        """Fetch the Dice job detail page and extract description + salary."""
        link = job.get("link", "")
        if not link:
            return job

        page = browser.new_page()
        page.set_extra_http_headers(self.HEADERS)

        try:
            page.goto(link, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 2.5))

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # --- Description ---
            # Dice embeds the full job description as JSON-LD in a <script> tag.
            # This is more reliable than scraping rendered HTML elements.
            import json as _json
            description = ""
            ld_script = soup.select_one("script[data-testid='jobDetailStructuredData']")
            if ld_script and ld_script.string:
                try:
                    ld = _json.loads(ld_script.string)
                    raw_desc = ld.get("description", "")
                    if raw_desc:
                        # Description may contain HTML; strip it
                        description = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)
                except Exception:
                    pass

            # Fallback: look for a large rendered div with description content
            if not description:
                for sel in ["div[data-testid='jobDescriptionHtml']", "div#jobDescription",
                            "[data-testid='jobDescription']", "div.job-description"]:
                    elem = soup.select_one(sel)
                    if elem:
                        description = elem.get_text(" ", strip=True)
                        break

            job["description"] = description[:2000]

            # --- Salary enrichment ---
            if job.get("salary") in ("", "Not specified"):
                salary = self._extract_salary(description)
                job["salary"] = salary or "Not specified"

        finally:
            page.close()

        return job

    def _extract_salary(self, text: str) -> str:
        """Extract a salary string from free text using regex patterns."""
        if not text:
            return ""

        patterns = [
            r"\$[\d,]+(?:\.\d+)?\s*[-–—]\s*\$[\d,]+(?:\.\d+)?(?:\s*(?:per year|\/yr|annually|USD))?",
            r"\$[\d,]+(?:\.\d+)?(?:\s*[-–—]\s*\$[\d,]+(?:\.\d+)?)?(?:\s*(?:per hour|\/hr|hourly))",
            r"\$[\d,]+(?:\.\d+)?(?:\s*(?:per year|\/yr|annually))",
            r"\d{2,3}[Kk]\s*[-–—]\s*\d{2,3}[Kk](?:\s*(?:per year|annually|USD))?",
            r"USD\s*\$?[\d,]+\s*[-–—]\s*\$?[\d,]+",
            r"\$[\d,]+\+",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", " ", match.group(0)).strip()

        return ""


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------

def scrape_dice(
    keywords: List[str],
    locations: List[str],
    max_jobs: int = 25,
    days_old: int = 1,
) -> List[Dict]:
    """
    Scrape Dice and return a list of job dicts.

    Signature matches scrape_indeed / scrape_builtin / scrape_linkedin so it
    can be passed directly to run_source() in multi_job_scraper.py.

    Args:
        keywords:  List of job title keywords to search.
        locations: List of locations (e.g. "Denver, CO", "remote").
        max_jobs:  Maximum number of jobs to scrape per keyword.
        days_old:  Only return jobs posted within this many days.
    """
    scraper = DiceScraper()
    return scraper.scrape_jobs(keywords, locations, max_jobs, days_old)


if __name__ == "__main__":
    jobs = scrape_dice(["DevOps Engineer"], ["Denver, CO", "remote"], max_jobs=5)
    print(f"Found {len(jobs)} Dice jobs")
    for job in jobs[:3]:
        print(f"{job['title']} - {job['company']} - {job['salary']}")
