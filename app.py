import os
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from sqlalchemy import UniqueConstraint, func
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'medhub-super-secret-key-2026')

if os.environ.get('AWS_LAMBDA_FUNCTION_NAME') or os.environ.get('NETLIFY'):
    db_path = '/tmp/medhub.db'
else:
    db_path = os.path.join(BASE_DIR, 'medhub.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'message': 'Требуется авторизация.'}), 401
    return redirect(url_for('login', next=request.url))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='student')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    applications = db.relationship('Application', back_populates='user', cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', back_populates='user', cascade='all, delete-orphan')


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    audience = db.Column(db.String(100), nullable=False)
    schedule = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    accent_class = db.Column(db.String(50), default='card-purple')
    applications = db.relationship('Application', back_populates='course')


class Application(db.Model):
    __tablename__ = 'application'
    __table_args__ = (UniqueConstraint('user_id', 'course_id', name='uq_application_user_course'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    parent_or_student_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(30), default='В обработке')
    user = db.relationship('User', back_populates='applications')
    course = db.relationship('Course', back_populates='applications')


class Gallery(db.Model):
    __tablename__ = 'gallery'
    event_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    file = db.Column(db.String(255), nullable=False)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    sender = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', back_populates='chat_messages')


last_submissions = {}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def migrate_legacy_database():
    """Upgrade the original prototype SQLite schema without discarding valid data."""
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'application' in tables:
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(application)')}
            if 'course_id' not in cols:
                conn.execute('ALTER TABLE application RENAME TO application_legacy')
                conn.execute('''CREATE TABLE application (
                    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
                    parent_or_student_name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL,
                    phone VARCHAR(30) NOT NULL, created_at DATETIME, status VARCHAR(30),
                    FOREIGN KEY(user_id) REFERENCES user(id), FOREIGN KEY(course_id) REFERENCES course(id),
                    UNIQUE(user_id, course_id))''')
                conn.execute('''CREATE TABLE IF NOT EXISTS application_legacy_unlinked (
                    id INTEGER, parent_or_student_name VARCHAR(120), email VARCHAR(120),
                    phone VARCHAR(30), course_name VARCHAR(150), created_at DATETIME, status VARCHAR(30))''')
                legacy_rows = conn.execute('SELECT * FROM application_legacy').fetchall()
                for row in legacy_rows:
                    user = conn.execute('SELECT id FROM user WHERE lower(email)=lower(?)', (row['email'],)).fetchone()
                    course = conn.execute('SELECT id FROM course WHERE title=?', (row['course_name'],)).fetchone()
                    if user and course:
                        conn.execute('''INSERT OR IGNORE INTO application
                            (id,user_id,course_id,parent_or_student_name,email,phone,created_at,status)
                            VALUES (?,?,?,?,?,?,?,?)''',
                            (row['id'], user['id'], course['id'], row['parent_or_student_name'], row['email'],
                             row['phone'], row['created_at'], row['status']))
                    else:
                        conn.execute('''INSERT INTO application_legacy_unlinked
                            (id,parent_or_student_name,email,phone,course_name,created_at,status)
                            VALUES (?,?,?,?,?,?,?)''',
                            (row['id'], row['parent_or_student_name'], row['email'], row['phone'],
                             row['course_name'], row['created_at'], row['status']))
                conn.execute('DROP TABLE application_legacy')
        if 'chat_message' in tables:
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(chat_message)')}
            if 'user_id' not in cols:
                conn.execute('''CREATE TABLE IF NOT EXISTS chat_message_legacy (
                    id INTEGER, sender VARCHAR(100), text TEXT, timestamp DATETIME)''')
                conn.execute('''INSERT INTO chat_message_legacy (id,sender,text,timestamp)
                    SELECT id,sender,text,timestamp FROM chat_message''')
                conn.execute('ALTER TABLE chat_message ADD COLUMN user_id INTEGER REFERENCES user(id)')
                # Old global messages are archived: they cannot safely be assigned to a private user thread.
                conn.execute('DELETE FROM chat_message WHERE user_id IS NULL')
        conn.commit()
    finally:
        conn.close()


def init_db():
    migrate_legacy_database()
    db.create_all()
    if not User.query.filter_by(email='admin@medhub.ru').first():
        db.session.add_all([
            User(email='admin@medhub.ru', password_hash=generate_password_hash('admin123'),
                 full_name='Главный Администратор', role='admin'),
            User(email='doc@medhub.ru', password_hash=generate_password_hash('doc123'),
                 full_name='Д-р Смирнов А.В.', role='staff'),
            User(email='student@medhub.ru', password_hash=generate_password_hash('student123'),
                 full_name='Иванов Петр (Студент 3 курс)', role='visitor')
        ])
    if not Course.query.first():
        db.session.add_all([
            Course(title='Школа юного медика', category='Основы медицины', audience='Школьники 8-11 класс',
                   schedule='Сб 15:00 - 17:00', description='Знакомство со строением человека, основы первой помощи, латинские термины и экскурсии на клинические кафедры.', accent_class='card-purple'),
            Course(title='Клинические дисциплины', category='Терапия и диагностика', audience='Студенты 3-6 курс',
                   schedule='Вт, Чт 17:30', description='Разбор сложных клинических кейсов, аускультация, ЭКГ-практикум и курация тематических пациентов.', accent_class='card-dark'),
            Course(title='Хирургия и шовная техника', category='Практические навыки', audience='Студенты 2-6 курс',
                   schedule='Ср 18:00 - 20:00', description='Отработка базовых и специальных хирургических швов, десмургия, работа с эндохирургическими тренажерами.', accent_class='card-orange'),
            Course(title='Экстренная медицина и BLS', category='Первая помощь', audience='Все желающие / Студенты',
                   schedule='Пт 16:30', description='Сердечно-легочная реанимация по стандартам BLS/ITLS, интубация на манекенах, остановка критических кровотечений.', accent_class='card-lavender')
        ])
    if not Gallery.query.first():
        # Начальное наполнение перенесено из прежнего статического gallery.html.
        db.session.add_all([
            Gallery(name='Симуляционный центр: отработка базовой сердечно-легочной реанимации', file='images/yesman.jpg'),
            Gallery(name='Анатомический практикум и коллекция препаратов', file='images/yesman.jpg'),
            Gallery(name='Хирургическая секция: техника сосудистого шва', file='images/surgery.jpg'),
            Gallery(name='Межкафедральный клинический разбор и студенческий консилиум', file='images/council.jpg')
        ])
    db.session.commit()


@app.before_request
def ensure_db_initialized():
    if not getattr(app, '_db_initialized', False):
        init_db()
        app._db_initialized = True


def staff_or_admin_required():
    if not current_user.is_authenticated or current_user.role not in ('staff', 'admin'):
        abort(403)


def admin_required():
    if not current_user.is_authenticated or current_user.role != 'admin':
        abort(403)


@app.route('/')
def index():
    courses = Course.query.limit(4).all()
    return render_template('index.html', courses=courses)


@app.route('/directions')
def directions():
    query = request.args.get('search', '').strip()
    q = Course.query
    if query:
        q = q.filter(Course.title.ilike(f'%{query}%') | Course.category.ilike(f'%{query}%'))
    courses = q.all()
    return render_template('directions.html', courses=courses, search_query=query)


@app.route('/gamification')
def gamification():
    return render_template('gamification.html')


@app.route('/gallery')
def gallery():
    events = Gallery.query.order_by(Gallery.created_at.desc(), Gallery.event_id.asc()).all()
    return render_template('gallery.html', events=events)


@app.route('/docs')
def docs():
    return render_template('docs.html')


@app.route('/apply', methods=['GET', 'POST'])
@login_required
def apply():
    courses = Course.query.all()
    preselected_course = request.args.get('course', type=int)
    if request.method == 'POST':
        ip = request.remote_addr or '127.0.0.1'
        now = datetime.utcnow()
        if ip in last_submissions and now - last_submissions[ip] < timedelta(seconds=15):
            flash('Слишком много запросов. Подождите 15 секунд перед повторной отправкой.', 'error')
            return redirect(url_for('apply'))

        captcha_check = request.form.get('captcha_check', '').strip()
        consent = request.form.get('consent')
        phone = request.form.get('phone', '').strip()
        course_id = request.form.get('course_id', type=int)
        if captcha_check != '7':
            flash('Неверный ответ на вопрос проверки безопасности (капча).', 'error')
            return redirect(url_for('apply', course=course_id))
        if not (phone and course_id and consent):
            flash('Заполните обязательные поля и дайте согласие на обработку данных.', 'error')
            return redirect(url_for('apply', course=course_id))

        # Never trust the submitted email/name: identity comes only from the authenticated account.
        registered_user = User.query.filter(func.lower(User.email) == current_user.email.lower()).first()
        if not registered_user or registered_user.id != current_user.id:
            flash('Для подачи заявки необходимо войти в аккаунт с зарегистрированным email.', 'error')
            return redirect(url_for('login'))
        course = db.session.get(Course, course_id)
        if not course:
            flash('Выбранный курс не найден.', 'error')
            return redirect(url_for('apply'))
        duplicate = Application.query.filter_by(user_id=current_user.id, course_id=course.id).first()
        if duplicate:
            flash('Вы уже подавали заявку на этот курс. Повторная заявка не создана.', 'error')
            return redirect(url_for('dashboard_visitor'))

        new_app = Application(user_id=current_user.id, course_id=course.id,
                              parent_or_student_name=current_user.full_name,
                              email=current_user.email, phone=phone)
        db.session.add(new_app)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Не удалось создать заявку. Возможно, она уже существует.', 'error')
            return redirect(url_for('dashboard_visitor'))
        last_submissions[ip] = now
        flash('Заявка успешно отправлена! Её статус можно отслеживать в личном кабинете.', 'success')
        return redirect(url_for('dashboard_visitor'))
    return render_template('apply.html', courses=courses, preselected_course=preselected_course)


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('dashboard_admin'))
    if current_user.role == 'staff':
        return redirect(url_for('dashboard_staff'))
    return redirect(url_for('dashboard_visitor'))


@app.route('/dashboard/visitor')
@login_required
def dashboard_visitor():
    applications = Application.query.filter_by(user_id=current_user.id).order_by(Application.created_at.desc()).all()
    return render_template('dashboard_visitor.html', user=current_user, applications=applications)


@app.route('/dashboard/staff')
@login_required
def dashboard_staff():
    staff_or_admin_required()
    apps = Application.query.join(User).join(Course).order_by(Application.created_at.desc()).all()
    return render_template('dashboard_staff.html', user=current_user, applications=apps)


@app.route('/dashboard/staff/application/<int:application_id>')
@login_required
def staff_application_detail(application_id):
    staff_or_admin_required()
    application = Application.query.get_or_404(application_id)
    user_applications = Application.query.filter_by(user_id=application.user_id).order_by(Application.created_at.desc()).all()
    return render_template('application_detail.html', application=application, user_applications=user_applications)


@app.route('/dashboard/staff/application/<int:application_id>/decision', methods=['POST'])
@login_required
def staff_application_decision(application_id):
    staff_or_admin_required()
    application = Application.query.get_or_404(application_id)
    decision = request.form.get('decision')
    if decision == 'accept':
        application.status = 'In progress'
        flash('Заявка принята. Статус обновлён на In progress.', 'success')
    elif decision == 'reject':
        application.status = 'Expelled'
        flash('Заявка отклонена. Статус обновлён на Expelled.', 'success')
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for('staff_application_detail', application_id=application.id))


@app.route('/dashboard/admin', methods=['GET', 'POST'])
@login_required
def dashboard_admin():
    admin_required()
    if request.method == 'POST':
        action = request.form.get('action', 'promote_staff')
        if action == 'create_course':
            title = request.form.get('title', '').strip()
            category = request.form.get('category', '').strip()
            audience = request.form.get('audience', '').strip()
            schedule = request.form.get('schedule', '').strip()
            description = request.form.get('description', '').strip()
            accent_class = request.form.get('accent_class', 'card-purple').strip()
            if not all([title, category, audience, schedule, description]):
                flash('Заполните все поля нового курса.', 'error')
            else:
                db.session.add(Course(title=title, category=category, audience=audience,
                                      schedule=schedule, description=description,
                                      accent_class=accent_class or 'card-purple'))
                db.session.commit()
                flash(f'Курс «{title}» успешно создан.', 'success')
            return redirect(url_for('dashboard_admin'))

        user_id = request.form.get('user_id', type=int)
        user = db.session.get(User, user_id) if user_id else None
        if not user:
            flash('Пользователь не найден.', 'error')
        elif user.role == 'admin':
            flash('Нельзя изменить роль администратора.', 'error')
        elif user.role == 'staff':
            flash('Этот пользователь уже является работником кафедры.', 'error')
        else:
            user.role = 'staff'
            db.session.commit()
            flash(f'{user.full_name} назначен работником кафедры.', 'success')
        return redirect(url_for('dashboard_admin'))

    users = User.query.order_by(User.full_name).all()
    courses = Course.query.all()
    apps = Application.query.order_by(Application.created_at.desc()).all()
    staff_candidates = [u for u in users if u.role in ('visitor', 'student')]
    return render_template('dashboard_admin.html', user=current_user, users=users, courses=courses,
                           applications=apps, staff_candidates=staff_candidates)


@app.route('/dashboard/admin/chats')
@login_required
def dashboard_admin_chats():
    admin_required()
    chat_users = User.query.join(ChatMessage).distinct().order_by(User.full_name).all()
    chat_threads = []
    for chat_user in chat_users:
        messages = ChatMessage.query.filter_by(user_id=chat_user.id).order_by(ChatMessage.timestamp.asc()).all()
        chat_threads.append({'user': chat_user, 'messages': messages})
    return render_template('dashboard_admin_chats.html', user=current_user, chat_threads=chat_threads)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            next_url = request.args.get('next', '')
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        flash('Неверный email или пароль.', 'error')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        if not email or not password or not full_name:
            flash('Заполните e-mail, пароль и ФИО.', 'error')
        elif len(password) < 8:
            flash('Пароль должен содержать не менее 8 символов.', 'error')
        elif User.query.filter(func.lower(User.email) == email).first():
            flash('Пользователь с таким e-mail уже зарегистрирован.', 'error')
        else:
            user = User(email=email, password_hash=generate_password_hash(password),
                        full_name=full_name, role='student')
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Регистрация прошла успешно. Добро пожаловать в МедХаб!', 'success')
            return redirect(url_for('dashboard_visitor'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/api/chat', methods=['GET', 'POST'])
@login_required
def api_chat():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        message_text = (data.get('text') or '').strip()
        if not message_text:
            return jsonify({'status': 'error', 'message': 'Пустой текст'}), 400
        if current_user.role == 'admin':
            target_id = data.get('user_id')
            target = db.session.get(User, target_id) if target_id else None
            if not target:
                return jsonify({'status': 'error', 'message': 'Не выбран пользователь'}), 400
            conversation_user_id = target.id
            sender = 'Администратор'
        else:
            conversation_user_id = current_user.id
            sender = current_user.full_name
        msg = ChatMessage(user_id=conversation_user_id, sender=sender, text=message_text)
        db.session.add(msg)
        db.session.commit()
        return jsonify({'status': 'ok', 'time': msg.timestamp.strftime('%H:%M')})

    if current_user.role == 'admin':
        target_id = request.args.get('user_id', type=int)
        if not target_id:
            return jsonify({'status': 'error', 'message': 'Укажите пользователя'}), 400
        messages = ChatMessage.query.filter_by(user_id=target_id).order_by(ChatMessage.timestamp.asc()).all()
    else:
        messages = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.timestamp.asc()).all()
    return jsonify([{'sender': m.sender, 'text': m.text, 'time': m.timestamp.strftime('%H:%M')}
                    for m in messages])


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, port=5000)
