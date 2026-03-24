# Job Scraper & Ranker for Indeed + Built In

Scrape Indeed and Built In job postings and automatically rank them by compatibility with your resume using semantic AI matching.

## Features

✅ **Scrapes Indeed + Built In** - Collects job postings for multiple keywords and locations  
✅ **Semantic Matching** - Uses AI embeddings to understand skills, not just keywords  
✅ **Smart Ranking** - Rates jobs by resumé fit with matched/missing skills  
✅ **Multi-format Output** - CSV (spreadsheet), JSON (programmatic), and TXT (human-readable)  
✅ **Salary Tracking** - Extracts and records salary ranges from postings
✅ **Comparison Report** - Produces a combined cross-site comparison report

## Quick Start

### 1. Install Dependencies

```bash
# Option A: Using pip
pip install -r requirements.txt
playwright install chromium

# Option B: Using uv (faster)
uv pip install -r requirements.txt
uv run playwright install chromium
```

### 2. Prepare Your Resume

Place your resume PDF in the `Resume/` folder:
```
job-scraper/
├── Resume/
│   └── resume.pdf
├── config.json
└── multi_job_scraper.py
```

### 3. Configure Search (Optional)

Edit `config.json` to customize:

```json
{
  "keywords": [
    "DevOps Engineer",
    "Cloud Engineer",
    ...
  ],
  "locations": [
    "Denver, CO",
    "Burlington, VT",
    "remote"
  ],
  "max_jobs": 100,
  "resume_path": "../Jobs/Resume/BrianLetourneauResume2026.pdf",
  "output_dir": "./results"
}
```

### 4. Run the Scraper

```bash
python multi_job_scraper.py
```

Wait for scraping and ranking to complete (2-10 minutes depending on job volume).

### 5. Check Results

Results are saved in a timestamped run folder with:
- **`indeed/`** - Indeed rankings in CSV, JSON, and TXT
- **`builtin/`** - Built In rankings in CSV, JSON, and TXT
- **`comparison/`** - Combined comparison report in CSV, JSON, and TXT

## Output Format

### CSV Columns
| Column | Content |
|--------|---------|
| rank | Ranking position (1 = best match) |
| compatibility_score | 0-100 match percentage |
| title | Job title |
| company | Company name |
| location | Job location |
| salary | Salary range (if available) |
| matched_skills | Skills from your resume found in job posting |
| missing_skills | Top 5 skills mentioned in job but not on your resume |
| link | Indeed job posting link |
| description | Job description snippet |

### Example Output
```
rank,compatibility_score,title,company,location,salary,matched_skills,missing_skills,link,description
1,87.5,Senior DevOps Engineer,TechCorp,Denver CO,$140K-$160K,"Kubernetes, Docker, Terraform, AWS, Python","Kubernetes Operator, Helm Charts",https://indeed.com/viewjob?...,Build and maintain cloud infrastructure...
2,82.3,Platform Engineer,CloudStart,Remote,"$130K-$150K","AWS, CI/CD, Monitoring","Spinnaker, AWS CDK",https://indeed.com/viewjob?...,...
```

## How Matching Works

The ranking algorithm uses **semantic embeddings** to understand job requirements:

1. **Resume Parsing** - Extracts text, skills, and experience from PDF
2. **Job Scraping** - Collects postings from Indeed and Built In
3. **Semantic Analysis** - Converts resume and jobs to AI embeddings
4. **Similarity Scoring** - Calculates semantic match (0-100%)
5. **Skill Extraction** - Identifies matched/missing tech keywords
6. **Ranking** - Sorts by overall compatibility score

**Why Semantic Matching?**
- Matches synonyms: "K8s" = "Kubernetes", "CI/CD" = "continuous integration"
- Understands context: "container orchestration" ≈ "Kubernetes"
- More accurate than keyword matching alone

## Advanced Usage

### Custom Resume Path
```bash
python multi_job_scraper.py --resume /path/to/my/resume.pdf
```

### Custom Output Directory
```bash
python multi_job_scraper.py --output /path/to/results
```

### Custom Config File
```bash
python multi_job_scraper.py --config /path/to/custom_config.json
```

## Troubleshooting

### "Playwright not installed"
```bash
playwright install chromium
```

### "Connection timeout" or "Blocked by Cloudflare"
- Indeed's anti-bot protection may block after multiple requests
- Wait a few minutes and try again
- Try searching for fewer keywords or locations at once

### "Resume file not found"
- Check the `resume_path` in `config.json`
- Ensure the PDF file exists and is readable
- Paths can be absolute or relative to `multi_job_scraper.py`

### "No jobs found"
- Try different keywords or locations
- Check if Indeed has job postings for your search
- Verify your internet connection

### Slow Performance
- First run downloads AI model (~400MB) - this takes 1-2 minutes
- Subsequent runs are faster (model cached)
- Scraping 100 jobs takes ~5-10 minutes due to rate limiting

## Project Structure

```
job-scraper/
├── multi_job_scraper.py    # Main orchestration script
├── pipeline_utils.py       # Shared config/output helpers
├── resume_parser.py        # Parse resume from PDF
├── indeed_scraper.py       # Scrape job postings from Indeed
├── builtin_scraper.py      # Scrape job postings from Built In
├── matcher.py              # Rank jobs by resume match
├── config.json             # Search keywords, locations, paths
├── pyproject.toml          # Dependencies specification
├── requirements.txt        # pip dependencies (alternative)
├── README.md               # This file
└── results/                # Output directory (created on first run)
    ├── job_rankings_*.csv
    ├── job_rankings_*.json
    └── job_rankings_*.txt
```

## Technologies Used

- **Web Scraping**: Playwright (handles JavaScript/CloudFlare)
- **Parsing**: BeautifulSoup, PyPDF2
- **NLP**: sentence-transformers (semantic embeddings)
- **Data Processing**: pandas
- **Analysis**: scikit-learn

## Notes

- **Rate Limiting**: Scripts add delays between requests to avoid blocking
- **Salary Tracking**: May not be present on all job postings
- **Freshness**: Job links go directly to Indeed; verify apply links still work
- **Resume Privacy**: All processing is local; no data sent to external services

## Future Improvements

- [ ] Database caching to avoid re-scraping
- [ ] Application tracking (mark applied, visited, rejected)
- [ ] Email alerts for new high-match jobs
- [ ] Support for custom resume words/phrases below 70% match
- [ ] Resume improvement suggestions based on top jobs
- [ ] Filter by salary range, experience level
- [ ] Support for other job boards (LinkedIn, Glassdoor, etc.)

## License

MIT - Use freely for personal use

---

**Questions?** Check the troubleshooting section or review the logs in job_scraper.py output.
