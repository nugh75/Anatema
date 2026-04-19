"""
Routes principali dell'applicazione
"""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from models import User, ExcelFile, TextCell, Label, CellAnnotation, Category, db

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Pagina principale"""
    # Statistiche generali
    stats = {
        'total_files': ExcelFile.query.count(),
        'total_cells': TextCell.query.count(),
        'total_labels': Label.query.count(),
        'total_annotations': CellAnnotation.query.count(),
        'total_users': User.query.count()
    }
    
    # File recenti
    recent_files = ExcelFile.query.order_by(ExcelFile.uploaded_at.desc()).limit(5).all()
    
    # Etichette popolari con colori calcolati
    popular_labels = db.session.query(
        Label,
        db.func.count(CellAnnotation.id).label('count')
    ).options(db.joinedload(Label.category_obj))\
        .join(CellAnnotation)\
        .group_by(Label.id)\
        .order_by(db.desc('count'))\
        .limit(10)\
        .all()
    
    return render_template('main/index.html', 
                         stats=stats, 
                         recent_files=recent_files,
                         popular_labels=popular_labels)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard utente"""
    user_stats = {
        'my_annotations': CellAnnotation.query.filter_by(user_id=current_user.id).count(),
        'my_files': ExcelFile.query.filter_by(uploaded_by=current_user.id).count(),
    }

    any_files = ExcelFile.query.count() > 0
    any_questions_defined = TextCell.query.filter(TextCell.question_type.isnot(None)).count() > 0
    any_labels = Label.query.count() > 0
    user_has_annotations = user_stats['my_annotations'] > 0
    any_ai_reviewed = CellAnnotation.query.filter_by(
        is_ai_generated=True, status='accepted'
    ).count() > 0

    completed_steps = []
    if any_files: completed_steps.append(1)
    if any_questions_defined: completed_steps.append(2)
    if any_labels: completed_steps.append(3)
    if user_has_annotations: completed_steps.append(4)
    if any_ai_reviewed: completed_steps.append(5)

    next_step = 1
    for s in (1, 2, 3, 4, 5, 6):
        if s not in completed_steps:
            next_step = s
            break
    else:
        next_step = 6

    recent_annotations = db.session.query(CellAnnotation, TextCell, Label)\
        .join(TextCell)\
        .join(Label)\
        .filter(CellAnnotation.user_id == current_user.id)\
        .order_by(CellAnnotation.created_at.desc())\
        .limit(10)\
        .all()

    last_file = ExcelFile.query.filter_by(uploaded_by=current_user.id)\
        .order_by(ExcelFile.uploaded_at.desc()).first()

    return render_template('main/dashboard.html',
                         user_stats=user_stats,
                         completed_steps=completed_steps,
                         next_step=next_step,
                         last_file=last_file,
                         recent_annotations=recent_annotations)
