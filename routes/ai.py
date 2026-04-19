"""
Routes per l'integrazione AI
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
import json
from sqlalchemy.orm import joinedload
from datetime import datetime

from models import db, TextCell, CellAnnotation, ExcelFile, Label, AIConfiguration, Category, PromptTemplate
from services.ai_annotator import AIAnnotatorService
from services.ai_label_service import AILabelService

ai_bp = Blueprint('ai', __name__)

# Route per gestione template
@ai_bp.route('/templates/manage')
@login_required
def manage_templates():
    """Pagina per gestire i template AI"""
    try:
        templates = PromptTemplate.query.order_by(PromptTemplate.category, PromptTemplate.name).all()
        categories = db.session.query(PromptTemplate.category).distinct().filter(
            PromptTemplate.category.isnot(None)
        ).all()
        categories = [cat[0] for cat in categories if cat[0]]
        
        active_count = PromptTemplate.query.filter_by(is_active=True).count()
        
        return render_template('ai/templates.html', 
                             templates=templates,
                             categories=categories,
                             active_count=active_count)
    except Exception as e:
        flash(f'Errore nel caricamento dei template: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))

@ai_bp.route('/templates/create', methods=['POST'])
@login_required
def create_template():
    """Crea un nuovo template"""
    try:
        data = request.get_json()
        
        template = PromptTemplate(
            name=data['name'],
            category=data['category'],
            description=data.get('description'),
            template_text=data['template_text'],
            is_active=data.get('is_active', True),
            created_at=datetime.utcnow()
        )
        
        db.session.add(template)
        db.session.commit()
        
        return jsonify({'success': True, 'template_id': template.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/templates/<int:template_id>')
@login_required
def get_template(template_id):
    """Recupera i dettagli di un template"""
    try:
        template = PromptTemplate.query.get_or_404(template_id)
        
        return jsonify({
            'success': True,
            'template': {
                'id': template.id,
                'name': template.name,
                'category': template.category,
                'description': template.description,
                'template_text': template.template_text,
                'is_active': template.is_active,
                'created_at': template.created_at.isoformat() if template.created_at else None
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/templates/<int:template_id>/toggle', methods=['POST'])
@login_required
def toggle_template(template_id):
    """Attiva/disattiva un template"""
    try:
        data = request.get_json()
        template = PromptTemplate.query.get_or_404(template_id)
        
        template.is_active = data['is_active']
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ...existing routes...

@ai_bp.route('/prompt/preview', methods=['POST'])
@login_required
def preview_prompt():
    """Restituisce il prompt AI generato in base ai parametri forniti (senza inviare all'AI)"""
    try:
        data = request.get_json() or {}
        file_id = data.get('file_id')
        template_id = int(data.get('template_id', 1))
        selected_categories = data.get('selected_categories', [])
        question_name = data.get('question_name')
        batch_size = int(data.get('batch_size', 5))
        
        # Validazione parametri
        if not file_id:
            return jsonify({'success': False, 'error': 'ID file mancante'}), 400
        
        if batch_size < 1 or batch_size > 20:
            return jsonify({'success': False, 'error': 'Batch size deve essere tra 1 e 20'}), 400
            
        # Verifica che il file esista
        excel_file = ExcelFile.query.get(file_id)
        if not excel_file:
            return jsonify({'success': False, 'error': 'File non trovato'}), 404
        
        ai_service = AIAnnotatorService()
        
        # Gestione migliorata delle categorie selezionate
        labels = []
        if selected_categories and len(selected_categories) > 0:
            # Filtra per categorie specifiche
            categories = Category.query.filter(
                Category.name.in_(selected_categories),
                Category.is_active == True,  # noqa: E712
                Category.merged_into_category_id.is_(None)
            ).all()
            
            if not categories:
                return jsonify({
                    'success': False, 
                    'error': f'Nessuna categoria attiva trovata tra: {", ".join(selected_categories)}'
                }), 400
            
            for cat in categories:
                cat_labels = Label.query.options(db.joinedload(Label.category_obj)).filter_by(
                    category_id=cat.id
                ).filter(
                    Label.is_active == True,  # noqa: E712
                    Label.merged_into_label_id.is_(None)
                ).all()
                labels.extend(cat_labels)
                
            if not labels:
                return jsonify({
                    'success': False, 
                    'error': 'Nessuna etichetta attiva trovata nelle categorie selezionate'
                }), 400
        else:
            # Prendi tutte le etichette attive
            labels = Label.query.options(db.joinedload(Label.category_obj)).filter(
                Label.is_active == True,  # noqa: E712
                Label.merged_into_label_id.is_(None)
            ).order_by(Label.name).all()
            labels = [
                lbl for lbl in labels
                if not lbl.category_obj or (
                    lbl.category_obj.is_active and lbl.category_obj.merged_into_category_id is None
                )
            ]
            
            if not labels:
                return jsonify({
                    'success': False, 
                    'error': 'Nessuna etichetta attiva disponibile nel sistema'
                }), 400
        
        # Prendi celle da annotare (migliore gestione dell'ordine)
        cells_query = TextCell.query.filter(
            TextCell.excel_file_id == file_id,
            ~TextCell.id.in_(db.session.query(CellAnnotation.text_cell_id).distinct())
        )
        if question_name:
            cells_query = cells_query.filter(TextCell.column_name == question_name)

        cells = cells_query.order_by(TextCell.row_index, TextCell.column_index).limit(batch_size).all()
        
        if not cells:
            return jsonify({
                'success': False, 
                'error': 'Nessuna cella non annotata trovata',
                'info': 'Tutte le celle di questo file sono già state annotate'
            }), 200
        
        texts = [cell.text_content for cell in cells]
        prompt = ai_service.build_annotation_prompt(texts, labels, template_id)
        
        return jsonify({
            'success': True, 
            'prompt': prompt,
            'stats': {
                'labels_count': len(labels),
                'cells_count': len(cells),
                'categories_used': len(selected_categories) if selected_categories else 'tutte',
                'template_id': template_id,
                'question_name': question_name
            }
        })
        
    except ValueError as e:
        return jsonify({'success': False, 'error': f'Parametro non valido: {str(e)}'}), 400
    except Exception as e:
        print(f"Errore in preview_prompt: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500

@ai_bp.route('/generate/<int:file_id>', methods=['POST'])
@login_required
def generate_annotations(file_id):
    """Genera annotazioni AI per un file"""
    try:
        # Verifica che il file esista
        excel_file = ExcelFile.query.get_or_404(file_id)
        
        # Parametri opzionali dal JSON body
        request_data = request.get_json() if request.is_json else {}
        batch_size = request_data.get('batch_size', 3)  # Default ridotto a 3
        mode = request_data.get('mode', 'new')  # new, replace, additional
        template_id = request_data.get('template_id', 1)
        selected_categories = request_data.get('selected_categories', [])
        question_name = request_data.get('question_name')
        max_cells_per_session = request_data.get('max_cells_per_session', 20)
        
        # Nuovi parametri dinamici
        max_tokens = request_data.get('max_tokens', 500)  # Default aumentato a 500
        timeout = request_data.get('timeout', 90)  # Default 90s
        
        # Converte mode in parametro legacy
        re_annotate = (mode == 'replace')
        
        print(f"🚀 AI Generate: file_id={file_id}, batch_size={batch_size}, mode={mode}, template_id={template_id}")
        print(f"   Categorie selezionate: {selected_categories}")
        if question_name:
            print(f"   Domanda filtrata: {question_name}")
        print(f"   Max tokens: {max_tokens}, Timeout: {timeout}s")
        
        # Inizializza il servizio AI
        ai_service = AIAnnotatorService()
        
        # Genera le annotazioni con i nuovi parametri
        result = ai_service.generate_annotations(
            file_id=file_id, 
            batch_size=batch_size, 
            mode=mode,
            template_id=template_id,
            selected_categories=selected_categories,
            max_tokens=max_tokens,
            timeout=timeout,
            question_name=question_name,
            max_cells_per_session=max_cells_per_session
        )
        
        if 'error' in result:
            print(f"❌ Errore generazione: {result['error']}")
            return jsonify({'success': False, 'error': result['error']}), 400
        
        action_type = "ri-etichettate" if mode == 'replace' else "generate"
        print(f"✅ Generazione completata: {len(result.get('annotations', []))} annotazioni {action_type}")
        
        return jsonify({
            'success': True,
            'message': result['message'],
            'total_processed': result.get('total_processed', 0),
            'annotations_count': len(result.get('annotations', [])),
            'mode': mode,
            're_annotate': (mode == 'replace'),
            'question_name': result.get('question_name'),
            'remaining_cells': result.get('remaining_cells', 0),
            'total_target_cells': result.get('total_target_cells', 0),
            'max_cells_per_session': result.get('max_cells_per_session', max_cells_per_session)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/pending/<int:file_id>')
@login_required
def get_pending_annotations(file_id):
    """Ottiene le annotazioni AI in attesa di revisione per un file"""
    try:
        ai_service = AIAnnotatorService()
        pending_annotations = ai_service.get_pending_annotations(file_id)
        
        return jsonify({
            'success': True,
            'annotations': pending_annotations,
            'count': len(pending_annotations)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/review/<int:annotation_id>', methods=['POST'])
@login_required
def review_annotation(annotation_id):
    """Rivede un'annotazione AI (accetta/rifiuta) - TEMPORANEAMENTE SENZA CSRF"""
    try:
        data = request.get_json()
        action = data.get('action')  # 'accept' o 'reject'
        
        if action not in ['accept', 'reject']:
            return jsonify({'success': False, 'error': 'Azione non valida'}), 400
        
        ai_service = AIAnnotatorService()
        success = ai_service.review_annotation(annotation_id, action, current_user.id)
        
        if success:
            return jsonify({
                'success': True, 
                'message': f'Annotazione {"accettata" if action == "accept" else "rifiutata"} con successo'
            })
        else:
            return jsonify({'success': False, 'error': 'Errore nella revisione'}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/review/batch', methods=['POST'])
@login_required
def batch_review_annotations():
    """Rivede multiple annotazioni AI in batch"""
    try:
        data = request.get_json()
        annotation_ids = data.get('annotation_ids', [])
        action = data.get('action')  # 'accept' o 'reject'
        
        if action not in ['accept', 'reject']:
            return jsonify({'success': False, 'error': 'Azione non valida'}), 400
        
        ai_service = AIAnnotatorService()
        success_count = 0
        
        for annotation_id in annotation_ids:
            if ai_service.review_annotation(annotation_id, action, current_user.id):
                success_count += 1
        
        return jsonify({
            'success': True,
            'message': f'{success_count}/{len(annotation_ids)} annotazioni processate',
            'processed': success_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/review/file/<int:file_id>')
@login_required
def review_file_annotations(file_id):
    """Pagina per rivedere le annotazioni AI di un file"""
    try:
        # Verifica che il file esista
        excel_file = ExcelFile.query.get_or_404(file_id)
        
        # Ottiene le annotazioni pending
        ai_service = AIAnnotatorService()
        pending_annotations = ai_service.get_pending_annotations(file_id)
        
        # Statistiche
        total_cells = TextCell.query.filter_by(excel_file_id=file_id).count()
        annotated_cells = db.session.query(CellAnnotation.text_cell_id).join(TextCell).filter(
            TextCell.excel_file_id == file_id,
            CellAnnotation.status == 'active'
        ).distinct().count()
        
        ai_annotations_count = CellAnnotation.query.join(TextCell).filter(
            TextCell.excel_file_id == file_id,
            CellAnnotation.is_ai_generated == True
        ).count()
        
        return render_template('ai/review_annotations.html',
                             excel_file=excel_file,
                             pending_annotations=pending_annotations,
                             total_cells=total_cells,
                             annotated_cells=annotated_cells,
                             ai_annotations_count=ai_annotations_count)
        
    except Exception as e:
        flash(f'Errore nel caricamento: {str(e)}', 'error')
        return redirect(url_for('excel.list_files'))

@ai_bp.route('/review/test/<int:file_id>')
@login_required
def test_review_file_annotations(file_id):
    """Pagina di test per rivedere le annotazioni AI di un file"""
    try:
        # Verifica che il file esista
        excel_file = ExcelFile.query.get_or_404(file_id)
        
        # Ottiene le annotazioni pending
        ai_service = AIAnnotatorService()
        pending_annotations = ai_service.get_pending_annotations(file_id)
        
        # Statistiche
        total_cells = TextCell.query.filter_by(excel_file_id=file_id).count()
        annotated_cells = db.session.query(CellAnnotation.text_cell_id).join(TextCell).filter(
            TextCell.excel_file_id == file_id,
            CellAnnotation.status == 'active'
        ).distinct().count()
        
        ai_annotations_count = CellAnnotation.query.join(TextCell).filter(
            TextCell.excel_file_id == file_id,
            CellAnnotation.is_ai_generated == True
        ).count()
        
        return render_template('ai/test_review.html',
                             excel_file=excel_file,
                             pending_annotations=pending_annotations,
                             total_cells=total_cells,
                             annotated_cells=annotated_cells,
                             ai_annotations_count=ai_annotations_count)
        
    except Exception as e:
        flash(f'Errore nel caricamento: {str(e)}', 'error')
        return redirect(url_for('excel.list_files'))

@ai_bp.route('/config/current')
@login_required
def get_current_ai_config():
    """Ottiene la configurazione AI attualmente attiva"""
    try:
        active_config = AIConfiguration.query.filter_by(is_active=True).first()
        
        if not active_config:
            return jsonify({
                'success': False, 
                'message': 'Nessuna configurazione AI attiva'
            })
        
        # Determina il modello in base al provider
        if active_config.provider == 'ollama':
            model_name = active_config.ollama_model
        elif active_config.provider == 'openrouter':
            model_name = active_config.openrouter_model
        else:
            model_name = 'Unknown'
        
        return jsonify({
            'success': True,
            'config': {
                'id': active_config.id,
                'name': active_config.name,
                'provider': active_config.provider,
                'model': model_name
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/status/<int:file_id>')
@login_required
def get_ai_status(file_id):
    """Ottiene lo status delle annotazioni AI per un file"""
    try:
        # Verifica che il file esista
        excel_file = ExcelFile.query.get_or_404(file_id)
        
        # Conta le annotazioni AI per questo file
        ai_annotations = CellAnnotation.query.join(TextCell).filter(
            TextCell.excel_file_id == file_id,
            CellAnnotation.is_ai_generated == True
        ).all()
        
        # Conta quelle in attesa di revisione
        pending_annotations = [ann for ann in ai_annotations if ann.status == 'pending_review']
        
        # Conta quelle approvate/rifiutate
        reviewed_annotations = [ann for ann in ai_annotations if ann.status in ['active', 'rejected']]
        approved_annotations = [ann for ann in reviewed_annotations if ann.status == 'active']
        
        return jsonify({
            'success': True,
            'ai_stats': {
                'total': len(ai_annotations),
                'pending': len(pending_annotations),
                'reviewed': len(reviewed_annotations),
                'approved': len(approved_annotations),
                'rejected': len(reviewed_annotations) - len(approved_annotations)
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/labels/for-ai')
@login_required
def get_labels_for_ai():
    """API per ottenere tutte le etichette formattate per l'AI"""
    try:
        labels_data = AILabelService.get_labels_for_ai()
        return jsonify({
            'success': True,
            'labels': labels_data,
            'total_count': len(labels_data)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/categories/for-ai')
@login_required
def get_categories_for_ai():
    """API per ottenere tutte le categorie con etichette per l'AI"""
    try:
        categories_data = AILabelService.get_categories_for_ai()
        return jsonify({
            'success': True,
            'categories': categories_data,
            'total_count': len(categories_data)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/prompt/annotation')
@login_required
def get_annotation_prompt():
    """Ottiene il prompt per l'annotazione AI"""
    try:
        prompt = AILabelService.get_ai_annotation_prompt()
        return jsonify({
            'success': True,
            'prompt': prompt
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/prompt/batch-annotation', methods=['POST'])
@login_required
def get_batch_annotation_prompt():
    """Ottiene il prompt per l'annotazione in batch"""
    try:
        data = request.get_json()
        if not data or 'texts' not in data:
            return jsonify({'success': False, 'error': 'Testi non forniti'}), 400
        
        texts = data['texts']
        if not isinstance(texts, list) or len(texts) == 0:
            return jsonify({'success': False, 'error': 'Lista testi non valida'}), 400
        
        prompt = AILabelService.get_ai_batch_annotation_prompt(texts)
        return jsonify({
            'success': True,
            'prompt': prompt,
            'text_count': len(texts)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/validate-response', methods=['POST'])
@login_required
def validate_ai_response():
    """Valida una risposta dell'AI"""
    try:
        data = request.get_json()
        if not data or 'response' not in data:
            return jsonify({'success': False, 'error': 'Risposta non fornita'}), 400
        
        is_valid = AILabelService.validate_ai_response(data['response'])
        return jsonify({
            'success': True,
            'is_valid': is_valid
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/suggest-labels', methods=['POST'])
@login_required
def suggest_labels():
    """Suggerisce etichette per un testo"""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'success': False, 'error': 'Testo non fornito'}), 400
        
        text = data['text']
        limit = data.get('limit', 5)
        
        suggestions = AILabelService.get_recommended_labels(text, limit)
        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'suggestion_count': len(suggestions)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/statistics/labels')
@login_required
def get_label_statistics():
    """Ottiene statistiche sull'utilizzo delle etichette"""
    try:
        stats = AILabelService.get_label_statistics()
        return jsonify({
            'success': True,
            'statistics': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/dashboard')
@login_required
def ai_dashboard():
    """Dashboard per la gestione dell'AI"""
    try:
        # Ottieni statistiche
        stats = AILabelService.get_label_statistics()
        
        # Configurazione AI
        ai_config = AIConfiguration.query.first()
        
        # File disponibili
        files = ExcelFile.query.order_by(ExcelFile.uploaded_at.desc()).limit(10).all()
        
        return render_template('ai/dashboard.html',
                             statistics=stats,
                             ai_config=ai_config,
                             files=files)
    except Exception as e:
        flash(f'Errore nel caricamento dashboard: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))

@ai_bp.route('/templates/available')
@login_required
def get_available_templates():
    """Restituisce i template di prompt disponibili"""
    try:
        ai_service = AIAnnotatorService()
        templates = ai_service.get_available_templates()
        
        return jsonify({
            'success': True,
            'templates': templates,
            'total_count': len(templates)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_bp.route('/validate-configuration')
@login_required
def validate_ai_configuration():
    """Valida la configurazione AI corrente"""
    try:
        ai_service = AIAnnotatorService()
        config = ai_service.get_active_configuration()
        
        if not config:
            return jsonify({
                'success': False,
                'error': 'Nessuna configurazione AI attiva',
                'needs_setup': True
            })
        
        # Verifica che il provider sia configurato correttamente
        validation_errors = []
        
        if config.provider == 'ollama':
            if not config.ollama_url:
                validation_errors.append('URL Ollama non configurato')
            if not config.ollama_model:
                validation_errors.append('Modello Ollama non selezionato')
        elif config.provider == 'openrouter':
            if not config.openrouter_api_key:
                validation_errors.append('API Key OpenRouter non configurata')
            if not config.openrouter_model:
                validation_errors.append('Modello OpenRouter non selezionato')
        else:
            validation_errors.append(f'Provider sconosciuto: {config.provider}')
        
        # Controlla che ci siano etichette attive
        from models import Label
        active_labels_count = Label.query.filter(
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).count()
        if active_labels_count == 0:
            validation_errors.append('Nessuna etichetta attiva disponibile')
        
        if validation_errors:
            return jsonify({
                'success': False,
                'error': 'Configurazione AI incompleta',
                'validation_errors': validation_errors,
                'needs_setup': True
            })
        
        # Determina il modello in base al provider
        model_name = config.ollama_model if config.provider == 'ollama' else config.openrouter_model

        return jsonify({
            'success': True,
            'config': {
                'id': config.id,
                'name': config.name,
                'provider': config.provider,
                'model': model_name,
                'active_labels_count': active_labels_count
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_bp.route('/bulk/preview', methods=['POST'])
@login_required
def bulk_annotation_preview():
    """Anteprima job di annotazione batch con template di prompt"""
    try:
        from services.bulk_annotation_service import BulkAnnotationService
        data = request.get_json() or {}

        file_id = data.get('file_id')
        question = data.get('question')
        template_id = data.get('template_id')
        config_id = data.get('config_id')
        options = data.get('options', {})

        if not all([file_id, question, template_id, config_id]):
            return jsonify({'success': False, 'error': 'Parametri mancanti: file_id, question, template_id, config_id richiesti'}), 400

        service = BulkAnnotationService()
        result = service.preview_annotation_job(file_id, question, int(template_id), int(config_id), options)

        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']}), 400

        return jsonify({'success': True, **result})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_bp.route('/bulk/execute', methods=['POST'])
@login_required
def bulk_annotation_execute():
    """Esegue annotazione batch con template di prompt"""
    try:
        from services.bulk_annotation_service import BulkAnnotationService
        data = request.get_json() or {}

        file_id = data.get('file_id')
        question = data.get('question')
        template_id = data.get('template_id')
        config_id = data.get('config_id')
        options = data.get('options', {})

        if not all([file_id, question, template_id, config_id]):
            return jsonify({'success': False, 'error': 'Parametri mancanti: file_id, question, template_id, config_id richiesti'}), 400

        service = BulkAnnotationService()
        result = service.execute_bulk_annotation(
            file_id, question, int(template_id), int(config_id), options,
            user_id=current_user.id
        )

        if not result.get('success'):
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
