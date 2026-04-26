"""
Job-Resume matching using semantic embeddings.
Compares resume text with job descriptions to calculate compatibility score.
"""

from typing import List, Dict, Tuple
import re
import logging
import json
import os

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


def _load_tech_keywords() -> set:
    """Load tech_keywords from config.json, falling back to an empty set."""
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as fh:
            cfg = json.load(fh)
        return set(cfg.get('tech_keywords', []))
    except Exception as exc:
        logger.warning(f"Could not load tech_keywords from config.json: {exc}")
        return set()


def get_embeddings_model():
    """Load sentence-transformers model for semantic similarity."""
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading semantic embedding model (sentence-transformers/all-MiniLM-L6-v2)...")
        # Using a smaller, faster model that's still quite good
        model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        return model
    except ImportError:
        raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")


def extract_tech_keywords(text: str) -> List[str]:
    """
    Extract technology keywords from text.
    Keywords are loaded from config.json (``tech_keywords`` list).
    """
    tech_keywords = _load_tech_keywords()

    found_keywords = []
    text_lower = text.lower()

    for keyword in tech_keywords:
        # Use word boundaries for more accurate matching
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        if re.search(pattern, text_lower):
            found_keywords.append(keyword)

    return list(set(found_keywords))  # Remove duplicates


def extract_skill_sections(resume_data: Dict[str, str]) -> Tuple[str, str]:
    """
    Extract skills and experience from parsed resume data.
    Returns (skills_text, experience_text)
    """
    skills = resume_data.get('skills', '') or ''
    experience = resume_data.get('experience', '') or ''
    return skills, experience


def calculate_match_score(resume_text: str, job_posting: Dict[str, str], model=None) -> Tuple[float, List[str], List[str]]:
    """
    Calculate semantic similarity score between resume and job posting.
    
    Args:
        resume_text: Full resume text
        job_posting: Job dict with 'title', 'description', 'salary'
        model: Sentence transformer model (lazy loaded if None)
        
    Returns:
        Tuple of (score: float 0-100, matched_skills: list, missing_skills: list)
    """
    # Lazy load model if not provided
    if model is None:
        model = get_embeddings_model()
    
    # Build comprehensive job text
    job_text = f"{job_posting.get('title', '')} {job_posting.get('description', '')}"
    
    if not job_text.strip() or not resume_text.strip():
        return 0.0, [], []
    
    try:
        # Get semantic embeddings
        resume_embedding = model.encode(resume_text, convert_to_tensor=True)
        job_embedding = model.encode(job_text, convert_to_tensor=True)
        
        # Calculate cosine similarity (returns -1 to 1, we'll scale to 0-100)
        from sentence_transformers.util import pytorch_cos_sim
        similarity = pytorch_cos_sim(resume_embedding, job_embedding).item()
        
        # Scale to 0-100
        score = max(0, (similarity + 1) / 2 * 100)
        
    except Exception as e:
        logger.warning(f"Error calculating similarity: {e}")
        score = 0.0
    
    # Extract technical skills
    resume_skills = set(extract_tech_keywords(resume_text))
    job_skills = set(extract_tech_keywords(job_text))
    
    matched_skills = list(resume_skills & job_skills)
    missing_skills = list(job_skills - resume_skills)
    
    return score, matched_skills, missing_skills


def rank_jobs(resume_data: Dict[str, str], jobs: List[Dict[str, str]]) -> List[Dict]:
    """
    Rank jobs by compatibility with resume.
    
    Args:
        resume_data: Parsed resume dictionary
        jobs: List of job posting dictionaries
        
    Returns:
        List of jobs sorted by compatibility score (highest first)
    """
    resume_text = resume_data.get('full_text', '')
    
    # Load model once for efficiency
    model = get_embeddings_model()
    
    ranked_jobs = []
    
    for idx, job in enumerate(jobs):
        logger.info(f"Scoring job {idx + 1}/{len(jobs)}: {job.get('title', 'Unknown')}...")
        
        score, matched_skills, missing_skills = calculate_match_score(
            resume_text, job, model
        )
        
        ranked_job = {
            **job,
            'compatibility_score': round(score, 2),
            'matched_skills': ', '.join(sorted(matched_skills)),
            'missing_skills': ', '.join(sorted(missing_skills[:5])),  # Top 5 missing
            'match_count': len(matched_skills),
        }
        
        ranked_jobs.append(ranked_job)
    
    # Sort by score (descending)
    ranked_jobs.sort(key=lambda x: x['compatibility_score'], reverse=True)
    
    return ranked_jobs


if __name__ == "__main__":
    # Test
    test_resume = """
    Senior DevOps Engineer with 5+ years experience
    Skills: Kubernetes, Docker, Terraform, AWS, Python, Bash
    Experience with CI/CD pipelines, monitoring with Prometheus/Grafana
    """
    
    test_job = {
        'title': 'DevOps Engineer',
        'description': 'Looking for DevOps Engineer experienced with Kubernetes, Docker, and AWS',
        'salary': '$120k-150k'
    }
    
    score, matched, missing = calculate_match_score(test_resume, test_job)
    print(f"Score: {score}")
    print(f"Matched: {matched}")
    print(f"Missing: {missing}")
