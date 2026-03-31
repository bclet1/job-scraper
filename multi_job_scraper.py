#!/usr/bin/env python3
"""
Combined job scraper runner for Indeed, Built In, and LinkedIn.

Uses the same config.json schema for all scrapers and writes one timestamped
results folder with site-specific subfolders plus a comparison report.
"""

import argparse
import csv
import importlib
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Dict, List, Tuple

from logging_setup import configure_logging
from pipeline_utils import (
    load_config,
    save_results_csv,
    save_results_json,
    save_results_summary,
    setup_output_dir,
)
from matcher import rank_jobs
from resume_parser import parse_resume

configure_logging()
logger = logging.getLogger(__name__)


def load_scrapers(scrapers_dir: str = 'scrapers') -> List[Tuple[str, Callable]]:
    """Discover and return all scrapers from *scrapers_dir*.

    Scans for ``<site>_scraper.py`` files and loads the ``scrape_<site>``
    function from each.  Returns a list of (site_label, callable) tuples
    sorted alphabetically so execution order is deterministic.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    scrapers_path = os.path.join(base, scrapers_dir)
    sources: List[Tuple[str, Callable]] = []

    for filename in sorted(os.listdir(scrapers_path)):
        if not filename.endswith('_scraper.py'):
            continue
        site = filename[: -len('_scraper.py')]          # e.g. "indeed"
        module_name = f'{scrapers_dir}.{filename[:-3]}' # e.g. "scrapers.indeed_scraper"
        fn_name = f'scrape_{site}'
        try:
            module = importlib.import_module(module_name)
            fn = getattr(module, fn_name, None)
            if fn and callable(fn):
                sources.append((site, fn))
                logger.debug(f'Loaded scraper: {fn_name} from {module_name}')
            else:
                logger.warning(f'No {fn_name}() in {module_name} — skipped')
        except Exception as exc:
            logger.warning(f'Failed to load {module_name}: {exc}')

    return sources


def annotate_source(jobs: List[Dict], source: str) -> List[Dict]:
    """Add a source field to each job."""
    return [{**job, 'source': source} for job in jobs]


def normalize_job_key(job: Dict) -> Tuple[str, str]:
    """Normalize title/company for overlap comparison across sites."""
    title = re.sub(r'\s+', ' ', job.get('title', '').strip().lower())
    company = re.sub(r'\s+', ' ', job.get('company', '').strip().lower())
    return title, company


def deduplicate_combined(jobs: List[Dict]) -> List[Dict]:
    """Remove cross-site duplicate jobs, keeping the highest-scored copy.

    Assumes *jobs* is already sorted by compatibility_score descending so the
    first occurrence of each (title, company) key is always the best match.
    """
    seen: set = set()
    unique: List[Dict] = []
    for job in jobs:
        key = normalize_job_key(job)
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def save_site_outputs(jobs: List[Dict], site_dir: str):
    """Save site outputs using the existing Indeed-style report format."""
    setup_output_dir(site_dir)
    save_results_csv(jobs, os.path.join(site_dir, 'job_rankings.csv'))
    save_results_json(jobs, os.path.join(site_dir, 'job_rankings.json'))
    save_results_summary(jobs, os.path.join(site_dir, 'job_rankings.txt'))


def save_comparison_csv(comparison_rows: List[Dict], output_path: str):
    """Save a comparison CSV across both sources."""
    fieldnames = [
        'rank',
        'source',
        'compatibility_score',
        'title',
        'company',
        'location',
        'salary',
        'matched_skills',
        'missing_skills',
        'link',
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for index, job in enumerate(comparison_rows, 1):
            writer.writerow({
                'rank': index,
                'source': job.get('source', ''),
                'compatibility_score': job.get('compatibility_score', ''),
                'title': job.get('title', ''),
                'company': job.get('company', ''),
                'location': job.get('location', ''),
                'salary': job.get('salary', ''),
                'matched_skills': job.get('matched_skills', ''),
                'missing_skills': job.get('missing_skills', ''),
                'link': job.get('link', ''),
            })


def save_comparison_json(payload: Dict, output_path: str):
    """Save comparison metadata and combined rankings to JSON."""
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def save_comparison_summary(
    source_jobs: Dict[str, List[Dict]],
    combined_jobs: List[Dict],
    output_path: str,
    duplicates_removed: int = 0,
):
    """
    Save a human-readable comparison report for an arbitrary number of sources.

    Args:
        source_jobs: Mapping of source label -> ranked job list.
        combined_jobs: Deduplicated, merged, score-sorted job list.
        output_path: File path to write the report.
        duplicates_removed: Number of cross-site duplicate entries removed.
    """
    # Build normalised key sets per source
    key_sets = {
        label: {normalize_job_key(job) for job in jobs}
        for label, jobs in source_jobs.items()
    }

    # Pairwise overlap detection across all source pairs
    source_labels = list(key_sets.keys())
    overlap_pairs: List[tuple] = []
    for i in range(len(source_labels)):
        for j in range(i + 1, len(source_labels)):
            a, b = source_labels[i], source_labels[j]
            shared = key_sets[a] & key_sets[b]
            if shared:
                overlap_pairs.append((a, b, shared))

    # Union overlap (jobs that appear in ANY two or more sources)
    all_keys_list = list(key_sets.values())
    union_overlap: set = set()
    for i in range(len(all_keys_list)):
        for j in range(i + 1, len(all_keys_list)):
            union_overlap |= all_keys_list[i] & all_keys_list[j]

    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write('JOB SOURCE COMPARISON REPORT\n')
        handle.write('=' * 80 + '\n')
        handle.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        for label, jobs in source_jobs.items():
            handle.write(f"{label.title()} jobs: {len(jobs)}\n")
        handle.write(f"Combined unique jobs: {len(combined_jobs)}\n")
        handle.write(f"Cross-site duplicates removed: {duplicates_removed}\n\n")

        # Per-source unique counts
        for label, keys in key_sets.items():
            other_keys: set = set()
            for other_label, other in key_sets.items():
                if other_label != label:
                    other_keys |= other
            handle.write(f"{label.title()}-only jobs: {len(keys - other_keys)}\n")
        handle.write('\n')

        # Pairwise overlaps
        if overlap_pairs:
            handle.write('OVERLAPPING JOBS (by source pair)\n')
            handle.write('-' * 80 + '\n')
            for a, b, shared in overlap_pairs:
                handle.write(f"  {a.title()} ∩ {b.title()} ({len(shared)} job(s)):\n")
                for title, company in sorted(shared):
                    handle.write(f"    • {title} @ {company}\n")
            handle.write('\n')

        handle.write('TOP COMBINED MATCHES\n')
        handle.write('-' * 80 + '\n')
        for index, job in enumerate(combined_jobs[:20], 1):
            handle.write(f"\nRANK #{index}\n")
            handle.write(f"Source:           {job.get('source', 'Unknown')}\n")
            handle.write(f"Score:            {job.get('compatibility_score', 0)}%\n")
            handle.write(f"Title:            {job.get('title', 'Unknown')}\n")
            handle.write(f"Company:          {job.get('company', 'Unknown')}\n")
            handle.write(f"Location:         {job.get('location', 'Unknown')}\n")
            handle.write(f"Salary:           {job.get('salary', 'Not specified')}\n")
            handle.write(f"Matched Skills:   {job.get('matched_skills', 'None') or 'None'}\n")
            handle.write(f"Missing Skills:   {job.get('missing_skills', 'None') or 'None'}\n")
            handle.write(f"Link:             {job.get('link', 'N/A')}\n")


def run_source(label: str, scraper_func, resume_data: Dict, keywords: List[str], locations: List[str], max_jobs: int, days_old: int = 1) -> List[Dict]:
    """Scrape, rank, and annotate a single source."""
    logger.info(f"\nScraping {label} job postings...")
    jobs = scraper_func(keywords, locations, max_jobs, days_old)
    if not jobs:
        logger.warning(f"No {label} jobs found")
        return []

    logger.info(f"✓ Scraped {len(jobs)} {label} jobs")
    ranked = rank_jobs(resume_data, jobs)
    logger.info(f"✓ Ranked {len(ranked)} {label} jobs")
    return annotate_source(ranked, label)


def find_resume(resume_dir: str = './Resume') -> str:
    """Return the path to the single PDF in *resume_dir*.

    Raises FileNotFoundError if none or more than one PDF is found.
    """
    pdfs = [
        os.path.join(resume_dir, f)
        for f in os.listdir(resume_dir)
        if f.lower().endswith('.pdf')
    ] if os.path.isdir(resume_dir) else []

    if len(pdfs) == 1:
        return pdfs[0]
    if len(pdfs) == 0:
        raise FileNotFoundError(f"No PDF found in '{resume_dir}'. Place your resume there or pass --resume.")
    raise FileNotFoundError(
        f"Multiple PDFs found in '{resume_dir}': {pdfs}. Remove all but one or pass --resume."
    )


def main(resume_path: str = None, output_dir: str = None, config_path: str = 'config.json', days_old: int = None) -> int:
    logger.info('=' * 80)
    logger.info('MULTI-SOURCE JOB SCRAPER - Starting')
    logger.info('=' * 80)

    config = load_config(config_path)

    days_old_override = days_old
    resume_path = resume_path or config.get('resume_path') or find_resume()
    output_dir = output_dir or config.get('output_dir', './results')
    keywords = config.get('keywords', [])
    locations = config.get('locations', [])
    max_jobs = config.get('max_jobs', 25)
    days_old = days_old_override if days_old_override is not None else config.get('days_old', 1)

    logger.info(f"Resume: {resume_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Keywords: {', '.join(keywords[:3])}... ({len(keywords)} total)")
    logger.info(f"Locations: {', '.join(locations)}")
    logger.info(f"Max jobs per keyword: {max_jobs}")
    logger.info(f"Max days old: {days_old} day(s)")

    output_dir = setup_output_dir(output_dir)

    logger.info('\nStep 1: Parsing resume...')
    try:
        resume_data = parse_resume(resume_path)
        logger.info('✓ Resume parsed successfully')
    except Exception as exc:
        logger.error(f"✗ Failed to parse resume: {exc}")
        return 1

    logger.info('\nStep 2: Scraping and ranking job postings (parallel)...')
    sources = load_scrapers()
    results: Dict[str, List[Dict]] = {}
    try:
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            future_to_label = {
                executor.submit(
                    run_source, label, fn, resume_data, keywords, locations, max_jobs, days_old
                ): label
                for label, fn in sources
            }
            for future in as_completed(future_to_label):
                label = future_to_label[future]
                try:
                    results[label] = future.result()
                except Exception as exc:
                    logger.error(f"✗ {label} scraping failed: {exc}")
                    results[label] = []
    except Exception as exc:
        logger.error(f"✗ Failed during parallel scraping/ranking: {exc}")
        return 1

    if not any(results.values()):
        logger.warning('No jobs found from any source. Exiting.')
        return 1

    logger.info('\nStep 3: Saving site outputs and comparison report...')
    timestamp = datetime.now().strftime('%m-%d_%H-%M')
    run_dir = os.path.join(output_dir, timestamp)
    comparison_dir = os.path.join(run_dir, 'comparison')

    try:
        for label in results:
            setup_output_dir(os.path.join(run_dir, label))
        setup_output_dir(comparison_dir)

        for label, ranked in results.items():
            if ranked:
                save_site_outputs(ranked, os.path.join(run_dir, label))

        combined_all = sorted(
            [job for ranked in results.values() for job in ranked],
            key=lambda job: job.get('compatibility_score', 0),
            reverse=True,
        )
        combined_ranked = deduplicate_combined(combined_all)
        duplicates_removed = len(combined_all) - len(combined_ranked)

        comparison_payload = {
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            **{f'{label}_count': len(ranked) for label, ranked in results.items()},
            'combined_count':    len(combined_ranked),
            'duplicates_removed': duplicates_removed,
            'jobs': [
                {**job, 'rank': index + 1}
                for index, job in enumerate(combined_ranked)
            ],
        }

        source_jobs = dict(results)

        save_comparison_csv(combined_ranked, os.path.join(comparison_dir, 'job_comparison.csv'))
        save_comparison_json(comparison_payload, os.path.join(comparison_dir, 'job_comparison.json'))
        save_comparison_summary(
            source_jobs,
            combined_ranked,
            os.path.join(comparison_dir, 'job_comparison.txt'),
            duplicates_removed=duplicates_removed,
        )
        logger.info(f"✓ Results saved to {run_dir}/")
    except Exception as exc:
        logger.error(f"✗ Failed to save outputs: {exc}")
        return 1

    logger.info('\n' + '=' * 80)
    site_list = ', '.join(results.keys())
    logger.info(f"COMPLETE - Check results/ directory for {site_list}, and comparison output")
    logger.info('=' * 80)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run Indeed, Built In, LinkedIn, and Dice scrapers and compare the ranked results'
    )
    parser.add_argument('--resume', help='Path to resume PDF')
    parser.add_argument('--output', help='Output directory for results')
    parser.add_argument('--config', default='config.json', help='Path to config.json (default: config.json)')
    parser.add_argument('--days', type=int, default=None, help='Only include jobs posted within this many days (overrides config.json days_old)')

    args = parser.parse_args()
    sys.exit(main(resume_path=args.resume, output_dir=args.output, config_path=args.config, days_old=args.days))