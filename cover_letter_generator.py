"""
Cover letter generator for the multi-source job scraper pipeline.

Generates 3 tailored cover letter variants for a given job using the
OpenAI Chat Completions API.  The writing instructions are fully
configurable via the ``cover_letter_instructions`` key in config.json.
"""

import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default instructions – used when config.json has no cover_letter_instructions
# ---------------------------------------------------------------------------
DEFAULT_INSTRUCTIONS = (
    "Write a professional, enthusiastic cover letter tailored to the job posting. "
    "Keep it to 3 short paragraphs: "
    "Always open with 'Dear Hiring Manager,"
    "always close with 'Best Regards,"
    "(1) hook / why this role excites me, "
    "(2) 2-3 concrete achievements from my resume that directly match the role requirements, "
    "(3) forward-looking close. "
    "Vary the tone and framing between the three versions — formal, conversational, and "
    "achievement-focused respectively. "
    "Do NOT use generic filler phrases like 'I am writing to express my interest'."
)

_VARIANT_LABELS = ["formal", "conversational", "achievement-focused"]


def _build_resume_summary(resume_data: Dict) -> str:
    """Flatten resume_data into a concise text block for the prompt."""
    lines: List[str] = []

    name = resume_data.get("name") or resume_data.get("candidate_name", "")
    if name:
        lines.append(f"Candidate: {name}")

    for key in ("summary", "objective"):
        val = resume_data.get(key, "")
        if val:
            lines.append(f"Summary: {val}")
            break

    skills = resume_data.get("skills", [])
    if isinstance(skills, list) and skills:
        lines.append(f"Skills: {', '.join(str(s) for s in skills[:40])}")
    elif isinstance(skills, str) and skills:
        lines.append(f"Skills: {skills[:600]}")

    for exp in (resume_data.get("experience") or resume_data.get("work_experience") or [])[:4]:
        if isinstance(exp, dict):
            title = exp.get("title", exp.get("role", ""))
            company = exp.get("company", "")
            years = exp.get("years", exp.get("duration", ""))
            highlights = exp.get("highlights", exp.get("description", ""))
            entry = f"  • {title} @ {company}"
            if years:
                entry += f" ({years})"
            lines.append(entry)
            if highlights:
                if isinstance(highlights, list):
                    for h in highlights[:3]:
                        lines.append(f"      - {h}")
                else:
                    lines.append(f"      - {str(highlights)[:200]}")

    for edu in (resume_data.get("education") or [])[:2]:
        if isinstance(edu, dict):
            degree = edu.get("degree", "")
            school = edu.get("school", edu.get("institution", ""))
            year = edu.get("year", edu.get("graduation_year", ""))
            lines.append(f"  Education: {degree} @ {school}{' (' + str(year) + ')' if year else ''}")

    return "\n".join(lines) if lines else str(resume_data)[:1000]


def _build_job_summary(job: Dict) -> str:
    """Build a concise job description block for the prompt."""
    lines = []
    for field in ("title", "company", "location", "salary"):
        val = job.get(field, "")
        if val:
            lines.append(f"{field.title()}: {val}")
    desc = job.get("description", "")
    if desc:
        lines.append(f"Description:\n{str(desc)[:1500]}")
    matched = job.get("matched_skills", "")
    if matched:
        lines.append(f"Matched skills: {matched}")
    missing = job.get("missing_skills", "")
    if missing:
        lines.append(f"Skills to address: {missing}")
    return "\n".join(lines)


def generate_cover_letters(
    resume_data: Dict,
    job: Dict,
    instructions: str = DEFAULT_INSTRUCTIONS,
    model: str = "gpt-4o-mini",
    num_variants: int = 3,
) -> List[str]:
    """Return *num_variants* cover letter strings for *job*.

    Each variant is a plain-text cover letter.  The three variants differ in
    tone/framing as directed by *instructions*.

    Args:
        resume_data: Parsed resume dict (from resume_parser.parse_resume).
        job: Single job dict (including title, company, description, etc.).
        instructions: Free-form writing guidance – edit via config.json.
        model: OpenAI model name.
        num_variants: Number of distinct cover letter versions to generate.

    Returns:
        List of cover letter strings, one per variant.

    Raises:
        RuntimeError: If the API call fails or the response cannot be parsed.
    """
    try:
        from openai import OpenAI  # lazy import – not required at module load
    except ImportError as exc:
        raise RuntimeError("openai package is not installed. Run: pip install openai") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")

    if github_token and not api_key:
        # Use GitHub Models endpoint (OpenAI-compatible, authenticated via GitHub PAT)
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=github_token,
        )
    elif api_key:
        client = OpenAI(api_key=api_key)
    else:
        raise RuntimeError(
            "No API key found. Set either OPENAI_API_KEY (OpenAI) or "
            "GITHUB_TOKEN (GitHub Models) in your .env file."
        )

    resume_summary = _build_resume_summary(resume_data)
    job_summary = _build_job_summary(job)
    rank = job.get("rank", job.get("compatibility_score", "?"))

    system_prompt = (
        "You are an expert career coach and professional writer. "
        "Your task is to write targeted, compelling cover letters based on the "
        "candidate's resume and the specific job posting provided."
    )

    variant_list = "\n".join(
        f"  Version {i + 1} ({_VARIANT_LABELS[i] if i < len(_VARIANT_LABELS) else f'variant {i+1}'} tone)"
        for i in range(num_variants)
    )

    user_prompt = f"""
WRITING INSTRUCTIONS:
{instructions}

CANDIDATE RESUME:
{resume_summary}

JOB POSTING (Rank #{rank}):
{job_summary}

---
Please write exactly {num_variants} distinct cover letter versions for this job:
{variant_list}

Separate each version with a line containing only: ---VERSION_BREAK---

Do not include any label or header before each version – just the letter text itself.
""".strip()

    logger.debug(f"Requesting {num_variants} cover letters for: {job.get('title')} @ {job.get('company')}")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.85,
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

    raw = response.choices[0].message.content or ""
    parts = [p.strip() for p in raw.split("---VERSION_BREAK---") if p.strip()]

    if len(parts) < num_variants:
        logger.warning(
            f"Expected {num_variants} cover letter variants but got {len(parts)} "
            f"for {job.get('title')} @ {job.get('company')}. Using what was returned."
        )

    return parts[:num_variants]


def save_cover_letters(
    cover_letters: List[str],
    rank: int,
    output_dir: str,
    job: Dict,
) -> List[str]:
    """Write cover letter variants to disk.

    Files are named ``coverletter-{rank}-v{n}.txt`` inside *output_dir*.

    Returns the list of written file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, letter in enumerate(cover_letters, 1):
        filename = f"coverletter-{rank}-v{i}.txt"
        filepath = os.path.join(output_dir, filename)
        header = (
            f"Cover Letter – Rank #{rank} – Version {i} "
            f"({_VARIANT_LABELS[i - 1] if i - 1 < len(_VARIANT_LABELS) else f'variant {i}'})\n"
            f"Job:     {job.get('title', 'N/A')}\n"
            f"Company: {job.get('company', 'N/A')}\n"
            f"Score:   {job.get('compatibility_score', 'N/A')}%\n"
            + "=" * 70 + "\n\n"
        )
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(header + letter)
        paths.append(filepath)
    return paths
