"""
Routes per le statistiche di annotazione
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, desc, distinct
from collections import defaultdict, Counter, namedtuple
from datetime import datetime, timedelta
import json
import traceback

from models import CellAnnotation, Label, User, TextCell, ExcelFile, Category, AnnotationAction, TextDocument, TextAnnotation, db

# Namedtuple per creare oggetti con attributi come quelli restituiti dalle query SQLAlchemy
UserStat = namedtuple('UserStat', ['username', 'id', 'annotation_count'])
LabelStat = namedtuple('LabelStat', ['name', 'color', 'usage_count'])

statistics_bp = Blueprint('statistics', __name__, url_prefix='/statistics')

@statistics_bp.route('/')
@login_required
def overview():
    """Pagina principale delle statistiche"""
    # Statistiche generali - Excel files
    total_cell_annotations = CellAnnotation.query.count()
    total_cells = TextCell.query.count()
    total_excel_files = ExcelFile.query.count()
    
    # Statistiche generali - Text documents  
    total_text_annotations = TextAnnotation.query.count()
    total_text_documents = TextDocument.query.count()
    
    # Statistiche combinate
    total_annotations = total_cell_annotations + total_text_annotations
    total_documents = total_excel_files + total_text_documents
    total_users = User.query.count()
    total_labels = Label.query.count()
    
    # Top 10 annotatori (combinando Excel e Text annotations)
    # Prima query per annotazioni Excel - convertita in subquery
    excel_annotators = db.session.query(
        User.username,
        User.id,
        func.count(CellAnnotation.id).label('cell_count'),
        func.cast(0, db.Integer).label('text_count')
    ).join(CellAnnotation, User.id == CellAnnotation.user_id)\
     .group_by(User.id).subquery()
    
    # Seconda query per annotazioni testo - convertita in subquery
    text_annotators = db.session.query(
        User.username,
        User.id,
        func.cast(0, db.Integer).label('cell_count'),
        func.count(TextAnnotation.id).label('text_count')
    ).join(TextAnnotation, User.id == TextAnnotation.user_id)\
     .group_by(User.id).subquery()
    
    # Combina i risultati
    combined_annotators = db.session.query(
        User.username,
        User.id,
        func.sum(func.coalesce(excel_annotators.c.cell_count, 0) + func.coalesce(text_annotators.c.text_count, 0)).label('total_count')
    ).select_from(User)\
     .outerjoin(excel_annotators, User.id == excel_annotators.c.id)\
     .outerjoin(text_annotators, User.id == text_annotators.c.id)\
     .group_by(User.id)\
     .order_by(desc('total_count'))\
     .limit(10)
    
    # Esegui la query in modo più semplice per evitare problemi
    top_annotators = []
    try:
        # Alternativa più semplice: calcola manualmente
        all_users = User.query.all()
        user_counts = []
        for user in all_users:
            cell_count = CellAnnotation.query.filter_by(user_id=user.id).count()
            text_count = TextAnnotation.query.filter_by(user_id=user.id).count()
            total_count = cell_count + text_count
            if total_count > 0:
                user_counts.append(UserStat(username=user.username, id=user.id, annotation_count=total_count))
        
        # Ordina e prendi i top 10
        user_counts.sort(key=lambda x: x.annotation_count, reverse=True)
        top_annotators = user_counts[:10]
    except Exception as e:
        # Fallback alla query originale in caso di errore
        top_annotators = db.session.query(
            User.username,
            User.id,
            func.count(CellAnnotation.id).label('annotation_count')
        ).join(CellAnnotation, User.id == CellAnnotation.user_id).group_by(User.id).order_by(desc('annotation_count')).limit(10).all()
    
    # Etichette più usate (combinando Excel e Text annotations)
    top_labels = []
    try:
        # Calcola manualmente per evitare problemi con query complesse
        all_labels = Label.query.all()
        label_counts = []
        for label in all_labels:
            cell_count = CellAnnotation.query.filter_by(label_id=label.id).count()
            text_count = TextAnnotation.query.filter_by(label_id=label.id).count()
            total_count = cell_count + text_count
            if total_count > 0:
                # Determina il colore
                color = label.category_obj.color if label.category_obj else label.color
                label_counts.append(LabelStat(name=label.name, color=color or '#6c757d', usage_count=total_count))
        
        # Ordina e prendi le top 10
        label_counts.sort(key=lambda x: x.usage_count, reverse=True)
        top_labels = label_counts[:10]
    except Exception as e:
        # Fallback alla query originale in caso di errore
        top_labels = db.session.query(
            Label.name,
            func.coalesce(Category.color, Label.color).label('color'),
            func.count(CellAnnotation.id).label('usage_count')
        ).join(CellAnnotation)\
         .outerjoin(Category, Label.category_id == Category.id)\
         .group_by(Label.id).order_by(desc('usage_count')).limit(10).all()
    
    # Statistiche per file Excel
    excel_file_stats = db.session.query(
        ExcelFile.id,
        ExcelFile.filename,
        func.count(distinct(TextCell.id)).label('total_cells'),
        func.count(CellAnnotation.id).label('total_annotations'),
        func.count(distinct(CellAnnotation.user_id)).label('annotator_count')
    ).outerjoin(TextCell, ExcelFile.id == TextCell.excel_file_id)\
     .outerjoin(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
     .group_by(ExcelFile.id)\
     .order_by(desc('total_annotations'))\
     .all()
    
    # Statistiche per documenti di testo
    text_document_stats = db.session.query(
        TextDocument.id,
        TextDocument.original_name,
        func.count(TextAnnotation.id).label('total_annotations'),
        func.count(distinct(TextAnnotation.user_id)).label('annotator_count')
    ).outerjoin(TextAnnotation, TextDocument.id == TextAnnotation.document_id)\
     .group_by(TextDocument.id)\
     .order_by(desc('total_annotations'))\
     .all()
    
    # Combina le statistiche per file (per compatibilità con il template)
    file_stats = []
    
    # Aggiungi file Excel
    for stat in excel_file_stats:
        file_stats.append({
            'id': stat.id,
            'filename': stat.filename,
            'type': 'excel',
            'total_cells': stat.total_cells,
            'total_annotations': stat.total_annotations,
            'annotator_count': stat.annotator_count
        })
    
    # Aggiungi documenti di testo  
    for stat in text_document_stats:
        file_stats.append({
            'id': stat.id,
            'filename': stat.original_name,
            'type': 'text',
            'total_cells': 1,  # Per i documenti di testo consideriamo 1 "unità"
            'total_annotations': stat.total_annotations,
            'annotator_count': stat.annotator_count
        })
    
    # Ordina per numero di annotazioni
    file_stats.sort(key=lambda x: x['total_annotations'], reverse=True)
    
    # Dati per grafici
    # Annotazioni per utente (per grafico) - combinando entrambi i tipi
    user_chart_data = []
    try:
        # Stesso approccio semplice usato sopra
        user_chart_counts = [(user.username, user.annotation_count) for user in top_annotators[:15]]
        user_chart_data = user_chart_counts
    except Exception as e:
        # Fallback alla query originale
        user_chart_data = db.session.query(
            User.username,
            func.count(CellAnnotation.id).label('count')
        ).join(CellAnnotation, User.id == CellAnnotation.user_id).group_by(User.id).order_by(desc('count')).limit(15).all()
    
    # Distribuzione etichette (per grafico) - usando i dati già calcolati
    label_chart_data = []
    try:
        # Usa i dati già calcolati da top_labels
        label_chart_data = top_labels[:10]
    except Exception as e:
        # Fallback alla query originale
        label_chart_data = db.session.query(
            Label.name,
            func.coalesce(Category.color, Label.color).label('color'),
            func.count(CellAnnotation.id).label('count')
        ).join(CellAnnotation)\
         .outerjoin(Category, Label.category_id == Category.id)\
         .group_by(Label.id).order_by(desc('count')).limit(10).all()
    
    # Timeline attività (combinando entrambi i tipi)
    try:
        # Timeline per annotazioni Excel
        excel_timeline = db.session.query(
            func.date(CellAnnotation.created_at).label('date'),
            func.count(CellAnnotation.id).label('count')
        ).group_by(func.date(CellAnnotation.created_at)).all()
        
        # Timeline per annotazioni testo
        text_timeline = db.session.query(
            func.date(TextAnnotation.created_at).label('date'),
            func.count(TextAnnotation.id).label('count')
        ).group_by(func.date(TextAnnotation.created_at)).all()
        
        # Combina le timeline
        timeline_dict = {}
        for date, count in excel_timeline:
            timeline_dict[date] = timeline_dict.get(date, 0) + count
        for date, count in text_timeline:
            timeline_dict[date] = timeline_dict.get(date, 0) + count
            
        # Converti in lista ordinata
        timeline_data = [(date, count) for date, count in sorted(timeline_dict.items())]
    except Exception as e:
        # Fallback alla query originale
        timeline_data = db.session.query(
            func.date(CellAnnotation.created_at).label('date'),
            func.count(CellAnnotation.id).label('count')
        ).group_by(func.date(CellAnnotation.created_at)).order_by('date').all()
    
    return render_template('statistics/overview.html',
                         total_annotations=total_annotations,
                         total_users=total_users,
                         total_cells=total_cells,
                         total_labels=total_labels,
                         total_documents=total_documents,
                         total_text_documents=total_text_documents,
                         total_excel_files=total_excel_files,
                         total_cell_annotations=total_cell_annotations,
                         total_text_annotations=total_text_annotations,
                         top_annotators=top_annotators,
                         top_labels=top_labels,
                         file_stats=file_stats,
                         user_chart_data=user_chart_data,
                         label_chart_data=label_chart_data,
                         timeline_data=timeline_data)

@statistics_bp.route('/user/<int:user_id>')
@login_required
def user_detail(user_id):
    """Statistiche dettagliate per un singolo utente"""
    user = User.query.get_or_404(user_id)
    
    # Statistiche base dell'utente
    user_annotations = CellAnnotation.query.filter_by(user_id=user_id).all()
    total_annotations = len(user_annotations)
    unique_cells = db.session.query(distinct(CellAnnotation.text_cell_id)).filter_by(user_id=user_id).count()
    unique_labels = db.session.query(distinct(CellAnnotation.label_id)).filter_by(user_id=user_id).count()
    
    # Media annotazioni per giorno
    first_annotation = db.session.query(func.min(CellAnnotation.created_at)).filter_by(user_id=user_id).scalar()
    days_active = 1
    if first_annotation:
        days_active = max(1, (datetime.now() - first_annotation).days + 1)
    avg_per_day = total_annotations / days_active
    
    # Distribuzione etichette
    label_usage = db.session.query(
        Label.name,
        func.coalesce(Category.color, Label.color).label('color'),
        Category.name.label('category_name'),
        func.count(CellAnnotation.id).label('count')
    ).select_from(CellAnnotation).join(Label).outerjoin(Category, Label.category_id == Category.id).filter(
        CellAnnotation.user_id == user_id
    ).group_by(Label.id).order_by(desc('count')).all()
    
    # Aggiungi percentuali
    label_usage_with_pct = []
    for usage in label_usage:
        percentage = (usage.count / total_annotations * 100) if total_annotations > 0 else 0
        label_usage_with_pct.append({
            'name': usage.name,
            'color': usage.color,
            'category_name': usage.category_name,
            'count': usage.count,
            'percentage': percentage
        })
    
    # Attività recente (ultime 20 azioni)
    recent_actions = db.session.query(AnnotationAction).filter_by(
        performed_by=user_id
    ).order_by(desc(AnnotationAction.timestamp)).limit(20).all()
    
    # Aggiungi info etichetta alle azioni
    recent_actions_with_labels = []
    for action in recent_actions:
        label = Label.query.get(action.label_id) if action.label_id else None
        recent_actions_with_labels.append({
            'timestamp': action.timestamp,
            'action': action.action_type,
            'cell_id': action.text_cell_id,
            'label_name': label.name if label else 'N/A',
            'label_color': label.color if label else '#000000'
        })
    
    # Timeline attività
    timeline_data = db.session.query(
        func.date(CellAnnotation.created_at).label('date'),
        func.count(CellAnnotation.id).label('count')
    ).filter(CellAnnotation.user_id == user_id).group_by(
        func.date(CellAnnotation.created_at)
    ).order_by('date').all()
    
    timeline_dates = []
    for item in timeline_data:
        if isinstance(item.date, str):
            # Se date è una stringa, verifica il formato e converti se necessario
            try:
                if '-' in item.date:  # Formato YYYY-MM-DD
                    date_obj = datetime.strptime(item.date, '%Y-%m-%d').date()
                    timeline_dates.append(date_obj.strftime('%Y-%m-%d'))
                else:  # Altri formati di data come stringa
                    timeline_dates.append(item.date)  # Usa la stringa originale
            except ValueError:
                timeline_dates.append(item.date)  # Fallback alla stringa originale
        else:
            # Altrimenti usa direttamente strftime
            timeline_dates.append(item.date.strftime('%Y-%m-%d'))
    timeline_counts = [item.count for item in timeline_data]
    
    # Statistiche per categoria
    category_stats = db.session.query(
        Category.name,
        func.count(CellAnnotation.id).label('total_annotations'),
        func.count(distinct(CellAnnotation.label_id)).label('unique_labels')
    ).select_from(CellAnnotation).join(Label).join(Category).filter(
        CellAnnotation.user_id == user_id
    ).group_by(Category.id).all()
    
    category_stats_with_pct = []
    for cat_stat in category_stats:
        percentage = (cat_stat.total_annotations / total_annotations * 100) if total_annotations > 0 else 0
        
        # Etichetta più usata nella categoria
        most_used = db.session.query(
            Label.name,
            Label.color,
            func.count(CellAnnotation.id).label('count')
        ).select_from(CellAnnotation).join(Label).join(Category).filter(
            CellAnnotation.user_id == user_id,
            Category.name == cat_stat.name
        ).group_by(Label.id).order_by(desc('count')).first()
        
        category_stats_with_pct.append({
            'name': cat_stat.name,
            'total_annotations': cat_stat.total_annotations,
            'unique_labels': cat_stat.unique_labels,
            'percentage': percentage,
            'most_used_label': {
                'name': most_used.name,
                'color': most_used.color,
                'count': most_used.count
            } if most_used else None
        })
    
    # Dati per grafici
    label_names = [item['name'] for item in label_usage_with_pct]
    label_counts = [item['count'] for item in label_usage_with_pct]
    label_colors = [item['color'] for item in label_usage_with_pct]
    
    stats = {
        'total_annotations': total_annotations,
        'unique_cells': unique_cells,
        'unique_labels': unique_labels,
        'avg_per_day': avg_per_day,
        'label_usage': label_usage_with_pct,
        'recent_actions': recent_actions_with_labels,
        'timeline_dates': timeline_dates,
        'timeline_counts': timeline_counts,
        'category_stats': category_stats_with_pct,
        'label_names': label_names,
        'label_counts': label_counts,
        'label_colors': label_colors
    }
    
    return render_template('statistics/user_detail.html', user=user, stats=stats)

@statistics_bp.route('/compare')
@login_required
def compare():
    """Confronto tra annotatori"""
    # Tutti gli utenti con annotazioni
    users = db.session.query(
        User.id,
        User.username,
        func.count(CellAnnotation.id).label('annotation_count')
    ).join(CellAnnotation, User.id == CellAnnotation.user_id).group_by(User.id).order_by(User.username).all()
    
    user1_id = request.args.get('user1_id', type=int)
    user2_id = request.args.get('user2_id', type=int)
    
    user1 = User.query.get(user1_id) if user1_id else None
    user2 = User.query.get(user2_id) if user2_id else None
    
    comparison = None
    if user1 and user2 and user1_id != user2_id:
        comparison = _calculate_comparison(user1, user2)
    
    return render_template('statistics/compare.html',
                         users=users,
                         user1=user1,
                         user2=user2,
                         comparison=comparison)

def _calculate_comparison(user1, user2):
    """Calcola dati di confronto tra due utenti"""
    # Statistiche base per entrambi gli utenti
    user1_stats = _get_user_basic_stats(user1.id)
    user2_stats = _get_user_basic_stats(user2.id)
    
    # Celle annotate da entrambi
    common_cells_query = db.session.query(CellAnnotation.text_cell_id).filter_by(user_id=user1.id).intersect(
        db.session.query(CellAnnotation.text_cell_id).filter_by(user_id=user2.id)
    )
    common_cells = [row[0] for row in common_cells_query.all()]
    
    # Calcola accordo inter-annotatore
    agreement = _calculate_inter_annotator_agreement(user1.id, user2.id, common_cells)
    
    # Conflitti (celle con etichette diverse)
    conflicts = _find_annotation_conflicts(user1.id, user2.id, common_cells)
    
    # Etichette comuni e specifiche
    common_labels, user1_only, user2_only = _compare_label_usage(user1.id, user2.id)
    
    # Dati per grafici
    chart_data = _prepare_chart_data(user1.id, user2.id)
    timeline_data = _prepare_timeline_data(user1.id, user2.id)
    
    # Confronto per quesito - TODO: implementare
    # question_comparison = _compare_by_question(user1.id, user2.id)
    question_comparison = []
    
    return {
        'user1_stats': user1_stats,
        'user2_stats': user2_stats,
        'agreement': agreement,
        'conflicts': conflicts,
        'common_labels': common_labels,
        'user1_only_labels': user1_only,
        'user2_only_labels': user2_only,
        'chart_data': chart_data,
        'timeline_data': timeline_data,
        'question_comparison': question_comparison
    }

def _get_user_basic_stats(user_id):
    """Ottieni statistiche base per un utente"""
    total_annotations = CellAnnotation.query.filter_by(user_id=user_id).count()
    unique_cells = db.session.query(distinct(CellAnnotation.text_cell_id)).filter_by(user_id=user_id).count()
    unique_labels = db.session.query(distinct(CellAnnotation.label_id)).filter_by(user_id=user_id).count()
    
    # Media annotazioni per giorno
    first_annotation = db.session.query(func.min(CellAnnotation.created_at)).filter_by(user_id=user_id).scalar()
    days_active = 1
    if first_annotation:
        days_active = max(1, (datetime.now() - first_annotation).days + 1)
    avg_per_day = total_annotations / days_active
    
    return {
        'total_annotations': total_annotations,
        'unique_cells': unique_cells,
        'unique_labels': unique_labels,
        'avg_per_day': avg_per_day
    }

def _calculate_inter_annotator_agreement(user1_id, user2_id, common_cells):
    """Calcola l'accordo inter-annotatore (Cohen's Kappa)"""
    if not common_cells:
        return {
            'common_cells': 0,
            'exact_matches': 0,
            'agreement_percentage': 0.0,
            'kappa': 0.0
        }
    
    exact_matches = 0
    total_comparisons = 0
    
    for cell_id in common_cells:
        # Etichette dell'utente 1 per questa cella
        user1_labels = set([
            ann.label_id for ann in CellAnnotation.query.filter_by(
                user_id=user1_id, text_cell_id=cell_id
            ).all()
        ])
        
        # Etichette dell'utente 2 per questa cella
        user2_labels = set([
            ann.label_id for ann in CellAnnotation.query.filter_by(
                user_id=user2_id, text_cell_id=cell_id
            ).all()
        ])
        
        # Confronta i set di etichette
        if user1_labels == user2_labels:
            exact_matches += 1
        total_comparisons += 1
    
    agreement_percentage = (exact_matches / total_comparisons * 100) if total_comparisons > 0 else 0
    
    # Calcolo semplificato di Cohen's Kappa (versione base)
    # Per un calcolo più preciso servirebbero più considerazioni statistiche
    pe = 0.5  # Probabilità di accordo casuale (semplificata)
    po = agreement_percentage / 100  # Probabilità di accordo osservato
    kappa = (po - pe) / (1 - pe) if (1 - pe) != 0 else 0
    
    return {
        'common_cells': len(common_cells),
        'exact_matches': exact_matches,
        'agreement_percentage': agreement_percentage,
        'kappa': max(0, kappa)  # Non può essere negativo in questa semplificazione
    }

def _find_annotation_conflicts(user1_id, user2_id, common_cells):
    """Trova conflitti di annotazione tra due utenti"""
    conflicts = []
    
    for cell_id in common_cells:
        # Etichette dell'utente 1
        user1_annotations = db.session.query(CellAnnotation, Label, Category).join(
            Label
        ).join(Category).filter(
            CellAnnotation.user_id == user1_id,
            CellAnnotation.text_cell_id == cell_id
        ).all()
        
        # Etichette dell'utente 2
        user2_annotations = db.session.query(CellAnnotation, Label, Category).join(
            Label
        ).join(Category).filter(
            CellAnnotation.user_id == user2_id,
            CellAnnotation.text_cell_id == cell_id
        ).all()
        
        user1_label_ids = set([ann[0].label_id for ann in user1_annotations])
        user2_label_ids = set([ann[0].label_id for ann in user2_annotations])
        
        # Se ci sono differenze, è un conflitto
        if user1_label_ids != user2_label_ids:
            conflicts.append({
                'cell_id': cell_id,
                'user1_labels': [{'name': ann[1].name, 'color': ann[1].color} for ann in user1_annotations],
                'user2_labels': [{'name': ann[1].name, 'color': ann[1].color} for ann in user2_annotations],
                'category': user1_annotations[0][2].name if user1_annotations else 'N/A'
            })
    
    return conflicts

def _compare_label_usage(user1_id, user2_id):
    """Confronta l'uso delle etichette tra due utenti"""
    # Etichette usate dall'utente 1
    user1_labels = db.session.query(
        Label.id, Label.name, Label.color,
        func.count(CellAnnotation.id).label('count')
    ).join(CellAnnotation).filter(
        CellAnnotation.user_id == user1_id
    ).group_by(Label.id).all()
    
    # Etichette usate dall'utente 2
    user2_labels = db.session.query(
        Label.id, Label.name, Label.color,
        func.count(CellAnnotation.id).label('count')
    ).join(CellAnnotation).filter(
        CellAnnotation.user_id == user2_id
    ).group_by(Label.id).all()
    
    user1_label_ids = set([l.id for l in user1_labels])
    user2_label_ids = set([l.id for l in user2_labels])
    
    # Crea dizionari per accesso rapido
    user1_dict = {l.id: l for l in user1_labels}
    user2_dict = {l.id: l for l in user2_labels}
    
    # Etichette in comune
    common_label_ids = user1_label_ids.intersection(user2_label_ids)
    common_labels = []
    for label_id in common_label_ids:
        label1 = user1_dict[label_id]
        label2 = user2_dict[label_id]
        common_labels.append({
            'id': label_id,
            'name': label1.name,
            'color': label1.color,
            'user1_count': label1.count,
            'user2_count': label2.count
        })
    
    # Etichette specifiche dell'utente 1
    user1_only_ids = user1_label_ids - user2_label_ids
    user1_only = [
        {'name': user1_dict[lid].name, 'color': user1_dict[lid].color, 'count': user1_dict[lid].count}
        for lid in user1_only_ids
    ]
    
    # Etichette specifiche dell'utente 2
    user2_only_ids = user2_label_ids - user1_label_ids
    user2_only = [
        {'name': user2_dict[lid].name, 'color': user2_dict[lid].color, 'count': user2_dict[lid].count}
        for lid in user2_only_ids
    ]
    
    return common_labels, user1_only, user2_only

def _prepare_chart_data(user1_id, user2_id):
    """Prepara dati per i grafici di confronto"""
    # Ottieni tutte le etichette usate da entrambi
    all_labels = db.session.query(Label.id, Label.name).join(CellAnnotation).filter(
        (CellAnnotation.user_id == user1_id) | (CellAnnotation.user_id == user2_id)
    ).distinct().all()
    
    label_names = [l.name for l in all_labels]
    user1_counts = []
    user2_counts = []
    
    for label in all_labels:
        # Count per utente 1
        count1 = CellAnnotation.query.filter_by(user_id=user1_id, label_id=label.id).count()
        user1_counts.append(count1)
        
        # Count per utente 2
        count2 = CellAnnotation.query.filter_by(user_id=user2_id, label_id=label.id).count()
        user2_counts.append(count2)
    
    return {
        'label_names': label_names,
        'user1_counts': user1_counts,
        'user2_counts': user2_counts
    }

def _prepare_timeline_data(user1_id, user2_id):
    """Prepara dati timeline per confronto"""
    # Date di tutte le annotazioni
    all_dates = db.session.query(
        func.date(CellAnnotation.created_at).label('date')
    ).filter(
        (CellAnnotation.user_id == user1_id) | (CellAnnotation.user_id == user2_id)
    ).distinct().order_by('date').all()
    
    dates = []
    for d in all_dates:
        if isinstance(d.date, str):
            # Se date è una stringa, usa direttamente
            dates.append(d.date)
        else:
            # Altrimenti usa strftime
            dates.append(d.date.strftime('%Y-%m-%d'))
    
    user1_counts = []
    user2_counts = []
    
    for date_obj in all_dates:
        # Estrai la data in formato corretto per il confronto
        if isinstance(date_obj.date, str):
            date_value = date_obj.date
        else:
            date_value = date_obj.date
        
        # Count per utente 1
        count1 = CellAnnotation.query.filter(
            CellAnnotation.user_id == user1_id,
            func.date(CellAnnotation.created_at) == date_value
        ).count()
        user1_counts.append(count1)
        
        # Count per utente 2
        count2 = CellAnnotation.query.filter(
            CellAnnotation.user_id == user2_id,
            func.date(CellAnnotation.created_at) == date_value
        ).count()
        user2_counts.append(count2)
    
    return {
        'dates': dates,
        'user1_counts': user1_counts,
        'user2_counts': user2_counts
    }

@statistics_bp.route('/api/chart_data/<chart_type>')
@login_required
def chart_data(chart_type):
    """API per dati dei grafici"""
    
    if chart_type == 'annotations_per_user':
        data = db.session.query(
            User.username,
            func.count(CellAnnotation.id).label('count')
        ).join(CellAnnotation, User.id == CellAnnotation.user_id).group_by(User.id).order_by(desc('count')).limit(20).all()
        
        return jsonify({
            'labels': [item.username for item in data],
            'values': [item.count for item in data]
        })
    
    elif chart_type == 'labels_usage':
        data = db.session.query(
            Label.name,
            func.count(CellAnnotation.id).label('count')
        ).join(CellAnnotation).group_by(Label.id).order_by(desc('count')).limit(15).all()
        
        return jsonify({
            'labels': [item.name for item in data],
            'values': [item.count for item in data]
        })
    
    elif chart_type == 'annotations_timeline':
        data = db.session.query(
            func.date(CellAnnotation.created_at).label('date'),
            func.count(CellAnnotation.id).label('count')
        ).group_by(func.date(CellAnnotation.created_at)).order_by('date').all()
        
        return jsonify({
            'dates': [item.date.isoformat() for item in data],
            'values': [item.count for item in data]
        })
    
    return jsonify({'error': 'Chart type not found'}), 404

@statistics_bp.route('/api/user_stats')
@login_required
def api_user_stats():
    """API per statistiche dell'utente corrente"""
    user_id = current_user.id
    
    total_annotations = CellAnnotation.query.filter_by(user_id=user_id).count()
    unique_cells = db.session.query(distinct(CellAnnotation.text_cell_id)).filter_by(user_id=user_id).count()
    unique_labels = db.session.query(distinct(CellAnnotation.label_id)).filter_by(user_id=user_id).count()
    
    return jsonify({
        'success': True,
        'stats': {
            'total_annotations': total_annotations,
            'unique_cells': unique_cells,
            'unique_labels': unique_labels
        }
    })

@statistics_bp.route('/api/global_stats')
@login_required
def api_global_stats():
    """API per statistiche globali del sistema"""
    total_annotations = CellAnnotation.query.count()
    total_users = User.query.count()
    total_cells = TextCell.query.count()
    total_labels = Label.query.count()
    
    return jsonify({
        'success': True,
        'stats': {
            'total_annotations': total_annotations,
            'total_users': total_users,
            'total_cells': total_cells,
            'total_labels': total_labels
        }
    })

@statistics_bp.route('/api/question_chart_data/<int:file_id>/<chart_type>')
@login_required
def question_chart_data(file_id, chart_type):
    """API per dati dei grafici delle pagine dei quesiti"""
    question = request.args.get('question')
    
    # Debug logging
    print(f"[DEBUG] API chiamata: file_id={file_id}, chart_type={chart_type}")
    print(f"[DEBUG] Question ricevuta: '{question}'")
    print(f"[DEBUG] Tutti i parametri: {dict(request.args)}")
    
    if not question:
        print("[ERROR] Question parameter mancante")
        return jsonify({'error': 'Question parameter required'}), 400
    
    # Parametri per il filtraggio
    category_filter = request.args.get('category')
    label_name_filter = request.args.get('label_name', '').strip()
    min_usage = request.args.get('min_usage', type=int)
    max_usage = request.args.get('max_usage', type=int)
    
    print(f"[DEBUG] Filtri: category={category_filter}, label_name='{label_name_filter}', min_usage={min_usage}, max_usage={max_usage}")
    
    try:
        if chart_type == 'labels_histogram':
            return _get_labels_histogram_data(file_id, question, category_filter, label_name_filter, min_usage, max_usage)
        elif chart_type == 'annotators_histogram':
            return _get_annotators_histogram_data(file_id, question, category_filter, label_name_filter, min_usage, max_usage)
        elif chart_type == 'categories_distribution':
            return _get_categories_distribution_data(file_id, question)
        elif chart_type == 'coverage_analysis':
            return _get_coverage_analysis_data(file_id, question)
        else:
            print(f"[ERROR] Chart type non supportato: {chart_type}")
            return jsonify({'error': 'Chart type not found'}), 404
    except Exception as e:
        print(f"[ERROR] Eccezione nell'API: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _get_labels_histogram_data(file_id, question, category_filter=None, label_name_filter=None, min_usage=None, max_usage=None):
    """Ottieni dati per istogramma etichette"""
    print(f"[DEBUG] _get_labels_histogram_data chiamata con: file_id={file_id}, question='{question}'")
    
    query = db.session.query(
        Label.name,
        Label.color,
        Category.name.label('category_name'),
        func.count(CellAnnotation.id).label('usage_count')
    ).join(CellAnnotation)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(Label.id)
    
    # Applica filtri
    if category_filter:
        query = query.filter(Category.name == category_filter)
        print(f"[DEBUG] Filtro categoria applicato: {category_filter}")
    
    if label_name_filter:
        query = query.filter(Label.name.ilike(f'%{label_name_filter}%'))
        print(f"[DEBUG] Filtro nome etichetta applicato: {label_name_filter}")
    
    if min_usage is not None:
        query = query.having(func.count(CellAnnotation.id) >= min_usage)
        print(f"[DEBUG] Filtro min_usage applicato: {min_usage}")
    
    if max_usage is not None:
        query = query.having(func.count(CellAnnotation.id) <= max_usage)
        print(f"[DEBUG] Filtro max_usage applicato: {max_usage}")
    
    # Ordina per utilizzo decrescente
    data = query.order_by(desc('usage_count')).all()
    
    print(f"[DEBUG] Query eseguita, trovati {len(data)} risultati")
    for item in data[:3]:  # Log primi 3 risultati
        print(f"[DEBUG] Risultato: {item.name}, {item.usage_count}, {item.color}")
    
    result = {
        'labels': [item.name for item in data],
        'values': [item.usage_count for item in data],
        'colors': [item.color or '#007bff' for item in data],
        'categories': [item.category_name or 'Senza categoria' for item in data]
    }
    
    print(f"[DEBUG] Risultato finale: {len(result['labels'])} etichette")
    
    return jsonify(result)

def _get_annotators_histogram_data(file_id, question, category_filter=None, label_name_filter=None, min_usage=None, max_usage=None):
    """Ottieni dati per istogramma annotatori con filtri applicati alle etichette"""
    
    # Query base per le annotazioni nel quesito
    base_query = db.session.query(CellAnnotation.id)\
                          .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
                          .join(Label, Label.id == CellAnnotation.label_id)\
                          .outerjoin(Category, Label.category_id == Category.id)\
                          .filter(TextCell.excel_file_id == file_id)\
                          .filter(TextCell.column_name == question)
    
    # Applica filtri etichette
    if category_filter:
        base_query = base_query.filter(Category.name == category_filter)
    
    if label_name_filter:
        base_query = base_query.filter(Label.name.ilike(f'%{label_name_filter}%'))
    
    # Per i filtri di utilizzo, dobbiamo prima identificare le etichette che soddisfano i criteri
    if min_usage is not None or max_usage is not None:
        valid_labels_query = db.session.query(Label.id)\
                                      .join(CellAnnotation)\
                                      .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
                                      .filter(TextCell.excel_file_id == file_id)\
                                      .filter(TextCell.column_name == question)\
                                      .group_by(Label.id)
        
        if min_usage is not None:
            valid_labels_query = valid_labels_query.having(func.count(CellAnnotation.id) >= min_usage)
        
        if max_usage is not None:
            valid_labels_query = valid_labels_query.having(func.count(CellAnnotation.id) <= max_usage)
        
        valid_label_ids = [row[0] for row in valid_labels_query.all()]
        base_query = base_query.filter(Label.id.in_(valid_label_ids))
    
    # Sottosquery per le annotazioni filtrate
    filtered_annotations = base_query.subquery()
    
    # Query per statistiche annotatori
    annotator_stats = db.session.query(
        User.username,
        User.id,
        func.count(CellAnnotation.id).label('annotation_count'),
        func.count(distinct(CellAnnotation.text_cell_id)).label('cell_count')
    ).join(CellAnnotation, User.id == CellAnnotation.user_id)\
     .filter(CellAnnotation.id.in_(
         db.session.query(filtered_annotations.c.id)
     ))\
     .group_by(User.id)\
     .order_by(desc('annotation_count'))\
     .all()
    
    return jsonify({
        'labels': [stat.username for stat in annotator_stats],
        'annotations': [stat.annotation_count for stat in annotator_stats],
        'cells': [stat.cell_count for stat in annotator_stats]
    })

def _get_categories_distribution_data(file_id, question):
    """Ottieni dati per distribuzione categorie"""
    data = db.session.query(
        Category.name.label('category_name'),
        func.count(CellAnnotation.id).label('annotation_count'),
        func.count(distinct(Label.id)).label('unique_labels')
    ).join(Label, Label.category_id == Category.id)\
     .join(CellAnnotation, CellAnnotation.label_id == Label.id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(Category.id)\
     .order_by(desc('annotation_count'))\
     .all()
    
    # Aggiungi categoria "Senza categoria" se ci sono etichette senza categoria
    uncategorized = db.session.query(
        func.count(CellAnnotation.id).label('annotation_count'),
        func.count(distinct(Label.id)).label('unique_labels')
    ).join(Label, Label.id == CellAnnotation.label_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .filter(Label.category_id.is_(None))\
     .first()
    
    categories = [item.category_name for item in data]
    annotations = [item.annotation_count for item in data]
    labels_count = [item.unique_labels for item in data]
    
    if uncategorized and uncategorized.annotation_count > 0:
        categories.append('Senza categoria')
        annotations.append(uncategorized.annotation_count)
        labels_count.append(uncategorized.unique_labels)
    
    return jsonify({
        'categories': categories,
        'annotations': annotations,
        'labels_count': labels_count
    })

def _get_coverage_analysis_data(file_id, question):
    """Ottieni dati per analisi copertura"""
    # Totale celle nel quesito
    total_cells = TextCell.query.filter_by(
        excel_file_id=file_id, 
        column_name=question
    ).count()
    
    # Celle annotate
    annotated_cells = db.session.query(TextCell.id)\
        .filter(TextCell.excel_file_id == file_id)\
        .filter(TextCell.column_name == question)\
        .join(CellAnnotation)\
        .distinct().count()
    
    unannotated_cells = total_cells - annotated_cells
    coverage_percentage = (annotated_cells / total_cells * 100) if total_cells > 0 else 0
    
    # Distribuzione intensità (numero di annotazioni per cella)
    intensity_data = db.session.query(
        func.count(CellAnnotation.id).label('annotations_per_cell'),
        func.count(TextCell.id).label('cell_count')
    ).select_from(TextCell)\
     .outerjoin(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(TextCell.id)\
     .subquery()
    
    distribution = db.session.query(
        intensity_data.c.annotations_per_cell,
        func.count(intensity_data.c.cell_count).label('cells_with_this_intensity')
    ).group_by(intensity_data.c.annotations_per_cell)\
     .order_by(intensity_data.c.annotations_per_cell)\
     .all()
    
    distribution_labels = []
    distribution_values = []
    
    for item in distribution:
        ann_count = item.annotations_per_cell
        if ann_count == 0:
            distribution_labels.append('Non annotate')
        elif ann_count == 1:
            distribution_labels.append('1 annotazione')
        else:
            distribution_labels.append(f'{ann_count} annotazioni')
        distribution_values.append(item.cells_with_this_intensity)
    
    return jsonify({
        'total_cells': total_cells,
        'annotated_cells': annotated_cells,
        'unannotated_cells': unannotated_cells,
        'coverage_percentage': coverage_percentage,
        'distribution_labels': distribution_labels,
        'distribution_values': distribution_values
    })

@statistics_bp.route('/file/<int:file_id>')
@login_required
def file_detail(file_id):
    """Statistiche dettagliate per un file specifico"""
    file_obj = ExcelFile.query.get_or_404(file_id)
    
    # Statistiche generali del file
    total_cells = TextCell.query.filter_by(excel_file_id=file_id).count()
    annotated_cells = db.session.query(TextCell.id)\
        .filter(TextCell.excel_file_id == file_id)\
        .join(CellAnnotation)\
        .distinct().count()
    
    # Annotazioni per utente in questo file
    user_stats = db.session.query(
        User.username,
        User.id,
        func.count(CellAnnotation.id).label('annotation_count')
    ).join(CellAnnotation, User.id == CellAnnotation.user_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .group_by(User.id)\
     .order_by(desc('annotation_count'))\
     .all()
    
    # Etichette più utilizzate in questo file
    label_stats = db.session.query(
        Label.name,
        func.coalesce(Category.color, Label.color).label('color'),  # Usa il colore della categoria se esiste, altrimenti quello dell'etichetta
        Category.name.label('category_name'),
        func.count(CellAnnotation.id).label('usage_count')
    ).join(CellAnnotation)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .group_by(Label.id)\
     .order_by(desc('usage_count'))\
     .all()
    
    # Statistiche per quesito
    question_stats = db.session.query(
        TextCell.column_name,
        func.count(distinct(TextCell.id)).label('total_cells'),
        func.count(CellAnnotation.id).label('total_annotations'),
        func.count(distinct(CellAnnotation.user_id)).label('annotator_count')
    ).outerjoin(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .group_by(TextCell.column_name)\
     .order_by(TextCell.column_name)\
     .all()
    
    return render_template('statistics/file_detail.html',
                         file=file_obj,
                         total_cells=total_cells,
                         annotated_cells=annotated_cells,
                         user_stats=user_stats,
                         label_stats=label_stats,
                         question_stats=question_stats)

@statistics_bp.route('/question/<int:file_id>/<question>')
@login_required
def question_detail(file_id, question):
    """Statistiche dettagliate per un quesito specifico"""
    file_obj = ExcelFile.query.get_or_404(file_id)
    
    # Verifica che il quesito esista
    question_exists = TextCell.query.filter_by(
        excel_file_id=file_id, 
        column_name=question
    ).first()
    
    if not question_exists:
        flash('Quesito non trovato.', 'error')
        return redirect(url_for('statistics.file_detail', file_id=file_id))
    
    # Parametri per il filtraggio delle etichette
    category_filter = request.args.get('category')
    label_name_filter = request.args.get('label_name', '').strip()
    min_usage = request.args.get('min_usage', type=int)
    max_usage = request.args.get('max_usage', type=int)
    sort_by = request.args.get('sort_by', default='name')
    sort_order = request.args.get('sort_order', default='asc')
    
    # Celle del quesito
    cells = TextCell.query.filter_by(
        excel_file_id=file_id, 
        column_name=question
    ).all()
    
    # Statistiche annotatori per questo quesito
    annotator_stats = db.session.query(
        User.username,
        User.id,
        func.count(CellAnnotation.id).label('annotation_count'),
        func.count(distinct(CellAnnotation.text_cell_id)).label('cell_count')
    ).join(CellAnnotation, User.id == CellAnnotation.user_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(User.id)\
     .order_by(desc('annotation_count'))\
     .all()
    
    # Tutte le etichette utilizzate per questo quesito (con filtri)
    label_stats_query = db.session.query(
        Label.id,
        Label.name,
        Label.color,
        Category.name.label('category_name'),
        func.count(CellAnnotation.id).label('usage_count')
    ).join(CellAnnotation)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(Label.id)
    
    # Applica filtri se specificati
    if category_filter:
        label_stats_query = label_stats_query.filter(Category.name == category_filter)
    
    if label_name_filter:
        label_stats_query = label_stats_query.filter(Label.name.ilike(f'%{label_name_filter}%'))
    
    if min_usage is not None:
        label_stats_query = label_stats_query.having(func.count(CellAnnotation.id) >= min_usage)
    
    if max_usage is not None:
        label_stats_query = label_stats_query.having(func.count(CellAnnotation.id) <= max_usage)
    
    # Applica ordinamento
    if sort_by == 'category':
        if sort_order == 'desc':
            label_stats_query = label_stats_query.order_by(desc(Category.name))
        else:
            label_stats_query = label_stats_query.order_by(Category.name)
    elif sort_by == 'usage':
        if sort_order == 'desc':
            label_stats_query = label_stats_query.order_by(desc('usage_count'))
        else:
            label_stats_query = label_stats_query.order_by('usage_count')
    else:  # sort_by == 'name' (default)
        if sort_order == 'desc':
            label_stats_query = label_stats_query.order_by(desc(Label.name))
        else:
            label_stats_query = label_stats_query.order_by(Label.name)
    
    label_stats = label_stats_query.all()
    
    # Ottieni tutte le categorie disponibili per il dropdown dei filtri
    available_categories = db.session.query(Category.name)\
        .join(Label, Label.category_id == Category.id)\
        .join(CellAnnotation, CellAnnotation.label_id == Label.id)\
        .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
        .filter(TextCell.excel_file_id == file_id)\
        .filter(TextCell.column_name == question)\
        .distinct()\
        .order_by(Category.name)\
        .all()
    
    # Statistiche per i filtri (min/max utilizzi)
    # Prima otteniamo tutti i conteggi degli utilizzi
    usage_counts_subquery = db.session.query(
        func.count(CellAnnotation.id).label('usage_count')
    ).select_from(Label)\
     .join(CellAnnotation)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(Label.id)\
     .subquery()
    
    # Poi calcoliamo min e max da questi conteggi
    usage_stats = db.session.query(
        func.min(usage_counts_subquery.c.usage_count).label('min_usage'),
        func.max(usage_counts_subquery.c.usage_count).label('max_usage')
    ).first()
    
    # Valori di default per min/max se non ci sono dati
    min_usage_available = usage_stats.min_usage if usage_stats and usage_stats.min_usage else 1
    max_usage_available = usage_stats.max_usage if usage_stats and usage_stats.max_usage else 1
    
    # Raggruppamento etichetta + commento con ID
    cell_annotations = db.session.query(
        TextCell.id.label('cell_id'),
        TextCell.text_content.label('content'),
        CellAnnotation.id.label('annotation_id'),
        CellAnnotation.status,
        CellAnnotation.is_ai_generated,
        CellAnnotation.ai_confidence,
        Label.name.label('label_name'),
        Label.color.label('label_color'),
        Category.name.label('category_name'),
        User.username.label('annotator')
    ).join(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
     .join(Label, Label.id == CellAnnotation.label_id)\
     .join(User, User.id == CellAnnotation.user_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .order_by(TextCell.id, Label.name)\
     .all()
    
    # Raggruppa per cella
    cells_with_annotations = defaultdict(list)
    for ann in cell_annotations:
        cells_with_annotations[ann.cell_id].append(ann)
    
    # Report delle etichette con i commenti completi
    label_comments_report = db.session.query(
        Label.id,
        Label.name,
        Label.color,
        Category.name.label('category_name'),
        TextCell.id.label('cell_id'),
        TextCell.row_index.label('row_number'),
        TextCell.text_content.label('content'),
        CellAnnotation.id.label('annotation_id'),
        User.username.label('annotator'),
        CellAnnotation.is_ai_generated,
        CellAnnotation.ai_confidence,
        CellAnnotation.status
    ).join(CellAnnotation, Label.id == CellAnnotation.label_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .join(User, User.id == CellAnnotation.user_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .order_by(Label.name, TextCell.row_index)\
     .all()
    
    # Raggruppa per etichetta
    labels_with_comments = defaultdict(list)
    for item in label_comments_report:
        labels_with_comments[item.name].append(item)
    
    return render_template('statistics/question_detail.html',
                         file=file_obj,
                         question=question,
                         cells=cells,
                         annotator_stats=annotator_stats,
                         label_stats=label_stats,
                         cells_with_annotations=dict(cells_with_annotations),
                         labels_with_comments=dict(labels_with_comments),
                         # Dati per i filtri
                         available_categories=[cat.name for cat in available_categories],
                         min_usage_available=min_usage_available,
                         max_usage_available=max_usage_available,
                         # Valori correnti dei filtri
                         current_filters={
                             'category': category_filter,
                             'label_name': label_name_filter,
                             'min_usage': min_usage,
                             'max_usage': max_usage,
                             'sort_by': sort_by,
                             'sort_order': sort_order
                         })

@statistics_bp.route('/question/<int:file_id>/<question>/compare')
@login_required
def question_compare(file_id, question):
    """Confronto annotatori per un quesito specifico"""
    file_obj = ExcelFile.query.get_or_404(file_id)
    
    # Ottieni tutti gli annotatori che hanno lavorato su questo quesito
    annotators = db.session.query(User)\
        .join(CellAnnotation, User.id == CellAnnotation.user_id)\
        .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
        .filter(TextCell.excel_file_id == file_id)\
        .filter(TextCell.column_name == question)\
        .distinct()\
        .all()
    
    user1_id = request.args.get('user1_id', type=int)
    user2_id = request.args.get('user2_id', type=int)
    
    comparison_data = None
    user1 = None
    user2 = None
    
    if user1_id and user2_id and user1_id != user2_id:
        user1 = User.query.get(user1_id)
        user2 = User.query.get(user2_id)
        
        if user1 and user2:
            comparison_data = calculate_question_comparison(file_id, question, user1_id, user2_id)
    
    return render_template('statistics/question_compare.html',
                         file=file_obj,
                         question=question,
                         annotators=annotators,
                         user1=user1,
                         user2=user2,
                         comparison=comparison_data)

def calculate_question_comparison(file_id, question, user1_id, user2_id):
    """Calcola il confronto tra due annotatori per un quesito specifico"""
    # Annotazioni utente 1
    user1_annotations = db.session.query(
        CellAnnotation.text_cell_id,
        CellAnnotation.label_id,
        CellAnnotation.status,
        CellAnnotation.is_ai_generated,
        Label.name.label('label_name'),
        Label.color.label('label_color')
    ).join(Label, Label.id == CellAnnotation.label_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .filter(CellAnnotation.user_id == user1_id)\
     .all()
    
    # Annotazioni utente 2
    user2_annotations = db.session.query(
        CellAnnotation.text_cell_id,
        CellAnnotation.label_id,
        CellAnnotation.status,
        CellAnnotation.is_ai_generated,
        Label.name.label('label_name'),
        Label.color.label('label_color')
    ).join(Label, Label.id == CellAnnotation.label_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .filter(CellAnnotation.user_id == user2_id)\
     .all()
    
    # Raggruppa per cella
    user1_by_cell = defaultdict(list)
    user2_by_cell = defaultdict(list)
    
    for ann in user1_annotations:
        user1_by_cell[ann.text_cell_id].append(ann)
    
    for ann in user2_annotations:
        user2_by_cell[ann.text_cell_id].append(ann)
    
    # Calcola statistiche
    user1_cells = set(user1_by_cell.keys())
    user2_cells = set(user2_by_cell.keys())
    common_cells = user1_cells & user2_cells
    
    agreements = 0
    conflicts = []
    
    for cell_id in common_cells:
        user1_labels = set(ann.label_id for ann in user1_by_cell[cell_id])
        user2_labels = set(ann.label_id for ann in user2_by_cell[cell_id])
        
        if user1_labels == user2_labels:
            agreements += 1
        else:
            conflicts.append({
                'cell_id': cell_id,
                'user1_annotations': user1_by_cell[cell_id],
                'user2_annotations': user2_by_cell[cell_id]
            })
    
    agreement_percentage = (agreements / len(common_cells) * 100) if common_cells else 0
    
    return {
        'user1_total': len(user1_cells),
        'user2_total': len(user2_cells),
        'common_cells': len(common_cells),
        'agreements': agreements,
        'conflicts': conflicts,
        'agreement_percentage': agreement_percentage,
        'user1_annotations': user1_annotations,
        'user2_annotations': user2_annotations
    }

@statistics_bp.route('/export/question/<int:file_id>/<question>/<format>')
@login_required
def export_question_report(file_id, question, format):
    """Esporta report completo per un quesito specifico"""
    from flask import make_response
    import csv
    import io
    from datetime import datetime
    
    file_obj = ExcelFile.query.get_or_404(file_id)
    
    # Verifica che il quesito esista
    question_exists = TextCell.query.filter_by(
        excel_file_id=file_id, 
        column_name=question
    ).first()
    
    if not question_exists:
        flash('Quesito non trovato.', 'error')
        return redirect(url_for('statistics.file_detail', file_id=file_id))
    
    # Raccogli tutti i dati necessari per il report
    report_data = _collect_question_report_data(file_id, question, file_obj)
    
    if format == 'csv':
        return _export_question_csv(report_data)
    elif format == 'json':
        return _export_question_json(report_data)
    elif format == 'txt':
        return _export_question_txt(report_data)
    elif format == 'word':
        return _export_question_word_html(report_data)
    else:
        flash('Formato di esportazione non supportato.', 'error')
        return redirect(url_for('statistics.question_detail', file_id=file_id, question=question))

def _collect_question_report_data(file_id, question, file_obj):
    """Raccoglie tutti i dati necessari per il report del quesito"""
    
    # Statistiche generali
    cells = TextCell.query.filter_by(
        excel_file_id=file_id, 
        column_name=question
    ).all()
    
    # Statistiche annotatori
    annotator_stats = db.session.query(
        User.username,
        User.id,
        func.count(CellAnnotation.id).label('annotation_count'),
        func.count(distinct(CellAnnotation.text_cell_id)).label('cell_count')
    ).join(CellAnnotation, User.id == CellAnnotation.user_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(User.id)\
     .order_by(desc('annotation_count'))\
     .all()
    
    # Statistiche etichette
    label_stats = db.session.query(
        Label.name,
        Label.color,
        Category.name.label('category_name'),
        func.count(CellAnnotation.id).label('usage_count')
    ).join(CellAnnotation)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .group_by(Label.id)\
     .order_by(desc('usage_count'))\
     .all()
    
    # Report completo etichette con commenti
    label_comments_report = db.session.query(
        Label.id,
        Label.name,
        Label.color,
        Category.name.label('category_name'),
        TextCell.id.label('cell_id'),
        TextCell.row_index.label('row_number'),
        TextCell.text_content.label('content'),
        CellAnnotation.id.label('annotation_id'),
        User.username.label('annotator'),
        CellAnnotation.is_ai_generated,
        CellAnnotation.ai_confidence,
        CellAnnotation.status
    ).join(CellAnnotation, Label.id == CellAnnotation.label_id)\
     .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
     .join(User, User.id == CellAnnotation.user_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .order_by(Label.name, TextCell.row_index)\
     .all()
    
    # Raggruppa per etichetta
    labels_with_comments = defaultdict(list)
    for item in label_comments_report:
        labels_with_comments[item.name].append(item)
    
    # Annotazioni per cella
    cell_annotations = db.session.query(
        TextCell.id.label('cell_id'),
        TextCell.text_content.label('content'),
        CellAnnotation.id.label('annotation_id'),
        CellAnnotation.status,
        CellAnnotation.is_ai_generated,
        CellAnnotation.ai_confidence,
        Label.name.label('label_name'),
        Label.color.label('label_color'),
        Category.name.label('category_name'),
        User.username.label('annotator')
    ).join(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
     .join(Label, Label.id == CellAnnotation.label_id)\
     .join(User, User.id == CellAnnotation.user_id)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .filter(TextCell.excel_file_id == file_id)\
     .filter(TextCell.column_name == question)\
     .order_by(TextCell.id, Label.name)\
     .all()
    
    # Raggruppa per cella
    cells_with_annotations = defaultdict(list)
    for ann in cell_annotations:
        cells_with_annotations[ann.cell_id].append(ann)
    
    return {
        'file': file_obj,
        'question': question,
        'cells': cells,
        'annotator_stats': annotator_stats,
        'label_stats': label_stats,
        'labels_with_comments': dict(labels_with_comments),
        'cells_with_annotations': dict(cells_with_annotations),
        'export_timestamp': datetime.now()
    }

def _export_question_csv(report_data):
    """Esporta il report del quesito in formato CSV"""
    from flask import make_response
    import csv
    import io
    
    output = io.StringIO()
    
    # Header del report
    output.write(f"Report Completo - {report_data['question']}\n")
    output.write(f"File: {report_data['file'].filename}\n")
    output.write(f"Data: {report_data['export_timestamp'].strftime('%d/%m/%Y %H:%M:%S')}\n\n")
    
    # Statistiche generali
    output.write("STATISTICHE GENERALI\n")
    output.write("Tipo,Valore\n")
    output.write(f"Celle Totali,{len(report_data['cells'])}\n")
    output.write(f"Celle Annotate,{len(report_data['cells_with_annotations'])}\n")
    output.write(f"Annotatori,{len(report_data['annotator_stats'])}\n")
    output.write(f"Etichette,{len(report_data['label_stats'])}\n\n")
    
    # Annotatori
    output.write("ANNOTATORI\n")
    output.write("Username,Annotazioni,Celle\n")
    for user in report_data['annotator_stats']:
        output.write(f"{user.username},{user.annotation_count},{user.cell_count}\n")
    output.write("\n")
    
    # Etichette
    output.write("TUTTE LE ETICHETTE DEL QUESITO\n")
    output.write("Nome,Categoria,Utilizzi,Colore\n")
    for label in report_data['label_stats']:
        category = label.category_name or 'Senza categoria'
        output.write(f'"{label.name}","{category}",{label.usage_count},"{label.color}"\n')
    output.write("\n")
    
    # Report Etichette con Commenti
    output.write("REPORT COMPLETO - ETICHETTE CON TUTTI I COMMENTI\n")
    output.write("Etichetta,Categoria,Numero Rispondente,Contenuto Commento,AI Generated,AI Confidence,Annotatore,Annotation ID\n")
    for label_name, comments in report_data['labels_with_comments'].items():
        for comment in comments:
            ai_gen = 'Sì' if comment.is_ai_generated else 'No'
            ai_conf = f"{comment.ai_confidence:.2f}" if comment.ai_confidence else ''
            content = comment.content.replace('"', '""') if comment.content else ''
            category = comment.category_name or 'Senza categoria'
            output.write(f'"{label_name}","{category}","#{comment.row_number}","{content}","{ai_gen}","{ai_conf}","{comment.annotator}","{comment.annotation_id}"\n')
    output.write("\n")
    
    # Annotazioni per Cella
    output.write("ANNOTAZIONI PER CELLA\n")
    output.write("ID Cella,Contenuto,Etichetta,Categoria,Annotatore,AI Generated,AI Confidence,Status,Annotation ID\n")
    for cell_id, annotations in report_data['cells_with_annotations'].items():
        cell_content = annotations[0].content.replace('"', '""') if annotations[0].content else ''
        for ann in annotations:
            ai_gen = 'Sì' if ann.is_ai_generated else 'No'
            ai_conf = f"{ann.ai_confidence:.2f}" if ann.ai_confidence else ''
            category = ann.category_name or 'Senza categoria'
            output.write(f'"{cell_id}","{cell_content}","{ann.label_name}","{category}","{ann.annotator}","{ai_gen}","{ai_conf}","{ann.status}","{ann.annotation_id}"\n')
    
    # Prepara la risposta
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    
    # Nome file sicuro
    safe_question = "".join(c for c in report_data['question'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_filename = "".join(c for c in report_data['file'].filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    timestamp = report_data['export_timestamp'].strftime('%Y%m%d_%H%M%S')
    filename = f"report_completo_{safe_question}_{safe_filename}_{timestamp}.csv"
    
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response

def _export_question_json(report_data):
    """Esporta il report del quesito in formato JSON"""
    import json
    from flask import make_response
    
    # Converte i dati in formato JSON-serializable
    json_data = {
        'file': {
            'id': report_data['file'].id,
            'filename': report_data['file'].filename
        },
        'question': report_data['question'],
        'export_timestamp': report_data['export_timestamp'].isoformat(),
        'statistics': {
            'total_cells': len(report_data['cells']),
            'annotated_cells': len(report_data['cells_with_annotations']),
            'total_annotators': len(report_data['annotator_stats']),
            'total_labels': len(report_data['label_stats'])
        },
        'annotators': [
            {
                'username': user.username,
                'annotation_count': user.annotation_count,
                'cell_count': user.cell_count
            }
            for user in report_data['annotator_stats']
        ],
        'labels': [
            {
                'name': label.name,
                'category': label.category_name or 'Senza categoria',
                'usage_count': label.usage_count,
                'color': label.color
            }
            for label in report_data['label_stats']
        ],
        'labels_with_comments': {
            label_name: [
                {
                    'row_number': comment.row_number,
                    'content': comment.content,
                    'is_ai_generated': comment.is_ai_generated,
                    'ai_confidence': comment.ai_confidence,
                    'annotator': comment.annotator,
                    'category_name': comment.category_name,
                    'annotation_id': comment.annotation_id,
                    'status': comment.status
                }
                for comment in comments
            ]
            for label_name, comments in report_data['labels_with_comments'].items()
        },
        'cells_with_annotations': {
            str(cell_id): {
                'content': annotations[0].content if annotations else '',
                'annotations': [
                    {
                        'annotation_id': ann.annotation_id,
                        'label_name': ann.label_name,
                        'label_color': ann.label_color,
                        'category_name': ann.category_name,
                        'annotator': ann.annotator,
                        'is_ai_generated': ann.is_ai_generated,
                        'ai_confidence': ann.ai_confidence,
                        'status': ann.status
                    }
                    for ann in annotations
                ]
            }
            for cell_id, annotations in report_data['cells_with_annotations'].items()
        }
    }
    
    # Crea la risposta JSON
    json_str = json.dumps(json_data, indent=2, ensure_ascii=False)
    response = make_response(json_str)
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    
    # Nome file sicuro
    safe_question = "".join(c for c in report_data['question'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_filename = "".join(c for c in report_data['file'].filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    timestamp = report_data['export_timestamp'].strftime('%Y%m%d_%H%M%S')
    filename = f"report_completo_{safe_question}_{safe_filename}_{timestamp}.json"
    
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response

def _export_question_txt(report_data):
    """Esporta il report del quesito in formato TXT"""
    from flask import make_response
    
    # Crea il contenuto testuale
    content = []
    content.append(f"REPORT COMPLETO - {report_data['question']}")
    content.append("=" * 80)
    content.append("")
    content.append(f"File: {report_data['file'].filename}")
    content.append(f"Data: {report_data['export_timestamp'].strftime('%d/%m/%Y %H:%M:%S')}")
    content.append("")
    
    # Statistiche generali
    content.append("STATISTICHE GENERALI")
    content.append("-" * 20)
    content.append(f"Celle Totali: {len(report_data['cells'])}")
    content.append(f"Celle Annotate: {len(report_data['cells_with_annotations'])}")
    content.append(f"Annotatori: {len(report_data['annotator_stats'])}")
    content.append(f"Etichette: {len(report_data['label_stats'])}")
    content.append("")
    
    # Annotatori
    content.append("ANNOTATORI")
    content.append("-" * 10)
    for user in report_data['annotator_stats']:
        content.append(f"{user.username}: {user.annotation_count} annotazioni, {user.cell_count} celle")
    content.append("")
    
    # Etichette
    content.append("TUTTE LE ETICHETTE DEL QUESITO")
    content.append("-" * 32)
    for label in report_data['label_stats']:
        category = label.category_name or 'Senza categoria'
        content.append(f"{label.name} ({category}): {label.usage_count} utilizzi")
    content.append("")
    
    # Report Etichette con Commenti
    content.append("REPORT COMPLETO - ETICHETTE CON TUTTI I COMMENTI")
    content.append("-" * 48)
    for label_name, comments in report_data['labels_with_comments'].items():
        content.append("")
        content.append(f"{label_name.upper()} ({len(comments)} commenti):")
        content.append("-" * (len(label_name) + 15))
        for comment in comments:
            ai_info = ""
            if comment.is_ai_generated:
                ai_info = " [🤖 AI"
                if comment.ai_confidence:
                    ai_info += f" {comment.ai_confidence:.0%}"
                ai_info += "]"
            
            annotator_info = f" - {comment.annotator}" if comment.annotator else ""
            content.append(f"#{comment.row_number}: {comment.content}{ai_info}{annotator_info}")
    content.append("")
    
    # Annotazioni per Cella
    content.append("ANNOTAZIONI PER CELLA")
    content.append("-" * 20)
    for cell_id, annotations in report_data['cells_with_annotations'].items():
        content.append("")
        content.append(f"Cella {cell_id}:")
        content.append(f"Contenuto: {annotations[0].content if annotations else 'N/A'}")
        content.append("Annotazioni:")
        for ann in annotations:
            ai_info = ""
            if ann.is_ai_generated:
                ai_info = " [🤖 AI"
                if ann.ai_confidence:
                    ai_info += f" {ann.ai_confidence:.0%}"
                ai_info += "]"
            
            status_info = f" [Status: {ann.status}]" if ann.status != 'active' else ""
            content.append(f"  - {ann.label_name} (ID: {ann.annotation_id}) - {ann.annotator}{ai_info}{status_info}")
    
    # Unisce tutto il contenuto
    text_content = "\n".join(content)
    
    # Crea la risposta
    response = make_response(text_content)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    
    # Nome file sicuro
    safe_question = "".join(c for c in report_data['question'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_filename = "".join(c for c in report_data['file'].filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    timestamp = report_data['export_timestamp'].strftime('%Y%m%d_%H%M%S')
    filename = f"report_completo_{safe_question}_{safe_filename}_{timestamp}.txt"
    
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response

def _export_question_word_html(report_data):
    """Esporta il report del quesito in formato HTML compatibile con Word"""
    from flask import make_response
    
    # Crea il contenuto HTML compatibile con Word
    html_content = f"""<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head>
    <meta charset="utf-8">
    <meta name="ProgId" content="Word.Document">
    <title>Report Completo - {report_data['question']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 15mm; font-size: 11pt; line-height: 1.3; }}
        h1, h2 {{ color: #2c3e50; }}
        h1 {{ font-size: 16pt; margin-bottom: 10pt; text-align: center; }}
        h2 {{ font-size: 13pt; margin-bottom: 8pt; margin-top: 15pt; border-bottom: 1pt solid #ccc; }}
        h3 {{ font-size: 11pt; margin-bottom: 5pt; margin-top: 10pt; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12pt 0; font-size: 10pt; }}
        th, td {{ border: 1pt solid #ddd; padding: 4pt; text-align: left; vertical-align: top; }}
        th {{ background-color: #f2f2f2; font-weight: bold; }}
        .stats-box {{ background-color: #f8f9fa; padding: 10pt; margin: 8pt 0; border: 1pt solid #ddd; }}
        .badge {{ color: white; padding: 2pt 6pt; border-radius: 3pt; font-size: 9pt; font-weight: bold; display: inline-block; margin: 1pt; }}
        .ai-badge {{ background-color: #17a2b8; }}
        .cell-content {{ max-width: 200pt; word-wrap: break-word; font-size: 9pt; }}
    </style>
</head>
<body>
    <h1>Report Completo - {report_data['question']}</h1>
    
    <div class="stats-box">
        <p><strong>File:</strong> {report_data['file'].filename}</p>
        <p><strong>Data Report:</strong> {report_data['export_timestamp'].strftime('%d/%m/%Y %H:%M:%S')}</p>
    </div>
    
    <h2>Statistiche Generali</h2>
    <div class="stats-box">
        <p><strong>Celle Totali:</strong> {len(report_data['cells'])}</p>
        <p><strong>Celle Annotate:</strong> {len(report_data['cells_with_annotations'])}</p>
        <p><strong>Annotatori:</strong> {len(report_data['annotator_stats'])}</p>
        <p><strong>Etichette Utilizzate:</strong> {len(report_data['label_stats'])}</p>
    </div>
    
    <h2>Annotatori</h2>
    <table>
        <tr><th>Username</th><th>Totale Annotazioni</th><th>Celle Annotate</th></tr>"""
    
    for user in report_data['annotator_stats']:
        html_content += f"""
        <tr>
            <td>{user.username}</td>
            <td>{user.annotation_count}</td>
            <td>{user.cell_count}</td>
        </tr>"""
    
    html_content += """
    </table>
    
    <h2>Tutte le Etichette del Quesito</h2>
    <table>
        <tr><th>Etichetta</th><th>Categoria</th><th>Utilizzi</th></tr>"""
    
    for label in report_data['label_stats']:
        category = label.category_name or 'Senza categoria'
        color = label.color or '#007bff'
        html_content += f"""
        <tr>
            <td><span class="badge" style="background-color: {color}">{label.name}</span></td>
            <td>{category}</td>
            <td>{label.usage_count}</td>
        </tr>"""
    
    html_content += """
    </table>
    
    <h2>Report Completo - Etichette con Tutti i Commenti</h2>"""
    
    for label_name, comments in report_data['labels_with_comments'].items():
        if comments:
            label_color = comments[0].color or '#007bff'
            category = comments[0].category_name or 'Senza categoria'
            html_content += f"""
    <h3><span class="badge" style="background-color: {label_color}">{label_name}</span> ({len(comments)} commenti)</h3>
    <table>
        <tr><th>Numero</th><th>Contenuto</th><th>Info</th></tr>"""
            
            for comment in comments:
                ai_info = ""
                if comment.is_ai_generated:
                    ai_info += '<span class="ai-badge">🤖 AI</span>'
                    if comment.ai_confidence:
                        ai_info += f' <small>({comment.ai_confidence:.0%})</small>'
                
                annotator_info = f'<small>{comment.annotator}</small>' if comment.annotator else ''
                
                content = (comment.content or '').replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                
                html_content += f"""
        <tr>
            <td><strong>#{comment.row_number}</strong></td>
            <td class="cell-content">{content}</td>
            <td>{ai_info}<br>{annotator_info}</td>
        </tr>"""
            
            html_content += """
    </table>"""
    
    html_content += """
    
    <h2>Annotazioni per Cella</h2>
    <table>
        <tr><th>ID Cella</th><th>Contenuto</th><th>Etichette</th><th>Annotatori</th></tr>"""
    
    for cell_id, annotations in report_data['cells_with_annotations'].items():
        if annotations:
            content = (annotations[0].content or '').replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
            
            etichette_html = ""
            annotatori_html = ""
            
            for ann in annotations:
                etichette_html += f"""<div><span class="badge" style="background-color: {ann.label_color}">{ann.label_name}</span> <small>(ID: {ann.annotation_id})</small>"""
                
                if ann.is_ai_generated:
                    etichette_html += ' <span class="ai-badge">🤖 AI</span>'
                    if ann.ai_confidence:
                        etichette_html += f' <small>({ann.ai_confidence:.0%})</small>'
                
                etichette_html += "</div>"
                annotatori_html += f'<div>{ann.annotator}</div>'
            
            html_content += f"""
        <tr>
            <td>{cell_id}</td>
            <td class="cell-content">{content}</td>
            <td>{etichette_html}</td>
            <td>{annotatori_html}</td>
        </tr>"""
    
    html_content += """
    </table>
    
    <div style="margin-top: 20pt; text-align: center; font-size: 9pt; color: #666;">
        <p>--- Fine del Report ---</p>
    </div>
</body>
</html>"""
    
    # Crea la risposta con content-type per Word
    response = make_response(html_content)
    response.headers['Content-Type'] = 'application/msword; charset=utf-8'
    
    # Nome file sicuro
    safe_question = "".join(c for c in report_data['question'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_filename = "".join(c for c in report_data['file'].filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    timestamp = report_data['export_timestamp'].strftime('%Y%m%d_%H%M%S')
    filename = f"report_completo_{safe_question}_{safe_filename}_{timestamp}.doc"
    
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response
