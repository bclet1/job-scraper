"""Site-specific job scraper modules.

Each file in this package follows the naming convention ``<site>_scraper.py``
and must expose a module-level function ``scrape_<site>(keywords, locations,
max_jobs, days_old) -> List[Dict]``.

Adding a new scraper is as simple as dropping a new ``<site>_scraper.py``
file here — ``multi_job_scraper.py`` discovers and loads them automatically.
"""
