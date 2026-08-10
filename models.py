from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class Job(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.Text, default='')   # comma-separated
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    matches      = db.relationship('Match', backref='job', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'required_skills': [s.strip() for s in self.required_skills.split(',') if s.strip()],
            'created_at': self.created_at.strftime('%d %b %Y'),
            'match_count': len(self.matches)
        }

class Candidate(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(200), default='Unknown')
    email            = db.Column(db.String(200), default='')
    skills           = db.Column(db.Text, default='')   # comma-separated
    experience_years = db.Column(db.Float, default=0)
    filename         = db.Column(db.String(300), default='')
    uploaded_at      = db.Column(db.DateTime, default=datetime.utcnow)
    matches          = db.relationship('Match', backref='candidate', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'skills': [s.strip() for s in self.skills.split(',') if s.strip()],
            'experience_years': self.experience_years,
            'filename': self.filename,
            'uploaded_at': self.uploaded_at.strftime('%d %b %Y')
        }

class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default='user')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.strftime('%d %b %Y')
        }

class Match(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    job_id       = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'), nullable=False)
    score        = db.Column(db.Float, default=0)        # 0-1
    breakdown    = db.Column(db.Text, default='{}')      # JSON
    status       = db.Column(db.String(50), default='new')  # new | shortlisted | rejected
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        c = self.candidate
        return {
            'id': self.id,
            'job_id': self.job_id,
            'candidate_id': self.candidate_id,
            'candidate_name': c.name if c else 'Unknown',
            'candidate_email': c.email if c else '',
            'candidate_skills': [s.strip() for s in c.skills.split(',') if s.strip()] if c else [],
            'experience_years': c.experience_years if c else 0,
            'score': round(self.score * 100, 1),
            'breakdown': json.loads(self.breakdown),
            'status': self.status,
            'created_at': self.created_at.strftime('%d %b %Y')
        }