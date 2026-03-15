import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'local-development-key'


@app.template_filter('date_only')
def date_only(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    return str(value).split(' ')[0]


def normalize_tag_label(label):
    if not label:
        return ''
    collapsed_spaces = ' '.join(label.strip().split())
    return collapsed_spaces.title()

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = BASE_DIR / 'schema.sql'
SQLITE_DB_FILE = BASE_DIR / 'omniworkspace.db'
database_url = f"sqlite:///{SQLITE_DB_FILE.as_posix()}"


def ensure_local_sqlite_schema():
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Missing schema file: {SCHEMA_FILE}")

    connection = sqlite3.connect(SQLITE_DB_FILE)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        schema_sql = SCHEMA_FILE.read_text(encoding='utf-8')
        connection.executescript(schema_sql)
        connection.commit()
    finally:
        connection.close()


ensure_local_sqlite_schema()

engine = create_engine(database_url)
is_sqlite = database_url.startswith('sqlite')


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if is_sqlite:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def insert_task_and_get_id(conn, task_data):
    insert_query = text("""
        INSERT INTO tasks (
            user_id, title, description, due_date, priority,
            energy_required, status, category_id, course_id, project_id,
            is_recurring, [interval]
        )
        VALUES (
            :user_id, :title, :description, :due_date, :priority,
            :energy_required, :status, :category_id, :course_id, :project_id,
            :is_recurring, :interval
        )
        RETURNING id
    """)
    inserted_row = conn.execute(insert_query, task_data).fetchone()
    return inserted_row.id if inserted_row else None


def compute_next_due_date(current_due_date, interval_value):
    if current_due_date is None:
        return None

    if isinstance(current_due_date, datetime):
        base_date = current_due_date.date()
    elif isinstance(current_due_date, date):
        base_date = current_due_date
    else:
        due_date_text = str(current_due_date).split(' ')[0]
        base_date = datetime.strptime(due_date_text, '%Y-%m-%d').date()

    if interval_value == 'daily':
        return base_date + timedelta(days=1)
    if interval_value == 'weekly':
        return base_date + timedelta(days=7)
    if interval_value == 'monthly':
        month = base_date.month + 1
        year = base_date.year
        if month > 12:
            month = 1
            year += 1

        max_day = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                   31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
        day = min(base_date.day, max_day)
        return date(year, month, day)

    return None


def maybe_clone_recurring_task(conn, user_id, task_id, previous_status, new_status):
    if new_status != 'completed' or previous_status == 'completed':
        return

    recurring_task_query = text("""
        SELECT id, title, description, due_date, priority, energy_required,
               category_id, course_id, project_id, is_recurring, [interval]
        FROM tasks
        WHERE id = :task_id AND user_id = :user_id
    """)
    recurring_task = conn.execute(recurring_task_query, {
        "task_id": task_id,
        "user_id": user_id
    }).fetchone()

    if not recurring_task or not recurring_task.is_recurring:
        return

    interval_value = (recurring_task.interval or '').strip().lower()
    allowed_intervals = {'daily', 'weekly', 'monthly'}
    if interval_value not in allowed_intervals:
        return

    next_due_date = compute_next_due_date(recurring_task.due_date, interval_value)
    if not next_due_date:
        return

    new_task_id = insert_task_and_get_id(conn, {
        "user_id": user_id,
        "title": recurring_task.title,
        "description": recurring_task.description,
        "due_date": next_due_date,
        "priority": recurring_task.priority,
        "energy_required": recurring_task.energy_required,
        "status": 'pending',
        "category_id": recurring_task.category_id,
        "course_id": recurring_task.course_id,
        "project_id": recurring_task.project_id,
        "is_recurring": 1,
        "interval": interval_value
    })

    if not new_task_id:
        return

    copy_tags_query = text("""
        INSERT INTO task_tags (task_id, tag_id)
        SELECT :new_task_id, tag_id
        FROM task_tags
        WHERE task_id = :original_task_id
    """)
    conn.execute(copy_tags_query, {
        "new_task_id": new_task_id,
        "original_task_id": task_id
    })


def sync_project_status(conn, user_id, project_id):
    if not project_id:
        return

    summary_query = text("""
        SELECT
            COUNT(*) AS total_tasks,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_tasks,
            SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress_tasks
        FROM tasks
        WHERE user_id = :user_id AND project_id = :project_id
    """)
    summary = conn.execute(summary_query, {"user_id": user_id, "project_id": project_id}).fetchone()

    total_tasks = int(summary.total_tasks or 0)
    completed_tasks = int(summary.completed_tasks or 0)
    in_progress_tasks = int(summary.in_progress_tasks or 0)

    new_status = 'pending'
    if total_tasks > 0 and completed_tasks == total_tasks:
        new_status = 'completed'
    elif in_progress_tasks > 0:
        new_status = 'progress'

    update_query = text("""
        UPDATE projects
        SET status = :status
        WHERE id = :project_id AND user_id = :user_id
    """)
    conn.execute(update_query, {"status": new_status, "project_id": project_id, "user_id": user_id})


def is_valid_session_user(user_id):
    if not user_id:
        return False
    with engine.connect() as conn:
        user_row = conn.execute(
            text("SELECT 1 FROM users WHERE id = :user_id"),
            {"user_id": user_id}
        ).fetchone()
    return bool(user_row)


@app.before_request
def enforce_authentication():
    public_endpoints = {'login', 'register', 'static'}
    endpoint = request.endpoint or ''

    if endpoint in public_endpoints:
        return

    user_id = session.get('user_id')
    if not is_valid_session_user(user_id):
        session.pop('user_id', None)
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('login'))


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not is_valid_session_user(user_id):
            session.pop('user_id', None)
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def index():
    user_id = session['user_id']
    today_iso = date.today().strftime('%Y-%m-%d')

    with engine.connect() as conn:
        query = text("""
            SELECT
                p.id AS project_id,
                p.name AS project_name,
                p.status AS project_status,
                c.color_hex AS category_color,
                c.name AS category_name,
                crs.code AS course_code,
                t.id AS task_id,
                t.title AS task_title,
                t.status AS task_status,
                t.due_date AS task_due_date,
                t.priority AS task_priority
            FROM projects p
            JOIN categories c ON p.category_id = c.id
            LEFT JOIN courses crs ON p.course_id = crs.id
            LEFT JOIN tasks t ON t.project_id = p.id AND t.user_id = :user_id
            WHERE p.user_id = :user_id
            ORDER BY p.name ASC, t.due_date ASC
        """)
        rows = conn.execute(query, {"user_id": user_id}).fetchall()

        tag_query = text("""
            SELECT tt.task_id, tg.id AS tag_id, tg.label
            FROM task_tags tt
            JOIN tags tg ON tg.id = tt.tag_id
            JOIN tasks t ON t.id = tt.task_id
            WHERE t.user_id = :user_id
            ORDER BY tg.label
        """)
        tag_rows = conn.execute(tag_query, {"user_id": user_id}).fetchall()

        daily_tasks_query = text("""
            SELECT
            t.id,
            t.title,
            t.status,
            t.due_date,
            t.priority,
            c.name AS category_name,
            c.color_hex AS category_color,
            p.name AS project_name
            FROM tasks t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN projects p ON p.id = t.project_id
            WHERE t.user_id = :user_id
              AND date(t.due_date) = :today_iso
            ORDER BY
            CASE t.status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END,
            CASE t.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
            t.id DESC
        """)
        daily_task_rows = conn.execute(daily_tasks_query, {
            "user_id": user_id,
            "today_iso": today_iso
        }).fetchall()

        calendar_tasks_query = text("""
            SELECT
                t.id,
                t.title,
                t.status,
                t.due_date,
                t.priority,
                c.name AS category_name,
                c.color_hex AS category_color,
                p.name AS project_name
            FROM tasks t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN projects p ON p.id = t.project_id
            WHERE t.user_id = :user_id
              AND t.due_date IS NOT NULL
            ORDER BY t.due_date ASC, t.id ASC
        """)
        calendar_task_rows = conn.execute(calendar_tasks_query, {"user_id": user_id}).fetchall()

    tags_by_task = {}
    for tag_row in tag_rows:
        task_id = tag_row.task_id
        if task_id not in tags_by_task:
            tags_by_task[task_id] = []
        tags_by_task[task_id].append({"id": tag_row.tag_id, "label": tag_row.label})

    projects_map = {}
    for row in rows:
        project_id = row.project_id
        if project_id not in projects_map:
            projects_map[project_id] = {
                "id": project_id,
                "name": row.project_name,
                "status": row.project_status,
                "category_color": row.category_color,
                "category_name": row.category_name,
                "course_code": row.course_code,
                "due_date": None,
                "tasks": []
            }

        if row.task_id:
            projects_map[project_id]["tasks"].append({
                "id": row.task_id,
                "title": row.task_title,
                "status": row.task_status,
                "due_date": row.task_due_date,
                "priority": row.task_priority,
                "tags": tags_by_task.get(row.task_id, [])
            })
            if row.task_due_date and (
                projects_map[project_id]["due_date"] is None
                or row.task_due_date > projects_map[project_id]["due_date"]
            ):
                projects_map[project_id]["due_date"] = row.task_due_date

    projects = list(projects_map.values())

    daily_tasks = []
    for row in daily_task_rows:
        daily_tasks.append({
            "id": row.id,
            "title": row.title,
            "status": row.status,
            "due_date": row.due_date,
            "priority": row.priority,
            "category_name": row.category_name,
            "category_color": row.category_color,
            "project_name": row.project_name,
            "tags": tags_by_task.get(row.id, [])
        })

    calendar_events = []
    for row in calendar_task_rows:
        due_iso = date_only(row.due_date)
        if not due_iso:
            continue
        calendar_events.append({
            "id": row.id,
            "title": row.title,
            "status": row.status,
            "due_date": due_iso,
            "priority": row.priority,
            "category_name": row.category_name,
            "category_color": row.category_color,
            "project_name": row.project_name,
            "tags": tags_by_task.get(row.id, [])
        })

    return render_template(
        'dashboard.html',
        projects=projects,
        daily_tasks=daily_tasks,
        today_iso=today_iso,
        calendar_events=calendar_events
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please fill out all fields.', 'danger')
            return redirect(url_for('register'))

        with engine.connect() as conn:
            query = text("SELECT id FROM users WHERE username = :username")
            existing_user = conn.execute(query, {"username": username}).fetchone()

            if existing_user:
                flash('Username already exists. Please choose a different one.', 'danger')
                return redirect(url_for('register'))

            hashed_pw = generate_password_hash(password)
            insert_query = text("INSERT INTO users (username, password_hash) VALUES (:username, :password_hash)")
            conn.execute(insert_query, {"username": username, "password_hash": hashed_pw})
            conn.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please fill out all fields.', 'danger')
            return redirect(url_for('login'))

        with engine.connect() as conn:
            query = text("SELECT id, password_hash FROM users WHERE username = :username")
            user = conn.execute(query, {"username": username}).fetchone()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/categories', methods=['GET', 'POST'])
@login_required
def categories():
    user_id = session['user_id']

    if request.method == 'POST':
        name = request.form.get('name')
        color_hex = request.form.get('color_hex', '#cccccc')

        if name:
            with engine.connect() as conn:
                query = text("INSERT INTO categories (user_id, name, color_hex) VALUES (:user_id, :name, :color_hex)")
                conn.execute(query, {"user_id": user_id, "name": name, "color_hex": color_hex})
                conn.commit()

            flash('Category added successfully.', 'success')
        return redirect(url_for('categories'))

    with engine.connect() as conn:
        query = text("SELECT id, name, color_hex FROM categories WHERE user_id = :user_id")
        user_categories = conn.execute(query, {"user_id": user_id}).fetchall()

    return render_template('categories.html', categories=user_categories)

@app.route('/categories/edit/<int:id>', methods=['POST'])
@login_required
def edit_category(id):
    user_id = session['user_id']
    name = request.form.get('name')
    color_hex = request.form.get('color_hex', '#cccccc')

    if name:
        with engine.connect() as conn:
            query = text("UPDATE categories SET name = :name, color_hex = :color_hex WHERE id = :id AND user_id = :user_id")
            conn.execute(query, {"name": name, "color_hex": color_hex, "id": id, "user_id": user_id})
            conn.commit()
        flash('Category updated successfully.', 'success')
    return redirect(url_for('categories'))

@app.route('/categories/delete/<int:id>', methods=['POST'])
@login_required
def delete_category(id):
    user_id = session['user_id']
    with engine.connect() as conn:
        query = text("DELETE FROM categories WHERE id = :id AND user_id = :user_id")
        try:
            conn.execute(query, {"id": id, "user_id": user_id})
            conn.commit()
            flash('Category deleted successfully.', 'success')
        except IntegrityError:
            conn.rollback()
            flash('Cannot delete this category because it is being used elsewhere.', 'danger')
    return redirect(url_for('categories'))


@app.route('/tags', methods=['GET', 'POST'])
@login_required
def tags():
    user_id = session['user_id']

    if request.method == 'POST':
        label = normalize_tag_label(request.form.get('label', ''))
        if label:
            with engine.connect() as conn:
                exists_query = text("""
                    SELECT 1
                    FROM tags
                    WHERE user_id = :user_id AND label = :label
                """)
                existing_tag = conn.execute(exists_query, {"user_id": user_id, "label": label}).fetchone()
                if existing_tag:
                    flash('Tag already exists for this user.', 'danger')
                    return redirect(url_for('tags'))

                query = text("INSERT INTO tags (user_id, label) VALUES (:user_id, :label)")
                try:
                    conn.execute(query, {"user_id": user_id, "label": label})
                    conn.commit()
                    flash('Tag added successfully.', 'success')
                except IntegrityError:
                    conn.rollback()
                    flash('Tag already exists for this user.', 'danger')
        return redirect(url_for('tags'))

    with engine.connect() as conn:
        query = text("SELECT id, label FROM tags WHERE user_id = :user_id ORDER BY label ASC")
        user_tags = conn.execute(query, {"user_id": user_id}).fetchall()

    return render_template('tags.html', tags=user_tags)


@app.route('/tags/edit/<int:id>', methods=['POST'])
@login_required
def edit_tag(id):
    user_id = session['user_id']
    label = normalize_tag_label(request.form.get('label', ''))

    if label:
        with engine.connect() as conn:
            exists_query = text("""
                SELECT 1
                FROM tags
                WHERE user_id = :user_id AND label = :label AND id <> :id
            """)
            existing_tag = conn.execute(exists_query, {
                "user_id": user_id,
                "label": label,
                "id": id
            }).fetchone()
            if existing_tag:
                flash('Tag already exists for this user.', 'danger')
                return redirect(url_for('tags'))

            query = text("UPDATE tags SET label = :label WHERE id = :id AND user_id = :user_id")
            try:
                conn.execute(query, {"label": label, "id": id, "user_id": user_id})
                conn.commit()
                flash('Tag updated successfully.', 'success')
            except IntegrityError:
                conn.rollback()
                flash('Tag already exists for this user.', 'danger')
    return redirect(url_for('tags'))


@app.route('/tags/delete/<int:id>', methods=['POST'])
@login_required
def delete_tag(id):
    user_id = session['user_id']
    with engine.connect() as conn:
        try:
            delete_links_query = text("""
                DELETE FROM task_tags
                WHERE tag_id IN (
                    SELECT id
                    FROM tags
                    WHERE id = :id AND user_id = :user_id
                )
            """)
            conn.execute(delete_links_query, {"id": id, "user_id": user_id})

            delete_tag_query = text("DELETE FROM tags WHERE id = :id AND user_id = :user_id")
            conn.execute(delete_tag_query, {"id": id, "user_id": user_id})
            conn.commit()
            flash('Tag deleted successfully.', 'success')
        except IntegrityError:
            conn.rollback()
            flash('Cannot delete this tag right now.', 'danger')
    return redirect(url_for('tags'))

@app.route('/courses', methods=['GET', 'POST'])
@login_required
def courses():
    user_id = session['user_id']

    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        semester = request.form.get('semester')

        if name and code:
            with engine.connect() as conn:
                query = text("INSERT INTO courses (user_id, name, code, semester) VALUES (:user_id, :name, :code, :semester)")
                conn.execute(query, {"user_id": user_id, "name": name, "code": code, "semester": semester if semester else None})
                conn.commit()

            flash('Course added successfully.', 'success')
        return redirect(url_for('courses'))

    with engine.connect() as conn:
        query = text("SELECT id, name, code, semester FROM courses WHERE user_id = :user_id")
        user_courses = conn.execute(query, {"user_id": user_id}).fetchall()

    return render_template('courses.html', courses=user_courses)

@app.route('/courses/edit/<int:id>', methods=['POST'])
@login_required
def edit_course(id):
    user_id = session['user_id']
    name = request.form.get('name')
    code = request.form.get('code')
    semester = request.form.get('semester')

    if name and code:
        with engine.connect() as conn:
            query = text("UPDATE courses SET name = :name, code = :code, semester = :semester WHERE id = :id AND user_id = :user_id")
            conn.execute(query, {"name": name, "code": code, "semester": semester if semester else None, "id": id, "user_id": user_id})
            conn.commit()
        flash('Course updated successfully.', 'success')
    return redirect(url_for('courses'))

@app.route('/courses/delete/<int:id>', methods=['POST'])
@login_required
def delete_course(id):
    user_id = session['user_id']
    with engine.connect() as conn:
        query = text("DELETE FROM courses WHERE id = :id AND user_id = :user_id")
        try:
            conn.execute(query, {"id": id, "user_id": user_id})
            conn.commit()
            flash('Course deleted successfully.', 'success')
        except IntegrityError:
            conn.rollback()
            flash('Cannot delete this course because it is being used elsewhere.', 'danger')
    return redirect(url_for('courses'))

@app.route('/projects', methods=['GET', 'POST'])
@login_required
def projects():
    user_id = session['user_id']

    if request.method == 'POST':
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        course_id = request.form.get('course_id')

        if name and category_id:
            with engine.connect() as conn:
                course_val = course_id if (course_id and course_id.strip() != "") else None
                query = text("""
                    INSERT INTO projects (user_id, name, category_id, course_id, status)
                    VALUES (:user_id, :name, :category_id, :course_id, :status)
                """)
                conn.execute(query, {
                    "user_id": user_id,
                    "name": name,
                    "category_id": category_id,
                    "course_id": course_val,
                    "status": 'pending'
                })
                conn.commit()

            flash('Project added successfully.', 'success')
        return redirect(url_for('projects'))

    with engine.connect() as conn:
        query = text("""
            SELECT p.id, p.name, p.status, p.category_id, p.course_id,
                   c.name as category_name, c.color_hex, crs.code as course_code
            FROM projects p
            JOIN categories c ON p.category_id = c.id
            LEFT JOIN courses crs ON p.course_id = crs.id
            WHERE p.user_id = :user_id
        """)
        user_projects = conn.execute(query, {"user_id": user_id}).fetchall()

        cat_query = text("SELECT id, name FROM categories WHERE user_id = :user_id")
        user_categories = conn.execute(cat_query, {"user_id": user_id}).fetchall()

        course_query = text("SELECT id, code, name FROM courses WHERE user_id = :user_id")
        user_courses = conn.execute(course_query, {"user_id": user_id}).fetchall()

    return render_template('projects.html', projects=user_projects, categories=user_categories, courses=user_courses)

@app.route('/projects/edit/<int:id>', methods=['POST'])
@login_required
def edit_project(id):
    user_id = session['user_id']
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    course_id = request.form.get('course_id')

    if name and category_id:
        with engine.connect() as conn:
            course_val = course_id if (course_id and course_id.strip() != "") else None
            query = text("""
                UPDATE projects
                SET name = :name, category_id = :category_id, course_id = :course_id
                WHERE id = :id AND user_id = :user_id
            """)
            conn.execute(query, {
                "name": name, "category_id": category_id, "course_id": course_val, "id": id, "user_id": user_id
            })
            sync_tasks_category_to_project_query = text("""
                UPDATE tasks
                SET category_id = :category_id
                WHERE user_id = :user_id AND project_id = :project_id
            """)
            conn.execute(sync_tasks_category_to_project_query, {
                "category_id": category_id,
                "user_id": user_id,
                "project_id": id
            })
            conn.commit()
        flash('Project updated successfully.', 'success')
    return redirect(url_for('projects'))

@app.route('/projects/delete/<int:id>', methods=['POST'])
@login_required
def delete_project(id):
    user_id = session['user_id']
    with engine.connect() as conn:
        query = text("DELETE FROM projects WHERE id = :id AND user_id = :user_id")
        try:
            conn.execute(query, {"id": id, "user_id": user_id})
            conn.commit()
            flash('Project deleted successfully.', 'success')
        except IntegrityError:
            conn.rollback()
            flash('Cannot delete this project because it is being used elsewhere.', 'danger')
    return redirect(url_for('projects'))

@app.route('/tasks', methods=['GET', 'POST'])
@login_required
def tasks():
    user_id = session['user_id']

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_date = request.form.get('due_date', '').strip()
        priority = request.form.get('priority', '').strip()
        energy_required = request.form.get('energy_required', '').strip()
        status = 'pending'
        category_id = request.form.get('category_id', '').strip()
        course_id = request.form.get('course_id', '').strip()
        project_id = request.form.get('project_id', '').strip()
        raw_tag_ids = request.form.getlist('tag_ids')
        is_recurring = 1 if request.form.get('is_recurring') else 0
        interval_value = request.form.get('interval', '').strip().lower()

        if not title or not due_date or not priority or not energy_required:
            flash('Title, due date, priority, and energy are required.', 'danger')
            return redirect(url_for('tasks'))

        allowed_priorities = {'High', 'Medium', 'Low'}
        allowed_energy = {'High', 'Medium', 'Low'}
        allowed_intervals = {'daily', 'weekly', 'monthly'}
        if priority not in allowed_priorities or energy_required not in allowed_energy:
            flash('Invalid priority or energy value.', 'danger')
            return redirect(url_for('tasks'))
        if is_recurring and interval_value not in allowed_intervals:
            flash('Please select a valid recurring interval.', 'danger')
            return redirect(url_for('tasks'))
        if not is_recurring:
            interval_value = None

        category_id = int(category_id) if category_id.isdigit() else None
        course_id = int(course_id) if course_id.isdigit() else None
        project_id = int(project_id) if project_id.isdigit() else None
        tag_ids = sorted({int(tag_id) for tag_id in raw_tag_ids if str(tag_id).isdigit()})

        with engine.connect() as conn:
            if project_id:
                project_query = text("""
                    SELECT category_id
                    FROM projects
                    WHERE id = :project_id AND user_id = :user_id
                """)
                project_row = conn.execute(project_query, {
                    "project_id": project_id,
                    "user_id": user_id
                }).fetchone()
                if not project_row:
                    flash('Invalid project selected.', 'danger')
                    return redirect(url_for('tasks'))
                category_id = project_row.category_id

            try:
                inserted_task_id = insert_task_and_get_id(conn, {
                    "user_id": user_id,
                    "title": title,
                    "description": description,
                    "due_date": due_date,
                    "priority": priority,
                    "energy_required": energy_required,
                    "status": status,
                    "category_id": category_id,
                    "course_id": course_id,
                    "project_id": project_id,
                    "is_recurring": is_recurring,
                    "interval": interval_value
                })

                if inserted_task_id:
                    insert_tag_query = text("""
                        INSERT INTO task_tags (task_id, tag_id)
                        SELECT :task_id, :tag_id
                        WHERE EXISTS (SELECT 1 FROM tags WHERE id = :tag_id AND user_id = :user_id)
                    """)
                    for tag_id in tag_ids:
                        conn.execute(insert_tag_query, {
                            "task_id": inserted_task_id,
                            "tag_id": tag_id,
                            "user_id": user_id
                        })

                sync_project_status(conn, user_id, project_id)
                conn.commit()
                flash('Task added successfully.', 'success')
            except IntegrityError:
                conn.rollback()
                flash('Unable to add task because related data is invalid or missing.', 'danger')
            except Exception as e:
                conn.rollback()
                flash(f'System Error: {str(e)}', 'danger')
        return redirect(url_for('tasks'))

    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip().lower()
    priority_filter = request.args.get('priority', '').strip()
    category_filter_raw = request.args.get('category_id', '').strip()
    project_filter_raw = request.args.get('project_id', '').strip()
    tag_filter_raw = request.args.get('tag_id', '').strip()
    sort_by = request.args.get('sort_by', 'due_date').strip().lower()
    sort_dir = request.args.get('sort_dir', 'asc').strip().lower()

    category_filter = int(category_filter_raw) if category_filter_raw.isdigit() else None
    project_filter = int(project_filter_raw) if project_filter_raw.isdigit() else None
    tag_filter = int(tag_filter_raw) if tag_filter_raw.isdigit() else None

    allowed_status = {'pending', 'in_progress', 'completed'}
    allowed_priorities = {'High', 'Medium', 'Low'}
    if status_filter not in allowed_status:
        status_filter = ''
    if priority_filter not in allowed_priorities:
        priority_filter = ''

    sort_fields = {
        'due_date': 't.due_date',
        'title': 't.title',
        'priority': "CASE t.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END",
        'status': "CASE t.status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END",
        'category': 'c.name'
    }
    sort_expression = sort_fields.get(sort_by, 't.due_date')
    safe_sort_dir = 'DESC' if sort_dir == 'desc' else 'ASC'
    if sort_by not in sort_fields:
        sort_by = 'due_date'
    sort_dir = safe_sort_dir.lower()

    where_clauses = ["t.user_id = :user_id"]
    query_params = {"user_id": user_id}

    if search_query:
        where_clauses.append("(t.title LIKE :search_query OR t.description LIKE :search_query)")
        query_params["search_query"] = f"%{search_query}%"

    if status_filter:
        where_clauses.append("t.status = :status_filter")
        query_params["status_filter"] = status_filter

    if priority_filter:
        where_clauses.append("t.priority = :priority_filter")
        query_params["priority_filter"] = priority_filter

    if category_filter:
        where_clauses.append("t.category_id = :category_filter")
        query_params["category_filter"] = category_filter

    if project_filter:
        where_clauses.append("t.project_id = :project_filter")
        query_params["project_filter"] = project_filter

    if tag_filter:
        where_clauses.append("""
            EXISTS (
                SELECT 1
                FROM task_tags tt_filter
                JOIN tags tg_filter ON tg_filter.id = tt_filter.tag_id
                WHERE tt_filter.task_id = t.id
                  AND tg_filter.user_id = :user_id
                  AND tg_filter.id = :tag_filter
            )
        """)
        query_params["tag_filter"] = tag_filter

    tasks_query = text(f"""
        SELECT t.id, t.title, t.description, t.due_date, t.priority,
               t.energy_required, t.status, t.is_recurring, t.[interval],
               t.category_id, t.course_id, t.project_id,
               c.name as category_name, c.color_hex as category_color,
               crs.code as course_code,
               p.name as project_name
        FROM tasks t
        LEFT JOIN categories c ON t.category_id = c.id
        LEFT JOIN courses crs ON t.course_id = crs.id
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {sort_expression} {safe_sort_dir}, t.id DESC
    """)

    with engine.connect() as conn:
        user_tasks = conn.execute(tasks_query, query_params).fetchall()
        categories = conn.execute(
            text("SELECT id, name FROM categories WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchall()
        courses = conn.execute(
            text("SELECT id, code, name FROM courses WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchall()
        projects = conn.execute(
            text("SELECT id, name, category_id FROM projects WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchall()
        all_tags = conn.execute(
            text("SELECT id, label FROM tags WHERE user_id = :user_id ORDER BY label ASC"),
            {"user_id": user_id}
        ).fetchall()

        task_tag_rows = conn.execute(text("""
            SELECT tt.task_id, tg.id AS tag_id, tg.label
            FROM task_tags tt
            JOIN tags tg ON tg.id = tt.tag_id
            JOIN tasks t ON t.id = tt.task_id
            WHERE t.user_id = :user_id
            ORDER BY tg.label ASC
        """), {"user_id": user_id}).fetchall()

    task_tags_map = {}
    task_tag_ids_map = {}
    for row in task_tag_rows:
        if row.task_id not in task_tags_map:
            task_tags_map[row.task_id] = []
        if row.task_id not in task_tag_ids_map:
            task_tag_ids_map[row.task_id] = []

        task_tags_map[row.task_id].append({"id": row.tag_id, "label": row.label})
        task_tag_ids_map[row.task_id].append(row.tag_id)

    return render_template(
        'tasks.html',
        tasks=user_tasks,
        categories=categories,
        courses=courses,
        projects=projects,
        all_tags=all_tags,
        task_tags_map=task_tags_map,
        task_tag_ids_map=task_tag_ids_map,
        filters={
            "q": search_query,
            "status": status_filter,
            "priority": priority_filter,
            "category_id": str(category_filter) if category_filter else '',
            "project_id": str(project_filter) if project_filter else '',
            "tag_id": str(tag_filter) if tag_filter else '',
            "sort_by": sort_by,
            "sort_dir": sort_dir
        }
    )


@app.route('/routines', methods=['POST'])
@login_required
def create_routine():
    user_id = session['user_id']

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    interval_value = request.form.get('interval', '').strip().lower()
    priority = request.form.get('priority', '').strip()
    category_id = request.form.get('category_id', '').strip()

    due_date = request.form.get('due_date', '').strip()
    energy_required = request.form.get('energy_required', 'Medium').strip() or 'Medium'
    status = request.form.get('status', 'pending').strip().lower() or 'pending'
    course_id = request.form.get('course_id', '').strip()
    project_id = request.form.get('project_id', '').strip()
    raw_tag_ids = request.form.getlist('tag_ids')

    if not title or not priority or not category_id or not interval_value:
        flash('Routine name, interval, priority, and category are required.', 'danger')
        return redirect(url_for('tasks'))

    allowed_priorities = {'High', 'Medium', 'Low'}
    allowed_energy = {'High', 'Medium', 'Low'}
    allowed_status = {'pending', 'in_progress', 'completed'}
    allowed_intervals = {'daily', 'weekly', 'monthly'}

    if priority not in allowed_priorities:
        flash('Invalid routine priority.', 'danger')
        return redirect(url_for('tasks'))
    if energy_required not in allowed_energy:
        flash('Invalid routine energy value.', 'danger')
        return redirect(url_for('tasks'))
    if status not in allowed_status:
        status = 'pending'
    if interval_value not in allowed_intervals:
        flash('Invalid routine interval.', 'danger')
        return redirect(url_for('tasks'))

    category_id = int(category_id) if category_id.isdigit() else None
    course_id = int(course_id) if course_id.isdigit() else None
    project_id = int(project_id) if project_id.isdigit() else None
    tag_ids = sorted({int(tag_id) for tag_id in raw_tag_ids if str(tag_id).isdigit()})

    if not due_date:
        due_date = date.today().strftime('%Y-%m-%d')

    with engine.connect() as conn:
        if project_id:
            project_query = text("""
                SELECT category_id
                FROM projects
                WHERE id = :project_id AND user_id = :user_id
            """)
            project_row = conn.execute(project_query, {
                "project_id": project_id,
                "user_id": user_id
            }).fetchone()
            if not project_row:
                flash('Invalid project selected for routine.', 'danger')
                return redirect(url_for('tasks'))
            category_id = project_row.category_id

        try:
            inserted_task_id = insert_task_and_get_id(conn, {
                "user_id": user_id,
                "title": title,
                "description": description,
                "due_date": due_date,
                "priority": priority,
                "energy_required": energy_required,
                "status": status,
                "category_id": category_id,
                "course_id": course_id,
                "project_id": project_id,
                "is_recurring": 1,
                "interval": interval_value
            })

            if inserted_task_id:
                insert_tag_query = text("""
                    INSERT INTO task_tags (task_id, tag_id)
                    SELECT :task_id, :tag_id
                    WHERE EXISTS (SELECT 1 FROM tags WHERE id = :tag_id AND user_id = :user_id)
                """)
                for tag_id in tag_ids:
                    conn.execute(insert_tag_query, {
                        "task_id": inserted_task_id,
                        "tag_id": tag_id,
                        "user_id": user_id
                    })

            sync_project_status(conn, user_id, project_id)
            if inserted_task_id:
                maybe_clone_recurring_task(conn, user_id, inserted_task_id, 'pending', status)
            conn.commit()
            flash('Routine added successfully.', 'success')
        except IntegrityError:
            conn.rollback()
            flash('Unable to add routine because related data is invalid or missing.', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'System Error: {str(e)}', 'danger')

    return redirect(url_for('tasks'))


@app.route('/routines/edit/<int:id>', methods=['POST'])
@login_required
def edit_routine(id):
    user_id = session['user_id']

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    interval_value = request.form.get('interval', '').strip().lower()
    priority = request.form.get('priority', '').strip()
    category_id = request.form.get('category_id', '').strip()

    due_date = request.form.get('due_date', '').strip()
    energy_required = request.form.get('energy_required', 'Medium').strip() or 'Medium'
    status = request.form.get('status', 'pending').strip().lower() or 'pending'
    course_id = request.form.get('course_id', '').strip()
    project_id = request.form.get('project_id', '').strip()
    raw_tag_ids = request.form.getlist('tag_ids')

    if not title or not priority or not category_id or not interval_value:
        flash('Routine name, interval, priority, and category are required.', 'danger')
        return redirect(url_for('tasks'))

    allowed_priorities = {'High', 'Medium', 'Low'}
    allowed_energy = {'High', 'Medium', 'Low'}
    allowed_status = {'pending', 'in_progress', 'completed'}
    allowed_intervals = {'daily', 'weekly', 'monthly'}

    if priority not in allowed_priorities:
        flash('Invalid routine priority.', 'danger')
        return redirect(url_for('tasks'))
    if energy_required not in allowed_energy:
        flash('Invalid routine energy value.', 'danger')
        return redirect(url_for('tasks'))
    if status not in allowed_status:
        status = 'pending'
    if interval_value not in allowed_intervals:
        flash('Invalid routine interval.', 'danger')
        return redirect(url_for('tasks'))

    category_id = int(category_id) if category_id.isdigit() else None
    course_id = int(course_id) if course_id.isdigit() else None
    project_id = int(project_id) if project_id.isdigit() else None
    tag_ids = sorted({int(tag_id) for tag_id in raw_tag_ids if str(tag_id).isdigit()})

    if not due_date:
        due_date = date.today().strftime('%Y-%m-%d')

    with engine.connect() as conn:
        existing_query = text("""
            SELECT project_id, status, is_recurring
            FROM tasks
            WHERE id = :id AND user_id = :user_id
        """)
        existing_task = conn.execute(existing_query, {"id": id, "user_id": user_id}).fetchone()
        if not existing_task:
            flash('Routine not found.', 'danger')
            return redirect(url_for('tasks'))
        if not existing_task.is_recurring:
            flash('Selected item is not a routine.', 'danger')
            return redirect(url_for('tasks'))

        previous_project_id = existing_task.project_id
        previous_status = existing_task.status

        if project_id:
            project_query = text("""
                SELECT category_id
                FROM projects
                WHERE id = :project_id AND user_id = :user_id
            """)
            project_row = conn.execute(project_query, {
                "project_id": project_id,
                "user_id": user_id
            }).fetchone()
            if not project_row:
                flash('Invalid project selected for routine.', 'danger')
                return redirect(url_for('tasks'))
            category_id = project_row.category_id

        update_query = text("""
            UPDATE tasks
            SET title = :title,
                description = :description,
                due_date = :due_date,
                priority = :priority,
                energy_required = :energy_required,
                status = :status,
                category_id = :category_id,
                course_id = :course_id,
                project_id = :project_id,
                is_recurring = 1,
                [interval] = :interval
            WHERE id = :id AND user_id = :user_id
        """)
        conn.execute(update_query, {
            "title": title,
            "description": description,
            "due_date": due_date,
            "priority": priority,
            "energy_required": energy_required,
            "status": status,
            "category_id": category_id,
            "course_id": course_id,
            "project_id": project_id,
            "interval": interval_value,
            "id": id,
            "user_id": user_id
        })

        delete_tag_links_query = text("""
            DELETE FROM task_tags
            WHERE task_id = :task_id
              AND EXISTS (
                  SELECT 1
                  FROM tasks t
                  WHERE t.id = :task_id AND t.user_id = :user_id
              )
        """)
        conn.execute(delete_tag_links_query, {"task_id": id, "user_id": user_id})

        insert_tag_query = text("""
            INSERT INTO task_tags (task_id, tag_id)
            SELECT :task_id, :tag_id
            WHERE EXISTS (SELECT 1 FROM tasks WHERE id = :task_id AND user_id = :user_id)
              AND EXISTS (SELECT 1 FROM tags WHERE id = :tag_id AND user_id = :user_id)
        """)
        for tag_id in tag_ids:
            conn.execute(insert_tag_query, {"task_id": id, "tag_id": tag_id, "user_id": user_id})

        maybe_clone_recurring_task(conn, user_id, id, previous_status, status)
        sync_project_status(conn, user_id, previous_project_id)
        sync_project_status(conn, user_id, project_id)
        conn.commit()

    flash('Routine updated successfully.', 'success')
    return redirect(url_for('tasks'))

@app.route('/tasks/edit/<int:id>', methods=['POST'])
@login_required
def edit_task(id):
    user_id = session['user_id']
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    due_date = request.form.get('due_date', '').strip()
    priority = request.form.get('priority', '').strip()
    energy_required = request.form.get('energy_required', '').strip()
    status = request.form.get('status', '').strip()
    category_id = request.form.get('category_id', '').strip()
    course_id = request.form.get('course_id', '').strip()
    project_id = request.form.get('project_id', '').strip()
    raw_tag_ids = request.form.getlist('tag_ids')

    if not due_date:
        flash('Due date is required to update a task.', 'danger')
        return redirect(url_for('tasks'))

    category_id = int(category_id) if category_id.isdigit() else None
    course_id = int(course_id) if course_id.isdigit() else None
    project_id = int(project_id) if project_id.isdigit() else None
    tag_ids = sorted({int(tag_id) for tag_id in raw_tag_ids if str(tag_id).isdigit()})

    status_map = {
        'Pending': 'pending',
        'In Progress': 'in_progress',
        'Completed': 'completed',
        'pending': 'pending',
        'in_progress': 'in_progress',
        'completed': 'completed'
    }
    status = status_map.get(status) if status else None

    if not title or not priority or not energy_required or not due_date:
        flash('Title, due date, priority, and energy are required to update a task.', 'danger')
        return redirect(url_for('tasks'))

    with engine.connect() as conn:
        existing_project_query = text("SELECT project_id, status FROM tasks WHERE id = :id AND user_id = :user_id")
        existing_task = conn.execute(existing_project_query, {"id": id, "user_id": user_id}).fetchone()
        previous_project_id = existing_task.project_id if existing_task else None
        previous_status = existing_task.status if existing_task else None

        if project_id:
            project_query = text("""
                SELECT category_id
                FROM projects
                WHERE id = :project_id AND user_id = :user_id
            """)
            project_row = conn.execute(project_query, {
                "project_id": project_id,
                "user_id": user_id
            }).fetchone()
            if not project_row:
                flash('Invalid project selected.', 'danger')
                return redirect(url_for('tasks'))
            category_id = project_row.category_id

        if status:
            query = text("""
                UPDATE tasks
                SET title = :title, description = :description, due_date = :due_date,
                    priority = :priority, energy_required = :energy_required, status = :status,
                    category_id = :category_id, course_id = :course_id, project_id = :project_id
                WHERE id = :id AND user_id = :user_id
            """)
            conn.execute(query, {
                "title": title, "description": description, "due_date": due_date,
                "priority": priority, "energy_required": energy_required, "status": status,
                "category_id": category_id, "course_id": course_id, "project_id": project_id,
                "id": id, "user_id": user_id
            })
        else:
            query = text("""
                UPDATE tasks
                SET title = :title, description = :description, due_date = :due_date,
                    priority = :priority, energy_required = :energy_required,
                    category_id = :category_id, course_id = :course_id, project_id = :project_id
                WHERE id = :id AND user_id = :user_id
            """)
            conn.execute(query, {
                "title": title, "description": description, "due_date": due_date,
                "priority": priority, "energy_required": energy_required,
                "category_id": category_id, "course_id": course_id, "project_id": project_id,
                "id": id, "user_id": user_id
            })

        delete_tag_links_query = text("""
            DELETE FROM task_tags
            WHERE task_id = :task_id
              AND EXISTS (
                  SELECT 1
                  FROM tasks t
                  WHERE t.id = :task_id AND t.user_id = :user_id
              )
        """)
        conn.execute(delete_tag_links_query, {"task_id": id, "user_id": user_id})

        insert_tag_query = text("""
            INSERT INTO task_tags (task_id, tag_id)
            SELECT :task_id, :tag_id
            WHERE EXISTS (SELECT 1 FROM tasks WHERE id = :task_id AND user_id = :user_id)
              AND EXISTS (SELECT 1 FROM tags WHERE id = :tag_id AND user_id = :user_id)
        """)
        for tag_id in tag_ids:
            conn.execute(insert_tag_query, {"task_id": id, "tag_id": tag_id, "user_id": user_id})

        resulting_status = status if status else previous_status
        maybe_clone_recurring_task(conn, user_id, id, previous_status, resulting_status)

        sync_project_status(conn, user_id, previous_project_id)
        sync_project_status(conn, user_id, project_id)
        conn.commit()
    flash('Task updated successfully.', 'success')
    return redirect(url_for('tasks'))

@app.route('/tasks/delete/<int:id>', methods=['POST'])
@login_required
def delete_task(id):
    user_id = session['user_id']
    with engine.connect() as conn:
        existing_project_query = text("SELECT project_id FROM tasks WHERE id = :id AND user_id = :user_id")
        existing_task = conn.execute(existing_project_query, {"id": id, "user_id": user_id}).fetchone()
        project_id = existing_task.project_id if existing_task else None

        query = text("DELETE FROM tasks WHERE id = :id AND user_id = :user_id")
        try:
            delete_tag_links_query = text("DELETE FROM task_tags WHERE task_id = :id")
            conn.execute(delete_tag_links_query, {"id": id})
            conn.execute(query, {"id": id, "user_id": user_id})
            sync_project_status(conn, user_id, project_id)
            conn.commit()
            flash('Task deleted successfully.', 'success')
        except IntegrityError:
            conn.rollback()
            flash('Cannot delete this task because it is being used elsewhere.', 'danger')
    return redirect(url_for('tasks'))

@app.route('/tasks/status/<int:id>', methods=['POST'])
@login_required
def update_task_status(id):
    user_id = session['user_id']
    next_url = request.form.get('next', '').strip()
    incoming_status = request.form.get('status', '').strip()
    status_map = {
        'Pending': 'pending',
        'In Progress': 'in_progress',
        'Completed': 'completed',
        'pending': 'pending',
        'in_progress': 'in_progress',
        'completed': 'completed'
    }
    next_status = status_map.get(incoming_status)
    if next_status:
        with engine.connect() as conn:
            current_query = text("SELECT status, project_id FROM tasks WHERE id = :id AND user_id = :user_id")
            current_row = conn.execute(current_query, {"id": id, "user_id": user_id}).fetchone()
            if not current_row:
                return redirect(url_for('tasks'))

            query = text("UPDATE tasks SET status = :status WHERE id = :id AND user_id = :user_id")
            conn.execute(query, {"status": next_status, "id": id, "user_id": user_id})
            maybe_clone_recurring_task(conn, user_id, id, current_row.status, next_status)
            sync_project_status(conn, user_id, current_row.project_id)
            conn.commit()
    if next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('tasks'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)

