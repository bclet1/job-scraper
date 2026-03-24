"""Shared config and output helpers for the multi-source pipeline."""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


def load_config(config_path: str = 'config.json') -> Dict:
    """Load configuration from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
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

    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
        writer.writeheader()

        for rank, job in enumerate(jobs, 1):
            row = {col: job.get(col, '') for col in csv_columns}
            row['rank'] = rank
            writer.writerow(row)


def save_results_json(jobs: List[Dict], output_path: str):
    """Save ranked jobs to JSON."""
    if not jobs:
        return

    with open(output_path, 'w', encoding='utf-8') as handle:
        ranked_jobs = [
            {**job, 'rank': idx + 1}
            for idx, job in enumerate(jobs)
        ]
        json.dump(ranked_jobs, handle, indent=2, ensure_ascii=False)


def save_results_summary(jobs: List[Dict], output_path: str):
    """Save a human-readable summary."""
    if not jobs:
        return

    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write('JOB RANKING SUMMARY\n')
        handle.write('=' * 80 + '\n')
        handle.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        handle.write(f"Total Jobs: {len(jobs)}\n\n")

        for rank, job in enumerate(jobs, 1):
            handle.write(f"\n{'─' * 80}\n")
            handle.write(f"RANK #{rank}\n")
            handle.write(f"{'─' * 80}\n")
            handle.write(f"Score:            {job.get('compatibility_score', 0)}%\n")
            handle.write(f"Title:            {job.get('title', 'Unknown')}\n")
            handle.write(f"Company:          {job.get('company', 'Unknown')}\n")
            handle.write(f"Location:         {job.get('location', 'Unknown')}\n")
            handle.write(f"Salary:           {job.get('salary', 'Not specified')}\n")

            matched_skills = job.get('matched_skills', '')
            if isinstance(matched_skills, str) and matched_skills:
                skills_list = [s.strip() for s in matched_skills.split(',') if s.strip()]
                if skills_list:
                    handle.write(f"Matched Skills:   {len(skills_list)} skill(s)\n")
                    for skill in skills_list:
                        handle.write(f"                  • {skill}\n")
                else:
                    handle.write('Matched Skills:   None\n')
            else:
                handle.write('Matched Skills:   None\n')

            missing_skills = job.get('missing_skills', '')
            if isinstance(missing_skills, str) and missing_skills:
                skills_list = [s.strip() for s in missing_skills.split(',') if s.strip()]
                if skills_list:
                    handle.write(f"Missing Skills:   {len(skills_list)} skill(s)\n")
                    for skill in skills_list:
                        handle.write(f"                  • {skill}\n")
                else:
                    handle.write('Missing Skills:   None\n')
            else:
                handle.write('Missing Skills:   None\n')

            handle.write(f"Description:      {job.get('description', 'N/A')[:150]}...\n")
            handle.write(f"Link:             {job.get('link', 'N/A')}\n")