# Job Scraper — Claude Agent Context

## Project Purpose
Scrape job postings from Indeed, Built In, LinkedIn, and Dice, then rank them by
compatibility with a resume PDF using semantic AI embeddings. Output is written to
timestamped result folders under `results/`.

---

## Architecture

```
multi_job_scraper.py   ← Entry point. Orchestrates the full pipeline.
├── scrapers/              ← Auto-discovered site scrapers (drop a file here to add a site)
│   ├── indeed_scraper.py  ← Playwright-based scraper (JavaScript-rendered SPA)
│   ├── builtin_scraper.py ← requests + BeautifulSoup scraper
│   ├── linkedin_scraper.py← Playwright-based scraper
│   ├── dice_scraper.py    ← Playwright-based scraper (React SPA)
│   └── glassdoor_scraper.py ← Playwright-based scraper
├── matcher.py         ← Semantic matching via sentence-transformers
├── resume_parser.py   ← PDF text extraction (pypdf)
├── pipeline_utils.py  ← Shared config loading + CSV/JSON/TXT output helpers
├── logging_setup.py   ← Suppresses noisy third-party loggers
├── config.json        ← Search configuration (keywords, locations, max_jobs, etc.)
└── results/           ← Output directory (timestamped subfolders per run)
```

### Data Flow
1. `parse_resume()` → extracts text from PDF
2. All scrapers run **in parallel** via `ThreadPoolExecutor` in `multi_job_scraper.py`
3. Each scraper returns `List[Dict]` with fields: `title`, `company`, `location`, `salary`, `link`, `description`
4. `rank_jobs()` scores each job against the resume using cosine similarity (sentence-transformers `all-MiniLM-L6-v2`)
5. Results are annotated with `source`, saved per-site, then merged into a deduped comparison report

---

## Scraper Contract

Every scraper **must** expose a module-level function with this exact signature:

```python
def scrape_<site>(
    keywords: List[str],
    locations: List[str],
    max_jobs: int,
    days_old: int,
) -> List[Dict]:
    ...
```

The returned dicts must include these keys (empty string if unavailable):
- `title` — job title
- `company` — company name
- `location` — location string
- `salary` — salary range string (e.g. `"$120K-$140K"`) or `""`
- `link` — full URL to job posting
- `description` — job description text (used for matching)

Internally each scraper has a class (`IndeedScraper`, `DiceScraper`, etc.) and the
module-level function is a thin wrapper that instantiates it and calls `scrape_jobs()`.

---

## Adding a New Scraper

1. Create `scrapers/<site>_scraper.py` following the contract above.
2. That's it — the file is auto-discovered on the next run.

No changes to `multi_job_scraper.py` are needed.

---

## Testing a New Scraper in Isolation

Never run `multi_job_scraper.py` to test a scraper — it's 2–10 minutes and runs all
sites in parallel. Instead, test the new scraper directly:

```python
# Quick smoke test — paste into a scratch script or run interactively
from scrapers.<site>_scraper import scrape_<site>

jobs = scrape_<site>(
    keywords=["DevOps Engineer"],
    locations=["remote"],
    max_jobs=3,
    days_old=7,
)

print(f"Returned {len(jobs)} jobs")
for job in jobs:
    print(job.get('title'), '|', job.get('company'), '|', job.get('salary'))
    print('  link:', job.get('link'))
    print('  desc chars:', len(job.get('description', '')))
    print()
```

Or run the scraper file directly if it has a `__main__` block:
```bash
python scrapers/<site>_scraper.py
```

### What to check
- `len(jobs) > 0` — scraper returns results at all
- All required fields present and non-None (title, company, location, link, description)
- `description` has meaningful length (>100 chars) — short descriptions hurt match scores
- `link` is a full URL (starts with `https://`)
- `salary` is `""` (not `None`) when not available
- No duplicates by (title, company)

---

## Validating Results After a Full Run

The fastest way to spot-check a run:

```bash
# View the human-readable comparison report
cat results/<timestamp>/comparison/job_comparison.txt

# Or open the CSV in Excel / check top 5 in terminal
python -c "
import json
jobs = json.load(open('results/<timestamp>/comparison/job_comparison.json'))['jobs']
for j in jobs[:5]:
    print(f\"{j['compatibility_score']:.1f}%  {j['title']} @ {j['company']}  [{j['source']}]\")
"
```

### Signs of a healthy run
- Scores spread across ~55–85 range (not all identical)
- `matched_skills` contains recognizable tech (Kubernetes, Terraform, etc.)
- `description` field is populated (empty = scraper missed the detail page)
- Mix of sources in the comparison report

### Common failure modes
| Symptom | Likely cause |
|---|---|
| 0 jobs from a site | Site blocked the scraper; try increasing `time.sleep()` or rotating user-agent |
| All scores identical | Description field is empty — scraper not fetching job detail pages |
| `salary` is `None` | Return `""` not `None` when salary unavailable (breaks CSV output) |
| Duplicate jobs | Dedup key `(title, company)` normalization mismatch — check casing |
| Playwright timeout | Site is slow; increase `page.wait_for_selector()` timeout or add explicit waits |

---

## Configuration (`config.json`)

| Field | Type | Description |
|---|---|---|
| `keywords` | `List[str]` | Job title search terms |
| `keywords_disabled` | `List[str]` | Ignored — used to park inactive keywords |
| `locations` | `List[str]` | Location strings; use `"remote"` for remote |
| `max_jobs` | `int` | Max jobs per keyword per scraper |
| `days_old` | `int` | Only include postings from last N days |
| `resume_path` | `str` | *(Optional)* Path to resume PDF — auto-detected from `./Resume/*.pdf` if omitted |
| `output_dir` | `str` | Base output directory (default `./results`) |

---

## CLI

```bash
python multi_job_scraper.py                         # uses config.json defaults
python multi_job_scraper.py --days 7                # override days_old
python multi_job_scraper.py --resume ./Resume/r.pdf # override resume path
python multi_job_scraper.py --config other.json     # use alternate config

# Windows shortcut
.\run.bat
```

---

## Output Structure

```
results/
└── MM-DD_HH-MM/          ← timestamp of run
    ├── indeed/
    │   ├── job_rankings.csv
    │   ├── job_rankings.json
    │   └── job_rankings.txt
    ├── builtin/
    ├── linkedin/
    ├── dice/
    └── comparison/
        ├── job_comparison.csv   ← all sources merged, deduped, ranked
        ├── job_comparison.json
        └── job_comparison.txt   ← human-readable with overlap analysis
```

### Key Output Fields
- `compatibility_score` — 0–100 semantic match percentage
- `matched_skills` — comma-separated skills found in both resume and posting
- `missing_skills` — top 5 skills in posting but not on resume (not prioritized)
- `source` — which site the job came from (comparison report only)

---

## Matching Logic (`matcher.py`)

- Model: `sentence-transformers/all-MiniLM-L6-v2` (loaded once per thread)
- Score formula: `max(0, (cosine_similarity + 1) / 2 * 100)` — scores cluster in ~55–85 range, not 0–100
- Tech keyword extraction uses a hardcoded set in `extract_tech_keywords()`
- `missing_skills` is not ranked by importance — it's the raw set difference

---

## Known Issues / Improvement Backlog

- [x] Step 3 output saving is hardcoded per-site — needs data-driven refactor
- [ ] `missing_skills` not ranked by cross-posting frequency
- [x] `PyPDF2` → `pypdf` migration complete
- [ ] Salary stored as raw string — no numeric parsing for sort/filter
- [ ] No result caching — re-scrapes everything on each run
- [ ] No tests — add pytest coverage for `matcher.py` and `pipeline_utils.py`
- [ ] `keywords_disabled` is a config smell — needs proper enable/disable support

---

## Dependencies

Installed via `pip install -r requirements.txt` then `playwright install chromium`.

Key packages: `playwright`, `beautifulsoup4`, `sentence-transformers`, `pypdf`,
`requests`, `torch`.

## MCP Server

An MCP server (`mcp_server.py`) is available for Claude Desktop / claude CLI integration.
See setup instructions at the bottom of that file. Tools exposed:
- `get_config` / `update_config`
- `get_latest_results` / `get_top_matches`
- `analyze_missing_skills`
- `run_scraper`
