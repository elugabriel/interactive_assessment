# app.py
"""
Interactive Assessment Platform - Single-file Flask app
Stack: Flask + Flask-SQLAlchemy (SQLite)
Passwords are stored as plain text for simplicity.
"""

import os
import random
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, abort
)
from flask_sqlalchemy import SQLAlchemy

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance")
os.makedirs(DB_PATH, exist_ok=True)
DB_FILE = os.path.join(DB_PATH, "database.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", "change-this-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_FILE}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------
# Database models
# ---------------------------------------------------------------------


# -------------------- Student --------------------
class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)  # renamed to 'id' for FK consistency
    fullname = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)  # plain-text password
    class_level = db.Column(db.String(50))
    gender = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------- Admin --------------------
class Admin(db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)  # renamed to 'id' for consistency
    fullname = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)  # plain-text password
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------- Question --------------------
class Question(db.Model):
    __tablename__ = "questions"
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.Text, nullable=False)
    model_answer = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    


# -------------------- Exam --------------------
class Exam(db.Model):
    __tablename__ = "exams"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    total_score = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default="active")
    duration_minutes = db.Column(db.Integer, default=30)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Optional relationship
    student = db.relationship("Student", backref="exams")

# -------------------- ExamQuestion --------------------
class ExamQuestion(db.Model):
    __tablename__ = "exam_questions"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    question_order = db.Column(db.Integer, nullable=False)

# -------------------- ExamAnswer --------------------
class ExamAnswer(db.Model):
    __tablename__ = "exam_answers"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    student_answer = db.Column(db.Text, nullable=True)
    is_correct = db.Column(db.Boolean, default=False)
    score = db.Column(db.Float, default=0) 

# -------------------- AuditLog --------------------
class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------
# Utilities & helpers
# ---------------------------------------------------------------------


def init_db():
    db.create_all()


def login_required_student(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "student_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def login_required_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in as admin to continue.", "warning")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def add_log(student_id, action):
    log = AuditLog(student_id=student_id, action=action)
    db.session.add(log)
    db.session.commit()


def create_exam_for_student(student_id, num_questions=50, duration_minutes=60):
    exam = Exam(student_id=student_id, start_time=datetime.utcnow(),
                duration_minutes=duration_minutes, status="in-progress")
    db.session.add(exam)
    db.session.commit()

    all_qs = Question.query.all()
    if not all_qs:
        return None
    selected = random.sample(all_qs, min(num_questions, len(all_qs)))

    for idx, q in enumerate(selected, start=1):
        eq = ExamQuestion(exam_id=exam.id, question_id=q.id, question_order=idx)
        db.session.add(eq)
    db.session.commit()

    add_log(student_id, f"Started exam {exam.id} with {len(selected)} questions")
    return exam


import difflib

def grade_answer_text(student_answer, model_answer):
    if not student_answer:
        return False, 0

    # Normalize text
    s = student_answer.strip().lower()
    m = model_answer.strip().lower()

    # Compute similarity between 0 and 1
    similarity = difflib.SequenceMatcher(None, s, m).ratio()

    # Decide correct/wrong based on threshold
    is_correct = similarity >= 0.60  # 60% similarity is correct
    score = 1 if is_correct else 0

    return is_correct, score



def grade_exam(exam_id):
    exam = Exam.query.get(exam_id)
    answers = ExamAnswer.query.filter_by(exam_id=exam_id).all()
    total_score = 0

    for ans in answers:
        q = Question.query.get(ans.question_id)
        if not q:
            continue

        # Compare student's answer with model_answer
        is_correct, score = grade_answer_text(ans.student_answer or "", q.model_answer)
        ans.is_correct = is_correct
        ans.score = score
        total_score += score

        db.session.add(ans)

    exam.total_score = total_score
    exam.status = "completed"
    db.session.add(exam)
    db.session.commit()

    return total_score



def check_time_allowed(exam):
    if not exam.start_time:
        return False
    limit = exam.start_time + timedelta(minutes=exam.duration_minutes)
    return datetime.utcnow() <= limit


def auto_submit_exam(exam):
    q_links = ExamQuestion.query.filter_by(exam_id=exam.id).all()
    existing_qids = {a.question_id for a in ExamAnswer.query.filter_by(exam_id=exam.id).all()}
    for ql in q_links:
        if ql.question_id not in existing_qids:
            placeholder = ExamAnswer(exam_id=exam.id, question_id=ql.question_id, student_answer="")
            db.session.add(placeholder)
    db.session.commit()
    total = grade_exam(exam.id)
    exam = Exam.query.get(exam.id)
    exam.status = "auto-submitted"
    exam.end_time = datetime.utcnow()
    exam.total_score = total
    db.session.add(exam)
    db.session.commit()
    add_log(exam.student_id, f"Exam {exam.id} auto-submitted with score {total}")
    return total


# ---------------------------------------------------------------------
# Routes - Student
# ---------------------------------------------------------------------


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form.get("fullname")
        username = request.form.get("username")
        password = request.form.get("password")
        class_level = request.form.get("class_level")
        if not (fullname and username and password):
            flash("Please fill all fields", "danger")
            return redirect(url_for("register"))
        if Student.query.filter_by(username=username).first():
            flash("Username exists", "danger")
            return redirect(url_for("register"))
        student = Student(fullname=fullname, username=username, password=password, class_level=class_level)
        db.session.add(student)
        db.session.commit()
        flash("Registration successful", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        student = Student.query.filter_by(username=username).first()
        if student and student.password == password:
            session.clear()
            session["student_id"] = student.id
            session["student_name"] = student.fullname
            add_log(student.id, "Logged in")
            return redirect(url_for("student_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    sid = session.get("student_id")
    session.clear()
    if sid:
        add_log(sid, "Logged out")
    flash("Logged out", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required_student
def student_dashboard():
    student_id = session["student_id"]
    exams = Exam.query.filter_by(student_id=student_id).order_by(Exam.created_at.desc()).limit(10).all()
    return render_template("student_dashboard.html", exams=exams, student_name=session.get("student_name"))


@app.route("/start_exam", methods=["POST"])
@login_required_student
def start_exam():
    student_id = session["student_id"]

    # Optional: mark old in-progress exams as completed
    old_exams = Exam.query.filter_by(student_id=student_id, status="in-progress").all()
    for e in old_exams:
        e.status = "completed"
        e.end_time = datetime.utcnow()
        db.session.add(e)
    db.session.commit()

    # Create new exam
    exam = create_exam_for_student(student_id, num_questions=50, duration_minutes=60)
    if not exam:
        flash("No questions available.", "danger")
        return redirect(url_for("student_dashboard"))

    return redirect(url_for("exam_page", exam_id=exam.id))



@app.route("/exam/<int:exam_id>")
@login_required_student
def exam_page(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if exam.student_id != session["student_id"]:
        abort(403)
    limit = exam.start_time + timedelta(minutes=exam.duration_minutes)
    remaining = int((limit - datetime.utcnow()).total_seconds())
    if remaining < 0:
        if exam.status == "in-progress":
            auto_submit_exam(exam)
        return redirect(url_for("results_page", exam_id=exam_id))
    return render_template("exam.html", exam=exam, time_remaining=remaining)


@app.route("/api/exam_questions/<int:exam_id>")
@login_required_student
def api_get_exam_questions(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if exam.student_id != session["student_id"]:
        abort(403)

    qlinks = ExamQuestion.query.filter_by(exam_id=exam_id).order_by(ExamQuestion.question_order).all()

    payload = []
    for ql in qlinks:
        q = Question.query.get(ql.question_id)
        payload.append({
            "question_order": ql.question_order,
            "question_id": q.id,  # FIXED
            "question_text": q.question_text  # FIXED
        })

    return jsonify({"exam_id": exam_id, "questions": payload})



@app.route("/submit_exam/<int:exam_id>", methods=["POST"])
@login_required_student
def submit_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if exam.student_id != session["student_id"]:
        abort(403)

    # Check if time expired
    if not check_time_allowed(exam):
        auto_submit_exam(exam)
        flash("Time expired; exam auto-submitted.", "warning")
        return jsonify({
            "status": "auto-submitted",
            "redirect": url_for("results_page", exam_id=exam_id)
        }), 200

    # Get answers from request payload
    data = request.get_json()
    if not data or "answers" not in data:
        return jsonify({"error": "Invalid payload"}), 400

    answers = data["answers"]
    for item in answers:
        qid = item.get("question_id")
        ans_text = item.get("answer", "")
        if qid is None:
            continue  # skip invalid entries

        existing = ExamAnswer.query.filter_by(exam_id=exam_id, question_id=qid).first()
        if existing:
            existing.student_answer = ans_text
            db.session.add(existing)
        else:
            new_answer = ExamAnswer(
                exam_id=exam_id,
                question_id=qid,
                student_id=exam.student_id,  # ensure student_id is recorded
                student_answer=ans_text
            )
            db.session.add(new_answer)

    db.session.commit()

    # Grade the exam
    total_score = 0
    exam_answers = ExamAnswer.query.filter_by(exam_id=exam_id).all()
    for ans in exam_answers:
        q = Question.query.get(ans.question_id)
        is_correct, score = grade_answer_text(ans.student_answer or "", q.model_answer)
        ans.is_correct = is_correct
        ans.score = score
        total_score += score
        db.session.add(ans)
    exam.total_score = total_score
    exam.status = "completed"
    db.session.add(exam)
    db.session.commit()

    return jsonify({
        "status": "graded",
        "total_score": total_score,
        "redirect": url_for("results_page", exam_id=exam_id)
    }), 200




@app.route("/results/<int:exam_id>")
@login_required_student
def results_page(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if exam.student_id != session["student_id"]:
        abort(403)

    answers = ExamAnswer.query.filter_by(exam_id=exam_id).all()
    results = []

    for a in answers:
        q = Question.query.get(a.question_id)
        results.append({
            "question_id": q.id,
            "question_text": q.question_text,
            "student_answer": a.student_answer,
            "correct_answer": q.model_answer,  # use model_answer here
            "is_correct": a.is_correct,
            "score": a.score
        })

    return render_template("results.html", exam=exam, results=results)





@app.route("/api/results_data/<int:exam_id>")
@login_required_student
def api_results_data(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if exam.student_id != session["student_id"]:
        abort(403)
    answers = ExamAnswer.query.filter_by(exam_id=exam_id).all()
    max_score = len(answers)
    correct = sum(1 for a in answers if a.is_correct)
    incorrect = max_score - correct
    topic_summary = {}
    for a in answers:
        q = Question.query.get(a.question_id)
        topic = "General"

        if topic not in topic_summary:
            topic_summary[topic] = {"total": 0, "correct": 0}
        topic_summary[topic]["total"] += 1
        if a.is_correct:
            topic_summary[topic]["correct"] += 1
    topics = list(topic_summary.keys())
    topic_correct = [topic_summary[t]["correct"] for t in topics]
    topic_total = [topic_summary[t]["total"] for t in topics]
    return jsonify({
        "exam_id": exam_id,
        "total_score": exam.total_score,
        "max_score": max_score,
        "correct_count": correct,
        "incorrect_count": incorrect,
        "topics": topics,
        "topic_correct": topic_correct,
        "topic_total": topic_total
    })


# ---------------------------------------------------------------------
# Routes - Admin
# ---------------------------------------------------------------------


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.password == password:
            session.clear()
            session["admin_id"] = admin.id
            session["admin_name"] = admin.fullname
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials", "danger")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    flash("Admin logged out", "info")
    return redirect(url_for("home"))


@app.route("/admin/dashboard")
@login_required_admin
def admin_dashboard():
    questions = Question.query.order_by(Question.created_at.desc()).limit(100).all()
    return render_template("admin_dashboard.html", questions=questions)


@app.route("/admin/add_question", methods=["GET", "POST"])
def admin_add_question():
    if request.method == "POST":
        question_text = request.form.get("question_text")
        model_answer = request.form.get("model_answer")

        if not question_text or not model_answer:
            flash("Question text and correct answer required", "danger")
            return redirect(url_for("admin_add_question"))

        q = Question(question_text=question_text, model_answer=model_answer)
        db.session.add(q)
        db.session.commit()

        flash("Question added successfully!", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_add_question.html")


@app.route("/admin/upload_exam", methods=["GET", "POST"])
def admin_upload_exam():
    if request.method == "POST":
        file = request.files.get("file")
        if file and file.filename.endswith(".xlsx"):
            filepath = os.path.join("uploads", secure_filename(file.filename))
            file.save(filepath)
            df = pd.read_excel(filepath)
            required_cols = ["Question Text", "Model Answer"]
            if not all(col in df.columns for col in required_cols):
                flash("Excel must contain 'Question Text' and 'Model Answer'", "error")
                return redirect(request.url)
            for _, row in df.iterrows():
                q = Question(
                    question_text=row["Question Text"],
                    model_answer=row["Model Answer"]
                )
                db.session.add(q)
            db.session.commit()
            flash("Questions loaded successfully!", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("admin_upload.html")


# ---------------------------------------------------------------------
# CLI Utilities
# ---------------------------------------------------------------------


@app.cli.command("init-db")
def cli_init_db():
    init_db()
    print("Database initialized.")


@app.cli.command("create-admin")
def cli_create_admin():
    username = input("Admin username: ").strip()
    fullname = input("Fullname: ").strip()
    pwd = input("Password: ").strip()
    if not username or not pwd:
        print("username and password required.")
        return
    if Admin.query.filter_by(username=username).first():
        print("Admin exists.")
        return
    admin = Admin(fullname=fullname, username=username, password=pwd)
    db.session.add(admin)
    db.session.commit()
    print("Admin created.")


# ---------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)

