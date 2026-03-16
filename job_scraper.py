#!/usr/bin/env python3
"""
Job Scraper and Ranker - Main Script

Scrapes Indeed for job postings and ranks them by resume compatibility.

Usage:
    python job_scraper.py
    python job_scraper.py --resume PATH_TO_RESUME --output PATH_TO_OUTPUT
"""

import json
import csv
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
import argparse
from typing import List, Dict

# Local imports
from resume_parser import parse_resume
from indeed_scraper import scrape_indeed
from matcher import rank_jobs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = 'config.json') -> Dict:
    """Load configuration from JSON file."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded config from {config_path}")
        return config
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        raise
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in {config_path}")
        raise


def setup_output_dir(output_dir: str) -> str:
    """Create output directory if it doesn't exist."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return output_dir


def save_results_csv(jobs: List[Dict], output_path: str):
    """Save ranked jobs to CSV."""
    if not jobs:
        logger.warning("No jobs to save")
        return
    
    csv_columns = [
        'rank',
        'compatibility_score',
        'title',
        'company',
        'location',
        'salary',
        'matched_skills',
        'missing_skills',
        'link',
        'description'
    ]
    
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            writer.writeheader()
            
            for rank, job in enumerate(jobs, 1):
                row = {col: job.get(col, '') for col in csv_columns}
                row['rank'] = rank
                writer.writerow(row)
        
        logger.info(f"Saved {len(jobs)} jobs to {output_path}")
    except Exception as e:
        logger.error(f"Error saving CSV: {e}")
        raise


def save_results_json(jobs: List[Dict], output_path: str):
    """Save ranked jobs to JSON."""
    if not jobs:
        logger.warning("No jobs to save")
        return
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            # Add rank to each job
            ranked_jobs = [
                {**job, 'rank': idx + 1}
                for idx, job in enumerate(jobs)
            ]
            json.dump(ranked_jobs, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(jobs)} jobs to {output_path}")
    except Exception as e:
        logger.error(f"Error saving JSON: {e}")
        raise


def save_results_summary(jobs: List[Dict], output_path: str):
    """Save a human-readable summary."""
    if not jobs:
        logger.warning("No jobs to save")
        return
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("JOB RANKING SUMMARY\n")
            f.write("=" * 80 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Jobs: {len(jobs)}\n\n")
            
            for rank, job in enumerate(jobs, 1):
                f.write(f"\n{'─' * 80}\n")
                f.write(f"RANK #{rank}\n")
                f.write(f"{'─' * 80}\n")
                f.write(f"Score:            {job.get('compatibility_score', 0)}%\n")
                f.write(f"Title:            {job.get('title', 'Unknown')}\n")
                f.write(f"Company:          {job.get('company', 'Unknown')}\n")
                f.write(f"Location:         {job.get('location', 'Unknown')}\n")
                f.write(f"Salary:           {job.get('salary', 'Not specified')}\n")
                
                # Format matched skills as a list
                matched_skills = job.get('matched_skills', '')
                if isinstance(matched_skills, str) and matched_skills:
                    skills_list = [s.strip() for s in matched_skills.split(',') if s.strip()]
                    if skills_list:
                        f.write(f"Matched Skills:   {len(skills_list)} skill(s)\n")
                        for skill in skills_list:
                            f.write(f"                  • {skill}\n")
                    else:
                        f.write(f"Matched Skills:   None\n")
                else:
                    f.write(f"Matched Skills:   None\n")
                
                # Format missing skills as a list
                missing_skills = job.get('missing_skills', '')
                if isinstance(missing_skills, str) and missing_skills:
                    skills_list = [s.strip() for s in missing_skills.split(',') if s.strip()]
                    if skills_list:
                        f.write(f"Missing Skills:   {len(skills_list)} skill(s)\n")
                        for skill in skills_list:
                            f.write(f"                  • {skill}\n")
                    else:
                        f.write(f"Missing Skills:   None\n")
                else:
                    f.write(f"Missing Skills:   None\n")
                
                f.write(f"Description:      {job.get('description', 'N/A')[:150]}...\n")
                f.write(f"Link:             {job.get('link', 'N/A')}\n")
        
        logger.info(f"Saved summary to {output_path}")
    except Exception as e:
        logger.error(f"Error saving summary: {e}")
        raise


def main(resume_path: str = None, output_dir: str = None, config_path: str = 'config.json'):
    """
    Main execution function.
    
    Args:
        resume_path: Optional path to resume (overrides config)
        output_dir: Optional output directory (overrides config)
        config_path: Path to config.json
    """
    logger.info("=" * 80)
    logger.info("JOB SCRAPER AND RANKER - Starting")
    logger.info("=" * 80)
    
    # Load configuration
    config = load_config(config_path)
    
    # Override with command line args if provided
    resume_path = resume_path or config.get('resume_path')
    output_dir = output_dir or config.get('output_dir', './results')
    
    keywords = config.get('keywords', [])
    locations = config.get('locations', [])
    max_jobs = config.get('max_jobs', 25)
    
    logger.info(f"Resume: {resume_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Keywords: {', '.join(keywords[:3])}... ({len(keywords)} total)")
    logger.info(f"Locations: {', '.join(locations)}")
    logger.info(f"Max jobs per keyword: {max_jobs}")
    logger.info(f"Expected total jobs: ~{max_jobs * len(keywords) * len(locations)} (before deduplication)")
    
    # Create output directory
    output_dir = setup_output_dir(output_dir)
    
    # Step 1: Parse resume
    logger.info("\nStep 1: Parsing resume...")
    try:
        resume_data = parse_resume(resume_path)
        logger.info(f"✓ Resume parsed successfully")
        logger.info(f"  - Full text: {len(resume_data['full_text'])} characters")
        logger.info(f"  - Skills section: {len(resume_data['skills'])} characters")
    except Exception as e:
        logger.error(f"✗ Failed to parse resume: {e}")
        return 1
    
    # Step 2: Scrape Indeed
    logger.info("\nStep 2: Scraping Indeed job postings...")
    try:
        jobs = scrape_indeed(keywords, locations, max_jobs)
        logger.info(f"✓ Scraped {len(jobs)} job postings")
        if jobs:
            logger.info(f"  Sample: {jobs[0].get('title')} at {jobs[0].get('company')}")
    except Exception as e:
        logger.error(f"✗ Failed to scrape Indeed: {e}")
        logger.info("Note: Ensure Playwright browser is installed with: playwright install")
        return 1
    
    if not jobs:
        logger.warning("No jobs found. Exiting.")
        return 1
    
    # Step 3: Rank jobs by compatibility
    logger.info("\nStep 3: Ranking jobs by resume compatibility...")
    try:
        ranked_jobs = rank_jobs(resume_data, jobs)
        logger.info(f"✓ Ranked {len(ranked_jobs)} jobs")
        
        if ranked_jobs:
            top_match = ranked_jobs[0]
            logger.info(f"  Top match: {top_match['title']} ({top_match['compatibility_score']}% match)")
            stats = {
                'avg_score': sum(j['compatibility_score'] for j in ranked_jobs) / len(ranked_jobs),
                'max_score': max(j['compatibility_score'] for j in ranked_jobs),
                'min_score': min(j['compatibility_score'] for j in ranked_jobs),
            }
            logger.info(f"  Avg score: {stats['avg_score']:.1f}% | Max: {stats['max_score']:.1f}% | Min: {stats['min_score']:.1f}%")
    except Exception as e:
        logger.error(f"✗ Failed to rank jobs: {e}")
        return 1
    
    # Step 4: Save results in multiple formats
    logger.info("\nStep 4: Saving results...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    try:
        # Create timestamped subdirectory for this run
        run_dir = os.path.join(output_dir, timestamp)
        setup_output_dir(run_dir)
        
        csv_path = os.path.join(run_dir, 'job_rankings.csv')
        save_results_csv(ranked_jobs, csv_path)
        
        json_path = os.path.join(run_dir, 'job_rankings.json')
        save_results_json(ranked_jobs, json_path)
        
        summary_path = os.path.join(run_dir, 'job_rankings.txt')
        save_results_summary(ranked_jobs, summary_path)
        
        logger.info(f"✓ Results saved to {run_dir}/")
    except Exception as e:
        logger.error(f"✗ Failed to save results: {e}")
        return 1
    
    logger.info("\n" + "=" * 80)
    logger.info("COMPLETE - Check results/ directory for output files")
    logger.info("=" * 80)
    
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Scrape Indeed and rank jobs by resume compatibility'
    )
    parser.add_argument(
        '--resume',
        help='Path to resume PDF'
    )
    parser.add_argument(
        '--output',
        help='Output directory for results'
    )
    parser.add_argument(
        '--config',
        default='config.json',
        help='Path to config.json (default: config.json)'
    )
    
    args = parser.parse_args()
    
    exit_code = main(
        resume_path=args.resume,
        output_dir=args.output,
        config_path=args.config
    )
    
    sys.exit(exit_code)
