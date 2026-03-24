#!/usr/bin/env python3
"""
Combined job scraper runner for Indeed and Built In.

Uses the same config.json schema as the single-site scripts and writes one
timestamped results folder with site-specific subfolders plus a comparison
report.
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple

from builtin_scraper import scrape_builtin
from indeed_scraper import scrape_indeed
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


def annotate_source(jobs: List[Dict], source: str) -> List[Dict]:
    """Add a source field to each job."""
    return [{**job, 'source': source} for job in jobs]


def normalize_job_key(job: Dict) -> Tuple[str, str]:
    """Normalize title/company for overlap comparison across sites."""
    title = re.sub(r'\s+', ' ', job.get('title', '').strip().lower())
    company = re.sub(r'\s+', ' ', job.get('company', '').strip().lower())
    return title, company


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
    indeed_jobs: List[Dict],
    builtin_jobs: List[Dict],
    combined_jobs: List[Dict],
    output_path: str,
):
    """Save a human-readable comparison report."""
    indeed_keys = {normalize_job_key(job) for job in indeed_jobs}
    builtin_keys = {normalize_job_key(job) for job in builtin_jobs}
    overlap = indeed_keys & builtin_keys

    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write('JOB SOURCE COMPARISON REPORT\n')
        handle.write('=' * 80 + '\n')
        handle.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        handle.write(f"Indeed jobs: {len(indeed_jobs)}\n")
        handle.write(f"Built In jobs: {len(builtin_jobs)}\n")
        handle.write(f"Combined jobs: {len(combined_jobs)}\n")
        handle.write(f"Overlap by title+company: {len(overlap)}\n")
        handle.write(f"Indeed-only jobs: {len(indeed_keys - builtin_keys)}\n")
        handle.write(f"Built In-only jobs: {len(builtin_keys - indeed_keys)}\n\n")

        if overlap:
            handle.write('OVERLAPPING JOBS\n')
            handle.write('-' * 80 + '\n')
            for title, company in sorted(overlap):
                handle.write(f"• {title} @ {company}\n")
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


def main(resume_path: str = None, output_dir: str = None, config_path: str = 'config.json', days_old: int = None) -> int:
    logger.info('=' * 80)
    logger.info('MULTI-SOURCE JOB SCRAPER - Starting')
    logger.info('=' * 80)

    config = load_config(config_path)

    days_old_override = days_old
    resume_path = resume_path or config.get('resume_path')
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

    logger.info('\nStep 2: Scraping and ranking job postings...')
    try:
        indeed_ranked = run_source('indeed', scrape_indeed, resume_data, keywords, locations, max_jobs, days_old)
        builtin_ranked = run_source('builtin', scrape_builtin, resume_data, keywords, locations, max_jobs, days_old)
    except Exception as exc:
        logger.error(f"✗ Failed during scraping/ranking: {exc}")
        return 1

    if not indeed_ranked and not builtin_ranked:
        logger.warning('No jobs found from either source. Exiting.')
        return 1

    logger.info('\nStep 3: Saving site outputs and comparison report...')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(output_dir, timestamp)
    indeed_dir = os.path.join(run_dir, 'indeed')
    builtin_dir = os.path.join(run_dir, 'builtin')
    comparison_dir = os.path.join(run_dir, 'comparison')

    try:
        setup_output_dir(indeed_dir)
        setup_output_dir(builtin_dir)
        setup_output_dir(comparison_dir)

        if indeed_ranked:
            save_site_outputs(indeed_ranked, indeed_dir)
        if builtin_ranked:
            save_site_outputs(builtin_ranked, builtin_dir)

        combined_ranked = sorted(
            [*indeed_ranked, *builtin_ranked],
            key=lambda job: job.get('compatibility_score', 0),
            reverse=True,
        )

        comparison_payload = {
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'indeed_count': len(indeed_ranked),
            'builtin_count': len(builtin_ranked),
            'combined_count': len(combined_ranked),
            'jobs': [
                {**job, 'rank': index + 1}
                for index, job in enumerate(combined_ranked)
            ],
        }

        save_comparison_csv(combined_ranked, os.path.join(comparison_dir, 'job_comparison.csv'))
        save_comparison_json(comparison_payload, os.path.join(comparison_dir, 'job_comparison.json'))
        save_comparison_summary(
            indeed_ranked,
            builtin_ranked,
            combined_ranked,
            os.path.join(comparison_dir, 'job_comparison.txt'),
        )
        logger.info(f"✓ Results saved to {run_dir}/")
    except Exception as exc:
        logger.error(f"✗ Failed to save outputs: {exc}")
        return 1

    logger.info('\n' + '=' * 80)
    logger.info('COMPLETE - Check results/ directory for indeed, builtin, and comparison output')
    logger.info('=' * 80)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run Indeed and Built In scrapers and compare the ranked results'
    )
    parser.add_argument('--resume', help='Path to resume PDF')
    parser.add_argument('--output', help='Output directory for results')
    parser.add_argument('--config', default='config.json', help='Path to config.json (default: config.json)')
    parser.add_argument('--days', type=int, default=None, help='Only include jobs posted within this many days (overrides config.json days_old)')

    args = parser.parse_args()
    sys.exit(main(resume_path=args.resume, output_dir=args.output, config_path=args.config, days_old=args.days))