"""
Routes per la gestione dei file Excel
"""

import os
import pandas as pd
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from models import ExcelFile, TextCell, CellAnnotation, Label, Category, db
from forms import UploadForm

excel_bp = Blueprint('excel', __name__)

def allowed_file(filename):
    """Verifica se il file ha un'estensione consentita"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['xlsx', 'xls']


def is_demographic_question(question_name: str) -> bool:
    """
    Heuristica per identificare domande anagrafiche/non tematiche
    (nome, età, contatti, codici identificativi, ecc.).
    """
    if not question_name:
        return False

    text = question_name.lower()
    text = (
        text.replace('à', 'a')
            .replace('è', 'e')
            .replace('é', 'e')
            .replace('ì', 'i')
            .replace('ò', 'o')
            .replace('ù', 'u')
    )

    demographic_markers = [
        'anagraf',
        'nome e cognome',
        'nome completo',
        'il tuo nome',
        'tuo nome',
        'cognome',
        'eta',
        'sesso',
        'genere',
        'nascita',
        'codice fiscale',
        'codice di',
        'telefono',
        'cellulare',
        'email',
        'e-mail',
        'indirizzo',
        'residenza',
        'cap ',
        'comune',
        'provincia',
        'madre',
        'padre',
    ]

    return any(marker in text for marker in demographic_markers)

def extract_text_cells(file_path, excel_file_id):
    """Estrae le celle testuali da un file Excel"""
    try:
        # Leggi tutti i fogli del file Excel
        excel_data = pd.read_excel(file_path, sheet_name=None, engine='openpyxl', header=0)
        
        cells_extracted = 0
        
        for sheet_name, df in excel_data.items():
            # Salva le intestazioni (prima riga)
            headers = df.columns.tolist()
            
            # Itera su tutte le righe (escludendo l'header)
            for row_idx, row in df.iterrows():
                for col_idx, cell_value in enumerate(row):
                    # Verifica se la cella contiene testo non vuoto
                    if pd.notna(cell_value) and isinstance(cell_value, str) and len(cell_value.strip()) > 0:
                        # Il nome della colonna è l'intestazione (quesito)
                        question_text = headers[col_idx] if col_idx < len(headers) else f'Colonna_{col_idx}'
                        
                        # Crea un nuovo oggetto TextCell
                        text_cell = TextCell(
                            excel_file_id=excel_file_id,
                            sheet_name=sheet_name,
                            row_index=row_idx + 1,  # +1 perché row_idx parte da 0 ma saltiamo l'header
                            column_index=col_idx,
                            column_name=question_text,
                            text_content=cell_value.strip()
                        )
                        db.session.add(text_cell)
                        cells_extracted += 1
        
        db.session.commit()
        return cells_extracted
        
    except Exception as e:
        db.session.rollback()
        raise e

@excel_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """Caricamento di file Excel"""
    form = UploadForm()
    
    if form.validate_on_submit():
        file = form.file.data
        
        if file and allowed_file(file.filename):
            # Genera un nome file sicuro
            filename = secure_filename(file.filename)
            timestamp = str(int(pd.Timestamp.now().timestamp()))
            safe_filename = f"{timestamp}_{filename}"
            
            # Salva il file
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)
            file.save(file_path)
            
            try:
                # Crea record nel database
                excel_file = ExcelFile(
                    filename=safe_filename,
                    original_filename=filename,
                    file_path=file_path,
                    uploaded_by=current_user.id
                )
                db.session.add(excel_file)
                db.session.flush()  # Per ottenere l'ID
                
                # Estrai le celle testuali
                cells_count = extract_text_cells(file_path, excel_file.id)
                
                db.session.commit()
                
                flash(f'File caricato con successo! Estratte {cells_count} celle testuali.', 'success')
                return redirect(url_for('excel.view_file', file_id=excel_file.id))
                
            except Exception as e:
                db.session.rollback()
                # Rimuovi il file se l'elaborazione fallisce
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'Errore durante l\'elaborazione del file: {str(e)}', 'error')
        else:
            flash('File non valido. Sono supportati solo file .xlsx e .xls', 'error')
    
    return render_template('excel/upload.html', form=form)

@excel_bp.route('/files')
@login_required
def list_files():
    """Lista di tutti i file Excel caricati"""
    page = request.args.get('page', 1, type=int)
    files = ExcelFile.query.order_by(ExcelFile.uploaded_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    return render_template('excel/list_files.html', files=files)

@excel_bp.route('/file/<int:file_id>')
@login_required
def view_file(file_id):
    """Visualizza un file Excel specifico"""
    excel_file = ExcelFile.query.get_or_404(file_id)
    
    # Paginazione delle celle
    page = request.args.get('page', 1, type=int)
    sheet_filter = request.args.get('sheet', '')
    view_mode = request.args.get('view', 'cells')  # 'cells' o 'questions'
    
    # Query base
    query = TextCell.query.filter_by(excel_file_id=file_id)
    
    if sheet_filter:
        query = query.filter_by(sheet_name=sheet_filter)
    
    # Lista dei fogli per il filtro
    sheets = db.session.query(TextCell.sheet_name)\
                      .filter_by(excel_file_id=file_id)\
                      .distinct()\
                      .all()
    sheet_names = [sheet[0] for sheet in sheets]
    
    # Lista delle domande/colonne per il filtro
    questions = db.session.query(TextCell.column_name)\
                          .filter_by(excel_file_id=file_id)\
                          .distinct()\
                          .order_by(TextCell.column_name)\
                          .all()
    question_names = [q[0] for q in questions if q[0]]
    
    # Verifica disponibilità etichette
    available_labels_count = Label.query.count()
    
    if view_mode == 'questions':
        # Vista per quesiti: raggruppa per colonna/domanda
        cells = query.order_by(TextCell.column_name, TextCell.row_index)\
                     .paginate(page=page, per_page=50, error_out=False)
    else:
        # Vista tradizionale per celle
        cells = query.order_by(TextCell.sheet_name, TextCell.row_index, TextCell.column_index)\
                     .paginate(page=page, per_page=20, error_out=False)
    
    # Statistiche rapide
    total_responses = query.count()
    questions_count = len(question_names)
    
    # Calcola il numero di celle annotate per questo file
    annotated_cells_count = db.session.query(TextCell.id)\
        .filter_by(excel_file_id=file_id)\
        .join(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
        .distinct().count()
    
    # Se c'è un filtro foglio, calcola le annotazioni solo per quel foglio
    if sheet_filter:
        annotated_cells_count = db.session.query(TextCell.id)\
            .filter_by(excel_file_id=file_id, sheet_name=sheet_filter)\
            .join(CellAnnotation, TextCell.id == CellAnnotation.text_cell_id)\
            .distinct().count()
    
    # Per la vista per domande, calcola le statistiche per ogni domanda
    questions_stats = []
    if view_mode == 'questions':
        base_query = db.session.query(
            TextCell.column_name,
            db.func.count(TextCell.id).label('total_responses'),
            db.func.count(CellAnnotation.id).label('annotated_responses')
        ).outerjoin(CellAnnotation)\
         .filter(TextCell.excel_file_id == file_id)
        
        # Applica filtro per foglio se selezionato
        if sheet_filter:
            base_query = base_query.filter(TextCell.sheet_name == sheet_filter)
        
        questions_stats = base_query.group_by(TextCell.column_name)\
                                   .order_by(TextCell.column_name)\
                                   .all()
    
    # Recupera tutte le annotazioni del file
    annotations = db.session.query(CellAnnotation, Label, TextCell)\
        .join(Label, CellAnnotation.label_id == Label.id)\
        .join(TextCell, TextCell.id == CellAnnotation.text_cell_id)\
        .filter(TextCell.excel_file_id == file_id)\
        .all()

    # Raggruppa i commenti per etichetta con tutte le info necessarie
    from collections import defaultdict
    label_comments_dict = defaultdict(list)
    label_objs = {}
    for annotation, label, text_cell in annotations:
        label_comments_dict[label.id].append({
            'text': text_cell.text_content,
            'row_index': text_cell.row_index,
            'annotation_id': annotation.id
        })
        label_objs[label.id] = label
    label_comments = [(label_objs[lid], comments) for lid, comments in label_comments_dict.items()]

    return render_template('excel/view_file.html', 
                         excel_file=excel_file, 
                         cells=cells,
                         sheet_names=sheet_names,
                         question_names=question_names,
                         current_sheet=sheet_filter,
                         view_mode=view_mode,
                         total_responses=total_responses,
                         questions_count=questions_count,
                         available_labels_count=available_labels_count,
                         annotated_cells_count=annotated_cells_count,
                         questions_stats=questions_stats,
                         label_comments=label_comments)

@excel_bp.route('/file/<int:file_id>/question/')
@excel_bp.route('/file/<int:file_id>/question')
@login_required
def view_question_empty(file_id):
    """Gestisce il caso di question_name vuoto - reindirizza alla vista delle domande"""
    return redirect(url_for('excel.view_file', file_id=file_id, view='questions'))

@excel_bp.route('/file/<int:file_id>/question/<question_name>')
@login_required
def view_question(file_id, question_name):
    """Visualizza tutte le risposte a una specifica domanda"""
    # Gestisce il caso di question_name vuoto anche qui
    if not question_name or question_name.strip() == "":
        return redirect(url_for('excel.view_file', file_id=file_id, view='questions'))
    
    excel_file = ExcelFile.query.get_or_404(file_id)
    
    # Ottieni tutte le risposte per questa domanda
    page = request.args.get('page', 1, type=int)
    
    responses = TextCell.query.filter_by(
        excel_file_id=file_id,
        column_name=question_name
    ).order_by(TextCell.row_index)\
     .paginate(page=page, per_page=30, error_out=False)
    
    # Statistiche per questa domanda
    total_responses = responses.total
    annotated_responses = db.session.query(TextCell.id)\
        .join(CellAnnotation)\
        .filter(TextCell.excel_file_id == file_id)\
        .filter(TextCell.column_name == question_name)\
        .distinct().count()
    
    # Etichette più usate per questa domanda
    popular_labels = db.session.query(
        Label.name, 
        db.func.coalesce(Category.color, Label.color).label('color'), 
        db.func.count(CellAnnotation.id).label('count')
    ).join(CellAnnotation)\
        .join(TextCell)\
        .outerjoin(Category, Label.category_id == Category.id)\
        .filter(TextCell.excel_file_id == file_id)\
        .filter(TextCell.column_name == question_name)\
        .group_by(Label.id)\
        .order_by(db.desc('count'))\
        .limit(10)\
        .all()
    
    # Ottieni tutte le categorie attive per la selezione AI
    categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
    
    return render_template('excel/view_question.html',
                         excel_file=excel_file,
                         question_name=question_name,
                         responses=responses,
                         total_responses=total_responses,
                         annotated_responses=annotated_responses,
                         popular_labels=popular_labels,
                         categories=categories)

@excel_bp.route('/file/<int:file_id>/questions')
@login_required
def questions_overview(file_id):
    """Panoramica di tutte le domande del questionario"""
    excel_file = ExcelFile.query.get_or_404(file_id)
    
    # Ottieni statistiche per ogni domanda
    questions_stats = db.session.query(
        TextCell.column_name,
        db.func.count(db.distinct(TextCell.id)).label('total_responses'),
        db.func.count(db.distinct(CellAnnotation.text_cell_id)).label('annotated_responses')
    ).outerjoin(CellAnnotation)\
     .filter(TextCell.excel_file_id == file_id)\
     .group_by(TextCell.column_name)\
     .order_by(TextCell.column_name)\
     .all()

    demographic_questions = {
        question_name for question_name, _, _ in questions_stats
        if is_demographic_question(question_name)
    }
    
    return render_template('excel/questions_overview.html',
                         excel_file=excel_file,
                         questions_stats=questions_stats,
                         demographic_questions=demographic_questions)

@excel_bp.route('/file/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(file_id):
    """Elimina un file Excel e tutte le sue celle/annotazioni associate"""
    excel_file = ExcelFile.query.get_or_404(file_id)
    
    # Verifica che l'utente sia autorizzato a eliminare il file
    if current_user.id != excel_file.uploaded_by:
        flash('Non hai i permessi per eliminare questo file.', 'error')
        return redirect(url_for('excel.list_files'))
    
    try:
        # Elimina il file fisico
        if os.path.exists(excel_file.file_path):
            os.remove(excel_file.file_path)
        
        # Le annotazioni e le celle testuali verranno eliminate automaticamente
        # grazie alle relazioni cascade definite nei modelli
        db.session.delete(excel_file)
        db.session.commit()
        
        flash(f'File "{excel_file.original_filename}" eliminato con successo.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'eliminazione del file: {str(e)}', 'error')
    
    return redirect(url_for('excel.list_files'))

@excel_bp.route('/file/<int:file_id>/download')
@login_required
def download_file(file_id):
    """Scarica un file Excel"""
    excel_file = ExcelFile.query.get_or_404(file_id)
    
    try:
        return send_file(
            excel_file.file_path,
            as_attachment=True,
            download_name=excel_file.original_filename
        )
    except Exception as e:
        flash(f'Errore durante il download del file: {str(e)}', 'error')
        return redirect(url_for('excel.view_file', file_id=file_id))
