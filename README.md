# Job Scraper & Ranker

Scrape Indeed, Built In, LinkedIn, Dice, and Glassdoor job postings and automatically rank them by compatibility with your resume using semantic AI matching. Generates tailored cover letters for top matches.

## Features

✅ **Multi-site Scraping** — Indeed, Built In, LinkedIn, Dice, and Glassdoor in parallel  
✅ **Semantic Matching** — AI embeddings understand skills, not just keywords  
✅ **Smart Ranking** — Rates jobs by résumé fit with matched/missing skills  
✅ **Cover Letter Generation** — Produces 3 tailored variants (formal, conversational, achievement-focused) for the top 25 jobs via OpenAI  
✅ **Multi-format Output** — CSV, JSON, and TXT per site plus a merged comparison report  
✅ **Auto-discovered Scrapers** — Drop a `<site>_scraper.py` into `scrapers/` to add a new source  
✅ **MCP Server** — Claude Desktop / claude CLI integration via `mcp_server.py`

## Quick Start

### 1. Install Dependencies

```bash
# Option A: pip
pip install -r requirements.txt
playwright install chromium

# Option B: uv (faster)
uv pip install -r requirements.txt
uv run playwright install chromium
```

### 2. Prepare Your Resume

Place your resume PDF in the `Resume/` folder:
```
job-scraper/
├── Resume/
│   └── your_resume.pdf
├── config.json
└── multi_job_scraper.py
```

The scraper auto-detects the single PDF in `Resume/`. If there are multiple PDFs, pass `--resume` explicitly.

### 3. Configure Search (Optional)

Edit `config.json`:

```json
{
  "keywords": [
    "DevOps Engineer",
    "Platform Engineer"
  ],
  "locations": [
    "Denver, CO",
    "remote"
  ],
  "max_jobs": 25,
  "days_old": 1,
  "output_dir": "./results",
  "cover_letter_model": "gpt-4o-mini",
  "cover_letter_instructions": "Write a professional cover letter..."
}
```

| Field | Description |
|-------|-------------|
| `keywords` | Job title search terms |
| `keywords_disabled` | Parked/inactive keywords (ignored at runtime) |
| `locations` | Location strings; use `"remote"` for remote |
| `max_jobs` | Max jobs per keyword per scraper |
| `days_old` | Only include postings from the last N days |
| `resume_path` | *(Optional)* Explicit path to resume PDF |
| `output_dir` | Base output directory (default `./results`) |
| `cover_letter_model` | OpenAI model for cover letters (default `gpt-4o-mini`) |
| `cover_letter_instructions` | Prompt instructions for cover letter style |

### 4. Set Up Environment Variables

Create a `.env` file for the cover letter feature:

```
OPENAI_API_KEY=sk-...
```

Cover letter generation is skipped gracefully if no key is set.

### 5. Run the Scraper

```bash
python multi_job_scraper.py
```

Wait 2–10 minutes depending on job volume. Progress is logged to the console.

**Windows shortcut:** `.\run.bat`

### CLI Options

```bash
python multi_job_scraper.py --days 7                  # override days_old
python multi_job_scraper.py --resume ./Resume/r.pdf   # override resume path
python multi_job_scraper.py --output ./my-results     # override output dir
python multi_job_scraper.py --config other.json       # use alternate config
```

### 6. Check Results

Results are saved in a timestamped subfolder:

```
results/
└── MM-DD_HH-MM/
    ├── indeed/
    │   ├── job_rankings.csv
    │   ├── job_rankings.json
    │   └── job_rankings.txt
    ├── builtin/
    ├── linkedin/
    ├── dice/
    ├── glassdoor/
    └── comparison/
        ├── job_comparison.csv      ← all sources merged, deduped, ranked
        ├── job_comparison.json
        ├── job_comparison.txt      ← human-readable with overlap analysis
        └── cover_letters/          ← 3 cover letter variants per top-25 job
```

## Output Format

### CSV Columns (comparison report)

| Column | Content |
|--------|---------|
| `rank` | Ranking position (1 = best match) |
| `source` | Which site the job came from |
| `compatibility_score` | Semantic match percentage (typically 55–85) |
| `title` | Job title |
| `company` | Company name |
| `location` | Job location |
| `salary` | Salary range string, or empty if not listed |
| `matched_skills` | Skills from your résumé found in the posting |
| `missing_skills` | Skills in the posting not found on your résumé |
| `link` | Full URL to the job posting |

## How Matching Works

1. **Resume Parsing** — Extracts text from your PDF via `pypdf`
2. **Parallel Scraping** — All sites scraped simultaneously via `ThreadPoolExecutor`
3. **Semantic Embeddings** — Resume and job descriptions encoded with `sentence-transformers/all-MiniLM-L6-v2`
4. **Cosine Similarity** — Scores scaled to a 0–100 range (realistic scores cluster ~55–85)
5. **Skill Extraction** — Matched/missing tech keywords identified from a curated keyword set
6. **Deduplication** — Cross-site duplicates removed by normalised `(title, company)` key

**Why Semantic Matching?**
- Handles synonyms: "K8s" ≈ "Kubernetes", "CI/CD" ≈ "continuous integration"
- Understands context: "container orchestration" ≈ "Kubernetes"
- More accurate than keyword matching alone

## Adding a New Scraper

1. Create `scrapers/<site>_scraper.py` with this function signature:

```python
def scrape_<site>(
    keywords: List[str],
    locations: List[str],
    max_jobs: int,
    days_old: int,
) -> List[Dict]:
    ...
```

2. Return dicts with: `title`, `company`, `location`, `salary`, `link`, `description` (use `""` not `None` for missing fields).

3. That's it — the file is auto-discovered on the next run.

## MCP Server

`mcp_server.py` exposes job-scraper as an MCP tool server for Claude Desktop or the `claude` CLI.

**Tools available:**
- `get_config` / `update_config` — Read or write `config.json` settings
- `list_runs` — List all result run folders with timestamps
- `get_latest_results` — Load ranked jobs from the most recent (or specified) run
- `get_top_matches` — Return the top N jobs across all sources
- `analyze_missing_skills` — Aggregate missing skills across runs to surface résumé gaps
- `run_scraper` — Execute the full pipeline and return a summary

**Claude Desktop setup** — add to `~/AppData/Roaming/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "job-scraper": {
      "command": "python",
      "args": ["C:/local-repos/job-scraper/mcp_server.py"],
      "cwd": "C:/local-repos/job-scraper"
    }
  }
}
```

## Project Structure

```
job-scraper/
├── multi_job_scraper.py      # Entry point — orchestrates the full pipeline
├── scrapers/                 # Auto-discovered site scrapers
│   ├── indeed_scraper.py
│   ├── builtin_scraper.py
│   ├── linkedin_scraper.py
│   ├── dice_scraper.py
│   └── glassdoor_scraper.py
├── matcher.py                # Semantic job ranking
├── resume_parser.py          # PDF text extraction
├── cover_letter_generator.py # OpenAI cover letter generation
├── pipeline_utils.py         # Config loading + CSV/JSON/TXT output helpers
├── logging_setup.py          # Suppresses noisy third-party loggers
├── mcp_server.py             # MCP server for Claude Desktop / claude CLI
├── config.json               # Search keywords, locations, and settings
├── pyproject.toml            # Project metadata and dependencies
├── requirements.txt          # pip dependencies
└── results/                  # Output directory (timestamped subfolders per run)
```

## Technologies

- **Web Scraping**: Playwright (JavaScript/SPA sites), requests + BeautifulSoup (static sites)
- **PDF Parsing**: pypdf
- **NLP / Matching**: sentence-transformers, scikit-learn
- **Cover Letters**: OpenAI API (gpt-4o-mini by default)
- **MCP Integration**: mcp, anthropic

## Troubleshooting

| Symptom | Likely Cause |
|---------|-------------|
| 0 jobs from a site | Site blocked the scraper — try increasing `time.sleep()` or rotating user-agent |
| All scores identical | `description` field is empty — scraper not fetching job detail pages |
| `salary` is `None` | Return `""` not `None` when salary is unavailable (breaks CSV output) |
| Duplicate jobs | Dedup key `(title, company)` normalisation mismatch — check casing |
| Playwright timeout | Site is slow — increase `page.wait_for_selector()` timeout or add explicit waits |
| No cover letters generated | Missing `OPENAI_API_KEY` in `.env` — generation is skipped gracefully |
| First run is slow | AI model (~400 MB) downloads on first use; subsequent runs use the cached model |

## Notes

- **Rate Limiting**: Scrapers add delays between requests to avoid being blocked
- **Cover Letters**: Sent to the OpenAI API — ensure you're comfortable with that before running
- **Result Links**: Job links go directly to the source site; verify postings are still active before applying
**Questions?** Check the troubleshooting section or review the logs in job_scraper.py output.
