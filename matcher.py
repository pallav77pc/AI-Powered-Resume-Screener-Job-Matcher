import json
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

_cache: dict = {}

def embed(text: str) -> np.ndarray:
    key = text[:200]
    if key not in _cache:
        _cache[key] = get_model().encode([text])[0]
    return _cache[key]

def skill_overlap(candidate_skills: list, job_skills: list) -> float:
    if not job_skills:
        return 0.0
    c = {s.lower().strip() for s in candidate_skills}
    j = {s.lower().strip() for s in job_skills}
    return len(c & j) / len(j)

def compute_match_score(parsed: dict, job) -> tuple[float, dict]:
    # ── 1. Semantic similarity ──────────────────────────────────────────────
    resume_text = parsed.get('clean_text', parsed.get('raw_text', ''))[:2000]
    job_text    = f"{job.title}. {job.description}"[:2000]

    sem_score = float(cosine_similarity(
        [embed(resume_text)], [embed(job_text)]
    )[0][0])
    sem_score = max(0.0, min(1.0, sem_score))   # clamp

    # ── 2. Skill overlap ────────────────────────────────────────────────────
    job_skills  = [s.strip() for s in job.required_skills.split(',') if s.strip()]
    cand_skills = parsed.get('skills', [])
    sk_score    = skill_overlap(cand_skills, job_skills)

    matched  = sorted(set(s.lower() for s in cand_skills) & set(s.lower() for s in job_skills))
    missing  = sorted(set(s.lower() for s in job_skills)  - set(s.lower() for s in cand_skills))

    # ── 3. Experience score ─────────────────────────────────────────────────
    exp_years = parsed.get('experience_years', 0)
    exp_score = min(exp_years, 10) / 10.0

    # ── Weighted composite ──────────────────────────────────────────────────
    final = 0.50 * sem_score + 0.35 * sk_score + 0.15 * exp_score

    breakdown = {
        'semantic_score':    round(sem_score  * 100, 1),
        'skill_score':       round(sk_score   * 100, 1),
        'experience_score':  round(exp_score  * 100, 1),
        'final_score':       round(final      * 100, 1),
        'matched_skills':    matched[:10],
        'missing_skills':    missing[:10],
        'experience_years':  exp_years,
    }
    return final, breakdown