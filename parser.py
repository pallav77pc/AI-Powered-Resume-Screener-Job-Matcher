import re
import os
import pdfplumber
import spacy
from docx import Document

# Load spaCy once at import time
try:
    nlp = spacy.load('en_core_web_sm')
except OSError:
    import subprocess
    subprocess.run(['python', '-m', 'spacy', 'download', 'en_core_web_sm'], check=True)
    nlp = spacy.load('en_core_web_sm')

# ── Skill taxonomy ──────────────────────────────────────────────────────────
SKILLS = [
    # Languages
    'python', 'javascript', 'java', 'c++', 'c#', 'ruby', 'go', 'rust',
    'typescript', 'php', 'swift', 'kotlin', 'scala', 'r',
    # Web
    'html', 'css', 'react', 'angular', 'vue', 'next.js', 'tailwind',
    'flask', 'django', 'fastapi', 'node.js', 'express', 'graphql', 'rest api',
    # Data / ML
    'machine learning', 'deep learning', 'nlp', 'computer vision',
    'tensorflow', 'pytorch', 'scikit-learn', 'pandas', 'numpy',
    'data analysis', 'data visualization', 'tableau', 'power bi',
    # Databases
    'sql', 'mysql', 'postgresql', 'mongodb', 'redis', 'sqlite', 'elasticsearch',
    # Cloud / DevOps
    'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'terraform', 'ci/cd',
    'linux', 'bash', 'git', 'github', 'jenkins',
    # Soft / process
    'agile', 'scrum', 'jira', 'communication', 'leadership', 'teamwork',
]

# ── Text extraction ─────────────────────────────────────────────────────────
def extract_text(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        text = ''
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or '') + '\n'
        return text
    elif ext == '.docx':
        doc = Document(filepath)
        return '\n'.join(p.text for p in doc.paragraphs)
    else:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

# ── Field extractors ────────────────────────────────────────────────────────
def extract_email(text: str) -> str:
    m = re.search(r'\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b', text, re.I)
    return m.group() if m else ''

def extract_name(doc) -> str:
    for ent in doc.ents:
        if ent.label_ == 'PERSON':
            return ent.text.strip()
    return 'Unknown'

def extract_skills(text: str) -> list:
    lower = text.lower()
    return sorted({s for s in SKILLS if s in lower})

def extract_experience_years(text: str) -> float:
    # Explicit statement: "5 years of experience"
    m = re.search(r'(\d+)\+?\s*years?\s*(?:of\s+)?experience', text, re.I)
    if m:
        return float(m.group(1))

    # Sum date ranges: "Jan 2019 – Mar 2022", "2018 - present"
    ranges = re.findall(
        r'(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2}|present|current)',
        text, re.I
    )
    total = 0.0
    for start, end in ranges:
        s = int(start)
        e = 2024 if end.lower() in ('present', 'current') else int(end)
        total += max(0, e - s)
    return round(min(total, 30), 1)

def scrub_pii(text: str) -> str:
    """Strip identifiable info before scoring to reduce demographic bias."""
    text = re.sub(r'\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b', '[EMAIL]', text, flags=re.I)
    text = re.sub(r'(\+?\d[\d\s\-(). ]{7,}\d)', '[PHONE]', text)
    text = re.sub(r'https?://\S+', '[URL]', text)
    return text

# ── Main entry ──────────────────────────────────────────────────────────────
def parse_resume(filepath: str) -> dict:
    raw_text = extract_text(filepath)
    doc      = nlp(raw_text[:50_000])   # cap for speed

    return {
        'name':             extract_name(doc),
        'email':            extract_email(raw_text),
        'skills':           extract_skills(raw_text),
        'experience_years': extract_experience_years(raw_text),
        'raw_text':         raw_text,
        'clean_text':       scrub_pii(raw_text),
    }