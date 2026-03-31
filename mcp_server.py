#!/usr/bin/env python3
"""
MCP (Model Context Protocol) server for job-scraper.

Exposes tools that let a Claude agent inspect results, manage config,
analyze skill gaps, and trigger scraping runs — all without manually
reading files or running commands.

## Setup

1. Install the MCP package:
       pip install mcp

2. For Claude Desktop, add to ~/AppData/Roaming/Claude/claude_desktop_config.json:
       {
         "mcpServers": {
           "job-scraper": {
             "command": "python",
             "args": ["C:/local-repos/job-scraper/mcp_server.py"],
             "cwd": "C:/local-repos/job-scraper"
           }
         }
       }

3. For the claude CLI:
       claude --mcp-config '{"job-scraper": {"command": "python", "args": ["mcp_server.py"]}}'

## Tools

- get_config            Read current config.json settings
- update_config         Write one or more config.json fields
- list_runs             List all result run folders with timestamps
- get_latest_results    Load ranked jobs from the most recent (or specified) run
- get_top_matches       Return the top N jobs across all sources from the latest run
- analyze_missing_skills Aggregate missing skills across runs to surface resume gaps
- run_scraper           Execute the full pipeline and return a summary
"""

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"
RESULTS_DIR = BASE_DIR / "results"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _sorted_run_dirs() -> list[Path]:
    """Return result run directories sorted newest-first."""
    if not RESULTS_DIR.exists():
        return []
    dirs = [d for d in RESULTS_DIR.iterdir() if d.is_dir()]
    return sorted(dirs, key=lambda d: d.name, reverse=True)


def _load_jobs_from_run(run_dir: Path) -> list[dict]:
    """Load all jobs from a run's comparison JSON (or fall back to site JSONs)."""
    comparison_json = run_dir / "comparison" / "job_comparison.json"
    if comparison_json.exists():
        with open(comparison_json, encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("jobs", [])

    # Fallback: aggregate from per-site JSONs
    jobs: list[dict] = []
    for site_dir in run_dir.iterdir():
        if not site_dir.is_dir() or site_dir.name == "comparison":
            continue
        site_json = site_dir / "job_rankings.json"
        if site_json.exists():
            with open(site_json, encoding="utf-8") as fh:
                site_jobs = json.load(fh)
            for job in site_jobs:
                job.setdefault("source", site_dir.name)
            jobs.extend(site_jobs)

    return sorted(jobs, key=lambda j: j.get("compatibility_score", 0), reverse=True)


def _summarize_job(job: dict, rank: int | None = None) -> str:
    """Format a single job as a readable string."""
    lines = []
    if rank:
        lines.append(f"#{rank} [{job.get('source', '?').upper()}]  {job.get('compatibility_score', 0):.1f}%")
    lines.append(f"  Title:    {job.get('title', 'N/A')}")
    lines.append(f"  Company:  {job.get('company', 'N/A')}")
    lines.append(f"  Location: {job.get('location', 'N/A')}")
    salary = job.get('salary') or 'Not listed'
    lines.append(f"  Salary:   {salary}")
    matched = job.get('matched_skills') or 'None'
    lines.append(f"  Matched:  {matched}")
    missing = job.get('missing_skills') or 'None'
    lines.append(f"  Missing:  {missing}")
    lines.append(f"  Link:     {job.get('link', 'N/A')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

server = Server("job-scraper")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_config",
            description="Read the current config.json: keywords, locations, max_jobs, days_old, resume_path.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="update_config",
            description=(
                "Update one or more fields in config.json. "
                "Pass a JSON object with only the fields to change. "
                "Example: {\"keywords\": [\"DevOps Engineer\"], \"days_old\": 7}"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "object",
                        "description": "Key-value pairs to merge into config.json",
                    }
                },
                "required": ["updates"],
            },
        ),
        types.Tool(
            name="list_runs",
            description="List all past scraping run folders with timestamps, newest first.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_latest_results",
            description=(
                "Load ranked jobs from the most recent run (or a specific run folder). "
                "Returns source counts and top matches."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_name": {
                        "type": "string",
                        "description": "Optional: specific run folder name (e.g. '03-30_10-58'). Defaults to most recent.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max jobs to return (default 10).",
                        "default": 10,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_top_matches",
            description="Return the top N jobs from the latest run, formatted for quick review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "Number of top jobs to return (default 5).",
                        "default": 5,
                    },
                    "source": {
                        "type": "string",
                        "description": "Optional: filter by source (indeed, builtin, linkedin, dice).",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Optional: only return jobs with compatibility_score >= this value.",
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="analyze_missing_skills",
            description=(
                "Aggregate missing_skills across all jobs in recent runs to find the most "
                "frequently requested skills not on your resume. Useful for resume gap analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "Number of top missing skills to return (default 15).",
                        "default": 15,
                    },
                    "runs": {
                        "type": "integer",
                        "description": "How many recent runs to include (default 3).",
                        "default": 3,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="run_scraper",
            description=(
                "Execute the full scraping and ranking pipeline. "
                "Optionally override days_old or keywords before running. "
                "Returns a summary of results when complete. This can take 2–10 minutes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days_old": {
                        "type": "integer",
                        "description": "Override days_old for this run only.",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Override keywords for this run only (updates config.json temporarily).",
                    },
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:

    # -------------------------------------------------------------------
    def _text(content: str) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=content)]
    # -------------------------------------------------------------------

    if name == "get_config":
        config = _load_config()
        return _text(json.dumps(config, indent=2))

    elif name == "update_config":
        updates = arguments.get("updates", {})
        if not updates:
            return _text("No updates provided.")
        config = _load_config()
        config.update(updates)
        _save_config(config)
        return _text(f"config.json updated:\n{json.dumps(updates, indent=2)}")

    elif name == "list_runs":
        run_dirs = _sorted_run_dirs()
        if not run_dirs:
            return _text("No runs found in results/")
        lines = [f"Found {len(run_dirs)} run(s):"]
        for d in run_dirs:
            sites = [s.name for s in d.iterdir() if s.is_dir()]
            lines.append(f"  • {d.name}  ({', '.join(sorted(sites))})")
        return _text("\n".join(lines))

    elif name == "get_latest_results":
        run_name = arguments.get("run_name")
        limit = int(arguments.get("limit", 10))

        run_dirs = _sorted_run_dirs()
        if not run_dirs:
            return _text("No runs found.")

        if run_name:
            run_dir = RESULTS_DIR / run_name
            if not run_dir.exists():
                return _text(f"Run '{run_name}' not found.")
        else:
            run_dir = run_dirs[0]

        jobs = _load_jobs_from_run(run_dir)
        if not jobs:
            return _text(f"No jobs found in {run_dir.name}.")

        source_counts = Counter(j.get("source", "unknown") for j in jobs)
        lines = [
            f"Run: {run_dir.name}",
            f"Total unique jobs: {len(jobs)}",
            "By source: " + ", ".join(f"{s}={c}" for s, c in sorted(source_counts.items())),
            "",
            f"Top {min(limit, len(jobs))} matches:",
            "=" * 60,
        ]
        for i, job in enumerate(jobs[:limit], 1):
            lines.append(_summarize_job(job, rank=i))
            lines.append("")

        return _text("\n".join(lines))

    elif name == "get_top_matches":
        n = int(arguments.get("n", 5))
        source_filter = arguments.get("source", "").lower()
        min_score = arguments.get("min_score")

        run_dirs = _sorted_run_dirs()
        if not run_dirs:
            return _text("No runs found.")

        jobs = _load_jobs_from_run(run_dirs[0])
        if source_filter:
            jobs = [j for j in jobs if j.get("source", "").lower() == source_filter]
        if min_score is not None:
            jobs = [j for j in jobs if j.get("compatibility_score", 0) >= float(min_score)]

        if not jobs:
            return _text("No jobs match the specified filters.")

        lines = [f"Top {min(n, len(jobs))} from {run_dirs[0].name}", "=" * 60, ""]
        for i, job in enumerate(jobs[:n], 1):
            lines.append(_summarize_job(job, rank=i))
            lines.append("")

        return _text("\n".join(lines))

    elif name == "analyze_missing_skills":
        top_n = int(arguments.get("top_n", 15))
        runs = int(arguments.get("runs", 3))

        run_dirs = _sorted_run_dirs()[:runs]
        if not run_dirs:
            return _text("No runs found.")

        skill_counter: Counter = Counter()
        total_jobs = 0

        for run_dir in run_dirs:
            jobs = _load_jobs_from_run(run_dir)
            total_jobs += len(jobs)
            for job in jobs:
                raw = job.get("missing_skills", "") or ""
                for skill in [s.strip() for s in raw.split(",") if s.strip()]:
                    skill_counter[skill.lower()] += 1

        if not skill_counter:
            return _text("No missing skills data found.")

        lines = [
            f"Missing Skills Analysis",
            f"Runs analyzed: {len(run_dirs)} ({', '.join(d.name for d in run_dirs)})",
            f"Total jobs analyzed: {total_jobs}",
            f"",
            f"Top {top_n} skills to consider adding to your resume:",
            "=" * 50,
        ]
        for skill, count in skill_counter.most_common(top_n):
            pct = count / total_jobs * 100
            bar = "█" * min(int(pct / 2), 25)
            lines.append(f"  {skill:<30} {count:>3} jobs  {pct:5.1f}%  {bar}")

        return _text("\n".join(lines))

    elif name == "run_scraper":
        days_old = arguments.get("days_old")
        keywords_override = arguments.get("keywords")

        # Temporarily patch config if keywords override provided
        original_keywords = None
        if keywords_override:
            config = _load_config()
            original_keywords = config.get("keywords")
            config["keywords"] = keywords_override
            _save_config(config)

        cmd = [sys.executable, str(BASE_DIR / "multi_job_scraper.py")]
        if days_old is not None:
            cmd += ["--days", str(days_old)]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=900,  # 15 minute max
            )
        finally:
            if original_keywords is not None:
                config = _load_config()
                config["keywords"] = original_keywords
                _save_config(config)

        output = result.stdout + result.stderr
        exit_code = result.returncode

        if exit_code == 0:
            # Summarize what was produced
            run_dirs = _sorted_run_dirs()
            summary = f"Scraper completed successfully (exit 0).\n"
            if run_dirs:
                latest = run_dirs[0]
                jobs = _load_jobs_from_run(latest)
                source_counts = Counter(j.get("source", "unknown") for j in jobs)
                summary += f"Run folder: {latest.name}\n"
                summary += f"Total unique jobs: {len(jobs)}\n"
                summary += "By source: " + ", ".join(f"{s}={c}" for s, c in sorted(source_counts.items())) + "\n"
                if jobs:
                    top = jobs[0]
                    summary += f"\nBest match: {top.get('title')} @ {top.get('company')} "
                    summary += f"({top.get('compatibility_score', 0):.1f}%)\n"
            return _text(summary)
        else:
            return _text(f"Scraper failed (exit {exit_code}).\n\nOutput:\n{output[-3000:]}")

    else:
        return _text(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="job-scraper",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
