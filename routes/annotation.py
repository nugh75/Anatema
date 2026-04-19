"""
Routes per l'annotazione delle celle
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
import plotly.graph_objs as go
import plotly.utils
import json
import os
import logging
from collections import defaultdict

from models import TextCell, Label, CellAnnotation, ExcelFile, User, AnnotationAction, Category, db
from sqlalchemy import func

annotation_bp = Blueprint('annotation', __name__)

@annotation_bp.route('/cell/<int:cell_id>', methods=['GET', 'POST'])
@login_required
def annotate_cell(cell_id):
    """Pagina di annotazione per una singola cella"""
    cell = TextCell.query.get_or_404(cell_id)
    
    # Verifica se la cella è di un tipo non annotabile
    if hasattr(cell, 'question_type') and cell.question_type in ['anagrafica', 'chiusa_binaria', 'chiusa_multipla', 'likert', 'numerica']:
        flash(f'Questa cella contiene una domanda di tipo "{cell.question_type}" e non necessita di annotazione.', 'info')
        return redirect(url_for('annotation.browse_annotations'))
    
    # Ottieni tutte le etichette disponibili
    # Ordiniamo prima per categoria (trattando None come stringa vuota) poi per nome
    labels = Label.query.all()
    labels.sort(key=lambda x: (x.category or '', x.name))
    
    # Ottieni tutte le categorie disponibili
    from models import Category
    categories = Category.query.order_by(Category.name).all()
    
    # Ottieni le annotazioni esistenti per questa cella
    annotations = db.session.query(CellAnnotation)\
        .join(Label, CellAnnotation.label_id == Label.id)\
        .join(User, CellAnnotation.user_id == User.id)\
        .filter(CellAnnotation.text_cell_id == cell_id)\
        .order_by(CellAnnotation.created_at.desc())\
        .all()
    
    # Converti in una struttura che includa label e user
    annotation_data = []
    for annotation in annotations:
        annotation_data.append({
            'annotation': annotation,
            'label': annotation.label,
            'user': annotation.user
        })
    
    # Annotazioni dell'utente corrente
    user_annotations = CellAnnotation.query.filter_by(
        text_cell_id=cell_id,
        user_id=current_user.id
    ).all()
    
    user_label_ids = [ann.label_id for ann in user_annotations]
    
    next_url = request.args.get('next') or request.form.get('next')
    
    # === NUOVA LOGICA DI NAVIGAZIONE ===
    # Calcola la navigazione per la stessa domanda mantenendo i filtri
    navigation_context = get_navigation_context(cell, request.args)

    # Gestione richiesta AJAX per aggiornare lo storico
    ajax = request.args.get('ajax', type=int)
    if ajax == 1:
        return jsonify({
            'annotations': [
                {
                    'annotation': {
                        'id': item['annotation'].id,
                        'created_at': item['annotation'].created_at.isoformat(),
                        'user_id': item['annotation'].user_id
                    },
                    'label': {
                        'name': item['label'].name,
                        'color': item['label'].color,
                        'category': item['label'].category
                    },
                    'user': {
                        'username': item['user'].username
                    }
                } for item in annotation_data
            ],
            'user_label_ids': list(user_label_ids)
        })

    if request.method == 'POST':
        # Esempio: gestione di una form classica (aggiungi qui la logica di salvataggio se serve)
        # ...
        flash('Annotazione salvata!', 'success')
        return redirect(next_url or url_for('annotation.browse_annotations'))

    return render_template('annotation/annotate_cell.html',
                         cell=cell,
                         labels=labels,
                         categories=categories,
                         annotations=annotation_data,
                         user_label_ids=list(user_label_ids),
                         next_url=next_url,
                         navigation=navigation_context)


def get_navigation_context(current_cell, request_args):
    """Calcola il contesto di navigazione per celle della stessa domanda"""
    
    # Costruisci query per celle della stessa domanda
    query = TextCell.query.filter_by(column_name=current_cell.column_name)
    
    # Applica gli stessi filtri della pagina browse_annotations
    file_id = request_args.get('file_id', type=int)
    sheet_name = request_args.get('sheet', '')
    question_type_filter = request_args.get('question_type', '')
    annotated_only = request_args.get('annotated_only', '')
    
    # Mantieni i filtri originali
    filter_params = {}
    if file_id:
        query = query.filter_by(excel_file_id=file_id)
        filter_params['file_id'] = file_id
    if sheet_name:
        query = query.filter_by(sheet_name=sheet_name)
        filter_params['sheet'] = sheet_name
    if question_type_filter:
        if question_type_filter == 'all':
            pass  # Mostra tutti i tipi
        elif question_type_filter:
            query = query.filter_by(question_type=question_type_filter)
            filter_params['question_type'] = question_type_filter
    else:
        # Default: solo celle annotabili
        query = query.filter(
            db.or_(
                TextCell.question_type == 'aperta',
                TextCell.question_type.is_(None)
            )
        )
    
    if annotated_only == '1':
        query = query.join(CellAnnotation).distinct()
        filter_params['annotated_only'] = '1'
    elif annotated_only == '0':
        query = query.outerjoin(CellAnnotation).filter(CellAnnotation.id.is_(None))
        filter_params['annotated_only'] = '0'
    
    # Ordina per navigazione sequenziale
    cells = query.order_by(TextCell.excel_file_id, TextCell.sheet_name, 
                          TextCell.row_index, TextCell.column_index).all()
    
    # Trova posizione corrente
    current_index = -1
    for i, cell in enumerate(cells):
        if cell.id == current_cell.id:
            current_index = i
            break
    
    # Calcola celle precedente e successiva
    prev_cell = cells[current_index - 1] if current_index > 0 else None
    next_cell = cells[current_index + 1] if current_index < len(cells) - 1 else None
    
    # Costruisci URL di navigazione mantenendo i filtri
    base_filter_params = dict(filter_params)
    if request_args.get('next'):
        base_filter_params['next'] = request_args.get('next')
    
    prev_url = None
    if prev_cell:
        prev_url = url_for('annotation.annotate_cell', cell_id=prev_cell.id, **base_filter_params)
    
    next_url = None
    if next_cell:
        next_url = url_for('annotation.annotate_cell', cell_id=next_cell.id, **base_filter_params)
    
    # URL di ritorno alla lista
    back_url = url_for('annotation.browse_annotations', **filter_params)
    
    return {
        'current_index': current_index,
        'total_cells': len(cells),
        'prev_cell': prev_cell,
        'next_cell': next_cell,
        'prev_url': prev_url,
        'next_url': next_url,
        'back_url': back_url,
        'question_text': current_cell.column_name,
        'active_filters': filter_params
    }

@annotation_bp.route('/api/add_annotation', methods=['POST'])
@login_required
def api_add_annotation():
    """API per aggiungere un'annotazione"""
    import logging
    logger = logging.getLogger(__name__)
    
    data = request.get_json()
    
    cell_id = data.get('cell_id') if data else None
    label_id = data.get('label_id') if data else None
    
    logger.info(f"ADD_ANNOTATION: User {current_user.id} ({current_user.username}) trying to add label {label_id} to cell {cell_id}")
    
    if not cell_id or not label_id:
        logger.error(f"ADD_ANNOTATION: Missing parameters - cell_id: {cell_id}, label_id: {label_id}")
        return jsonify({'success': False, 'message': 'Parametri mancanti'}), 400
    
    # Verifica che la cella e l'etichetta esistano
    cell = TextCell.query.get(cell_id)
    label = Label.query.get(label_id)
    
    if not cell or not label:
        logger.error(f"ADD_ANNOTATION: Cell {cell_id} or Label {label_id} not found - cell: {cell}, label: {label}")
        return jsonify({'success': False, 'message': 'Cella o etichetta non trovata'}), 404
    
    logger.info(f"ADD_ANNOTATION: Found cell '{cell.text_content[:50]}...' and label '{label.name}'")
    
    try:
        # Permettiamo annotazioni multiple della stessa etichetta da parte dello stesso utente
        # Questo consente maggiore flessibilità nella gestione delle annotazioni
        
        # Crea l'annotazione
        annotation = CellAnnotation(
            text_cell_id=cell_id,
            label_id=label_id,
            user_id=current_user.id
        )
        
        db.session.add(annotation)
        db.session.flush()  # Per ottenere l'ID dell'annotazione
        
        logger.info(f"ADD_ANNOTATION: Created new annotation with ID {annotation.id}")
        
        # Traccia l'azione
        action = AnnotationAction(
            text_cell_id=cell_id,
            label_id=label_id,
            action_type='added',
            performed_by=current_user.id,
            target_user_id=current_user.id,
            annotation_id=annotation.id,
            notes=f"Aggiunta etichetta '{label.name}' dall'utente {current_user.username}"
        )
        db.session.add(action)
        
        db.session.commit()
        
        logger.info(f"ADD_ANNOTATION: Successfully added annotation {annotation.id} and logged action {action.id}")
        
        return jsonify({
            'success': True,
            'message': 'Annotazione aggiunta con successo',
            'annotation_id': annotation.id
        })
        
    except IntegrityError as e:
        db.session.rollback()
        logger.error(f"ADD_ANNOTATION: IntegrityError - {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Hai già assegnato questa etichetta a questa cella'
        }), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"ADD_ANNOTATION: Unexpected error - {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Errore del server: {str(e)}'
        }), 500

@annotation_bp.route('/api/remove_annotation', methods=['POST'])
@login_required
def api_remove_annotation():
    """API per rimuovere un'annotazione"""
    import logging
    logger = logging.getLogger(__name__)
    
    data = request.get_json()
    
    cell_id = data.get('cell_id')
    label_id = data.get('label_id')
    
    logger.info(f"REMOVE_ANNOTATION: User {current_user.id} ({current_user.username}) trying to remove label {label_id} from cell {cell_id}")
    
    if not cell_id or not label_id:
        logger.error(f"REMOVE_ANNOTATION: Missing parameters - cell_id: {cell_id}, label_id: {label_id}")
        return jsonify({'success': False, 'message': 'Parametri mancanti'}), 400
    
    # Verifica che la cella e l'etichetta esistano
    cell = TextCell.query.get(cell_id)
    label = Label.query.get(label_id)
    
    if not cell or not label:
        logger.error(f"REMOVE_ANNOTATION: Cell {cell_id} or Label {label_id} not found - cell: {cell}, label: {label}")
        return jsonify({'success': False, 'message': 'Cella o etichetta non trovata'}), 404
    
    logger.info(f"REMOVE_ANNOTATION: Found cell '{cell.text_content[:50]}...' and label '{label.name}'")
    
    # Trova TUTTE le annotazioni per questa cella/label (non solo dell'utente corrente)
    annotations = CellAnnotation.query.filter_by(
        text_cell_id=cell_id,
        label_id=label_id
    ).all()
    
    if not annotations:
        logger.warning(f"REMOVE_ANNOTATION: No annotations found for cell {cell_id} and label {label_id}")
        return jsonify({
            'success': False,
            'message': 'Nessuna annotazione trovata per questa etichetta'
        }), 404
    
    logger.info(f"REMOVE_ANNOTATION: Found {len(annotations)} annotations to remove")
    
    try:
        removed_count = 0
        # Rimuovi tutte le annotazioni per questa cella/label e traccia le azioni
        for annotation in annotations:
            logger.info(f"REMOVE_ANNOTATION: Removing annotation {annotation.id} (user: {annotation.user_id}, ai_generated: {annotation.is_ai_generated})")
            
            # Crea un record dell'azione prima di eliminare l'annotazione
            action = AnnotationAction(
                text_cell_id=cell_id,
                label_id=label_id,
                action_type='removed',
                performed_by=current_user.id,
                target_user_id=annotation.user_id,
                annotation_id=annotation.id,
                was_ai_generated=annotation.is_ai_generated,
                ai_confidence=annotation.ai_confidence,
                ai_model=annotation.ai_model,
                ai_provider=annotation.ai_provider,
                notes=f'Rimossa annotazione di {annotation.user.username}' if annotation.user_id != current_user.id else 'Rimossa propria annotazione'
            )
            db.session.add(action)
            db.session.delete(annotation)
            db.session.flush()  # Sincronizza le modifiche prima di continuare
            removed_count += 1
            
            logger.info(f"REMOVE_ANNOTATION: Removed annotation {annotation.id} and logged action {action.id}")
        
        db.session.commit()
        
        logger.info(f"REMOVE_ANNOTATION: Successfully removed {removed_count} annotations")
        
        message = f'Rimosse {removed_count} annotazione/i con successo'
        
        return jsonify({
            'success': True,
            'message': message,
            'removed_count': removed_count
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"REMOVE_ANNOTATION: Unexpected error - {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Errore del server: {str(e)}'
        }), 500

@annotation_bp.route('/api/remove_annotation_by_id', methods=['POST'])
@login_required
def api_remove_annotation_by_id():
    """API per rimuovere un'annotazione specifica tramite ID"""
    logger = logging.getLogger(__name__)
    data = request.get_json()
    
    annotation_id = data.get('annotation_id')
    
    logger.info(f"REMOVE_ANNOTATION_BY_ID: User {current_user.id} ({current_user.username}) trying to remove annotation {annotation_id}")
    
    if not annotation_id:
        logger.error(f"REMOVE_ANNOTATION_BY_ID: Missing annotation_id")
        return jsonify({'success': False, 'message': 'ID annotazione mancante'}), 400
    
    try:
        # Trova l'annotazione
        annotation = CellAnnotation.query.get(annotation_id)
        
        if not annotation:
            logger.error(f"REMOVE_ANNOTATION_BY_ID: Annotation {annotation_id} not found")
            return jsonify({'success': False, 'message': 'Annotazione non trovata'}), 404
        
        logger.info(f"REMOVE_ANNOTATION_BY_ID: Found annotation {annotation_id} - Cell: {annotation.text_cell_id}, Label: {annotation.label_id}, User: {annotation.user_id}")
        
        # Traccia l'azione di rimozione
        action = AnnotationAction(
            text_cell_id=annotation.text_cell_id,
            label_id=annotation.label_id,
            action_type='removed',
            performed_by=current_user.id,
            target_user_id=annotation.user_id,
            annotation_id=annotation_id,
            was_ai_generated=annotation.is_ai_generated,
            ai_confidence=annotation.ai_confidence,
            ai_model=annotation.ai_model,
            ai_provider=annotation.ai_provider,
            notes=f"Rimossa annotazione di {annotation.user.username}"
        )
        
        db.session.add(action)
        logger.info(f"REMOVE_ANNOTATION_BY_ID: AnnotationAction created for removal")
        
        # Rimuovi l'annotazione
        db.session.delete(annotation)
        db.session.flush()
        logger.info(f"REMOVE_ANNOTATION_BY_ID: Annotation {annotation_id} deleted")
        
        db.session.commit()
        logger.info(f"REMOVE_ANNOTATION_BY_ID: Successfully removed annotation {annotation_id}")
        
        return jsonify({
            'success': True,
            'message': 'Annotazione rimossa con successo'
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"REMOVE_ANNOTATION_BY_ID: Error removing annotation {annotation_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Errore del server: {str(e)}'
        }), 500

@annotation_bp.route('/browse')
@login_required
def browse_annotations():
    """Naviga tra le celle per l'annotazione"""
    page = request.args.get('page', 1, type=int)
    file_id = request.args.get('file_id', type=int)
    sheet_name = request.args.get('sheet', '')
    annotated_only = request.args.get('annotated_only', '')
    view_mode = request.args.get('view_mode', 'classic')
    selected_question = request.args.get('question', '')
    question_type_filter = request.args.get('question_type', '')  # Nuovo filtro per tipo domanda
    ajax = request.args.get('ajax', '')
    
    # Se è una richiesta AJAX, restituisci solo i dati dei filtri
    if ajax == '1' and file_id:
        # Per i fogli, considera solo celle annotabili o non classificate se non c'è filtro specifico
        sheets_query = db.session.query(TextCell.sheet_name)\
                                .filter_by(excel_file_id=file_id)
        
        if not question_type_filter:
            sheets_query = sheets_query.filter(db.or_(
                TextCell.question_type == 'aperta',
                TextCell.question_type.is_(None)
            ))
        elif question_type_filter != 'all':
            sheets_query = sheets_query.filter_by(question_type=question_type_filter)
            
        sheets = sheets_query.distinct().all()
        sheet_names = [sheet[0] for sheet in sheets]
        
        # Per le domande, applica lo stesso filtro
        questions_query = db.session.query(TextCell.column_name)\
                                   .filter_by(excel_file_id=file_id)
        
        if not question_type_filter:
            questions_query = questions_query.filter(db.or_(
                TextCell.question_type == 'aperta',
                TextCell.question_type.is_(None)
            ))
        elif question_type_filter != 'all':
            questions_query = questions_query.filter_by(question_type=question_type_filter)
            
        questions = questions_query.distinct()\
                                 .order_by(TextCell.column_name)\
                                 .all()
        question_names = [q[0] for q in questions if q[0]]
        
        return jsonify({
            'sheets': sheet_names,
            'questions': question_names
        })
    
    query = TextCell.query
    
    # FILTRO PER TIPO DOMANDA
    if question_type_filter == 'all':
        # Mostra tutti i tipi di domanda
        pass
    elif question_type_filter:
        # Filtra per tipo specifico
        query = query.filter_by(question_type=question_type_filter)
    else:
        # Default: solo celle annotabili (domande aperte e non classificate)
        query = query.filter(
            db.or_(
                TextCell.question_type == 'aperta',
                TextCell.question_type.is_(None)  # Include celle non ancora classificate
            )
        )
    
    if file_id:
        query = query.filter_by(excel_file_id=file_id)
    
    if sheet_name:
        query = query.filter_by(sheet_name=sheet_name)
        
    if selected_question:
        query = query.filter_by(column_name=selected_question)
    
    if annotated_only == '1':
        # Solo celle che hanno almeno un'annotazione
        query = query.join(CellAnnotation).distinct()
    elif annotated_only == '0':
        # Solo celle non annotate
        query = query.outerjoin(CellAnnotation).filter(CellAnnotation.id.is_(None))
    
    cells = query.order_by(TextCell.excel_file_id, TextCell.sheet_name, 
                          TextCell.row_index, TextCell.column_index)\
                 .paginate(page=page, per_page=20, error_out=False)
    
    # Per i filtri
    files = ExcelFile.query.order_by(ExcelFile.original_filename).all()
    
    # Ottieni tutti i fogli disponibili
    if file_id:
        # Se è selezionato un file, mostra solo i fogli di quel file
        sheets = db.session.query(TextCell.sheet_name)\
                          .filter_by(excel_file_id=file_id)\
                          .distinct().all()
        sheet_names = [sheet[0] for sheet in sheets]
        
        # Ottieni tutte le domande/colonne per il file selezionato
        questions = db.session.query(TextCell.column_name)\
                             .filter_by(excel_file_id=file_id)\
                             .distinct()\
                             .order_by(TextCell.column_name)\
                             .all()
        question_names = [q[0] for q in questions if q[0]]
    else:
        # Se non è selezionato nessun file, mostra tutti i fogli di tutti i file
        sheets = db.session.query(TextCell.sheet_name)\
                          .distinct().all()
        sheet_names = [sheet[0] for sheet in sheets]
        
        # Ottieni tutte le domande/colonne di tutti i file
        questions = db.session.query(TextCell.column_name)\
                             .distinct()\
                             .order_by(TextCell.column_name)\
                             .all()
        question_names = [q[0] for q in questions if q[0]]
    
    # Per la Vista per Domanda, calcola le statistiche per domanda
    questions_stats = []
    if view_mode == 'per_domanda':
        # Ottieni statistiche per ogni domanda come in questions_overview
        base_query = db.session.query(
            TextCell.column_name,
            db.func.count(TextCell.id).label('total_responses'),
            db.func.count(CellAnnotation.id).label('annotated_responses')
        ).outerjoin(CellAnnotation)
        
        # Applica filtro per file se selezionato
        if file_id:
            base_query = base_query.filter(TextCell.excel_file_id == file_id)
        
        # Applica filtro per domanda specifica se selezionata
        if selected_question:
            base_query = base_query.filter(TextCell.column_name == selected_question)
        
        # Applica filtro per foglio se selezionato
        if sheet_name:
            base_query = base_query.filter(TextCell.sheet_name == sheet_name)
        
        questions_stats = base_query.group_by(TextCell.column_name)\
                                   .order_by(TextCell.column_name)\
                                   .all()
    
    # Ottieni tutti i tipi di domanda disponibili per il filtro
    available_question_types = db.session.query(TextCell.question_type)\
                                        .filter(TextCell.question_type.isnot(None))\
                                        .distinct()\
                                        .order_by(TextCell.question_type)\
                                        .all()
    question_types = [qt[0] for qt in available_question_types]
    
    return render_template('annotation/browse_annotations.html',
                         cells=cells,
                         files=files,
                         sheet_names=sheet_names,
                         question_names=question_names,
                         question_types=question_types,
                         current_file_id=file_id,
                         current_sheet=sheet_name,
                         selected_question=selected_question,
                         question_type_filter=question_type_filter,
                         annotated_only=annotated_only,
                         view_mode=view_mode,
                         questions_stats=questions_stats)

@annotation_bp.route('/statistics')
@login_required
def statistics():
    """Statistiche sulle annotazioni"""
    # Statistiche generali
    total_cells = TextCell.query.count()
    annotated_cells = db.session.query(TextCell.id)\
        .join(CellAnnotation)\
        .distinct().count()
    
    # Annotazioni per utente
    user_stats = db.session.query(User.username, db.func.count(CellAnnotation.id))\
        .join(CellAnnotation, User.id == CellAnnotation.user_id)\
            .group_by(User.id)\
        .order_by(db.desc(db.func.count(CellAnnotation.id)))\
        .all()
    
    # Etichette più utilizzate
    label_stats = db.session.query(
        Label.name, 
        func.coalesce(Category.color, Label.color).label('color'), 
        db.func.count(CellAnnotation.id)
    ).join(CellAnnotation)\
     .outerjoin(Category, Label.category_id == Category.id)\
     .group_by(Label.id)\
     .order_by(db.desc(db.func.count(CellAnnotation.id)))\
     .limit(20)\
     .all()
    
    # Progress per file
    file_progress = db.session.query(
        ExcelFile.original_filename,
        db.func.count(TextCell.id).label('total_cells'),
        db.func.count(CellAnnotation.id).label('annotated_cells')
    ).select_from(ExcelFile)\
     .outerjoin(TextCell, ExcelFile.id == TextCell.excel_file_id)\
     .outerjoin(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
     .group_by(ExcelFile.id)\
     .all()
    
    # Nuove statistiche dettagliate per file
    file_label_stats = get_file_label_statistics()
    overview_charts = create_overview_charts(file_label_stats)

    # Genera i grafici per le statistiche generali
    user_stats_chart = create_user_stats_chart(user_stats)
    label_stats_chart = create_label_stats_chart(label_stats)
    file_progress_chart = create_file_progress_chart(file_progress)
    
    return render_template('annotation/statistics.html',
                          total_cells=total_cells,
                          annotated_cells=annotated_cells,
                          user_stats=user_stats,
                          label_stats=label_stats,
                          file_progress=file_progress,
                          file_label_stats=file_label_stats,
                          overview_charts=overview_charts,
                          user_stats_chart=user_stats_chart,
                          label_stats_chart=label_stats_chart,
                          file_progress_chart=file_progress_chart)

@annotation_bp.route('/file_statistics/<int:file_id>')
@login_required
def file_statistics(file_id):
    """Statistiche dettagliate per un file specifico"""
    file_obj = ExcelFile.query.get_or_404(file_id)
    
    # Ottieni statistiche solo per questo file
    file_stats = get_file_label_statistics()
    current_file_stats = None
    
    for stat in file_stats:
        if stat['file'].id == file_id:
            current_file_stats = stat
            break
    
    if not current_file_stats:
        flash('Nessuna statistica trovata per questo file.', 'warning')
        return redirect(url_for('statistics.overview'))
    
    return render_template('annotation/file_statistics.html',
                         file_stats=current_file_stats)

def get_file_label_statistics():
    """Genera statistiche dettagliate delle etichette per ogni file"""
    file_stats = []
    
    # Ottieni tutti i file con le loro statistiche
    files = ExcelFile.query.all()
    
    for file in files:
        # Statistiche base del file
        total_cells = TextCell.query.filter_by(excel_file_id=file.id).count()
        annotated_cells = db.session.query(TextCell.id)\
            .filter_by(excel_file_id=file.id)\
            .join(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
            .distinct().count()
        
        # Statistiche per etichetta in questo file
        label_stats = db.session.query(
            Label.name,
            func.coalesce(Category.color, Label.color).label('color'),
            func.coalesce(Category.name, Label.category, 'Senza categoria').label('category'),
            db.func.count(CellAnnotation.id).label('count')
        ).select_from(Label)\
         .join(CellAnnotation, Label.id == CellAnnotation.label_id)\
         .outerjoin(Category, Label.category_id == Category.id)\
         .join(TextCell, CellAnnotation.text_cell_id == TextCell.id)\
         .filter(TextCell.excel_file_id == file.id)\
         .group_by(Label.id)\
         .order_by(db.desc('count'))\
         .all()
        
        # Statistiche per categoria in questo file
        # Usa il nome dalla Category FK; fallback al campo legacy per etichette non migrate
        category_stats = db.session.query(
            db.func.coalesce(Category.name, Label.category, 'Senza categoria').label('category'),
            db.func.count(CellAnnotation.id).label('count')
        ).select_from(Label)\
         .join(CellAnnotation, Label.id == CellAnnotation.label_id)\
         .join(TextCell, CellAnnotation.text_cell_id == TextCell.id)\
         .outerjoin(Category, Label.category_id == Category.id)\
         .filter(TextCell.excel_file_id == file.id)\
         .group_by(db.func.coalesce(Category.name, Label.category, 'Senza categoria'))\
         .order_by(db.desc('count'))\
         .all()
        
        # Contributori al file
        contributors = db.session.query(
            User.username,
            db.func.count(CellAnnotation.id).label('count')
        ).select_from(User)\
         .join(CellAnnotation, User.id == CellAnnotation.user_id)\
         .join(TextCell, CellAnnotation.text_cell_id == TextCell.id)\
         .filter(TextCell.excel_file_id == file.id)\
         .group_by(User.id)\
         .order_by(db.desc('count'))\
         .all()
        
        # Crea grafici per questo file
        charts = create_file_charts(file.id, label_stats, category_stats, contributors)
        
        file_stats.append({
            'file': file,
            'total_cells': total_cells,
            'annotated_cells': annotated_cells,
            'completion_rate': round((annotated_cells / total_cells * 100) if total_cells > 0 else 0, 1),
            'label_stats': label_stats,
            'category_stats': category_stats,
            'contributors': contributors,
            'charts': charts
        })
    
    return file_stats

def create_file_charts(file_id, label_stats, category_stats, contributors):
    """Crea grafici Plotly per un file specifico"""
    charts = {}
    
    # Grafico a torta delle etichette
    if label_stats:
        labels = [stat.name for stat in label_stats]
        values = [stat.count for stat in label_stats]
        colors = [stat.color for stat in label_stats]
        
        fig_labels = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            marker_colors=colors,
            hole=0.3,
            textinfo='label+percent',
            textposition='outside'
        )])
        
        fig_labels.update_layout(
            title=f"Distribuzione Etichette",
            showlegend=True,
            height=400,
            font=dict(size=12)
        )
        
        charts['labels_pie'] = json.dumps(fig_labels, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Grafico a barre delle categorie
    if category_stats:
        categories = [stat.category for stat in category_stats]
        counts = [stat.count for stat in category_stats]
        
        fig_categories = go.Figure(data=[go.Bar(
            x=categories,
            y=counts,
            marker_color='rgb(55, 83, 109)'
        )])
        
        fig_categories.update_layout(
            title="Annotazioni per Categoria",
            xaxis_title="Categoria",
            yaxis_title="Numero di Annotazioni",
            height=400
        )
        
        charts['categories_bar'] = json.dumps(fig_categories, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Grafico dei contributori
    if contributors:
        users = [contrib.username for contrib in contributors[:10]]  # Top 10
        counts = [contrib.count for contrib in contributors[:10]]
        
        fig_contributors = go.Figure(data=[go.Bar(
            x=counts,
            y=users,
            orientation='h',
            marker_color='rgb(26, 118, 255)'
        )])
        
        fig_contributors.update_layout(
            title="Top Contributori",
            xaxis_title="Numero di Annotazioni",
            yaxis_title="Utente",
            height=max(400, len(users) * 30)
        )
        
        charts['contributors_bar'] = json.dumps(fig_contributors, cls=plotly.utils.PlotlyJSONEncoder)
    
    return charts

def create_overview_charts(file_stats):
    """Crea grafici di panoramica generale"""
    charts = {}
    
    # Grafico del tasso di completamento per file
    file_names = [stat['file'].original_filename[:30] + "..." if len(stat['file'].original_filename) > 30 
                  else stat['file'].original_filename for stat in file_stats]
    completion_rates = [stat['completion_rate'] for stat in file_stats]
    
    fig_completion = go.Figure(data=[go.Bar(
        x=file_names,
        y=completion_rates,
        marker_color=['rgb(26, 118, 255)' if rate >= 50 else 'rgb(255, 65, 54)' for rate in completion_rates]
    )])
    
    fig_completion.update_layout(
        title="Tasso di Completamento per File",
        xaxis_title="File",
        yaxis_title="Percentuale Completamento (%)",
        height=400,
        xaxis_tickangle=-45
    )
    
    charts['completion_overview'] = json.dumps(fig_completion, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Distribuzione generale delle etichette (tutti i file)
    all_labels = defaultdict(int)
    label_colors = {}
    
    for stat in file_stats:
        for label_stat in stat['label_stats']:
            all_labels[label_stat.name] += label_stat.count
            label_colors[label_stat.name] = label_stat.color
    
    if all_labels:
        labels = list(all_labels.keys())
        values = list(all_labels.values())
        colors = [label_colors.get(label, '#cccccc') for label in labels]
        
        fig_all_labels = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            marker_colors=colors,
            hole=0.3
        )])
        
        fig_all_labels.update_layout(
            title="Distribuzione Generale delle Etichette",
            height=500
        )
        
        charts['all_labels_pie'] = json.dumps(fig_all_labels, cls=plotly.utils.PlotlyJSONEncoder)
    
    return charts

def create_user_stats_chart(user_stats):
    """Crea un grafico a barre per le annotazioni per utente."""
    if not user_stats:
        return None

    users = [stat.username for stat in user_stats]
    counts = [stat[1] for stat in user_stats] # stat[1] is the count from the query

    fig = go.Figure(data=[go.Bar(
        x=counts,
        y=users,
        orientation='h',
        marker_color='rgb(93, 164, 214)'
    )])

    fig.update_layout(
        title="Annotazioni per Utente",
        xaxis_title="Numero di Annotazioni",
        yaxis_title="Utente",
        height=max(400, len(users) * 30),
        yaxis=dict(autorange="reversed") # Per avere l'utente con più annotazioni in alto
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def create_label_stats_chart(label_stats):
    """Crea un grafico a barre per le etichette più utilizzate."""
    if not label_stats:
        return None

    labels = [stat.name for stat in label_stats]
    counts = [stat[2] for stat in label_stats] # stat[2] is the count from the query
    colors = [stat.color for stat in label_stats]

    fig = go.Figure(data=[go.Bar(
        x=labels,
        y=counts,
        marker_color=colors
    )])

    fig.update_layout(
        title="Etichette più Utilizzate",
        xaxis_title="Etichetta",
        yaxis_title="Numero di Annotazioni",
        height=400,
        xaxis_tickangle=-45
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def create_file_progress_chart(file_progress):
    """Crea un grafico a barre per il progresso di annotazione per file."""
    if not file_progress:
        return None

    file_names = [stat.original_filename for stat in file_progress]
    total_cells = [stat.total_cells for stat in file_progress]
    annotated_cells = [stat.annotated_cells for stat in file_progress]

    fig = go.Figure(data=[
        go.Bar(
            name='Celle Totali',
            x=file_names,
            y=total_cells,
            marker_color='rgb(26, 118, 255)'
        ),
        go.Bar(
            name='Celle Annotate',
            x=file_names,
            y=annotated_cells,
            marker_color='rgb(55, 128, 200)'
        )
    ])

    fig.update_layout(
        barmode='group',
        title="Progresso Annotazione per File",
        xaxis_title="File",
        yaxis_title="Numero di Celle",
        height=450,
        xaxis_tickangle=-45
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

@annotation_bp.route('/<int:annotation_id>', methods=['DELETE'])
@login_required
def delete_annotation(annotation_id):
    """API per eliminare un'annotazione tramite ID (compatibile con frontend)"""
    print(f"DELETE_ANNOTATION: User {current_user.id} ({current_user.username}) deleting annotation {annotation_id}")

    try:
        # Trova l'annotazione
        annotation = CellAnnotation.query.get(annotation_id)
        
        if not annotation:
            print(f"DELETE_ANNOTATION: Annotation {annotation_id} not found")
            return jsonify({'success': False, 'message': 'Annotazione non trovata'}), 404
        
        print(f"DELETE_ANNOTATION: Found annotation {annotation_id} - Cell: {annotation.text_cell_id}, Label: {annotation.label_id}, User: {annotation.user_id}")
        
        # Verifica se l'annotazione ha un utente associato
        user_username = "N/A"
        if annotation.user_id:
            user = User.query.get(annotation.user_id)
            if user:
                user_username = user.username
            else:
                print(f"DELETE_ANNOTATION: Warning - User {annotation.user_id} not found for annotation {annotation_id}")
        
        print(f"DELETE_ANNOTATION: User for annotation: {user_username}")
        
        # Traccia l'azione di rimozione
        action = AnnotationAction(
            text_cell_id=annotation.text_cell_id,
            label_id=annotation.label_id,
            action_type='removed',
            performed_by=current_user.id,
            target_user_id=annotation.user_id,
            annotation_id=annotation_id,
            was_ai_generated=annotation.is_ai_generated,
            ai_confidence=annotation.ai_confidence,
            ai_model=annotation.ai_model,
            ai_provider=annotation.ai_provider,
            notes=f"Rimossa annotazione di {user_username}"
        )
        
        db.session.add(action)
        print(f"DELETE_ANNOTATION: AnnotationAction created for removal")
        
        # Rimuovi l'annotazione
        db.session.delete(annotation)
        db.session.flush()
        print(f"DELETE_ANNOTATION: Annotation {annotation_id} deleted from session")
        
        db.session.commit()
        print(f"DELETE_ANNOTATION: Successfully committed removal of annotation {annotation_id}")
        
        return jsonify({
            'success': True,
            'message': 'Annotazione rimossa con successo'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"DELETE_ANNOTATION: Error removing annotation {annotation_id}: {str(e)}")
        print(f"DELETE_ANNOTATION: Exception type: {type(e).__name__}")
        import traceback
        print(f"DELETE_ANNOTATION: Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'Errore del server: {str(e)}'
        }), 500

@annotation_bp.route('/admin/question-classification')
@login_required
def question_classification_admin():
    """Reindirizza alla nuova interfaccia di gestione delle domande"""
    flash('La classificazione automatica è stata rimossa. Usa la nuova interfaccia di gestione manuale.', 'info')
    return redirect(url_for('questions.manage_questions'))

@annotation_bp.route('/admin/classify-questions/<int:file_id>', methods=['POST'])
@login_required  
def classify_questions(file_id=None):
    """Reindirizza alla nuova interfaccia di gestione delle domande"""
    flash('La classificazione automatica è stata rimossa. Usa la nuova interfaccia di gestione manuale.', 'info')
    return redirect(url_for('questions.manage_questions'))

@annotation_bp.route('/api/annotatable-cells/<int:file_id>')
@login_required
def get_annotatable_cells(file_id):
    """API per ottenere le celle di un file (solo domande aperte sono annotabili)"""
    
    # Ottieni le celle che sono domande aperte o non classificate
    annotatable_cells = TextCell.query.filter_by(excel_file_id=file_id)\
        .filter(db.or_(
            TextCell.question_type == 'aperta',
            TextCell.question_type.is_(None)
        )).all()
    
    cells_data = []
    for cell in annotatable_cells:
        cells_data.append({
            'id': cell.id,
            'sheet_name': cell.sheet_name,
            'cell_reference': cell.cell_reference,
            'column_name': cell.column_name,
            'text_content': cell.text_content[:100] + '...' if len(cell.text_content) > 100 else cell.text_content,
            'question_type': getattr(cell, 'question_type', None)
        })
    
    return jsonify({
        'total': len(cells_data),
        'cells': cells_data
    })
