import os
import time
import requests

# ── Country codes Adzuna supports ─────────────────────────────────────────────
COUNTRY_CODES = {
    'india':          'in',
    'uk':             'gb',
    'united kingdom': 'gb',
    'usa':            'us',
    'united states':  'us',
    'australia':      'au',
    'canada':         'ca',
    'germany':        'de',
    'france':         'fr',
    'brazil':         'br',
    'singapore':      'sg',
    'south africa':   'za',
    'netherlands':    'nl',
    'new zealand':    'nz',
    'poland':         'pl',
    'russia':         'ru',
}

# ── Simple in-memory cache (avoids hitting rate limits on repeated queries) ───
_cache: dict = {}
CACHE_TTL = 300   # seconds — 5 minutes

BASE_URL = 'https://api.adzuna.com/v1/api/jobs'


def _get_country_code(country_input: str) -> str:
    """Accept either a full country name or a 2-letter code."""
    raw = country_input.lower().strip()
    if len(raw) == 2:
        return raw   # already a code like 'in', 'gb'
    return COUNTRY_CODES.get(raw, 'in')   # default to India


def _cached_get(url: str, params: dict) -> dict | None:
    """GET with simple TTL cache keyed by url+params."""
    cache_key = url + str(sorted(params.items()))
    now = time.time()

    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _cache[cache_key] = (data, now)
        return data
    except requests.exceptions.Timeout:
        print('[Adzuna] Request timed out.')
    except requests.exceptions.HTTPError as e:
        print(f'[Adzuna] HTTP error: {e.response.status_code} — {e.response.text[:200]}')
    except requests.exceptions.RequestException as e:
        print(f'[Adzuna] Request error: {e}')
    except Exception as e:
        print(f'[Adzuna] Unexpected error: {e}')
    return None


def _base_params() -> dict:
    return {
        'app_id':       os.environ.get('ADZUNA_APP_ID', ''),
        'app_key':      os.environ.get('ADZUNA_APP_KEY', ''),
        'content-type': 'application/json',
    }


# ── Main search function ───────────────────────────────────────────────────────
def search_jobs(
    query:            str,
    location:         str  = '',
    country:          str  = 'in',       # 'in' = India
    page:             int  = 1,
    results_per_page: int  = 20,
    sort_by:          str  = 'relevance',  # relevance | date | salary
    salary_min:       int  = None,
    salary_max:       int  = None,
    full_time:        bool = False,
    permanent:        bool = False,
    what_exclude:     str  = '',          # keywords to exclude
    category:         str  = '',          # e.g. 'it-jobs'
) -> dict:
    """
    Search Adzuna job listings.

    Returns:
        {
          'count':    int,        # total matching jobs across all pages
          'page':     int,
          'pages':    int,        # total pages available
          'jobs':     [ {...} ],  # list of normalised job dicts
          'error':    str | None
        }
    """
    country_code = _get_country_code(country)
    url = f'{BASE_URL}/{country_code}/search/{page}'

    params = _base_params()
    params['results_per_page'] = results_per_page

    if query:
        params['what'] = query
    if location:
        params['where'] = location
    if sort_by in ('relevance', 'date', 'salary'):
        params['sort_by'] = sort_by
    if salary_min is not None:
        params['salary_min'] = salary_min
    if salary_max is not None:
        params['salary_max'] = salary_max
    if full_time:
        params['full_time'] = 1
    if permanent:
        params['permanent'] = 1
    if what_exclude:
        params['what_exclude'] = what_exclude
    if category:
        params['category'] = category

    data = _cached_get(url, params)
    if data is None:
        return {'count': 0, 'page': page, 'pages': 0, 'jobs': [], 'error': 'API request failed'}

    total   = data.get('count', 0)
    results = data.get('results', [])
    pages   = max(1, -(-total // results_per_page))  # ceiling division

    jobs = [_normalise(j) for j in results]
    return {
        'count': total,
        'page':  page,
        'pages': min(pages, 50),   # Adzuna max 50 pages
        'jobs':  jobs,
        'error': None,
    }


def _normalise(raw: dict) -> dict:
    """Convert Adzuna's raw response into a clean flat dict."""
    loc    = raw.get('location', {})
    area   = loc.get('area', [])
    # area is [Country, Region, City, District] — take last 2 for display
    location_str = ', '.join(area[-2:]) if area else loc.get('display_name', '')

    salary_min = raw.get('salary_min')
    salary_max = raw.get('salary_max')
    predicted  = raw.get('salary_is_predicted', 0)

    if salary_min and salary_max:
        salary_str = f'₹{int(salary_min):,} – ₹{int(salary_max):,}'
        if predicted:
            salary_str += ' (est.)'
    elif salary_min:
        salary_str = f'₹{int(salary_min):,}+'
    else:
        salary_str = 'Not specified'

    category = raw.get('category', {})

    return {
        'id':            raw.get('id', ''),
        'title':         raw.get('title', 'Untitled'),
        'company':       raw.get('company', {}).get('display_name', 'Unknown'),
        'location':      location_str,
        'description':   raw.get('description', ''),
        'salary':        salary_str,
        'salary_min':    salary_min,
        'salary_max':    salary_max,
        'salary_predicted': bool(predicted),
        'contract_type': raw.get('contract_type', ''),     # permanent | contract
        'contract_time': raw.get('contract_time', ''),     # full_time | part_time
        'category':      category.get('label', ''),
        'category_tag':  category.get('tag', ''),
        'posted_date':   raw.get('created', ''),
        'apply_url':     raw.get('redirect_url', ''),
        'latitude':      raw.get('latitude'),
        'longitude':     raw.get('longitude'),
        'source':        'Adzuna',
    }


# ── Fetch categories (useful for dropdown filter) ─────────────────────────────
def get_categories(country: str = 'in') -> list:
    country_code = _get_country_code(country)
    url  = f'{BASE_URL}/{country_code}/categories'
    data = _cached_get(url, _base_params())
    if not data:
        return []
    return [
        {'label': c.get('label', ''), 'tag': c.get('tag', '')}
        for c in data.get('results', [])
    ]


# ── Salary histogram for a job title (bonus feature) ─────────────────────────
def get_salary_histogram(job_title: str, country: str = 'in') -> dict:
    country_code = _get_country_code(country)
    url    = f'https://api.adzuna.com/v1/api/jobs/{country_code}/histogram'
    params = {**_base_params(), 'what': job_title}
    data   = _cached_get(url, params)
    if not data:
        return {}
    return data.get('histogram', {})