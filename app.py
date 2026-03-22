from flask import Flask, render_template, request, redirect, session, flash, url_for
import sqlite3
import random
import re
from flask import jsonify
import hashlib
import os
import csv

app = Flask(__name__)
app.secret_key = "change_this_to_a_secure_random_value"

# ---------------- PASSWORD UTILS ---------------- #

def hash_password(password: str) -> str:
    """Return a salted SHA256 hash for the given password."""
    salt = os.environ.get("PASSWORD_SALT", "change_this_default_salt")
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    return hash_password(password) == stored_hash


# Context processor to make user available in all templates
@app.context_processor
def inject_user():
    user = session.get('user')
    admin = session.get('admin')
    return {
        'current_user': type('User', (), {
            'is_authenticated': bool(user),
            'name': user.get('name') if user else None,
            'department': user.get('department') if user else None,
            'ktuid': user.get('ktuid') if user else None,
            'roll_no': user.get('roll_no') if user else None,
            'id': user.get('id') if user else None
        })(),
        'current_admin': type('Admin', (), {
            'is_authenticated': bool(admin),
            'username': admin.get('username') if admin else None,
            'name': admin.get('name') if admin else None
        })()
    }

# ---------------- DATABASE ---------------- #

def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS mcq (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        semester TEXT,
        subject TEXT,
        question TEXT,
        option1 TEXT,
        option2 TEXT,
        option3 TEXT,
        option4 TEXT,
        answer TEXT,
        module TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        ktuid TEXT UNIQUE,
        roll_no TEXT,
        department TEXT,
        password_hash TEXT,
        total_score REAL DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        semester TEXT,
        subject TEXT,
        module TEXT,
        score REAL,
        total_marks REAL,
        correct INTEGER,
        total_questions INTEGER,
        taken_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        name TEXT,
        password_hash TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS co_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        semester TEXT NOT NULL,
        subject TEXT NOT NULL,
        module TEXT,
        course_outcome TEXT,
        question_text TEXT NOT NULL,
        UNIQUE(semester, subject, module, course_outcome, question_text)
    )
    """)

    conn.commit()
    # ensure existing DB has `module` column
    try:
        c.execute("ALTER TABLE mcq ADD COLUMN module TEXT")
        conn.commit()
    except Exception:
        # column likely exists
        pass

    # ensure existing DB has `password_hash` column for users
    try:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        conn.commit()
    except Exception:
        # column likely exists
        pass

    # create default admin if none exists
    c.execute("SELECT COUNT(*) FROM admins")
    admin_count = c.fetchone()[0]
    if admin_count == 0:
        default_username = os.environ.get("ADMIN_USERNAME", "admin")
        default_password = os.environ.get("ADMIN_PASSWORD", "admin123")
        default_name = os.environ.get("ADMIN_NAME", "Administrator")
        c.execute(
            "INSERT INTO admins (username, name, password_hash) VALUES (?,?,?)",
            (default_username, default_name, hash_password(default_password)),
        )
        conn.commit()

    # import CO questions from co.csv (if present)
    co_csv_path = os.path.join(os.path.dirname(__file__), "co.csv")
    if os.path.exists(co_csv_path):
        try:
            c.execute("DELETE FROM co_questions")
            conn.commit()
            with open(co_csv_path, mode="r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    semester = (row.get("semester") or "").strip()
                    subject = (row.get("subject") or "").strip()
                    module = (row.get("module") or "").strip()
                    course_outcome = (row.get("course_outcome") or "").strip()
                    question_text = (row.get("question_text") or "").strip()
                    if not (semester and subject and question_text):
                        continue
                    c.execute(
                        """
                        INSERT OR IGNORE INTO co_questions
                        (semester, subject, module, course_outcome, question_text)
                        VALUES (?,?,?,?,?)
                        """,
                        (semester, subject, module, course_outcome, question_text),
                    )
            conn.commit()
        except Exception:
            # avoid breaking app startup if CSV has issues
            pass

    conn.close()

init_db()





# ---------------- ROUTES ---------------- #

@app.route("/")
def home():
    if session.get('admin'):
        return redirect(url_for('admin_dashboard'))
    if session.get('user'):
        return redirect(url_for('dashboard'))
    return render_template('home.html')


@app.route('/dashboard')
def dashboard():
    if not session.get('user'):
        return redirect(url_for('login'))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT semester FROM mcq")
    semesters = [r[0] for r in c.fetchall() if r[0] and re.match(r'^S\d', r[0].strip())]
    semesters = sorted(set(semesters), key=lambda s: int(re.search(r"(\d+)", s).group(1)) if re.search(r"(\d+)", s) else 999)
    conn.close()

    return render_template('dashboard.html', semesters=semesters)


@app.route('/syllabus')
def syllabus():
    if not session.get('user'):
        return redirect(url_for('login'))

    semester = (request.args.get('semester') or '').strip()
    subject = (request.args.get('subject') or '').strip()
    module = (request.args.get('module') or '').strip()

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT DISTINCT semester FROM co_questions")
    co_semesters = [r[0] for r in c.fetchall() if r[0]]
    co_semesters = sorted(
        set(co_semesters),
        key=lambda s: int(re.search(r"(\d+)", s).group(1)) if re.search(r"(\d+)", s) else 999,
    )

    query = """
        SELECT semester, subject, module, course_outcome, question_text
        FROM co_questions
        WHERE 1=1
    """
    params = []
    if semester:
        query += " AND semester=?"
        params.append(semester)
    if subject:
        query += " AND subject=?"
        params.append(subject)
    if module:
        query += " AND module=?"
        params.append(module)
    query += " ORDER BY semester, subject, module, course_outcome, id"

    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()

    return render_template(
        'syllabus.html',
        semesters=co_semesters,
        selected_semester=semester,
        selected_subject=subject,
        selected_module=module,
        rows=rows,
    )


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not (username and password):
            flash('Please enter username and password', 'danger')
            return render_template('admin_login.html', username=username)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("SELECT id, username, name, password_hash FROM admins WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()

        if not row:
            flash('Invalid admin credentials', 'danger')
            return render_template('admin_login.html', username=username)

        admin_id, username_db, name, password_hash = row
        if not verify_password(password, password_hash):
            flash('Invalid admin credentials', 'danger')
            return render_template('admin_login.html', username=username)

        session['admin'] = {'id': admin_id, 'username': username_db, 'name': name}
        flash('Admin login successful', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    flash('Admin logged out', 'info')
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    ktuid_filter = request.args.get('ktuid', '').strip()
    department_filter = request.args.get('department', '').strip()

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    user_filters = []
    user_filter_params = []
    if ktuid_filter:
        user_filters.append("u.ktuid = ?")
        user_filter_params.append(ktuid_filter)
    if department_filter:
        user_filters.append("u.department = ?")
        user_filter_params.append(department_filter)
    where_users = f"WHERE {' AND '.join(user_filters)}" if user_filters else ""

    c.execute(f"SELECT COUNT(*) FROM users u {where_users}", tuple(user_filter_params))
    total_students = c.fetchone()[0]

    c.execute(
        f"""
        SELECT COUNT(*)
        FROM scores s
        JOIN users u ON u.id = s.user_id
        {where_users}
        """,
        tuple(user_filter_params),
    )
    total_attempts = c.fetchone()[0]

    c.execute(
        f"""
        SELECT IFNULL(SUM(s.score), 0), IFNULL(SUM(s.total_marks), 0)
        FROM scores s
        JOIN users u ON u.id = s.user_id
        {where_users}
        """,
        tuple(user_filter_params),
    )
    total_scored, total_possible = c.fetchone()
    avg_percent = round((total_scored / total_possible) * 100, 2) if total_possible else 0

    c.execute(f"""
        SELECT u.name, u.ktuid, u.department,
               COUNT(s.id) AS attempts,
               IFNULL(SUM(s.score), 0) AS scored,
               IFNULL(SUM(s.total_marks), 0) AS possible,
               u.id
        FROM users u
        LEFT JOIN scores s ON s.user_id = u.id
        {where_users}
        GROUP BY u.id, u.name, u.ktuid, u.department
        ORDER BY attempts DESC, u.name ASC
    """, tuple(user_filter_params))
    students = c.fetchall()

    c.execute(f"""
        SELECT u.name, u.ktuid, s.semester, s.subject, s.module, s.score, s.total_marks, s.correct, s.total_questions, s.taken_at
        FROM scores s
        JOIN users u ON u.id = s.user_id
        {where_users}
        ORDER BY s.taken_at DESC
        LIMIT 200
    """, tuple(user_filter_params))
    attempts = c.fetchall()

    conn.close()
    return render_template(
        'admin_dashboard.html',
        total_students=total_students,
        total_attempts=total_attempts,
        avg_percent=avg_percent,
        students=students,
        attempts=attempts,
        ktuid_filter=ktuid_filter,
        department_filter=department_filter,
    )


@app.route('/admin/student/<int:user_id>')
def admin_student_detail(user_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute(
        "SELECT id, name, ktuid, roll_no, department FROM users WHERE id=?",
        (user_id,),
    )
    student = c.fetchone()

    if not student:
        conn.close()
        flash('Student not found', 'danger')
        return redirect(url_for('admin_dashboard'))

    c.execute(
        """
        SELECT semester, subject, module, score, total_marks, correct, total_questions, taken_at
        FROM scores
        WHERE user_id=?
        ORDER BY taken_at DESC
        """,
        (user_id,),
    )
    history = c.fetchall()

    c.execute(
        """
        SELECT COUNT(*), IFNULL(SUM(score), 0), IFNULL(SUM(total_marks), 0)
        FROM scores
        WHERE user_id=?
        """,
        (user_id,),
    )
    total_attempts, total_scored, total_possible = c.fetchone()
    avg_percent = round((total_scored / total_possible) * 100, 2) if total_possible else 0

    conn.close()
    return render_template(
        'admin_student_detail.html',
        student=student,
        history=history,
        total_attempts=total_attempts,
        total_scored=total_scored,
        total_possible=total_possible,
        avg_percent=avg_percent,
    )


@app.route('/api/subjects')
def api_subjects():
    semester = request.args.get('semester')
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if not semester:
        return jsonify([])
    c.execute("SELECT DISTINCT subject FROM mcq WHERE semester=?", (semester,))
    subjects = [r[0] for r in c.fetchall()]
    conn.close()
    return jsonify(subjects)


@app.route('/api/modules')
def api_modules():
    semester = request.args.get('semester')
    subject = request.args.get('subject')
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if not (semester and subject):
        return jsonify([])
    c.execute("SELECT DISTINCT module FROM mcq WHERE semester=? AND subject=? AND module IS NOT NULL", (semester, subject))
    modules = [r[0] for r in c.fetchall() if r[0]]
    conn.close()
    return jsonify(modules)


@app.route('/api/co_subjects')
def api_co_subjects():
    semester = request.args.get('semester')
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if not semester:
        conn.close()
        return jsonify([])
    c.execute("SELECT DISTINCT subject FROM co_questions WHERE semester=? ORDER BY subject", (semester,))
    subjects = [r[0] for r in c.fetchall() if r[0]]
    conn.close()
    return jsonify(subjects)


@app.route('/api/co_modules')
def api_co_modules():
    semester = request.args.get('semester')
    subject = request.args.get('subject')
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if not (semester and subject):
        conn.close()
        return jsonify([])
    c.execute(
        "SELECT DISTINCT module FROM co_questions WHERE semester=? AND subject=? AND module IS NOT NULL ORDER BY module",
        (semester, subject),
    )
    modules = [r[0] for r in c.fetchall() if r[0]]
    conn.close()
    return jsonify(modules)


@app.route("/subjects/<semester>")
def subjects(semester):
    if not session.get('user'):
        return redirect(url_for('login'))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT DISTINCT subject FROM mcq WHERE semester=?", (semester,))
    subjects = c.fetchall()

    conn.close()

    return render_template("subjects.html", semester=semester, subjects=subjects)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ktuid = request.form.get('ktuid', '').strip()
        roll_no = request.form.get('roll_no', '').strip()
        department = request.form.get('department', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not (name and ktuid and roll_no and department and password and confirm_password):
            flash('Please fill all fields', 'danger')
            return render_template(
                'register.html',
                name=name,
                ktuid=ktuid,
                roll_no=roll_no,
                department=department,
            )

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template(
                'register.html',
                name=name,
                ktuid=ktuid,
                roll_no=roll_no,
                department=department,
            )

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE ktuid=?", (ktuid,))
        existing = c.fetchone()
        if existing:
            conn.close()
            flash('An account with this KTU ID already exists. Please login.', 'warning')
            return redirect(url_for('login'))

        password_hash = hash_password(password)
        c.execute(
            "INSERT INTO users (name, ktuid, roll_no, department, password_hash) VALUES (?,?,?,?,?)",
            (name, ktuid, roll_no, department, password_hash),
        )
        user_id = c.lastrowid
        conn.commit()
        conn.close()

        session['user'] = {
            'id': user_id,
            'name': name,
            'ktuid': ktuid,
            'roll_no': roll_no,
            'department': department,
        }
        flash('Registration successful. You are now logged in.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user'):
        return redirect(url_for('profile'))

    if request.method == 'POST':
        ktuid = request.form.get('ktuid', '').strip()
        password = request.form.get('password', '')

        if not (ktuid and password):
            flash('Please enter both KTU ID and password', 'danger')
            return render_template('login.html', ktuid=ktuid)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute(
            "SELECT id, name, ktuid, roll_no, department, password_hash FROM users WHERE ktuid=?",
            (ktuid,),
        )
        row = c.fetchone()
        conn.close()

        if not row:
            flash('No account found for this KTU ID. Please register first.', 'danger')
            return redirect(url_for('register'))

        user_id, name, ktuid_db, roll_no, department, password_hash = row

        if not password_hash:
            flash('This account does not have a password set. Please register again.', 'warning')
            return redirect(url_for('register'))

        if not verify_password(password, password_hash):
            flash('Invalid KTU ID or password', 'danger')
            return render_template('login.html', ktuid=ktuid)

        session['user'] = {
            'id': user_id,
            'name': name,
            'ktuid': ktuid_db,
            'roll_no': roll_no,
            'department': department,
        }
        flash('Logged in successfully', 'success')
        return redirect(url_for('profile'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('admin', None)
    flash('Logged out', 'info')
    return redirect(url_for('home'))


@app.route('/profile')
def profile():
    if not session.get('user'):
        return redirect(url_for('login'))

    user_id = session['user']['id']
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT id, name, ktuid, roll_no, department FROM users WHERE id=?", (user_id,))
    user = c.fetchone()

    c.execute(
        "SELECT semester, subject, module, score, total_marks, correct, total_questions, taken_at FROM scores WHERE user_id=? ORDER BY taken_at DESC",
        (user_id,),
    )
    history = c.fetchall()

    conn.close()
    return render_template('profile.html', user=user, history=history)


@app.route("/quiz/<semester>/<subject>", methods=["GET","POST"])
def quiz(semester, subject):
    if not session.get('user'):
        return redirect(url_for('login'))

    # module comes from query params (both for GET display and POST submit)
    module = request.args.get('module')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == "POST":
        # collect submitted question ids
        submitted_keys = [k for k in request.form.keys() if k.isdigit()]
        qids = [int(k) for k in submitted_keys]

        total_questions = len(qids)
        # MCQ: 1 mark per question
        total_marks = float(request.form.get('total_marks') or 0)
        if total_marks <= 0:
            total_marks = total_questions

        score_correct = 0
        review_list = []  # list of dicts: question, options, correct_answer, user_answer, is_correct
        if qids:
            placeholders = ','.join('?' for _ in qids)
            c.execute(f"SELECT id, question, option1, option2, option3, option4, answer FROM mcq WHERE id IN ({placeholders})", qids)
            rows_by_id = {r[0]: r for r in c.fetchall()}
            # preserve order of qids
            for idx, qid in enumerate(qids):
                row = rows_by_id.get(qid)
                if not row:
                    continue
                qid, question_text, o1, o2, o3, o4, correct_ans = row
                options = [o1, o2, o3, o4]
                user_ans = request.form.get(str(qid), '').strip()
                is_correct = bool(user_ans and correct_ans and user_ans == correct_ans)
                if is_correct:
                    score_correct += 1
                review_list.append({
                    'num': idx + 1,
                    'question': question_text,
                    'options': options,
                    'correct_answer': correct_ans,
                    'user_answer': user_ans,
                    'is_correct': is_correct,
                })

        # 1 mark per correct answer
        marks_awarded = score_correct
        total_display = total_questions
        percent = round((score_correct / total_display) * 100, 2) if total_display else 0
        incorrect = total_display - score_correct

        # store attempt for logged-in user
        try:
            user_id = session.get('user', {}).get('id')
            if user_id:
                from datetime import datetime
                taken_at = datetime.utcnow().isoformat()
                c.execute("INSERT INTO scores (user_id, semester, subject, module, score, total_marks, correct, total_questions, taken_at) VALUES (?,?,?,?,?,?,?,?,?)",
                          (user_id, semester, subject, module, marks_awarded, total_display, score_correct, total_questions, taken_at))
                # update total score for user
                c.execute("UPDATE users SET total_score = IFNULL(total_score,0) + ? WHERE id=?", (marks_awarded, user_id))
                conn.commit()
        except Exception:
            # ignore DB errors to avoid breaking result display
            pass

        conn.close()
        return render_template("result.html",
                              score=marks_awarded,
                              total=total_display,
                              correct=score_correct,
                              incorrect=incorrect,
                              total_questions=total_questions,
                              semester=semester,
                              subject=subject,
                              percent=percent,
                              review=review_list)

    # GET: optional filters
    try:
        count = int(request.args.get('count')) if request.args.get('count') else None
    except ValueError:
        count = None

    query = "SELECT * FROM mcq WHERE semester=? AND subject=?"
    params = [semester, subject]
    if module:
        # match module headers loosely (CSV stores full headings like 'Module 1 – Topic')
        query += " AND module LIKE ?"
        params.append(f"%{module}%")

    if count:
        query += " ORDER BY RANDOM() LIMIT ?"
        params.append(count)
    questions = c.execute(query, params).fetchall()

    conn.close()
    # duration passed via query param (seconds) default 0 (no timer)
    duration = int(request.args.get('duration') or 0)
    # MCQ: 1 mark per question (total_marks = number of questions)
    total_marks = len(questions)
    return render_template("quiz.html",
                           questions=questions,
                           semester=semester,
                           subject=subject,
                           duration=duration,
                           total_marks=total_marks,
                           requested_count=count)


if __name__ == "__main__":
    app.run(debug=True)
