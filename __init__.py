"""Job Scraper and Ranker Package"""

__version__ = "1.0.0"
__author__ = "Bclet"

from .resume_parser import parse_resume
from .scrapers.indeed_scraper import scrape_indeed
from .matcher import rank_jobs

__all__ = ['parse_resume', 'scrape_indeed', 'rank_jobs']
