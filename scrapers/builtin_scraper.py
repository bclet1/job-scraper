"""
Built In job scraper using HTTP requests and BeautifulSoup.
"""

import re
import time
import logging
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class BuiltInScraper:
    """Scrape job listings from Built In."""

    def __init__(self):
        self.base_url = "https://builtin.com"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def scrape_jobs(self, keywords: List[str], locations: List[str], max_jobs: int = 25, days_old: int = 1) -> List[Dict]:
        """Scrape Built In jobs using the shared config contract.
        
        Args:
            keywords: List of job title keywords to search
            locations: List of locations (e.g., "Denver, CO", "remote")
            max_jobs: Maximum number of jobs to scrape per keyword
            days_old: Only return jobs posted within this many days (1 = last 24 hours)
        """
        all_jobs: List[Dict] = []
        jobs_per_search = max_jobs

        for keyword in keywords:
            logger.info(f"Searching Built In for: {keyword}")
            for location in locations:
                logger.info(f"  Location: {location}")
                try:
                    jobs = self._scrape_keyword_location(keyword, location, jobs_per_search, days_old)
                    all_jobs.extend(jobs)
                except Exception as exc:
                    logger.warning(f"Error scraping Built In for {keyword} in {location}: {exc}")
                    continue

                time.sleep(1)

        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        return unique_jobs[:max_jobs]

    def _scrape_keyword_location(self, keyword: str, location: str, limit: int, days_old: int = 1) -> List[Dict]:
        jobs: List[Dict] = []
        page = 1
        max_pages = 5

        while len(jobs) < limit and page <= max_pages:
            url = self._build_search_url(keyword, location, page, days_old)
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            page_jobs = self._parse_search_results(response.text)
            if not page_jobs:
                break

            for job in page_jobs:
                key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))
                existing = {
                    (existing_job.get("title", ""), existing_job.get("company", ""), existing_job.get("location", ""))
                    for existing_job in jobs
                }
                if key in existing:
                    continue

                jobs.append(job)
                if len(jobs) >= limit:
                    break

            page += 1

        enriched_jobs = []
        for job in jobs[:limit]:
            try:
                enriched_jobs.append(self._enrich_job_details(job))
            except Exception as exc:
                logger.debug(f"Error enriching Built In job {job.get('link')}: {exc}")
                job.setdefault("salary", "Not specified")
                job.setdefault("description", "")
                enriched_jobs.append(job)
            time.sleep(0.5)

        logger.info(f"  Found {len(enriched_jobs)} Built In jobs")
        return enriched_jobs

    def _build_search_url(self, keyword: str, location: str, page: int, days_old: int = 1) -> str:
        encoded_keyword = quote(keyword)
        normalized_location = location.strip().lower()

        # Map days_old to Built In's timeframe filter values
        if days_old <= 1:
            timeframe = "last-24-hours"
        elif days_old <= 7:
            timeframe = "last-week"
        elif days_old <= 30:
            timeframe = "last-month"
        else:
            timeframe = ""

        if normalized_location == "remote":
            base = f"{self.base_url}/jobs/remote?search={encoded_keyword}"
        else:
            city = quote(self._extract_city(location))
            base = f"{self.base_url}/jobs?search={encoded_keyword}&city={city}"

        if timeframe:
            base = f"{base}&timeframe={timeframe}"

        if page > 1:
            base = f"{base}&page={page}"

        return base

    def _extract_city(self, location: str) -> str:
        if "," in location:
            return location.split(",", 1)[0].strip()
        return location.strip()

    def _parse_search_results(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div[data-id='job-card']")

        jobs = []
        for card in cards:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        return jobs

    def _parse_job_card(self, card) -> Optional[Dict]:
        title_link = card.select_one("a[data-id='job-card-title']")
        if not title_link:
            return None

        title = title_link.get_text(" ", strip=True)
        link = title_link.get("href", "").strip()
        if link and not link.startswith("http"):
            link = f"{self.base_url}{link}"

        company_elem = card.select_one("a[data-id='company-title'] span") or card.select_one("a[data-id='company-title']")
        company = company_elem.get_text(" ", strip=True) if company_elem else "Unknown"

        location = "Location not specified"
        location_elem = card.select_one("span[aria-label='Job locations']")
        if location_elem:
            tooltip = location_elem.get("data-bs-title", "")
            tooltip_text = BeautifulSoup(tooltip, "html.parser").get_text(" | ", strip=True)
            location = tooltip_text or location_elem.get_text(" ", strip=True)

        salary = "Not specified"
        for span in card.select("span.font-barlow.text-gray-04"):
            text = span.get_text(" ", strip=True)
            if self._extract_salary_text(text):
                salary = self._extract_salary_text(text)
                break

        description = self._extract_summary_text(card.get_text(" ", strip=True), title, company)

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "link": link,
            "description": description,
            "source": "builtin",
        }

    def _extract_summary_text(self, text: str, title: str, company: str) -> str:
        cleaned = text.replace(title, "", 1).replace(company, "", 1).strip()
        parts = cleaned.split("Top Skills:")
        return parts[0][:500].strip()

    def _extract_salary_text(self, text: str) -> str:
        if not text:
            return ""

        patterns = [
            r"\$\s?\d[\d,]*(?:\s?[—-]\s?\$?\d[\d,]*)?\s*(?:USD\s*)?(?:Annually|Hourly|Monthly|Weekly)",
            r"\d[\d,]*K\s?[—-]\s?\d[\d,]*K\s*(?:Annually|Hourly|Monthly|Weekly)",
            r"\$\s?\d[\d,]*(?:\s?[—-]\s?\$?\d[\d,]*)?\s*USD",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return re.sub(r"\s+", " ", match.group(0)).strip()

        return ""

    def _enrich_job_details(self, job: Dict) -> Dict:
        link = job.get("link")
        if not link:
            job.setdefault("salary", "Not specified")
            job.setdefault("description", "")
            return job

        response = self.session.get(link, timeout=30)
        response.raise_for_status()
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)

        description_match = re.search(
            r"Job Description\s*(.*?)\s*(?:Read Full Description|## Top Skills|Top Skills)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if description_match:
            job["description"] = re.sub(r"\s+", " ", description_match.group(1)).strip()

        salary = self._extract_salary_text(text)
        if salary:
            job["salary"] = salary
        else:
            job.setdefault("salary", "Not specified")

        return job


def scrape_builtin(keywords: List[str], locations: List[str], max_jobs: int = 25, days_old: int = 1) -> List[Dict]:
    """Convenience wrapper for Built In scraping.
    
    Args:
        keywords: List of job title keywords to search
        locations: List of locations (e.g., "Denver, CO", "remote")
        max_jobs: Maximum number of jobs to scrape per keyword
        days_old: Only return jobs posted within this many days (1 = last 24 hours)
    """
    scraper = BuiltInScraper()
    return scraper.scrape_jobs(keywords, locations, max_jobs, days_old)


if __name__ == "__main__":
    jobs = scrape_builtin(["DevOps Engineer"], ["Denver, CO", "remote"], max_jobs=5)
    print(f"Found {len(jobs)} Built In jobs")
    for job in jobs[:3]:
        print(job["title"], "-", job["company"], "-", job["salary"])
