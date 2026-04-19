"""
Routes per l'amministrazione del sistema
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, send_file
from flask_login import login_required, current_user
from functools import wraps
import os
import json
import zipfile
from datetime import datetime
import shutil

from models import User, Label, ExcelFile, TextCell, CellAnnotation, db
from models import AIConfiguration, OpenRouterModel, OllamaModel
from services.ollama_client import OllamaClient
from services.openrouter_client import OpenRouterClient, KNOWN_FREE_MODELS, POPULAR_PAID_MODELS

admin_bp = Blueprint('admin', __name__)


def _format_size_bytes(size_bytes):
    """Converte bytes in stringa leggibile."""
    try:
        size = float(size_bytes or 0)
    except (TypeError, ValueError):
        return "N/A"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(size)} {units[unit_idx]}"
    return f"{size:.1f} {units[unit_idx]}"


def _split_model_name(full_name):
    full_name = (full_name or '').strip()
    if not full_name:
        return '', ''
    if ':' in full_name:
        return full_name.split(':', 1)
    return full_name, 'latest'


def _build_ollama_select_models(ollama_url=None, ensure_full_name=None):
    """
    Prepara una lista modelli per i dropdown:
    - prova prima a leggere i modelli live da Ollama (se raggiungibile),
    - fallback ai modelli locali in DB,
    - garantisce la presenza del modello configurato (ensure_full_name).
    """
    models = []

    # Fallback locale (DB)
    db_models = OllamaModel.query.filter_by(is_pulled=True).all()
    for model in db_models:
        models.append({
            'name': model.name,
            'tag': model.tag or 'latest',
            'size': model.size or 0,
            'from_config': False
        })

    # Tentativo live
    if ollama_url:
        try:
            client = OllamaClient(ollama_url)
            if client.test_connection():
                raw_models = client.list_models() or []
                live_models = []
                for model in raw_models:
                    full_name = (model.get('name') or '').strip()
                    if not full_name:
                        continue
                    name, tag = _split_model_name(full_name)
                    live_models.append({
                        'name': name,
                        'tag': tag,
                        'size': model.get('size', 0) or 0,
                        'from_config': False
                    })
                if live_models:
                    models = live_models
        except Exception:
            # Manteniamo fallback DB
            pass

    # Deduplica per full_name
    dedup = {}
    for model in models:
        full_name = f"{model['name']}:{model['tag']}"
        dedup[full_name] = model
    models = list(dedup.values())

    # Garantisce che il modello già salvato sia sempre visibile/selezionabile
    if ensure_full_name:
        name, tag = _split_model_name(ensure_full_name)
        if name:
            full_name = f"{name}:{tag}"
            if full_name not in {f"{m['name']}:{m['tag']}" for m in models}:
                models.insert(0, {
                    'name': name,
                    'tag': tag,
                    'size': 0,
                    'from_config': True
                })

    models.sort(key=lambda item: (item['name'].lower(), item['tag'].lower()))
    return models

def admin_required(f):
    """Decorator per verificare che l'utente sia amministratore"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_manage_users():
            flash('Accesso negato. Sono richiesti privilegi di amministratore.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/users')
@login_required
@admin_required
def manage_users():
    """Gestione degli utenti"""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    """Crea un nuovo utente"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'annotatore')
        
        # Validazione
        if not username or not email or not password:
            flash('Tutti i campi sono obbligatori.', 'error')
            return render_template('admin/create_user.html')
        
        # Verifica se l'utente esiste già
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            flash('Username o email già in uso.', 'error')
            return render_template('admin/create_user.html')
        
        # Crea il nuovo utente
        new_user = User(username=username, email=email, role=role)
        new_user.set_password(password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash(f'Utente "{username}" creato con successo.', 'success')
            return redirect(url_for('admin.manage_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante la creazione dell\'utente: {str(e)}', 'error')
    
    return render_template('admin/create_user.html')

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Modifica un utente"""
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.username = request.form.get('username', user.username)
        user.email = request.form.get('email', user.email)
        user.role = request.form.get('role', user.role)
        user.is_active = request.form.get('is_active') == 'on'
        
        # Cambia password solo se fornita
        new_password = request.form.get('password')
        if new_password:
            user.set_password(new_password)
        
        try:
            db.session.commit()
            flash(f'Utente "{user.username}" aggiornato con successo.', 'success')
            return redirect(url_for('admin.manage_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
    
    return render_template('admin/edit_user.html', user=user)

@admin_bp.route('/users/<int:user_id>/toggle_status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(user_id):
    """Attiva/disattiva un utente"""
    user = User.query.get_or_404(user_id)
    
    # Non permettere di disattivare se stesso
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Non puoi disattivare il tuo account.'})
    
    user.is_active = not user.is_active
    
    try:
        db.session.commit()
        status = 'attivato' if user.is_active else 'disattivato'
        return jsonify({
            'success': True, 
            'message': f'Utente {status} con successo.',
            'is_active': user.is_active
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'})

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Elimina un utente"""
    user = User.query.get_or_404(user_id)
    
    # Non permettere di eliminare se stesso
    if user.id == current_user.id:
        flash('Non puoi eliminare il tuo account.', 'error')
        return redirect(url_for('admin.manage_users'))
    
    try:
        # Le annotazioni verranno eliminate automaticamente per le relazioni cascade
        db.session.delete(user)
        db.session.commit()
        flash(f'Utente "{user.username}" eliminato con successo.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'eliminazione: {str(e)}', 'error')
    
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Profilo utente per cambiare password"""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Validazione
        if not current_password or not new_password or not confirm_password:
            flash('Tutti i campi sono obbligatori.', 'error')
            return render_template('admin/profile.html')
        
        if not current_user.check_password(current_password):
            flash('Password attuale non corretta.', 'error')
            return render_template('admin/profile.html')
        
        if new_password != confirm_password:
            flash('Le nuove password non coincidono.', 'error')
            return render_template('admin/profile.html')
        
        if len(new_password) < 6:
            flash('La password deve essere di almeno 6 caratteri.', 'error')
            return render_template('admin/profile.html')
        
        # Aggiorna la password
        current_user.set_password(new_password)
        
        try:
            db.session.commit()
            flash('Password aggiornata con successo.', 'success')
            return redirect(url_for('admin.profile'))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
    
    return render_template('admin/profile.html')

@admin_bp.route('/backup')
@login_required
@admin_required
def backup_page():
    """Pagina di gestione backup"""
    # Statistiche del sistema
    stats = {
        'users_count': User.query.count(),
        'labels_count': Label.query.count(),
        'files_count': ExcelFile.query.count(),
        'cells_count': TextCell.query.count(),
        'annotations_count': CellAnnotation.query.count()
    }
    
    return render_template('admin/backup.html', stats=stats)

@admin_bp.route('/backup/create')
@login_required
@admin_required
def create_backup():
    """Crea un backup completo del sistema"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = f'backup_{timestamp}'
        backup_path = os.path.join('backups', backup_dir)
        
        # Crea la directory di backup
        os.makedirs(backup_path, exist_ok=True)
        os.makedirs('backups', exist_ok=True)
        
        # Backup del database
        db_source = 'instance/analisi_mu.db'
        if os.path.exists(db_source):
            shutil.copy2(db_source, os.path.join(backup_path, 'analisi_mu.db'))
        
        # Backup dei file caricati
        uploads_source = 'uploads'
        if os.path.exists(uploads_source):
            shutil.copytree(uploads_source, os.path.join(backup_path, 'uploads'))
        
        # Backup delle configurazioni (esporta dati in JSON)
        backup_data = {
            'created_at': datetime.now().isoformat(),
            'users': [{
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'role': u.role,
                'is_active': u.is_active,
                'created_at': u.created_at.isoformat() if u.created_at else None
            } for u in User.query.all()],
            'labels': [{
                'id': l.id,
                'name': l.name,
                'description': l.description,
                'category': l.category,
                'color': l.color
            } for l in Label.query.all()],
            'excel_files': [{
                'id': f.id,
                'original_filename': f.original_filename,
                'uploaded_at': f.uploaded_at.isoformat() if f.uploaded_at else None,
                'uploaded_by': f.uploaded_by
            } for f in ExcelFile.query.all()]
        }
        
        with open(os.path.join(backup_path, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        
        # Crea un file ZIP
        zip_path = f'backups/backup_{timestamp}.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_path)
                    zipf.write(file_path, arcname)
        
        # Rimuovi la directory temporanea
        shutil.rmtree(backup_path)
        
        flash(f'Backup creato con successo: backup_{timestamp}.zip', 'success')
        return send_file(zip_path, as_attachment=True, download_name=f'backup_{timestamp}.zip')
        
    except Exception as e:
        flash(f'Errore durante la creazione del backup: {str(e)}', 'error')
        return redirect(url_for('admin.backup_page'))

@admin_bp.route('/system_stats')
@login_required
@admin_required
def system_stats():
    """Statistiche del sistema"""
    stats = {
        'users': {
            'total': User.query.count(),
            'active': User.query.filter_by(is_active=True).count(),
            'administrators': User.query.filter_by(role='amministratore').count(),
            'annotators': User.query.filter_by(role='annotatore').count()
        },
        'content': {
            'labels': Label.query.count(),
            'excel_files': ExcelFile.query.count(),
            'text_cells': TextCell.query.count(),
            'annotations': CellAnnotation.query.count()
        },
        'recent_activity': {
            'recent_users': User.query.order_by(User.last_login.desc()).limit(5).all(),
            'recent_files': ExcelFile.query.order_by(ExcelFile.uploaded_at.desc()).limit(5).all()
        }
    }
    
    return render_template('admin/system_stats.html', stats=stats)

@admin_bp.route('/ai-config')
@login_required
@admin_required
def ai_configuration():
    """Configurazione AI"""
    configurations = AIConfiguration.query.order_by(AIConfiguration.created_at.desc()).all()
    ollama_models = OllamaModel.query.all()
    openrouter_models = OpenRouterModel.query.all()
    
    return render_template('admin/ai_configuration.html', 
                         configurations=configurations,
                         ollama_models=ollama_models,
                         openrouter_models=openrouter_models)

@admin_bp.route('/ai-config/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_ai_config():
    """Crea una nuova configurazione AI"""
    if request.method == 'POST':
        provider = request.form.get('provider')
        name = request.form.get('name')
        
        # Disattiva le altre configurazioni se questa è marcata come attiva
        is_active = request.form.get('is_active') == 'on'
        if is_active:
            AIConfiguration.query.update({'is_active': False})
        
        config = AIConfiguration(
            provider=provider,
            name=name,
            is_active=is_active,
            max_tokens=int(request.form.get('max_tokens', 1000)),
            temperature=float(request.form.get('temperature', 0.7)),
            system_prompt=request.form.get('system_prompt', '')
        )
        
        if provider == 'ollama':
            config.ollama_url = request.form.get('ollama_url')
            config.ollama_model = request.form.get('ollama_model')
        elif provider == 'openrouter':
            config.openrouter_api_key = request.form.get('openrouter_api_key')
            config.openrouter_model = request.form.get('openrouter_model')
        
        try:
            db.session.add(config)
            db.session.commit()
            flash('Configurazione AI creata con successo.', 'success')
            return redirect(url_for('admin.ai_configuration'))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore nella creazione: {str(e)}', 'error')
    
    # Carica modelli per dropdown (prefer live, fallback DB)
    active_ollama = AIConfiguration.query.filter_by(provider='ollama', is_active=True).first()
    live_url = active_ollama.ollama_url if active_ollama and active_ollama.ollama_url else None
    ollama_models = _build_ollama_select_models(ollama_url=live_url)
    openrouter_models = OpenRouterModel.query.filter_by(is_available=True).all()
    
    return render_template('admin/create_ai_config.html',
                         ollama_models=ollama_models,
                         openrouter_models=openrouter_models)

@admin_bp.route('/ai-config/edit/<int:config_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_ai_config(config_id):
    """Modifica una configurazione AI"""
    config = AIConfiguration.query.get_or_404(config_id)
    
    if request.method == 'POST':
        config.name = request.form.get('name')
        config.provider = request.form.get('provider')
        config.is_active = request.form.get('is_active') == 'on'
        config.max_tokens = int(request.form.get('max_tokens', 1000))
        config.temperature = float(request.form.get('temperature', 0.7))
        config.system_prompt = request.form.get('system_prompt', '')
        
        if config.provider == 'ollama':
            config.ollama_url = request.form.get('ollama_url')
            config.ollama_model = request.form.get('ollama_model')
            config.openrouter_api_key = None
            config.openrouter_model = None
        else:  # openrouter
            config.openrouter_api_key = request.form.get('openrouter_api_key')
            config.openrouter_model = request.form.get('openrouter_model')
            config.ollama_url = None
            config.ollama_model = None
        
        config.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Configurazione AI aggiornata con successo!', 'success')
            return redirect(url_for('admin.ai_configuration'))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
    
    # Carica modelli per dropdown (prefer live per URL configurato, fallback DB)
    ollama_models = _build_ollama_select_models(
        ollama_url=config.ollama_url if config.provider == 'ollama' else None,
        ensure_full_name=config.ollama_model if config.provider == 'ollama' else None
    )
    openrouter_models = OpenRouterModel.query.filter_by(is_available=True).all()
    
    return render_template('admin/edit_ai_config.html', 
                         config=config,
                         ollama_models=ollama_models,
                         openrouter_models=openrouter_models)

@admin_bp.route('/ai-config/<int:config_id>/activate', methods=['POST'])
@login_required
@admin_required
def activate_ai_config(config_id):
    """Attiva una configurazione AI"""
    try:
        # Disattiva tutte le configurazioni
        AIConfiguration.query.update({'is_active': False})
        
        # Attiva quella selezionata
        config = AIConfiguration.query.get_or_404(config_id)
        config.is_active = True
        
        db.session.commit()
        flash('Configurazione attivata con successo.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore nell\'attivazione: {str(e)}', 'error')
    
    return redirect(url_for('admin.ai_configuration'))

@admin_bp.route('/ai-config/<int:config_id>/test', methods=['POST'])
@login_required
@admin_required
def test_ai_config(config_id):
    """Testa una configurazione AI"""
    config = AIConfiguration.query.get_or_404(config_id)
    
    try:
        if config.provider == 'ollama':
            client = OllamaClient(config.ollama_url)
            is_connected = client.test_connection()
            
            if is_connected:
                # Testa anche il modello specifico
                models = client.list_models()
                model_available = any(m['name'] == config.ollama_model for m in models)
                
                if model_available:
                    return jsonify({'success': True, 'message': 'Connessione riuscita e modello disponibile'})
                else:
                    return jsonify({'success': False, 'message': f'Modello {config.ollama_model} non trovato'})
            else:
                return jsonify({'success': False, 'message': 'Impossibile connettersi a Ollama'})
                
        elif config.provider == 'openrouter':
            client = OpenRouterClient(config.openrouter_api_key)
            is_connected = client.test_connection()
            
            if is_connected:
                return jsonify({'success': True, 'message': 'API key valida'})
            else:
                return jsonify({'success': False, 'message': 'API key non valida'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/test-ai-config-preview', methods=['POST'])
@login_required
@admin_required
def test_ai_config_preview():
    """Testa una configurazione AI in preview (prima di salvarla)"""
    try:
        data = request.get_json()
        provider = data.get('provider')
        
        if provider == 'ollama':
            url = data.get('ollama_url')
            model = data.get('ollama_model')
            
            if not url or not model:
                return jsonify({'success': False, 'message': 'URL e modello Ollama richiesti'})
            
            client = OllamaClient(url)
            is_connected = client.test_connection()
            
            if is_connected:
                # Verifica se il modello è disponibile
                models = client.list_models()
                model_available = any(m['name'] == model for m in models)
                
                if model_available:
                    return jsonify({'success': True, 'message': f'Connessione riuscita! Modello {model} disponibile.'})
                else:
                    return jsonify({'success': False, 'message': f'Connesso ma modello {model} non trovato'})
            else:
                return jsonify({'success': False, 'message': f'Impossibile connettersi a {url}'})
                
        elif provider == 'openrouter':
            api_key = data.get('openrouter_api_key')
            model = data.get('openrouter_model')
            
            if not api_key or not model:
                return jsonify({'success': False, 'message': 'API key e modello OpenRouter richiesti'})
            
            client = OpenRouterClient(api_key)
            is_connected = client.test_connection()
            
            if is_connected:
                return jsonify({'success': True, 'message': f'API key valida! Modello {model} configurato.'})
            else:
                return jsonify({'success': False, 'message': 'API key non valida'})
                
        else:
            return jsonify({'success': False, 'message': 'Provider non valido'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore durante il test: {str(e)}'})


@admin_bp.route('/ollama/models/live')
@login_required
@admin_required
def ollama_live_models():
    """Restituisce i modelli presenti su un endpoint Ollama specifico."""
    ollama_url = (request.args.get('url') or '').strip()

    if not ollama_url:
        active_ollama = AIConfiguration.query.filter_by(provider='ollama', is_active=True).first()
        ollama_url = active_ollama.ollama_url if active_ollama and active_ollama.ollama_url else 'http://127.0.0.1:11434'

    try:
        client = OllamaClient(ollama_url)
        if not client.test_connection():
            return jsonify({'success': False, 'message': f'Impossibile connettersi a {ollama_url}'}), 400

        raw_models = client.list_models()

        models = []
        for model in raw_models:
            full_name = (model.get('name') or '').strip()
            if not full_name:
                continue

            if ':' in full_name:
                name, tag = full_name.split(':', 1)
            else:
                name, tag = full_name, 'latest'

            details = model.get('details') or {}
            size_bytes = model.get('size', 0) or 0

            models.append({
                'name': name,
                'tag': tag,
                'full_name': f'{name}:{tag}',
                'size_bytes': size_bytes,
                'size_human': _format_size_bytes(size_bytes),
                'family': details.get('family') or '',
                'parameter_size': details.get('parameter_size') or '',
                'quantization_level': details.get('quantization_level') or '',
            })

        models.sort(key=lambda item: (item['name'].lower(), item['tag'].lower()))

        return jsonify({
            'success': True,
            'url': ollama_url,
            'count': len(models),
            'models': models
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@admin_bp.route('/ollama/models')
@login_required
@admin_required
def ollama_models():
    """Gestione modelli Ollama"""
    # Ottiene la configurazione Ollama attiva
    ollama_config = AIConfiguration.query.filter_by(provider='ollama', is_active=True).first()
    
    if not ollama_config:
        flash('Nessuna configurazione Ollama attiva trovata.', 'error')
        return redirect(url_for('admin.ai_configuration'))
    
    client = OllamaClient(ollama_config.ollama_url)
    
    # Aggiorna i modelli nel database
    try:
        api_models = client.list_models()
        
        # Pulisci i modelli esistenti
        OllamaModel.query.delete()
        
        # Aggiungi i modelli correnti
        for model in api_models:
            db_model = OllamaModel(
                name=model.get('name', '').split(':')[0],
                tag=model.get('name', '').split(':')[1] if ':' in model.get('name', '') else 'latest',
                size=model.get('size', 0),
                digest=model.get('digest', ''),
                modified_at=datetime.now(),
                is_pulled=True
            )
            db.session.add(db_model)
        
        db.session.commit()
    except Exception as e:
        flash(f'Errore nell\'aggiornamento modelli: {str(e)}', 'error')
    
    installed_models = OllamaModel.query.all()
    available_models = client.search_models()
    
    return render_template('admin/ollama_models.html',
                         installed_models=installed_models,
                         available_models=available_models,
                         ollama_url=ollama_config.ollama_url)

@admin_bp.route('/ollama/pull/<model_name>', methods=['POST'])
@login_required
@admin_required
def ollama_pull_model(model_name):
    """Scarica un modello Ollama"""
    ollama_config = AIConfiguration.query.filter_by(provider='ollama', is_active=True).first()
    
    if not ollama_config:
        return jsonify({'error': 'Nessuna configurazione Ollama attiva'})
    
    client = OllamaClient(ollama_config.ollama_url)
    
    try:
        # Crea il record nel database
        db_model = OllamaModel(
            name=model_name.split(':')[0],
            tag=model_name.split(':')[1] if ':' in model_name else 'latest',
            is_pulled=False,
            pull_progress=0.0
        )
        db.session.add(db_model)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Download di {model_name} avviato'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)})

@admin_bp.route('/ollama/delete/<model_name>', methods=['POST'])
@login_required
@admin_required
def ollama_delete_model(model_name):
    """Elimina un modello Ollama"""
    ollama_config = AIConfiguration.query.filter_by(provider='ollama', is_active=True).first()
    
    if not ollama_config:
        return jsonify({'error': 'Nessuna configurazione Ollama attiva'})
    
    client = OllamaClient(ollama_config.ollama_url)
    
    try:
        success = client.delete_model(model_name)
        
        if success:
            # Rimuovi dal database
            name_part = model_name.split(':')[0]
            tag_part = model_name.split(':')[1] if ':' in model_name else 'latest'
            
            OllamaModel.query.filter_by(name=name_part, tag=tag_part).delete()
            db.session.commit()
            
            return jsonify({'success': True, 'message': f'Modello {model_name} eliminato'})
        else:
            return jsonify({'error': 'Errore nell\'eliminazione del modello'})
            
    except Exception as e:
        return jsonify({'error': str(e)})

@admin_bp.route('/openrouter/models')
@login_required
@admin_required
def openrouter_models():
    """Gestione modelli OpenRouter"""
    openrouter_config = AIConfiguration.query.filter_by(provider='openrouter', is_active=True).first()
    
    free_models = KNOWN_FREE_MODELS
    paid_models = POPULAR_PAID_MODELS
    
    # Se c'è una configurazione attiva, prova a ottenere i modelli dall'API
    if openrouter_config and openrouter_config.openrouter_api_key:
        try:
            client = OpenRouterClient(openrouter_config.openrouter_api_key)
            api_free_models = client.get_free_models()
            api_paid_models = client.get_paid_models()
            
            if api_free_models:
                free_models = api_free_models
            if api_paid_models:
                paid_models = api_paid_models[:20]  # Limita a 20 per non sovraccaricare l'UI
                
        except Exception as e:
            flash(f'Errore nel recupero modelli da OpenRouter: {str(e)}', 'warning')
    
    return render_template('admin/openrouter_models.html',
                         free_models=free_models,
                         paid_models=paid_models,
                         has_api_key=bool(openrouter_config and openrouter_config.openrouter_api_key))

@admin_bp.route('/openrouter/usage')
@login_required  
@admin_required
def openrouter_usage():
    """Visualizza l'utilizzo di OpenRouter"""
    openrouter_config = AIConfiguration.query.filter_by(provider='openrouter', is_active=True).first()
    
    if not openrouter_config or not openrouter_config.openrouter_api_key:
        flash('Nessuna configurazione OpenRouter attiva con API key.', 'error')
        return redirect(url_for('admin.ai_configuration'))
    
    try:
        client = OpenRouterClient(openrouter_config.openrouter_api_key)
        usage_data = client.get_usage()
        
        return render_template('admin/openrouter_usage.html', usage=usage_data)
        
    except Exception as e:
        flash(f'Errore nel recupero dati utilizzo: {str(e)}', 'error')
        return redirect(url_for('admin.ai_configuration'))

@admin_bp.route('/ai-config/delete/<int:config_id>', methods=['POST'])
@login_required
@admin_required
def delete_ai_config(config_id):
    """Elimina una configurazione AI"""
    config = AIConfiguration.query.get_or_404(config_id)
    
    try:
        db.session.delete(config)
        db.session.commit()
        flash(f'Configurazione "{config.name}" eliminata con successo!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'eliminazione: {str(e)}', 'error')
    
    return redirect(url_for('admin.ai_configuration'))

@admin_bp.route('/ai-config/toggle/<int:config_id>', methods=['POST'])
@login_required
@admin_required
def toggle_ai_config(config_id):
    """Attiva/disattiva una configurazione AI"""
    config = AIConfiguration.query.get_or_404(config_id)
    
    # Se stiamo attivando questa configurazione, disattiviamo tutte le altre
    if not config.is_active:
        AIConfiguration.query.filter_by(is_active=True).update({'is_active': False})
    
    config.is_active = not config.is_active
    config.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        status = 'attivata' if config.is_active else 'disattivata'
        flash(f'Configurazione "{config.name}" {status} con successo!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'operazione: {str(e)}', 'error')
    
    return redirect(url_for('admin.ai_configuration'))

@admin_bp.route('/ollama/test-model', methods=['POST'])
@login_required
@admin_required
def test_ollama_model():
    """Testa un modello Ollama specifico"""
    try:
        data = request.get_json()
        model_name = data.get('model')
        
        if not model_name:
            return jsonify({'success': False, 'message': 'Nome modello richiesto'})
        
        # Ottiene la configurazione Ollama attiva
        ollama_config = AIConfiguration.query.filter_by(provider='ollama', is_active=True).first()
        
        if not ollama_config:
            return jsonify({'success': False, 'message': 'Nessuna configurazione Ollama attiva'})
        
        client = OllamaClient(ollama_config.ollama_url)
        
        # Test semplice di generazione
        try:
            response = client.chat(model_name, "Ciao! Rispondi solo con 'OK' per confermare che funzioni.")
            if response and 'OK' in response.upper():
                return jsonify({'success': True, 'message': f'Modello {model_name} funziona correttamente!'})
            else:
                return jsonify({'success': True, 'message': f'Modello {model_name} risponde ma output inaspettato'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'Errore nel test del modello: {str(e)}'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore generale: {str(e)}'})

@admin_bp.route('/openrouter/test-model', methods=['POST'])
@login_required
@admin_required
def test_openrouter_model():
    """Testa un modello OpenRouter specifico"""
    try:
        data = request.get_json()
        model_name = data.get('model')
        
        if not model_name:
            return jsonify({'success': False, 'message': 'Nome modello richiesto'})
        
        # Ottiene la configurazione OpenRouter attiva
        openrouter_config = AIConfiguration.query.filter_by(provider='openrouter', is_active=True).first()
        
        if not openrouter_config or not openrouter_config.openrouter_api_key:
            return jsonify({'success': False, 'message': 'Nessuna configurazione OpenRouter attiva con API key'})
        
        client = OpenRouterClient(openrouter_config.openrouter_api_key)
        
        # Test semplice di generazione
        try:
            response = client.chat(model_name, "Ciao! Rispondi solo con 'OK' per confermare che funzioni.")
            if response and 'OK' in response.upper():
                return jsonify({'success': True, 'message': f'Modello {model_name} funziona correttamente!'})
            else:
                return jsonify({'success': True, 'message': f'Modello {model_name} risponde ma output inaspettato'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'Errore nel test del modello: {str(e)}'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore generale: {str(e)}'})

@admin_bp.route('/templates')
@login_required
@admin_required
def manage_templates():
    """Gestione dei template AI"""
    from models import AIPromptTemplate
    templates = AIPromptTemplate.query.order_by(AIPromptTemplate.created_at.desc()).all()
    return render_template('admin/templates.html', templates=templates)

@admin_bp.route('/templates/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_template():
    """Crea un nuovo template AI"""
    from models import AIPromptTemplate
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        base_prompt = request.form.get('base_prompt', '').strip()
        
        # Validazione
        if not name:
            flash('Nome template richiesto', 'error')
            return render_template('admin/template_form.html')
            
        if not base_prompt:
            flash('Prompt base richiesto', 'error')
            return render_template('admin/template_form.html')
            
        # Verifica unicità del nome
        existing = AIPromptTemplate.query.filter_by(name=name).first()
        if existing:
            flash('Un template con questo nome esiste già', 'error')
            return render_template('admin/template_form.html', 
                                 name=name, description=description, 
                                 category=category, base_prompt=base_prompt)
        
        try:
            # Crea il nuovo template
            template = AIPromptTemplate(
                name=name,
                description=description,
                category=category,
                base_prompt=base_prompt,
                is_active=True
            )
            
            db.session.add(template)
            db.session.commit()
            
            flash(f'Template "{name}" creato con successo!', 'success')
            return redirect(url_for('admin.manage_templates'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante la creazione: {str(e)}', 'error')
            return render_template('admin/template_form.html', 
                                 name=name, description=description, 
                                 category=category, base_prompt=base_prompt)
    
    return render_template('admin/template_form.html')

@admin_bp.route('/templates/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_template(template_id):
    """Modifica un template esistente"""
    from models import AIPromptTemplate
    
    template = AIPromptTemplate.query.get_or_404(template_id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        base_prompt = request.form.get('base_prompt', '').strip()
        is_active = request.form.get('is_active') == 'on'
        
        # Validazione
        if not name:
            flash('Nome template richiesto', 'error')
            return render_template('admin/template_form.html', template=template)
            
        if not base_prompt:
            flash('Prompt base richiesto', 'error')
            return render_template('admin/template_form.html', template=template)
            
        # Verifica unicità del nome (escluso il template corrente)
        existing = AIPromptTemplate.query.filter(
            AIPromptTemplate.name == name,
            AIPromptTemplate.id != template_id
        ).first()
        if existing:
            flash('Un template con questo nome esiste già', 'error')
            return render_template('admin/template_form.html', template=template)
        
        try:
            # Aggiorna il template
            template.name = name
            template.description = description
            template.category = category
            template.base_prompt = base_prompt
            template.is_active = is_active
            template.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Template "{name}" aggiornato con successo!', 'success')
            return redirect(url_for('admin.manage_templates'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
            
    return render_template('admin/template_form.html', template=template)

@admin_bp.route('/templates/<int:template_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_template(template_id):
    """Attiva/disattiva un template"""
    from models import AIPromptTemplate
    
    template = AIPromptTemplate.query.get_or_404(template_id)
    
    try:
        template.is_active = not template.is_active
        template.updated_at = datetime.utcnow()
        db.session.commit()
        
        status = "attivato" if template.is_active else "disattivato"
        return jsonify({
            'success': True, 
            'message': f'Template "{template.name}" {status}',
            'is_active': template.is_active
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_template(template_id):
    """Elimina un template"""
    from models import AIPromptTemplate
    
    template = AIPromptTemplate.query.get_or_404(template_id)
    
    try:
        template_name = template.name
        db.session.delete(template)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Template "{template_name}" eliminato con successo'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/templates/<int:template_id>/preview', methods=['POST'])
@login_required
@admin_required
def preview_template(template_id):
    """Anteprima di un template con dati di esempio"""
    from models import AIPromptTemplate, Label, LabelCategory
    
    template = AIPromptTemplate.query.get_or_404(template_id)
    
    try:
        # Ottiene alcune etichette di esempio
        labels = Label.query.filter_by(is_active=True).limit(10).all()
        
        # Testi di esempio
        sample_texts = [
            "L'AI mi ha aiutato molto a comprendere meglio l'argomento",
            "Sono preoccupato per la privacy dei miei dati",
            "Il chatbot è stato utile ma a volte dava risposte sbagliate"
        ]
        
        # Categorie di esempio (se disponibili)
        categories = [cat.name for cat in LabelCategory.query.filter_by(is_active=True).limit(3).all()]
        if not categories:
            categories = ['Sentiment Analysis', 'Usage Patterns']
        
        # Genera l'anteprima del prompt
        preview_prompt = template.build_prompt_with_categories(categories, labels, sample_texts)
        
        return jsonify({
            'success': True,
            'preview': preview_prompt,
            'categories_used': categories,
            'labels_count': len(labels),
            'sample_texts_count': len(sample_texts)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/templates/categories')
@login_required
@admin_required
def get_template_categories():
    """Ottiene le categorie utilizzate nei template"""
    from models import AIPromptTemplate
    
    templates = AIPromptTemplate.query.filter_by(is_active=True).all()
    categories = list(set([t.category for t in templates if t.category]))
    
    return jsonify({
        'success': True,
        'categories': sorted(categories)
    })
