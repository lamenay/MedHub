import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Определение путей к шаблонам и статике
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'medhub-super-secret-key-2026')

# Если приложение работает в Netlify Lambda, пишем БД в папку /tmp
if os.environ.get('AWS_LAMBDA_FUNCTION_NAME') or os.environ.get('NETLIFY'):
    db_path = '/tmp/medhub.db'
else:
    db_path = os.path.join(BASE_DIR, 'medhub.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Модели БД ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='visitor')  # visitor, staff, admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    audience = db.Column(db.String(100), nullable=False)
    schedule = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    accent_class = db.Column(db.String(50), default='card-purple')

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    parent_or_student_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    course_name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(30), default='В обработке')

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

last_submissions = {}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def init_db():
    db.create_all()
    if not User.query.filter_by(email='admin@medhub.ru').first():
        admin = User(
            email='admin@medhub.ru',
            password_hash=generate_password_hash('admin123'),
            full_name='Главный Администратор',
            role='admin'
        )
        staff = User(
            email='doc@medhub.ru',
            password_hash=generate_password_hash('doc123'),
            full_name='Д-р Смирнов А.В.',
            role='staff'
        )
        visitor = User(
            email='student@medhub.ru',
            password_hash=generate_password_hash('student123'),
            full_name='Иванов Петр (Студент 3 курс)',
            role='visitor'
        )
        db.session.add_all([admin, staff, visitor])

    if not Course.query.first():
        courses = [
            Course(
                title='Школа юного медика',
                category='Основы медицины',
                audience='Школьники 8-11 класс',
                schedule='Сб 15:00 - 17:00',
                description='Знакомство со строением человека, основы первой помощи, латинские термины и экскурсии на клинические кафедры.',
                accent_class='card-purple'
            ),
            Course(
                title='Клинические дисциплины',
                category='Терапия и диагностика',
                audience='Студенты 3-6 курс',
                schedule='Вт, Чт 17:30',
                description='Разбор сложных клинических кейсов, аускультация, ЭКГ-практикум и курация тематических пациентов.',
                accent_class='card-dark'
            ),
            Course(
                title='Хирургия и шовная техника',
                category='Практические навыки',
                audience='Студенты 2-6 курс',
                schedule='Ср 18:00 - 20:00',
                description='Отработка базовых и специальных хирургических швов, десмургия, работа с эндохирургическими тренажерами.',
                accent_class='card-orange'
            ),
            Course(
                title='Экстренная медицина и BLS',
                category='Первая помощь',
                audience='Все желающие / Студенты',
                schedule='Пт 16:30',
                description='Сердечно-легочная реанимация по стандартам BLS/ITLS, интубация на манекенах, остановка критических кровотечений.',
                accent_class='card-lavender'
            )
        ]
        db.session.add_all(courses)
    db.session.commit()

# Автоматическая инициализация таблиц перед первым запросом
@app.before_request
def ensure_db_initialized():
    if not hasattr(app, '_db_initialized'):
        init_db()
        app._db_initialized = True

# --- Маршруты страниц ---

@app.route('/')
def index():
    courses = Course.query.limit(4).all()
    return render_template('index.html', courses=courses)

@app.route('/directions')
def directions():
    query = request.args.get('search', '').strip()
    if query:
        courses = Course.query.filter(
            Course.title.ilike(f'%{query}%') | Course.category.ilike(f'%{query}%')
        ).all()
    else:
        courses = Course.query.all()
    return render_template('directions.html', courses=courses, search_query=query)

@app.route('/gamification')
def gamification():
    return render_template('gamification.html')

@app.route('/gallery')
def gallery():
    return render_template('gallery.html')

@app.route('/docs')
def docs():
    return render_template('docs.html')

@app.route('/apply', methods=['GET', 'POST'])
def apply():
    courses = Course.query.all()
    preselected_course = request.args.get('course', '')

    if request.method == 'POST':
        ip = request.remote_addr or '127.0.0.1'
        now = datetime.utcnow()
        if ip in last_submissions and now - last_submissions[ip] < timedelta(seconds=15):
            flash('Слишком много запросов. Подождите 15 секунд перед повторной отправкой.', 'error')
            return redirect(url_for('apply'))

        name = request.form.get('parent_or_student_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        course_name = request.form.get('course_name', '').strip()
        captcha_check = request.form.get('captcha_check', '').strip()
        consent = request.form.get('consent')

        if captcha_check != '7':
            flash('Неверный ответ на вопрос проверки безопасности (капча).', 'error')
            return redirect(url_for('apply', course=course_name))

        if not (name and email and phone and course_name and consent):
            flash('Заполните все обязательные поля и дайте согласие на обработку данных.', 'error')
            return redirect(url_for('apply', course=course_name))

        new_app = Application(
            parent_or_student_name=name,
            email=email,
            phone=phone,
            course_name=course_name
        )
        db.session.add(new_app)
        db.session.commit()
        last_submissions[ip] = now
        flash('Заявка успешно отправлена! Куратор свяжется с вами в течение 24 часов.', 'success')
        return redirect(url_for('apply'))

    return render_template('apply.html', courses=courses, preselected_course=preselected_course)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('dashboard_admin'))
    elif current_user.role == 'staff':
        return redirect(url_for('dashboard_staff'))
    return redirect(url_for('dashboard_visitor'))

@app.route('/dashboard/visitor')
@login_required
def dashboard_visitor():
    return render_template('dashboard_visitor.html', user=current_user)

@app.route('/dashboard/staff')
@login_required
def dashboard_staff():
    if current_user.role not in ['staff', 'admin']:
        flash('Доступ только для сотрудников и преподавателей.', 'error')
        return redirect(url_for('index'))
    apps = Application.query.order_by(Application.created_at.desc()).all()
    return render_template('dashboard_staff.html', user=current_user, applications=apps)

@app.route('/dashboard/admin')
@login_required
def dashboard_admin():
    if current_user.role != 'admin':
        flash('Требуются права администратора.', 'error')
        return redirect(url_for('index'))
    users = User.query.all()
    courses = Course.query.all()
    apps = Application.query.all()
    return render_template('dashboard_admin.html', user=current_user, users=users, courses=courses, applications=apps)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Неверный email или пароль.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/api/chat', methods=['GET', 'POST'])
def api_chat():
    if request.method == 'POST':
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        sender = data.get('sender', 'Гость')
        if not text:
            return jsonify({'status': 'error', 'message': 'Пустой текст'}), 400
        msg = ChatMessage(sender=sender, text=text)
        db.session.add(msg)
        db.session.commit()
        return jsonify({'status': 'ok'})
    messages = ChatMessage.query.order_by(ChatMessage.timestamp.asc()).limit(50).all()
    return jsonify([{
        'sender': m.sender,
        'text': m.text,
        'time': m.timestamp.strftime('%H:%M')
    } for m in messages])

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, port=5000)