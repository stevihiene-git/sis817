from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import db
from .models import User, Student, Course, CourseRegistration, Score, Payment, is_financially_cleared
from datetime import datetime
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

views_bp = Blueprint('views', __name__, template_folder='templates')


def get_redirect_url():
    if not current_user.is_authenticated:
        return url_for('views.index')
    role_routes = {
        'Admin': 'views.admin_dashboard',
        'Student': 'views.student_dashboard',
        'Lecturer': 'views.lecturer_dashboard',
        'Finance': 'views.finance_dashboard'
    }
    return url_for(role_routes.get(current_user.role, 'views.index'))

def validate_admin_access():
    if current_user.role != 'Admin':
        flash('Access restricted to administrators', 'error')
        return False
    return True

def validate_student_access():
    if current_user.role != 'Student':
        flash('Access restricted to students', 'error')
        return False
    return True

def validate_lecturer_access():
    if current_user.role != 'Lecturer':
        flash('Access restricted to lecturers', 'error')
        return False
    return True


@views_bp.route('/')
def index():
    roles = [
        {'name': 'Admin', 'description': 'Manage users and courses', 'url': '/auth/login'},
        {'name': 'Student', 'description': 'Register courses and view results', 'url': '/auth/login'},
        {'name': 'Lecturer', 'description': 'Upload scores for courses', 'url': '/auth/login'},
        {'name': 'Finance', 'description': 'Manage student payments', 'url': '/auth/login'}
    ]
    return render_template('index.html', roles=roles)


@views_bp.route('/dashboard')
@login_required
def dashboard():
    # Redirect to role-specific dashboard
    role_routes = {
        'Student': 'views.student_dashboard',
        'Admin': 'views.admin_dashboard',
        'Lecturer': 'views.lecturer_dashboard',
        'Finance': 'views.finance_dashboard'
    }
    
    route = role_routes.get(current_user.role)
    if route:
        return redirect(url_for(route))
    
    return render_template('index.html')


# --- Admin Routes ---
@views_bp.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not validate_admin_access():
        return redirect(get_redirect_url())

    users = User.query.order_by(User.role, User.name).all()
    courses = Course.query.order_by(Course.code).all()

    total_users = len(users)
    student_count = len([u for u in users if u.role == 'Student'])
    lecturer_count = len([u for u in users if u.role == 'Lecturer'])
    total_courses = len(courses)

    return render_template('admin_dashboard.html', 
                         users=users, 
                         courses=courses,
                         total_users=total_users,
                         student_count=student_count,
                         lecturer_count=lecturer_count,
                         total_courses=total_courses)


@views_bp.route('/admin/add_user', methods=['GET', 'POST'])
@login_required
def admin_add_user():
    if not validate_admin_access():
        return redirect(get_redirect_url())

    if request.method == 'POST':
        unique_id = request.form.get('unique_id', '').strip()
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        faculty = request.form.get('faculty', '').strip()
        department = request.form.get('department', '').strip()

        errors = []
        if not all([unique_id, name, role, faculty, department]):
            errors.append('All fields are required')
        if len(unique_id) < 3:
            errors.append('Unique ID must be at least 3 characters long')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('admin_add_user.html',
                                 unique_id=unique_id,
                                 name=name,
                                 role=role,
                                 faculty=faculty,
                                 department=department)

        if User.query.filter_by(unique_id=unique_id).first():
            flash('Unique ID already exists', 'error')
            return render_template('admin_add_user.html',
                                 unique_id=unique_id,
                                 name=name,
                                 role=role,
                                 faculty=faculty,
                                 department=department)

        try:
            user = User(
                unique_id=unique_id,
                name=name,
                role=role,
                faculty=faculty,
                department=department,
                is_active=False,
                must_change_password=True
            )
            db.session.add(user)
            db.session.commit()

            if role == 'Student':
                student = Student(user_id=user.id, balance=0.0)
                db.session.add(student)
                db.session.commit()

            flash(f'User {name} ({unique_id}) added successfully', 'success')
            return redirect(url_for('views.admin_dashboard'))

        except Exception as e:
            db.session.rollback()
            flash('Error adding user. Please try again.', 'error')
            return render_template('admin_add_user.html',
                                 unique_id=unique_id,
                                 name=name,
                                 role=role,
                                 faculty=faculty,
                                 department=department)

    return render_template('admin_add_user.html')


@views_bp.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if not validate_admin_access():
        return redirect(get_redirect_url())

    user = db.session.get(User, user_id)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('views.admin_dashboard'))

    if request.method == 'POST':
        unique_id = request.form.get('unique_id', '').strip()
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        faculty = request.form.get('faculty', '').strip()
        department = request.form.get('department', '').strip()
        is_active = request.form.get('is_active') == 'on'

        errors = []
        if not all([unique_id, name, role, faculty, department]):
            errors.append('All fields are required')
        if len(unique_id) < 3:
            errors.append('Unique ID must be at least 3 characters long')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('admin_edit_user.html', user=user)

        if unique_id != user.unique_id and User.query.filter_by(unique_id=unique_id).first():
            flash('Unique ID already exists', 'error')
            return render_template('admin_edit_user.html', user=user)

        try:
            user.unique_id = unique_id
            user.name = name
            user.role = role
            user.faculty = faculty
            user.department = department
            user.is_active = is_active

            if role == 'Student':
                student = Student.query.filter_by(user_id=user.id).first()
                if not student:
                    student = Student(user_id=user.id, balance=0.0)
                    db.session.add(student)
            else:
                student = Student.query.filter_by(user_id=user.id).first()
                if student:
                    db.session.delete(student)

            db.session.commit()
            flash('User updated successfully', 'success')
            return redirect(url_for('views.admin_dashboard'))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating user: {str(e)}")
            flash('Error updating user. Please try again.', 'error')
            return render_template('admin_edit_user.html', user=user)

    return render_template('admin_edit_user.html', user=user)


@views_bp.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not validate_admin_access():
        return redirect(get_redirect_url())

    user = db.session.get(User, user_id)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('views.admin_dashboard'))

    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('views.admin_dashboard'))

    try:
        if user.role == 'Student':
            student = Student.query.filter_by(user_id=user.id).first()
            if student:
                CourseRegistration.query.filter_by(student_id=student.id).delete()
                Score.query.filter_by(student_id=student.id).delete()
                db.session.delete(student)

        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully', 'success')

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error deleting user: {str(e)}")
        flash('Error deleting user. Please try again.', 'error')

    return redirect(url_for('views.admin_dashboard'))


@views_bp.route('/admin/add_course', methods=['GET', 'POST'])
@login_required
def admin_add_course():
    if not validate_admin_access():
        return redirect(get_redirect_url())

    lecturers = User.query.filter_by(role='Lecturer', is_active=True).order_by(User.name).all()

    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        title = request.form.get('title', '').strip()
        unit = request.form.get('unit', '').strip()
        session = request.form.get('session', '').strip()
        semester = request.form.get('semester', '').strip()
        lecturer_id = request.form.get('lecturer_id', '').strip()

        errors = []
        if not all([code, title, unit, session, semester]):
            errors.append('All fields except lecturer are required')
        if not unit.isdigit() or not (1 <= int(unit) <= 6):
            errors.append('Course units must be between 1 and 6')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('admin_add_course.html', lecturers=lecturers,
                                 code=code, title=title, unit=unit, session=session,
                                 semester=semester, lecturer_id=lecturer_id)

        if Course.query.filter_by(code=code).first():
            flash('Course code already exists', 'error')
            return render_template('admin_add_course.html', lecturers=lecturers,
                                 code=code, title=title, unit=unit, session=session,
                                 semester=semester, lecturer_id=lecturer_id)

        try:
            course = Course(
                code=code,
                title=title,
                unit=int(unit),
                session=session,
                semester=semester,
                lecturer_id=int(lecturer_id) if lecturer_id else None
            )
            db.session.add(course)
            db.session.commit()

            logger.info(f"User {current_user.unique_id} successfully added course {code}.")
            flash(f'Course {code} - {title} added successfully', 'success')
            return redirect(url_for('views.admin_dashboard'))

        except Exception as e:
            db.session.rollback()
            flash('Error adding course. Please try again.', 'error')
            return render_template('admin_add_course.html', lecturers=lecturers,
                                 code=code, title=title, unit=unit, session=session,
                                 semester=semester, lecturer_id=lecturer_id)

    return render_template('admin_add_course.html', lecturers=lecturers, now=datetime.now)


@views_bp.route('/admin/edit_course/<int:course_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_course(course_id):
    if not validate_admin_access():
        return redirect(get_redirect_url())

    course = db.session.get(Course, course_id)
    if not course:
        flash('Course not found', 'error')
        return redirect(url_for('views.admin_dashboard'))

    lecturers = User.query.filter_by(role='Lecturer', is_active=True).order_by(User.name).all()

    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        title = request.form.get('title', '').strip()
        unit = request.form.get('unit', '').strip()
        session = request.form.get('session', '').strip()
        semester = request.form.get('semester', '').strip()
        lecturer_id = request.form.get('lecturer_id', '').strip()

        errors = []
        if not all([code, title, unit, session, semester]):
            errors.append('All fields except lecturer are required')
        if not unit.isdigit() or not (1 <= int(unit) <= 6):
            errors.append('Course units must be between 1 and 6')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('admin_edit_course.html',
                                 course=course,
                                 lecturers=lecturers)

        if code != course.code and Course.query.filter_by(code=code).first():
            flash('Course code already exists', 'error')
            return render_template('admin_edit_course.html',
                                 course=course,
                                 lecturers=lecturers)

        try:
            course.code = code
            course.title = title
            course.unit = int(unit)
            course.session = session
            course.semester = semester
            course.lecturer_id = int(lecturer_id) if lecturer_id else None

            db.session.commit()
            flash('Course updated successfully', 'success')
            return redirect(url_for('views.admin_dashboard'))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating course: {str(e)}")
            flash('Error updating course. Please try again.', 'error')
            return render_template('admin_edit_course.html',
                                 course=course,
                                 lecturers=lecturers)

    return render_template('admin_edit_course.html', course=course, lecturers=lecturers)


@views_bp.route('/admin/delete_course/<int:course_id>', methods=['POST'])
@login_required
def admin_delete_course(course_id):
    if not validate_admin_access():
        return redirect(get_redirect_url())

    course = db.session.get(Course, course_id)
    if not course:
        flash('Course not found', 'error')
        return redirect(url_for('views.admin_dashboard'))

    try:
        CourseRegistration.query.filter_by(course_id=course.id).delete()
        Score.query.filter_by(course_id=course.id).delete()
        db.session.delete(course)
        db.session.commit()
        flash('Course deleted successfully', 'success')

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error deleting course: {str(e)}")
        flash('Error deleting course. Please try again.', 'error')

    return redirect(url_for('views.admin_dashboard'))


# --- Student Routes ---
@views_bp.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'Student':
        flash("Access denied.", "danger")
        return redirect(url_for('views.dashboard'))
    
    student = current_user.student
    
    # Check financial clearance
    is_cleared = is_financially_cleared(student.id)
    
    # Get recent payments
    payments = Payment.query.filter_by(
        student_id=student.id
    ).order_by(Payment.date_paid.desc()).limit(10).all()
    
    # Get registered courses
    registered_courses = [reg.course for reg in student.registrations]
    
    return render_template('student_dashboard.html',
                         student=student,
                         registered_courses=registered_courses,
                         financial_cleared=is_cleared,
                         balance=student.balance,
                         payments=payments)


@views_bp.route('/student/register_course', methods=['GET', 'POST'])
@login_required
def student_register_course():
    if not validate_student_access():
        return redirect(get_redirect_url())

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        flash('Student profile not found. Please contact administration.', 'error')
        return redirect(url_for('auth.logout'))

    all_courses = Course.query.all()
    registered_course_ids = [reg.course_id for reg in CourseRegistration.query.filter_by(student_id=student.id).all()]
    available_courses = [course for course in all_courses if course.id not in registered_course_ids]

    if request.method == 'POST':
        selected_courses = request.form.getlist('courses')

        if not selected_courses:
            flash('Please select at least one course to register', 'error')
            return render_template('student_register_course.html',
                                 courses=available_courses,
                                 all_courses=all_courses,
                                 registered_courses=registered_course_ids)

        try:
            for course_id in selected_courses:
                course = db.session.get(Course, int(course_id))
                if course and not CourseRegistration.query.filter_by(student_id=student.id, course_id=course.id).first():
                    registration = CourseRegistration(
                        student_id=student.id,
                        course_id=course.id,
                        date_registered=datetime.now()
                    )
                    db.session.add(registration)

            db.session.commit()
            flash('Courses registered successfully', 'success')
            return redirect(url_for('views.student_dashboard'))

        except Exception as e:
            db.session.rollback()
            flash('Error registering courses. Please try again.', 'error')
            return render_template('student_register_course.html',
                                 courses=available_courses,
                                 all_courses=all_courses,
                                 registered_courses=registered_course_ids)

    return render_template('student_register_course.html',
                         courses=available_courses,
                         all_courses=all_courses,
                         registered_courses=registered_course_ids)




@views_bp.route('/student/results')
@login_required
def student_results():
    if not validate_student_access():
        return redirect(get_redirect_url())

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        flash('Student profile not found. Please contact administration.', 'error')
        return redirect(url_for('auth.logout'))

    try:
        # Get all scores for the current student
        all_scores = Score.query.filter_by(student_id=student.id).all()
        
        # Define function to calculate grade points safely
        def calculate_grade_point(score):
            try:
                if not score.course:
                    return 0.0
                
                ca = float(score.ca_score) if score.ca_score is not None else 0.0
                exam = float(score.exam_score) if score.exam_score is not None else 0.0
                total = ca + exam
                units = float(score.course.unit) if score.course.unit else 0.0
                
                if total >= 70:
                    return 5.0 * units
                elif total >= 60:
                    return 4.0 * units
                elif total >= 50:
                    return 3.0 * units
                elif total >= 45:
                    return 2.0 * units
                elif total >= 40:
                    return 1.0 * units
                return 0.0
            except Exception as e:
                logging.error(f"Error calculating grade point: {e}")
                return 0.0

        # Organize results by session and semester
        results_by_session_semester = {}
        for score in all_scores:
            if score.course:
                session = score.course.session
                semester = score.course.semester

                if session not in results_by_session_semester:
                    results_by_session_semester[session] = {}
                if semester not in results_by_session_semester[session]:
                    results_by_session_semester[session][semester] = []

                results_by_session_semester[session][semester].append(score)

        # Calculate GPA for each semester and overall CGPA
        gpa_by_session_semester = {}
        overall_total_points = 0.0
        overall_total_units = 0.0

        for session, semesters in results_by_session_semester.items():
            gpa_by_session_semester[session] = {}
            for semester, scores in semesters.items():
                total_points = 0.0
                total_units = 0.0
                
                for score in scores:
                    points = calculate_grade_point(score)
                    units = float(score.course.unit) if score.course and score.course.unit else 0.0
                    total_points += points
                    total_units += units
                
                gpa = round(total_points / total_units, 2) if total_units > 0 else 0.0
                gpa_by_session_semester[session][semester] = gpa

                overall_total_points += total_points
                overall_total_units += total_units

        # Calculate CGPA
        cgpa = round(overall_total_points / overall_total_units, 2) if overall_total_units > 0 else 0.0

        # Determine final grade
        final_grade = "DISTINCTION" if cgpa >= 3.0 else "PASS"
        
        # Calculate total courses count
        total_courses = 0
        for session, semesters in results_by_session_semester.items():
            for semester, scores in semesters.items():
                total_courses += len(scores)

        return render_template(
            'student_results.html',
            results_by_session_semester=results_by_session_semester,
            gpa_by_session_semester=gpa_by_session_semester,
            cgpa=cgpa,
            final_grade=final_grade,
            student=student,
            total_courses=total_courses  # Add this line
        )

    except Exception as e:
        logging.error(f"Error loading student results: {str(e)}")
        import traceback
        traceback.print_exc()
        flash('Error loading results. Please try again.', 'error')
        return redirect(url_for('views.student_dashboard'))


# --- Lecturer Routes ---
@views_bp.route('/lecturer/dashboard')
@login_required
def lecturer_dashboard():
    if not validate_lecturer_access():
        return redirect(get_redirect_url())

    courses = Course.query.filter_by(lecturer_id=current_user.id).order_by(Course.code).all()
    course_count = len(courses)
    student_count = 0
    for course in courses:
        registrations = CourseRegistration.query.filter_by(course_id=course.id).count()
        student_count += registrations

    return render_template('lecturer_dashboard.html', 
                         courses=courses,
                         course_count=course_count, 
                         student_count=student_count)


@views_bp.route('/lecturer/upload_score/<int:course_id>', methods=['GET', 'POST'])
@login_required
def lecturer_upload_score(course_id):
    if not validate_lecturer_access():
        return redirect(get_redirect_url())

    course = db.session.get(Course, course_id)
    if not course:
        flash('Course not found', 'error')
        return redirect(url_for('views.lecturer_dashboard'))

    if course.lecturer_id != current_user.id:
        flash('You are not authorized to upload scores for this course', 'error')
        return redirect(url_for('views.lecturer_dashboard'))

    registrations = CourseRegistration.query.filter_by(course_id=course_id).all()
    students_in_course = [r.student for r in registrations if r.student]
    existing_scores = {score.student_id: score for score in Score.query.filter_by(course_id=course_id).all()}

    if request.method == 'POST':
        try:
            for student in students_in_course:
                ca_score_str = request.form.get(f'ca_score_{student.id}', '').strip()
                exam_score_str = request.form.get(f'exam_score_{student.id}', '').strip()

                ca_score = float(ca_score_str) if ca_score_str else None
                exam_score = float(exam_score_str) if exam_score_str else None

                if ca_score is not None and not (0 <= ca_score <= 40):
                    flash(f'Invalid CA score for student {student.user.name}. Must be between 0-40.', 'error')
                    return redirect(url_for('views.lecturer_upload_score', course_id=course_id))

                if exam_score is not None and not (0 <= exam_score <= 60):
                    flash(f'Invalid Exam score for student {student.user.name}. Must be between 0-60.', 'error')
                    return redirect(url_for('views.lecturer_upload_score', course_id=course_id))

                if ca_score is not None or exam_score is not None:
                    score = existing_scores.get(student.id)
                    if not score:
                        score = Score(student_id=student.id, course_id=course_id)
                        db.session.add(score)

                    if ca_score is not None:
                        score.ca_score = ca_score
                    if exam_score is not None:
                        score.exam_score = exam_score

            db.session.commit()
            flash('Scores uploaded successfully', 'success')
            return redirect(url_for('views.lecturer_dashboard'))

        except ValueError:
            flash('Invalid score format. Please enter numbers for scores.', 'error')
            return redirect(url_for('views.lecturer_upload_score', course_id=course_id))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error uploading scores: {str(e)}")
            flash('Error uploading scores. Please try again.', 'error')
            return redirect(url_for('views.lecturer_upload_score', course_id=course_id))

    return render_template('lecturer_upload_score.html',
                         course=course,
                         students=students_in_course,
                         existing_scores=existing_scores)


# --- Finance Routes ---
@views_bp.route('/finance_dashboard')
@login_required
def finance_dashboard():
    if current_user.role != 'Finance' and current_user.role != 'Admin':
        flash("Access denied.", "danger")
        return redirect(url_for('views.dashboard'))
    
    # Get all payments
    payments = Payment.query.order_by(Payment.date_paid.desc()).limit(50).all()
    
    # Get students with balances
    students_with_balance = Student.query.filter(Student.balance > 0).all()
    
    # Calculate totals
    total_revenue = db.session.query(db.func.sum(Payment.amount)).filter(Payment.status == 'Success').scalar() or 0
    
    return render_template('finance_dashboard.html',
                         payments=payments,
                         students_with_balance=students_with_balance,
                         total_revenue=total_revenue)


# --- Payment Routes ---
@views_bp.route('/make_payment', methods=['GET', 'POST'])
@login_required
def make_payment():
    if current_user.role != 'Student':
        flash("Only students can make payments.", "danger")
        return redirect(url_for('views.dashboard'))
    
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        
        if amount <= 0:
            flash("Invalid amount.", "danger")
            return redirect(url_for('views.make_payment'))
        
        # Create payment record
        payment = Payment(
            student_id=current_user.student.id,
            amount=amount,
            reference=f"PAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{current_user.id}",
            status='Success',
            date_paid=datetime.utcnow()
        )
        
        # Update student balance
        current_user.student.balance -= amount
        
        db.session.add(payment)
        db.session.commit()
        
        flash(f"Payment of ₦{amount:,.2f} successful!", "success")
        return redirect(url_for('views.student_dashboard'))
    
    return render_template('make_payment.html', 
                         balance=current_user.student.balance)


# --- API Routes ---
@views_bp.route('/api/v1/student/results')
@login_required
def api_get_results():
    if current_user.role != 'Student':
        return {"error": "Unauthorized"}, 403
        
    scores = Score.query.filter_by(student_id=current_user.student.id).all()
    results = []
    for s in scores:
        total = (s.ca_score or 0) + (s.exam_score or 0)
        results.append({
            "course_code": s.course.code,
            "total": total,
            "units": s.course.unit
        })
    return {"status": "success", "data": results}, 200