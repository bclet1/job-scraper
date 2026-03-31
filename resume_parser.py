"""
Resume parser - extracts text and key information from PDF resumes.
"""

import pypdf
import re
from typing import Dict


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text content from a PDF file."""
    text = ""
    try:
        with open(pdf_path, "rb") as pdf_file:
            pdf_reader = pypdf.PdfReader(pdf_file)
            for page in pdf_reader.pages:
                text += page.extract_text()
        return text
    except FileNotFoundError:
        raise FileNotFoundError(f"Resume file not found: {pdf_path}")
    except Exception as e:
        raise Exception(f"Error extracting PDF: {e}")


def parse_resume(pdf_path: str) -> Dict[str, str]:
    """
    Parse resume and extract sections.
    
    Returns:
        Dict with keys: full_text, skills, experience, education, summary
    """
    full_text = extract_text_from_pdf(pdf_path)
    
    # Normalize whitespace
    full_text = re.sub(r'\s+', ' ', full_text).strip()
    
    resume_data = {
        "full_text": full_text,
        "skills": extract_skills_section(full_text),
        "experience": extract_experience_section(full_text),
        "education": extract_education_section(full_text),
        "summary": extract_summary_section(full_text),
    }
    
    return resume_data


def extract_skills_section(text: str) -> str:
    """Extract skills section from resume text."""
    # Look for common section headers
    skill_patterns = [
        r'(?:Technical\s+)?Skills?[:\n]+(.*?)(?=\n[A-Z]|\Z)',
        r'(?:Technical\s+)?Competencies?[:\n]+(.*?)(?=\n[A-Z]|\Z)',
        r'Technologies?[:\n]+(.*?)(?=\n[A-Z]|\Z)',
    ]
    
    for pattern in skill_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            skills_text = match.group(1)
            # Clean up the text
            skills_text = re.sub(r'[\n•\-]', ' ', skills_text)
            return skills_text.strip()
    
    # If no explicit skills section found, return relevant parts of text
    return text


def extract_experience_section(text: str) -> str:
    """Extract work experience section."""
    exp_patterns = [
        r'(?:Work\s+)?Experience[:\n]+(.*?)(?=Education|\Z)',
        r'Professional\s+Experience[:\n]+(.*?)(?=Education|\Z)',
        r'Employment[:\n]+(.*?)(?=Education|\Z)',
    ]
    
    for pattern in exp_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    
    return ""


def extract_education_section(text: str) -> str:
    """Extract education section."""
    edu_pattern = r'Education[:\n]+(.*?)(?=\n[A-Z][a-z]+|\Z)'
    match = re.search(edu_pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def extract_summary_section(text: str) -> str:
    """Extract summary/objective section."""
    summary_patterns = [
        r'(?:Professional\s+)?Summary[:\n]+(.*?)(?=\n[A-Z][a-z]+|\Z)',
        r'Objective[:\n]+(.*?)(?=\n[A-Z][a-z]+|\Z)',
        r'Overview[:\n]+(.*?)(?=\n[A-Z][a-z]+|\Z)',
    ]
    
    for pattern in summary_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    
    return ""


if __name__ == "__main__":
    # Test
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        resume = parse_resume(pdf_path)
        print(f"Full text length: {len(resume['full_text'])} chars")
        print(f"Skills: {resume['skills'][:200]}...")
        print(f"Experience: {resume['experience'][:200]}...")
