import os
import requests

# ── Unified job schema ────────────────────────────────────────────────────────
def make_job(title, company, location, description, skills, url, source):
    return {
        'title':       title,
        'company':     company,
        'location':    location,
        'description': description,
        'skills':      skills,
        'apply_url':   url,
        'source':      source,
    }

# ─────────────────────────────────────────────────────────────────────────────
# 1. JSearch (RapidAPI) — covers LinkedIn, Indeed, Glassdoor simultaneously
#    Sign up free: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_jsearch(query: str, location: str = 'India', num_pages: int = 1) -> list:
    url     = 'https://jsearch.p.rapidapi.com/search'
    headers = {
        'X-RapidAPI-Key':  os.environ.get('JSEARCH_API_KEY', 'YOUR_KEY_HERE'),
        'X-RapidAPI-Host': 'jsearch.p.rapidapi.com',
    }
    params = {
        'query':      f'{query} in {location}',
        'page':       '1',
        'num_pages':  str(num_pages),
        'date_posted': 'week',
    }
    try:
        res  = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
    except Exception as e:
        print(f'[JSearch] Error: {e}')
        return []

    jobs = []
    for j in data.get('data', []):
        jobs.append(make_job(
            title       = j.get('job_title', ''),
            company     = j.get('employer_name', ''),
            location    = j.get('job_city', '') + ', ' + j.get('job_country', ''),
            description = j.get('job_description', '')[:1500],
            skills      = j.get('job_required_skills') or [],
            url         = j.get('job_apply_link', ''),
            source      = j.get('job_publisher', 'JSearch'),
        ))
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# 2. Adzuna — free, covers India (in = India country code)
#    Register free: https://developer.adzuna.com/
# ─────────────────────────────────────────────────────────────────────────────
def fetch_adzuna(query: str, location: str = '', country: str = 'in', page: int = 1) -> list:
    app_id  = os.environ.get('ADZUNA_APP_ID',  'YOUR_APP_ID')
    app_key = os.environ.get('ADZUNA_APP_KEY', 'YOUR_APP_KEY')
    url = f'https://api.adzuna.com/v1/api/jobs/{country}/search/{page}'
    params = {
        'app_id':         app_id,
        'app_key':        app_key,
        'results_per_page': 20,
        'what':           query,
        'where':          location,
        'content-type':   'application/json',
    }
    try:
        res  = requests.get(url, params=params, timeout=10)
        data = res.json()
    except Exception as e:
        print(f'[Adzuna] Error: {e}')
        return []

    jobs = []
    for j in data.get('results', []):
        loc_obj  = j.get('location', {})
        location_str = ', '.join(loc_obj.get('area', [])[-2:])
        jobs.append(make_job(
            title       = j.get('title', ''),
            company     = j.get('company', {}).get('display_name', ''),
            location    = location_str,
            description = j.get('description', '')[:1500],
            skills      = [],   # Adzuna doesn't separate skills
            url         = j.get('redirect_url', ''),
            source      = 'Adzuna',
        ))
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# 3. Remotive — completely free, no key, remote jobs
# ─────────────────────────────────────────────────────────────────────────────
def fetch_remotive(query: str) -> list:
    url    = 'https://remotive.com/api/remote-jobs'
    params = {'search': query, 'limit': 20}
    try:
        res  = requests.get(url, params=params, timeout=10)
        data = res.json()
    except Exception as e:
        print(f'[Remotive] Error: {e}')
        return []

    jobs = []
    for j in data.get('jobs', []):
        jobs.append(make_job(
            title       = j.get('title', ''),
            company     = j.get('company_name', ''),
            location    = j.get('candidate_required_location', 'Remote'),
            description = j.get('description', '')[:1500],
            skills      = j.get('tags', []),
            url         = j.get('url', ''),
            source      = 'Remotive',
        ))
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# 4. Apify — Naukri.com scraper (India-specific, ~$5/mo)
#    Sign up: https://apify.com · Actor: "jupri/naukri"
# ─────────────────────────────────────────────────────────────────────────────
def fetch_naukri_via_apify(query: str, location: str = '') -> list:
    token    = os.environ.get('APIFY_TOKEN', 'YOUR_APIFY_TOKEN')
    actor_id = 'jupri~naukri'
    run_url  = f'https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items'
    payload  = {
        'keyword':  query,
        'location': location,
        'maxItems': 20,
    }
    headers = {'Authorization': f'Bearer {token}'}
    try:
        res  = requests.post(run_url, json=payload, headers=headers, timeout=60)
        data = res.json()
    except Exception as e:
        print(f'[Apify/Naukri] Error: {e}')
        return []

    jobs = []
    for j in (data if isinstance(data, list) else []):
        jobs.append(make_job(
            title       = j.get('title', ''),
            company     = j.get('company', ''),
            location    = j.get('location', ''),
            description = j.get('jobDescription', '')[:1500],
            skills      = j.get('keySkills', '').split(',') if j.get('keySkills') else [],
            url         = j.get('jobUrl', ''),
            source      = 'Naukri',
        ))
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Master fetch — tries all enabled sources and merges results
# ─────────────────────────────────────────────────────────────────────────────
def fetch_live_jobs(query: str, location: str = '', sources: list = None) -> list:
    if sources is None:
        sources = ['adzuna', 'remotive']   # free defaults, no key needed

    results = []
    if 'jsearch'  in sources: results += fetch_jsearch(query, location)
    if 'adzuna'   in sources: results += fetch_adzuna(query, location)
    if 'remotive' in sources: results += fetch_remotive(query)
    if 'naukri'   in sources: results += fetch_naukri_via_apify(query, location)

    # Deduplicate by title+company
    seen = set()
    unique = []
    for j in results:
        key = (j['title'].lower()[:40], j['company'].lower()[:30])
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique