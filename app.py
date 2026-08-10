import os
import json
from functools import wraps
from flask import Flask, render_template, request, jsonify, abort, session, redirect, url_for, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, or_
from jobs_api import fetch_live_jobs
from adzuna import search_jobs, get_categories, get_salary_histogram
from dotenv import load_dotenv
load_dotenv()

from config import Config
from models import db, Job, Candidate, Match, User
from parser import parse_resume
from matcher import compute_match_score
from resume_analyzer import extract_text_from_pdf, analyse_resume_gemini

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ── auth helpers ─────────────────────────────────────────────────────────────

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

@app.before_request
def load_user():
    g.user = get_current_user()

@app.context_processor
def inject_user():
    return {'current_user': g.user}


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login', next=request.path))
        if g.user.role != 'admin':
            return abort(403)
        return view(*args, **kwargs)
    return wrapped_view


# ── helpers ─────────────────────────────────────────────────────────────────
def allowed(filename: str) -> bool:
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS'])

# ── pages ────────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    return render_template('index.html', jobs=jobs)

@app.route('/dashboard')
@admin_required
def dashboard():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    return render_template('dashboard.html', jobs=jobs)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    allow_admin = User.query.filter_by(role='admin').first() is None or (g.user and g.user.role == 'admin')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        normalized_email = email.lower()
        normalized_username = username.lower()

        if not username or not email or not password:
            error = 'Username, email and password are required.'
        elif User.query.filter(
            or_(
                func.lower(User.username) == normalized_username,
                func.lower(User.email) == normalized_email,
            )
        ).first():
            error = 'A user with that username or email already exists.'
        else:
            if role != 'admin' or not allow_admin:
                role = 'user'
            user = User(
                username=username,
                email=normalized_email,
                password_hash=generate_password_hash(password),
                role=role,
            )
            db.session.add(user)
            db.session.commit()
            session.clear()
            session['user_id'] = user.id
            return redirect(url_for('index'))

    return render_template('register.html', error=error, allow_admin=allow_admin)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    next_page = request.args.get('next') or url_for('index')

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        normalized_identifier = identifier.lower()

        if not identifier or not password:
            error = 'Username/email and password are required.'
        else:
            user = User.query.filter(
                or_(
                    func.lower(User.email) == normalized_identifier,
                    func.lower(User.username) == normalized_identifier,
                )
            ).first()

            if not user or not check_password_hash(user.password_hash, password):
                error = 'Invalid username/email or password.'
            else:
                session.clear()
                session['user_id'] = user.id
                return redirect(request.form.get('next') or next_page)

    return render_template('login.html', error=error, next=request.args.get('next', ''))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── API: Jobs ─────────────────────────────────────────────────────────────────
@app.route('/api/jobs', methods=['GET'])
@login_required
def get_jobs():
    return jsonify([j.to_dict() for j in Job.query.order_by(Job.created_at.desc()).all()])

@app.route('/api/jobs', methods=['POST'])
@login_required
def create_job():
    data = request.get_json()
    if not data or not data.get('title') or not data.get('description'):
        return jsonify({'error': 'title and description are required'}), 400
    job = Job(
        title           = data['title'].strip(),
        description     = data['description'].strip(),
        required_skills = ','.join(s.strip() for s in data.get('skills', []))
    )
    db.session.add(job)
    db.session.commit()
    return jsonify(job.to_dict()), 201

@app.route('/api/jobs/<int:job_id>', methods=['DELETE'])
@login_required
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({'message': 'deleted'})

# ── API: Resume upload ────────────────────────────────────────────────────────
@app.route('/api/resume/upload', methods=['POST'])
@login_required
def upload_resume():
    if 'resume' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file   = request.files['resume']
    job_id = request.form.get('job_id', type=int)

    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not allowed(file.filename):
        return jsonify({'error': 'Allowed types: pdf, docx, txt'}), 400

    filename = secure_filename(file.filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        parsed = parse_resume(filepath)
    except Exception as e:
        return jsonify({'error': f'Parse error: {e}'}), 500

    # Save candidate
    candidate = Candidate(
        name             = parsed['name'],
        email            = parsed['email'],
        skills           = ','.join(parsed['skills']),
        experience_years = parsed['experience_years'],
        filename         = filename,
    )
    db.session.add(candidate)
    db.session.flush()   # get candidate.id before commit

    result = {'candidate': candidate.to_dict(), 'score': None, 'breakdown': None}

    if job_id:
        job = Job.query.get(job_id)
        if job:
            score, breakdown = compute_match_score(parsed, job)
            match = Match(
                job_id       = job.id,
                candidate_id = candidate.id,
                score        = score,
                breakdown    = json.dumps(breakdown),
            )
            db.session.add(match)
            result['score']     = round(score * 100, 1)
            result['breakdown'] = breakdown

    db.session.commit()
    return jsonify(result), 201

# ── API: Candidates ──────────────────────────────────────────────────────────
@app.route('/api/candidates/<int:candidate_id>', methods=['DELETE'])
@login_required
def delete_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    filename = candidate.filename
    db.session.delete(candidate)
    db.session.commit()
    # Delete the file
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    return jsonify({'message': 'deleted'})

# ── API: Matches ──────────────────────────────────────────────────────────────
@app.route('/api/jobs/<int:job_id>/matches', methods=['GET'])
@login_required
def job_matches(job_id):
    Job.query.get_or_404(job_id)
    matches = (Match.query
               .filter_by(job_id=job_id)
               .order_by(Match.score.desc())
               .all())
    return jsonify([m.to_dict() for m in matches])

@app.route('/api/matches/<int:match_id>/status', methods=['PATCH'])
@login_required
def update_status(match_id):
    match  = Match.query.get_or_404(match_id)
    data   = request.get_json()
    status = data.get('status', '').strip()
    if status not in ('new', 'shortlisted', 'rejected'):
        return jsonify({'error': 'Invalid status'}), 400
    match.status = status
    db.session.commit()
    return jsonify({'message': 'updated', 'status': status})


@app.route('/api/live-jobs', methods=['GET'])
@login_required
def live_jobs():
    query    = request.args.get('q', 'python developer')
    location = request.args.get('location', '')
    sources  = request.args.get('sources', 'adzuna,remotive').split(',')

    try:
        jobs = fetch_live_jobs(query, location, sources)
        return jsonify({'count': len(jobs), 'jobs': jobs})
    except Exception as e:
        print(f'Live jobs API error: {e}')
        return jsonify({'error': 'Live job search is currently unavailable', 'count': 0, 'jobs': []}), 503


# ── Import a live job into your DB and auto-match with candidates ─────────────
@app.route('/api/live-jobs/import', methods=['POST'])
@login_required
def import_live_job():
    data = request.get_json()

    # Save as a Job in your database
    job = Job(
        title           = data.get('title', '').strip(),
        description     = data.get('description', '').strip(),
        required_skills = ','.join(data.get('skills', [])),
    )
    db.session.add(job)
    db.session.flush()

    # Auto-match against ALL existing candidates
    candidates = Candidate.query.all()
    matches_created = 0
    for candidate in candidates:
        parsed = {
            'name':             candidate.name,
            'skills':           [s.strip() for s in candidate.skills.split(',') if s.strip()],
            'experience_years': candidate.experience_years,
            'clean_text':       candidate.name + ' ' + candidate.skills,
        }
        score, breakdown = compute_match_score(parsed, job)
        match = Match(
            job_id       = job.id,
            candidate_id = candidate.id,
            score        = score,
            breakdown    = json.dumps(breakdown),
        )
        db.session.add(match)
        matches_created += 1

    db.session.commit()
    return jsonify({
        'message':         f'Job imported and matched against {matches_created} candidates',
        'job':             job.to_dict(),
        'matches_created': matches_created,
    }), 201

# ── Page: live jobs search ────────────────────────────────────────────────────
@app.route('/live-jobs')
@login_required
def live_jobs_page():
    try:
        categories = get_categories(country='in')
    except Exception as e:
        print(f'Error fetching categories: {e}')
        categories = []
    return render_template('live_jobs.html', categories=categories)


# ── API: search Adzuna ────────────────────────────────────────────────────────
@app.route('/api/adzuna/search')
@login_required
def adzuna_search():
    result = search_jobs(
        query            = request.args.get('q', ''),
        location         = request.args.get('location', ''),
        country          = request.args.get('country', 'in'),
        page             = request.args.get('page', 1, type=int),
        results_per_page = request.args.get('per_page', 20, type=int),
        sort_by          = request.args.get('sort_by', 'relevance'),
        salary_min       = request.args.get('salary_min', None, type=int),
        salary_max       = request.args.get('salary_max', None, type=int),
        full_time        = request.args.get('full_time') == '1',
        permanent        = request.args.get('permanent') == '1',
        what_exclude     = request.args.get('exclude', ''),
        category         = request.args.get('category', ''),
    )
    return jsonify(result)


# ── API: categories dropdown ──────────────────────────────────────────────────
@app.route('/api/adzuna/categories')
@login_required
def adzuna_categories():
    country = request.args.get('country', 'in')
    return jsonify(get_categories(country))


# ── API: salary histogram ─────────────────────────────────────────────────────
@app.route('/api/adzuna/salary')
@login_required
def adzuna_salary():
    title   = request.args.get('title', '')
    country = request.args.get('country', 'in')
    if not title:
        return jsonify({'error': 'title param required'}), 400
    return jsonify(get_salary_histogram(title, country))


# ── API: import Adzuna job into DB + auto-match candidates ────────────────────
@app.route('/api/adzuna/import', methods=['POST'])
@login_required
def adzuna_import():
    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({'error': 'title is required'}), 400

    job = Job(
        title           = data['title'].strip(),
        description     = data.get('description', '').strip(),
        required_skills = '',   # Adzuna doesn't return structured skills
    )
    db.session.add(job)
    db.session.flush()

    # Auto-match every existing candidate
    candidates = Candidate.query.all()
    for candidate in candidates:
        parsed = {
            'skills':           [s.strip() for s in candidate.skills.split(',') if s.strip()],
            'experience_years': candidate.experience_years,
            'clean_text':       f"{candidate.name} {candidate.skills}",
        }
        score, breakdown = compute_match_score(parsed, job)
        db.session.add(Match(
            job_id       = job.id,
            candidate_id = candidate.id,
            score        = score,
            breakdown    = json.dumps(breakdown),
        ))

    db.session.commit()
    return jsonify({
        'message':         f'Imported "{job.title}" and matched {len(candidates)} candidates',
        'job_id':          job.id,
        'matches_created': len(candidates),
    }), 201

# ── Page: resume analyzer ─────────────────────────────────────────────────────
@app.route('/resume-analyzer')
@login_required
def resume_analyzer():
    return render_template('resume_analyzer.html')

# ── API: analyze resume with Gemini ───────────────────────────────────────────
@app.route('/api/resume/analyze-gemini', methods=['POST'])
@login_required
def analyze_resume_gemini():
    if 'resume' not in request.files:
        return jsonify({'error': 'No resume file provided'}), 400
    file = request.files['resume']
    job_description = request.form.get('job_description', '').strip()
    if not file or not job_description:
        return jsonify({'error': 'Resume file and job description are required'}), 400

    filename = secure_filename(file.filename)
    if not allowed(filename):
        return jsonify({'error': 'Invalid file type. Only PDF, DOCX, TXT allowed'}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        if filename.lower().endswith('.pdf'):
            resume_content = extract_text_from_pdf(filepath)
        else:
            # For docx/txt, use existing parser or simple read
            with open(filepath, 'r', encoding='utf-8') as f:
                resume_content = f.read()
        
        analysis = analyse_resume_gemini(resume_content, job_description)
        return jsonify({
            'analysis': analysis,
            'resume_filename': filename
        })
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500
    finally:
        # Optionally remove the file after analysis
        if os.path.exists(filepath):
            os.remove(filepath)

# ── Bootstrap ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        os.makedirs('uploads', exist_ok=True)
    app.run(debug=True)