"""
Routes per la gestione delle etichette
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from models import Label, CellAnnotation, Category, TaxonomyMergeAudit, db
from forms import LabelForm, CategoryForm
from services.taxonomy_service import TaxonomyService

labels_bp = Blueprint('labels', __name__)


def _require_admin_or_redirect(next_endpoint):
    """Guard centralizzato per operazioni strutturali tassonomia."""
    if current_user.is_admin:
        return None
    flash('Solo gli amministratori possono modificare la tassonomia.', 'error')
    return redirect(url_for(next_endpoint))

@labels_bp.route('/')
@login_required
def list_labels():
    """Lista di tutte le etichette"""
    page = request.args.get('page', 1, type=int)
    category_filter = request.args.get('category')
    show_inactive = request.args.get('show_inactive', False, type=bool)
    show_all = request.args.get('show_all', False, type=bool)

    # Query di base per etichette attive con JOIN esplicito per categoria
    query = Label.query.options(db.joinedload(Label.category_obj))
    if not show_inactive:
        query = query.filter(
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        )

    current_category = None
    if category_filter == 'none':
        query = query.filter(Label.category_id == None)
        current_category = 'none'
    elif category_filter and category_filter.isdigit():
        query = query.filter_by(category_id=int(category_filter))
        current_category = int(category_filter)

    # Gestione paginazione: se show_all è True, mostra tutto senza paginazione
    if show_all:
        labels = query.order_by(Label.name).all()
        # Simula oggetto paginazione per compatibilità template
        class FakePagination:
            def __init__(self, items):
                self.items = items
                self.page = 1
                self.pages = 1
                self.has_prev = False
                self.has_next = False
                self.prev_num = None
                self.next_num = None
                self.total = len(items)
                self.per_page = len(items)
        
        labels = FakePagination(labels)
    else:
        labels = query.order_by(Label.name).paginate(
            page=page, per_page=20, error_out=False
        )

    # Liste delle categorie attive per il filtro
    categories = Category.query.filter(
        Category.is_active == True,  # noqa: E712
        Category.merged_into_category_id.is_(None)
    ).order_by(Category.name).all()
    
    # Statistiche per etichette senza categoria
    uncategorized_count = Label.query.filter(
        Label.category_id.is_(None),
        Label.is_active == True,  # noqa: E712
        Label.merged_into_label_id.is_(None)
    ).count()

    return render_template('labels/list_labels.html', 
                         labels=labels,
                         categories=categories,
                         current_category=current_category,
                         show_inactive=show_inactive,
                         show_all=show_all,
                         uncategorized_count=uncategorized_count)

@labels_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_label():
    """Crea una nuova etichetta"""
    denied = _require_admin_or_redirect('labels.list_labels')
    if denied:
        return denied

    form = LabelForm()
    next_url = request.args.get('next') or request.form.get('next')

    def render_form():
        categories = Category.query.filter(
            Category.is_active == True,  # noqa: E712
            Category.merged_into_category_id.is_(None)
        ).all()
        category_colors = {cat.id: cat.color for cat in categories}
        return render_template('labels/create_label.html', form=form, category_colors=category_colors)
    
    if form.validate_on_submit():
        taxonomy_service = TaxonomyService()
        label_name = form.name.data.strip()

        # Verifica se l'etichetta esiste già (match esatto legacy)
        existing_label = Label.query.filter_by(name=label_name).first()
        
        if existing_label:
            if existing_label.is_active and existing_label.merged_into_label_id is None:
                flash('Un\'etichetta canonica con questo nome esiste già.', 'error')
            elif existing_label.merged_into_label_id:
                flash(
                    f'L\'etichetta "{label_name}" è deprecata da merge. '
                    'Usa l\'etichetta canonica attiva.',
                    'error'
                )
            else:
                flash('Esiste già un\'etichetta inattiva con questo nome. Riattivala invece di ricrearla.', 'error')
            return render_form()

        # Vocabolario controllato: no collisioni normalizzate con canonical/alias attivi
        allowed, error_message = taxonomy_service.ensure_name_allowed('label', label_name)
        if not allowed:
            flash(error_message, 'error')
            return render_form()

        # Gestione della categoria
        category_id = None
        category = None
        legacy_category_name = None
        if form.new_category.data and form.new_category.data.strip():
            new_category_name = form.new_category.data.strip()

            # Se collide con categoria canonica attiva, riusa quella; se collide con alias -> blocca
            category_conflict = taxonomy_service.find_name_conflict('category', new_category_name)
            if category_conflict and category_conflict.get('type') == 'canonical':
                category = Category.query.get(category_conflict.get('id'))
                category_id = category.id if category else None
            else:
                if category_conflict:
                    flash(
                        'Nome categoria non consentito: collisione con alias tassonomico attivo. '
                        'Seleziona una categoria esistente o usa un nome differente.',
                        'error'
                    )
                    return render_form()

                category = Category(
                    name=new_category_name,
                    description=form.new_category_description.data,
                    color='#6c757d',
                    is_active=True
                )
                db.session.add(category)
                db.session.flush()
                category_id = category.id
        elif form.category_id.data and form.category_id.data != 0:
            category = Category.query.get(form.category_id.data)
            if not category or not category.is_active or category.merged_into_category_id is not None:
                flash('La categoria selezionata non è disponibile o è deprecata.', 'error')
                return render_form()
            category_id = category.id
        
        if category:
            legacy_category_name = category.name
        
        # Determina il colore dell'etichetta
        label_color = form.color.data or '#007bff'
        if category_id:
            # Se ha una categoria, usa il colore della categoria a meno che non sia stato specificato un colore diverso nel form
            category = category or Category.query.get(category_id)
            if category and (not form.color.data or form.color.data == '#007bff'):
                label_color = category.color
        
        # Crea l'etichetta
        label = Label(
            name=label_name,
            description=form.description.data,
            category_id=category_id,
            category=legacy_category_name,
            color=label_color,
            is_active=True,
            merged_into_label_id=None
        )
        
        try:
            db.session.add(label)
            db.session.commit()
            flash('Etichetta creata con successo!', 'success')
            if next_url:
                return redirect(next_url)
            return redirect(url_for('labels.list_labels'))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante la creazione: {str(e)}', 'error')
    
    return render_form()

@labels_bp.route('/edit/<int:label_id>', methods=['GET', 'POST'])
@login_required
def edit_label(label_id):
    """Modifica un'etichetta esistente"""
    denied = _require_admin_or_redirect('labels.list_labels')
    if denied:
        return denied

    label = Label.query.get_or_404(label_id)
    if label.merged_into_label_id is not None:
        flash('Questa etichetta è deprecata da merge e non può essere modificata.', 'error')
        return redirect(url_for('labels.list_labels', show_inactive=True))

    form = LabelForm(obj=label)
    
    if form.validate_on_submit():
        taxonomy_service = TaxonomyService()
        new_name = form.name.data.strip()

        # Verifica se un'altra etichetta ha già questo nome
        existing_label = Label.query.filter(
            Label.name == new_name,
            Label.id != label_id
        ).first()
        
        if existing_label:
            flash('Un\'altra etichetta con questo nome esiste già.', 'error')
        else:
            allowed, error_message = taxonomy_service.ensure_name_allowed(
                entity_type='label',
                name=new_name,
                exclude_id=label.id
            )
            if not allowed:
                flash(error_message, 'error')
                return render_template('labels/edit_label.html', form=form, label=label)

            label.name = new_name
            label.description = form.description.data
            
            # Gestione categoria e colore
            old_category_id = label.category_id
            new_category_id = form.category_id.data if form.category_id.data != 0 else None
            category_obj = Category.query.get(new_category_id) if new_category_id else None
            if new_category_id and (not category_obj or not category_obj.is_active or category_obj.merged_into_category_id is not None):
                flash('La categoria selezionata non è disponibile o è deprecata.', 'error')
                return render_template('labels/edit_label.html', form=form, label=label)

            label.category_id = new_category_id
            label.category = category_obj.name if category_obj else None
            
            # Se la categoria è cambiata, aggiorna il colore se l'etichetta non ha un colore personalizzato
            if old_category_id != new_category_id:
                if new_category_id:
                    # Ha una nuova categoria: eredita il colore se non personalizzato
                    if category_obj and not label.has_custom_color():
                        label.color = category_obj.color
                # Se viene rimossa la categoria, mantiene il colore attuale
            else:
                # Se la categoria non è cambiata, aggiorna comunque il colore dal form
                label.color = form.color.data
            
            db.session.commit()
            
            flash('Etichetta aggiornata con successo!', 'success')
            return redirect(url_for('labels.list_labels'))
    
    return render_template('labels/edit_label.html', form=form, label=label)

@labels_bp.route('/delete/<int:label_id>', methods=['POST'])
@login_required
def delete_label(label_id):
    """Depreca/disattiva un'etichetta preservando lo storico."""
    denied = _require_admin_or_redirect('labels.list_labels')
    if denied:
        return denied

    label = Label.query.get_or_404(label_id)
    
    # Conta le annotazioni associate
    annotation_count = CellAnnotation.query.filter_by(label_id=label_id).count()

    # Politica tassonomia: no hard-delete, solo deprecazione/disattivazione
    label.is_active = False
    db.session.commit()
    flash(
        f'Etichetta "{label.name}" deprecata/disattivata. '
        f'Annotazioni preservate: {annotation_count}.',
        'success'
    )
    
    return redirect(url_for('labels.list_labels'))

@labels_bp.route('/toggle-active/<int:label_id>', methods=['POST'])
@login_required
def toggle_label_active(label_id):
    """Attiva/disattiva un'etichetta"""
    denied = _require_admin_or_redirect('labels.list_labels')
    if denied:
        return denied

    label = Label.query.get_or_404(label_id)

    # Su riattivazione applica regole vocabolario controllato
    if not label.is_active:
        if label.merged_into_label_id is not None:
            flash(
                'Etichetta deprecata da merge: non può essere riattivata. '
                'Usa l\'etichetta canonica di destinazione.',
                'error'
            )
            return redirect(url_for('labels.list_labels', show_inactive=True))

        taxonomy_service = TaxonomyService()
        allowed, error_message = taxonomy_service.ensure_name_allowed(
            entity_type='label',
            name=label.name,
            exclude_id=label.id
        )
        if not allowed:
            flash(f'Riattivazione bloccata: {error_message}', 'error')
            return redirect(url_for('labels.list_labels', show_inactive=True))

    label.is_active = not label.is_active
    status = 'attivata' if label.is_active else 'disattivata'

    db.session.commit()
    flash(f'Etichetta "{label.name}" {status} con successo.', 'success')
    
    return redirect(url_for('labels.list_labels', show_inactive=True))

@labels_bp.route('/api/search')
@login_required
def api_search_labels():
    """API per la ricerca di etichette (per autocompletamento)"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify([])
    
    labels = Label.query.options(db.joinedload(Label.category_obj))\
                       .filter(Label.name.contains(query))\
                       .filter(Label.is_active == True, Label.merged_into_label_id.is_(None))\
                       .order_by(Label.name)\
                       .limit(10)\
                       .all()
    
    data = []
    for label in labels:
        if label.category_obj and (not label.category_obj.is_active or label.category_obj.merged_into_category_id is not None):
            continue
        data.append({
            'id': label.id,
            'name': label.name,
            'description': label.description,
            'category': label.category_obj.name if label.category_obj else None,
            'color': label.get_effective_color()
        })
    return jsonify(data)

@labels_bp.route('/merge', methods=['GET', 'POST'])
@login_required
def merge_labels():
    """Unisce due o più etichette in una sola"""
    denied = _require_admin_or_redirect('labels.list_labels')
    if denied:
        return denied

    taxonomy_service = TaxonomyService()

    if request.method == 'POST':
        source_label_ids = request.form.getlist('source_labels')
        target_label_id = request.form.get('target_label')
        dry_run_only = request.form.get('dry_run') == 'true'
        
        if not source_label_ids or not target_label_id:
            flash('Seleziona almeno un\'etichetta di origine e una di destinazione.', 'error')
            return redirect(url_for('labels.merge_labels'))
        
        # Converte gli ID in interi
        try:
            source_label_ids = [int(id) for id in source_label_ids]
            target_label_id = int(target_label_id)
        except ValueError:
            flash('ID etichette non validi.', 'error')
            return redirect(url_for('labels.merge_labels'))
        
        # Verifica che l'etichetta target non sia tra quelle di origine
        if target_label_id in source_label_ids:
            flash('L\'etichetta di destinazione non può essere tra quelle di origine.', 'error')
            return redirect(url_for('labels.merge_labels'))

        try:
            if dry_run_only:
                result = taxonomy_service.dry_run_label_merge(
                    source_label_ids=source_label_ids,
                    target_label_id=target_label_id,
                    performed_by=current_user.id,
                    write_audit=True,
                )
                if not result.get('success'):
                    flash(result.get('error', 'Dry-run non riuscito.'), 'error')
                    return redirect(url_for('labels.merge_labels'))
                flash(
                    f'Dry-run merge completato: {result["moved_annotations"]} annotazioni da migrare, '
                    f'{result["dedup_deleted"]} dedup previste.',
                    'info'
                )
                return redirect(url_for('labels.merge_labels'))

            result = taxonomy_service.apply_label_merge(
                source_label_ids=source_label_ids,
                target_label_id=target_label_id,
                performed_by=current_user.id,
                commit=True,
            )
            if not result.get('success'):
                flash(result.get('error', 'Merge non riuscito.'), 'error')
                return redirect(url_for('labels.merge_labels'))

            target = Label.query.get(result['target_id'])
            flash(
                f'Merge completato: {result["moved_annotations"]} annotazioni migrate su "{target.name if target else result["target_id"]}", '
                f'{result["dedup_deleted"]} duplicati rimossi automaticamente. '
                'Le etichette sorgenti sono state deprecate.',
                'success'
            )
            return redirect(url_for('labels.list_labels'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante il merge: {str(e)}', 'error')
            return redirect(url_for('labels.merge_labels'))
    
    # GET: mostra il form di merge
    labels = Label.query.options(db.joinedload(Label.category_obj)).filter(
        Label.is_active == True,  # noqa: E712
        Label.merged_into_label_id.is_(None)
    ).order_by(Label.name).all()
    
    # Raggruppa le etichette per categoria
    labels_by_category = {}
    for label in labels:
        category = label.category_obj.name if label.category_obj else 'Senza categoria'
        if category not in labels_by_category:
            labels_by_category[category] = []
        
        # Conta le annotazioni per ogni etichetta
        annotation_count = CellAnnotation.query.filter_by(label_id=label.id).count()
        label_data = {
            'id': label.id,
            'name': label.name,
            'description': label.description,
            'color': label.get_effective_color(),
            'annotation_count': annotation_count
        }
        labels_by_category[category].append(label_data)

    suggestions = taxonomy_service.suggest_label_merges()
    return render_template(
        'labels/merge_labels.html',
        labels_by_category=labels_by_category,
        suggestions=suggestions,
    )

@labels_bp.route('/api/suggest-merge')
@login_required
def api_suggest_merge():
    """API per suggerire etichette simili che potrebbero essere unite"""
    taxonomy_service = TaxonomyService()
    suggestions = taxonomy_service.suggest_label_merges()
    return jsonify(suggestions)


def _serialize_taxonomy_audit(audit_entry):
    return {
        'id': audit_entry.id,
        'entity_type': audit_entry.entity_type,
        'source_ids': audit_entry.get_source_ids(),
        'target_id': audit_entry.target_id,
        'moved_annotations': audit_entry.moved_annotations,
        'dedup_deleted': audit_entry.dedup_deleted,
        'performed_by': audit_entry.performed_by,
        'performed_by_username': audit_entry.performer.username if audit_entry.performer else None,
        'performed_at': audit_entry.performed_at.isoformat() if audit_entry.performed_at else None,
        'mode': audit_entry.mode,
        'payload': audit_entry.get_payload(),
    }


@labels_bp.route('/taxonomy')
@login_required
def taxonomy_dashboard():
    """Vista amministrativa per razionalizzazione tassonomia."""
    denied = _require_admin_or_redirect('labels.list_labels')
    if denied:
        return denied

    taxonomy_service = TaxonomyService()
    dry_run_report = taxonomy_service.dry_run_taxonomy(
        performed_by=current_user.id,
        write_audit=False
    )
    recent_audits = taxonomy_service.get_recent_audit(limit=30)

    return render_template(
        'labels/taxonomy.html',
        dry_run_report=dry_run_report,
        recent_audits=recent_audits,
    )


@labels_bp.route('/taxonomy/dry-run')
@login_required
def taxonomy_dry_run():
    """Report di dry-run tassonomia (label/category)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Permessi insufficienti'}), 403

    write_audit = request.args.get('write_audit', 'true').lower() in ('1', 'true', 'yes')
    taxonomy_service = TaxonomyService()
    report = taxonomy_service.dry_run_taxonomy(
        performed_by=current_user.id,
        write_audit=write_audit
    )
    return jsonify({'success': True, 'report': report})


@labels_bp.route('/taxonomy/apply', methods=['POST'])
@login_required
def taxonomy_apply():
    """Applica un piano tassonomico approvato (batch merge)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Permessi insufficienti'}), 403

    taxonomy_service = TaxonomyService()
    payload = request.get_json(silent=True) or {}
    label_merges = payload.get('label_merges', [])
    category_merges = payload.get('category_merges', [])
    apply_suggested = bool(payload.get('apply_suggested'))

    if apply_suggested and not (label_merges or category_merges):
        report = taxonomy_service.dry_run_taxonomy(performed_by=current_user.id, write_audit=False)
        label_merges = [
            {
                'source_ids': [src['id'] for src in item.get('sources', [])],
                'target_id': item.get('target', {}).get('id'),
            }
            for item in report.get('label_suggestions', [])
        ]
        category_merges = [
            {
                'source_ids': [src['id'] for src in item.get('sources', [])],
                'target_id': item.get('target', {}).get('id'),
            }
            for item in report.get('category_suggestions', [])
        ]

    if not label_merges and not category_merges:
        return jsonify({
            'success': False,
            'error': 'Nessuna operazione da applicare. Fornisci merge espliciti o apply_suggested=true.'
        }), 400

    try:
        result = taxonomy_service.apply_taxonomy_plan(
            label_merges=label_merges,
            category_merges=category_merges,
            performed_by=current_user.id
        )
        if not result.get('success'):
            return jsonify(result), 400
        return jsonify({'success': True, 'result': result})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


@labels_bp.route('/taxonomy/audit')
@login_required
def taxonomy_audit():
    """Storico operazioni tassonomia (dry-run/apply)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Permessi insufficienti'}), 403

    limit = request.args.get('limit', 100, type=int)
    limit = max(1, min(limit, 500))

    audits = TaxonomyMergeAudit.query.order_by(TaxonomyMergeAudit.performed_at.desc()).limit(limit).all()
    return jsonify({
        'success': True,
        'count': len(audits),
        'audit': [_serialize_taxonomy_audit(item) for item in audits],
    })

@labels_bp.route('/categories')
@login_required
def list_categories():
    """Lista di tutte le categorie"""
    page = request.args.get('page', 1, type=int)
    show_inactive = request.args.get('show_inactive', False, type=bool)
    
    # Query di base per categorie attive
    query = Category.query
    if not show_inactive:
        query = query.filter(
            Category.is_active == True,  # noqa: E712
            Category.merged_into_category_id.is_(None)
        )
    
    categories = query.order_by(Category.name).paginate(
        page=page, per_page=20, error_out=False
    )
    
    # Conta le etichette per categoria (solo quelle attive)
    category_stats = {}
    for category in categories.items:
        category_stats[category.id] = Label.query.filter(
            Label.category_id == category.id,
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).count()
    
    return render_template('labels/list_categories.html', 
                         categories=categories,
                         category_stats=category_stats,
                         show_inactive=show_inactive)

@labels_bp.route('/categories/create', methods=['GET', 'POST'])
@login_required
def create_category():
    """Crea una nuova categoria"""
    denied = _require_admin_or_redirect('labels.list_categories')
    if denied:
        return denied
    
    form = CategoryForm()
    
    if form.validate_on_submit():
        taxonomy_service = TaxonomyService()
        category_name = form.name.data.strip()

        # Verifica se la categoria esiste già
        existing_category = Category.query.filter_by(name=category_name).first()
        
        if existing_category:
            flash('Una categoria con questo nome esiste già!', 'error')
        else:
            allowed, error_message = taxonomy_service.ensure_name_allowed('category', category_name)
            if not allowed:
                flash(error_message, 'error')
                return render_template('labels/create_category.html', form=form)

            category = Category(
                name=category_name,
                description=form.description.data,
                color=form.color.data,
                is_active=True,
                merged_into_category_id=None
            )
            
            db.session.add(category)
            db.session.commit()
            
            flash('Categoria creata con successo!', 'success')
            return redirect(url_for('labels.list_categories'))
    
    return render_template('labels/create_category.html', form=form)

@labels_bp.route('/categories/edit/<int:category_id>', methods=['GET', 'POST'])
@login_required
def edit_category(category_id):
    """Modifica una categoria"""
    denied = _require_admin_or_redirect('labels.list_categories')
    if denied:
        return denied
    
    category = Category.query.get_or_404(category_id)
    if category.merged_into_category_id is not None:
        flash('Questa categoria è deprecata da merge e non può essere modificata.', 'error')
        return redirect(url_for('labels.list_categories', show_inactive=True))

    form = CategoryForm(obj=category)
    
    if form.validate_on_submit():
        taxonomy_service = TaxonomyService()
        new_name = form.name.data.strip()

        # Verifica se un'altra categoria ha già questo nome
        existing_category = Category.query.filter(
            Category.name == new_name,
            Category.id != category_id
        ).first()
        
        if existing_category:
            flash('Un\'altra categoria con questo nome esiste già.', 'error')
        else:
            allowed, error_message = taxonomy_service.ensure_name_allowed(
                entity_type='category',
                name=new_name,
                exclude_id=category.id
            )
            if not allowed:
                flash(error_message, 'error')
                return render_template('labels/edit_category.html', form=form, category=category)

            old_name = category.name
            category.name = new_name
            category.description = form.description.data
            category.color = form.color.data

            # Compatibilità legacy Label.category in sola lettura applicativa
            if old_name != new_name:
                labels_in_category = Label.query.filter_by(category_id=category.id).all()
                for lbl in labels_in_category:
                    lbl.category = new_name
            
            db.session.commit()
            
            flash('Categoria aggiornata con successo!', 'success')
            return redirect(url_for('labels.list_categories'))
    
    return render_template('labels/edit_category.html', form=form, category=category)

@labels_bp.route('/categories/delete/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    """Depreca una categoria con migrazione automatica delle etichette."""
    denied = _require_admin_or_redirect('labels.list_categories')
    if denied:
        return denied
    
    category = Category.query.get_or_404(category_id)
    if category.merged_into_category_id is not None:
        flash('La categoria è già deprecata da merge.', 'info')
        return redirect(url_for('labels.list_categories', show_inactive=True))
    
    # Conta le etichette associate (tutte, attive e inattive)
    all_labels = Label.query.filter_by(category_id=category_id).all()
    active_label_count = Label.query.filter(
        Label.category_id == category_id,
        Label.is_active == True,  # noqa: E712
        Label.merged_into_label_id.is_(None)
    ).count()
    
    try:
        if len(all_labels) > 0:
            # MIGRAZIONE AUTOMATICA: Sposta tutte le etichette in "Nessuna categoria"
            migrated_labels = []
            for label in all_labels:
                label.category_id = None
                label.category = None
                migrated_labels.append(label.name)
            
            # Depreca la categoria (no hard-delete)
            category.is_active = False
            db.session.commit()
            
            # REFRESH: Aggiorna la sessione per riflettere i cambiamenti
            db.session.expire_all()
            
            # Messaggio informativo dettagliato
            flash(
                f'Categoria "{category.name}" deprecata con successo. '
                f'{len(migrated_labels)} etichette migrate in "Nessuna categoria": '
                f'{", ".join(migrated_labels[:5])}{"..." if len(migrated_labels) > 5 else ""}.',
                'success'
            )
            
            # Suggerimento per gestire le etichette migrate
            if active_label_count > 0:
                flash(f'Suggerimento: Puoi ora gestire le {active_label_count} etichette attive usando il filtro "Nessuna categoria" nella pagina etichette.', 'info')
        else:
            # Categoria vuota: deprecazione diretta
            category.is_active = False
            db.session.commit()
            flash(f'Categoria "{category.name}" deprecata (era vuota).', 'success')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la deprecazione: {str(e)}', 'error')
    
    return redirect(url_for('labels.list_categories'))

@labels_bp.route('/categories/toggle-active/<int:category_id>', methods=['POST'])
@login_required
def toggle_category_active(category_id):
    """Attiva/disattiva una categoria"""
    denied = _require_admin_or_redirect('labels.list_categories')
    if denied:
        return denied
    
    category = Category.query.get_or_404(category_id)

    if not category.is_active:
        if category.merged_into_category_id is not None:
            flash(
                'Categoria deprecata da merge: non può essere riattivata. '
                'Usa la categoria canonica di destinazione.',
                'error'
            )
            return redirect(url_for('labels.list_categories', show_inactive=True))

        taxonomy_service = TaxonomyService()
        allowed, error_message = taxonomy_service.ensure_name_allowed(
            entity_type='category',
            name=category.name,
            exclude_id=category.id
        )
        if not allowed:
            flash(f'Riattivazione bloccata: {error_message}', 'error')
            return redirect(url_for('labels.list_categories', show_inactive=True))

    category.is_active = not category.is_active
    status = 'attivata' if category.is_active else 'disattivata'
    
    db.session.commit()
    flash(f'Categoria "{category.name}" {status} con successo.', 'success')
    
    return redirect(url_for('labels.list_categories', show_inactive=True))

@labels_bp.route('/categories/bulk-actions', methods=['POST'])
@login_required
def bulk_category_actions():
    """Gestisce le azioni in blocco per le categorie"""
    if not current_user.is_admin:
        flash('Non hai i permessi per questa operazione.', 'error')
        return redirect(url_for('labels.list_categories'))
    
    action = request.form.get('action')
    selected_categories = request.form.getlist('selected_categories')
    
    if not selected_categories:
        flash('Nessuna categoria selezionata.', 'warning')
        return redirect(url_for('labels.list_categories'))
    
    if action == 'delete':
        return bulk_delete_categories(selected_categories)
    elif action == 'merge':
        target_category_id = request.form.get('target_category_id')
        return bulk_merge_categories(selected_categories, target_category_id)
    else:
        flash('Azione non riconosciuta.', 'error')
        return redirect(url_for('labels.list_categories'))

@labels_bp.route('/bulk-actions', methods=['POST'])
@login_required
def bulk_actions():
    """Gestisce le azioni in blocco per le etichette"""
    if not current_user.is_admin:
        flash('Non hai i permessi per questa operazione.', 'error')
        return redirect(url_for('labels.list_labels'))
    
    action = request.form.get('action')
    selected_labels = request.form.getlist('selected_labels')
    
    if not selected_labels:
        flash('Nessuna etichetta selezionata.', 'warning')
        return redirect(url_for('labels.list_labels'))
    
    if action == 'delete':
        return bulk_delete_labels(selected_labels)
    elif action == 'assign_category':
        category_id = request.form.get('category_id')
        return bulk_assign_category(selected_labels, category_id)
    elif action == 'change_color':
        color = request.form.get('color')
        return bulk_change_color(selected_labels, color)
    else:
        flash('Azione non riconosciuta.', 'error')
        return redirect(url_for('labels.list_labels'))

def bulk_delete_labels(label_ids):
    """Depreca più etichette in blocco (no hard-delete)."""
    try:
        labels_to_delete = Label.query.filter(Label.id.in_(label_ids)).all()
        deactivated_labels = []
        
        for label in labels_to_delete:
            if label.merged_into_label_id is not None:
                continue
            label.is_active = False
            deactivated_labels.append(label.name)

        db.session.commit()
        if deactivated_labels:
            flash(f'Deprecate/disattivate {len(deactivated_labels)} etichette.', 'success')
        else:
            flash('Nessuna etichetta aggiornata (probabilmente già deprecate).', 'info')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la deprecazione: {str(e)}', 'error')
    
    return redirect(url_for('labels.list_labels'))

def bulk_assign_category(label_ids, category_id):
    """Assegna una categoria a più etichette"""
    try:
        category_id = int(category_id) if category_id and category_id != '0' else None
        category_name = None
        if category_id:
            category = Category.query.get(category_id)
            if not category or not category.is_active or category.merged_into_category_id is not None:
                flash('Categoria non valida o deprecata.', 'error')
                return redirect(url_for('labels.list_labels'))
            category_name = category.name
        
        labels = Label.query.filter(Label.id.in_(label_ids)).all()
        for label in labels:
            label.category_id = category_id
            label.category = category_name
        
        db.session.commit()
        category_name = category_name if category_name else "Nessuna categoria"
        flash(f'Assegnata la categoria "{category_name}" a {len(labels)} etichette.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'assegnazione: {str(e)}', 'error')
    
    return redirect(url_for('labels.list_labels'))

def bulk_change_color(label_ids, color):
    """Cambia il colore di più etichette"""
    try:
        if not color:
            flash('Colore non specificato.', 'error')
            return redirect(url_for('labels.list_labels'))
        
        labels = Label.query.filter(Label.id.in_(label_ids)).all()
        for label in labels:
            label.color = color
        
        db.session.commit()
        flash(f'Cambiato il colore di {len(labels)} etichette.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante il cambio colore: {str(e)}', 'error')
    
    return redirect(url_for('labels.list_labels'))

def bulk_delete_categories(category_ids):
    """Depreca più categorie in blocco con migrazione etichette."""
    try:
        categories_to_delete = Category.query.filter(Category.id.in_(category_ids)).all()
        
        total_migrated_labels = 0
        deprecated_categories = []
        
        for category in categories_to_delete:
            if category.merged_into_category_id is not None:
                continue

            # Trova tutte le etichette della categoria
            labels_in_category = Label.query.filter_by(category_id=category.id).all()
            
            # Migra le etichette a "Nessuna categoria"
            for label in labels_in_category:
                label.category_id = None
                label.category = None
                total_migrated_labels += 1
            
            category.is_active = False
            deprecated_categories.append(category.name)
        
        db.session.commit()
        
        # REFRESH: Aggiorna la sessione per riflettere i cambiamenti
        db.session.expire_all()
        
        if total_migrated_labels > 0:
            flash(
                f'Deprecate {len(deprecated_categories)} categorie: {", ".join(deprecated_categories)}. '
                f'{total_migrated_labels} etichette migrate in "Nessuna categoria".',
                'success'
            )
            flash('Suggerimento: Usa il filtro "Nessuna categoria" per gestire le etichette migrate.', 'info')
        else:
            flash(f'Deprecate {len(deprecated_categories)} categorie vuote con successo.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la deprecazione: {str(e)}', 'error')
    
    return redirect(url_for('labels.list_categories'))

def bulk_merge_categories(category_ids, target_category_id):
    """Unisce più categorie in una sola"""
    try:
        if not target_category_id:
            flash('Categoria di destinazione non specificata.', 'error')
            return redirect(url_for('labels.list_categories'))

        target_category_id = int(target_category_id)
        source_ids = [int(cat_id) for cat_id in category_ids if int(cat_id) != target_category_id]
        if not source_ids:
            flash('Seleziona almeno una categoria sorgente diversa dal target.', 'warning')
            return redirect(url_for('labels.list_categories'))

        taxonomy_service = TaxonomyService()
        result = taxonomy_service.apply_category_merge(
            source_category_ids=source_ids,
            target_category_id=target_category_id,
            performed_by=current_user.id,
            commit=True
        )
        if not result.get('success'):
            flash(result.get('error', 'Merge categorie non riuscito.'), 'error')
            return redirect(url_for('labels.list_categories'))

        target_category = Category.query.get(target_category_id)
        flash(
            f'Unite {len(result["source_ids"])} categorie in "{target_category.name if target_category else target_category_id}". '
            f'Spostate {result["moved_labels"]} etichette. '
            'Categorie sorgenti deprecate con audit.',
            'success'
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'unione: {str(e)}', 'error')
    
    return redirect(url_for('labels.list_categories'))

# API per l'integrazione con l'AI

@labels_bp.route('/api/labels-for-ai')
@login_required
def api_labels_for_ai():
    """API per ottenere tutte le etichette per l'AI"""
    labels = Label.query.options(db.joinedload(Label.category_obj)).filter(
        Label.is_active == True,  # noqa: E712
        Label.merged_into_label_id.is_(None)
    ).order_by(Label.name).all()
    
    labels_data = []
    for label in labels:
        if label.category_obj and (not label.category_obj.is_active or label.category_obj.merged_into_category_id is not None):
            continue

        category_name = label.category_obj.name if label.category_obj else 'Senza categoria'
        labels_data.append({
            'id': label.id,
            'name': label.name,
            'description': label.description,
            'category': category_name,
            'color': label.get_effective_color()
        })
    
    return jsonify(labels_data)

@labels_bp.route('/api/categories-for-ai')
@login_required
def api_categories_for_ai():
    """API per ottenere tutte le categorie per l'AI"""
    categories = Category.query.filter(
        Category.is_active == True,  # noqa: E712
        Category.merged_into_category_id.is_(None)
    ).order_by(Category.name).all()
    
    categories_data = []
    for category in categories:
        labels_in_category = Label.query.filter(
            Label.category_id == category.id,
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).all()
        categories_data.append({
            'id': category.id,
            'name': category.name,
            'description': category.description,
            'color': category.color,
            'labels': [{'id': label.id, 'name': label.name, 'description': label.description} for label in labels_in_category]
        })
    
    return jsonify(categories_data)


# NUOVE ROUTES PER GESTIONE COLORI

@labels_bp.route('/categories/colors')
@login_required
def manage_category_colors():
    """Pagina per gestire i colori delle categorie con slider"""
    if not current_user.is_admin:
        flash('Non hai i permessi per questa operazione.', 'error')
        return redirect(url_for('labels.list_categories'))
    
    categories = Category.query.filter(
        Category.is_active == True,  # noqa: E712
        Category.merged_into_category_id.is_(None)
    ).order_by(Category.name).all()
    
    # Calcola statistiche per ogni categoria
    category_stats = {}
    for category in categories:
        category_stats[category.id] = {
            'label_count': Label.query.filter(
                Label.category_id == category.id,
                Label.is_active == True,  # noqa: E712
                Label.merged_into_label_id.is_(None)
            ).count(),
            'annotation_count': db.session.query(CellAnnotation).join(Label).filter(
                Label.category_id == category.id,
                Label.is_active == True,  # noqa: E712
                Label.merged_into_label_id.is_(None)
            ).count()
        }
    
    return render_template('labels/category_colors.html', 
                         categories=categories,
                         category_stats=category_stats)

@labels_bp.route('/test-csrf')
@login_required
def test_csrf():
    """Route di test per il CSRF"""
    return render_template('labels/test_csrf.html')

@labels_bp.route('/categories/colors/update', methods=['POST'])
@login_required
def update_category_colors():
    """Aggiorna i colori delle categorie"""
    if not current_user.is_admin:
        flash('Non hai i permessi per questa operazione.', 'error')
        return redirect(url_for('labels.list_categories'))
    
    try:
        # Processa i dati inviati dal form
        updated_count = 0
        errors = []
        
        for key, value in request.form.items():
            if key.startswith('color_'):
                category_id = int(key.replace('color_', ''))
                category = Category.query.get_or_404(category_id)
                
                try:
                    # Valida e aggiorna il colore
                    category.update_color(value)
                    updated_count += 1
                except ValueError as e:
                    errors.append(f"Categoria '{category.name}': {str(e)}")
        
        if errors:
            for error in errors:
                flash(error, 'error')
        
        if updated_count > 0:
            db.session.commit()
            flash(f'Aggiornati i colori di {updated_count} categorie.', 'success')
        else:
            flash('Nessun colore è stato modificato.', 'info')
    
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
    
    return redirect(url_for('labels.manage_category_colors'))

@labels_bp.route('/categories/colors/sync', methods=['POST'])
@login_required
def sync_label_colors():
    """Sincronizza i colori delle etichette con le categorie"""
    if not current_user.is_admin:
        flash('Non hai i permessi per questa operazione.', 'error')
        return redirect(url_for('labels.list_categories'))
    
    try:
        # Verifica se forzare la sincronizzazione
        force_sync = request.form.get('force_sync') == 'true'
        
        # Trova tutte le etichette che hanno una categoria
        labels_with_category = Label.query.filter(
            Label.category_id.isnot(None),
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).all()
        
        updated_count = 0
        updated_labels = []
        
        for label in labels_with_category:
            if label.category_obj:
                old_color = label.color
                # Se force_sync è True, aggiorna tutte le etichette
                # Altrimenti solo quelle che non hanno un colore personalizzato
                if force_sync or not label.has_custom_color():
                    label.color = label.category_obj.color
                    updated_count += 1
                    updated_labels.append({
                        'name': label.name,
                        'old_color': old_color,
                        'new_color': label.color,
                        'category': label.category_obj.name
                    })
        
        if updated_count > 0:
            db.session.commit()
            sync_type = "forzata" if force_sync else "standard"
            flash(f'Sincronizzazione {sync_type} completata: aggiornate {updated_count} etichette con i colori delle categorie.', 'success')
        else:
            flash('Tutte le etichette sono già sincronizzate.', 'info')
    
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la sincronizzazione: {str(e)}', 'error')
    
    return redirect(url_for('labels.manage_category_colors'))

@labels_bp.route('/api/sync-colors', methods=['POST'])
@login_required
def api_sync_label_colors():
    """API endpoint per sincronizzare i colori delle etichette con le categorie"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Non hai i permessi per questa operazione.'}), 403
    
    try:
        # Verifica se forzare la sincronizzazione
        force_sync = request.json.get('force_sync', False) if request.is_json else request.form.get('force_sync') == 'true'
        
        # Trova tutte le etichette che hanno una categoria
        labels_with_category = Label.query.filter(
            Label.category_id.isnot(None),
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).all()
        
        updated_count = 0
        updated_labels = []
        skipped_labels = []
        
        for label in labels_with_category:
            if label.category_obj:
                old_color = label.color
                # Se force_sync è True, aggiorna tutte le etichette
                # Altrimenti solo quelle che non hanno un colore personalizzato
                if force_sync or not label.has_custom_color():
                    label.color = label.category_obj.color
                    updated_count += 1
                    updated_labels.append({
                        'id': label.id,
                        'name': label.name,
                        'old_color': old_color,
                        'new_color': label.color,
                        'category': label.category_obj.name,
                        'reason': 'forced' if force_sync else 'no_custom_color'
                    })
                else:
                    skipped_labels.append({
                        'id': label.id,
                        'name': label.name,
                        'color': label.color,
                        'category': label.category_obj.name,
                        'reason': 'has_custom_color'
                    })
        
        if updated_count > 0:
            db.session.commit()
        
        sync_type = "forzata" if force_sync else "standard"
        
        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'total_count': len(labels_with_category),
            'sync_type': sync_type,
            'updated_labels': updated_labels,
            'skipped_labels': skipped_labels,
            'message': f'Sincronizzazione {sync_type} completata: aggiornate {updated_count} etichette.'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Errore durante la sincronizzazione: {str(e)}'
        }), 500

@labels_bp.route('/categories/colors/reset/<int:category_id>', methods=['POST'])
@login_required
def reset_category_color(category_id):
    """Reset del colore di una categoria al default della palette"""
    if not current_user.is_admin:
        flash('Non hai i permessi per questa operazione.', 'error')
        return redirect(url_for('labels.list_categories'))
    
    try:
        category = Category.query.get_or_404(category_id)
        
        # Assegna un nuovo colore dalla palette
        new_color = Category.assign_next_color()
        category.update_color(new_color)
        
        db.session.commit()
        flash(f'Colore della categoria "{category.name}" ripristinato.', 'success')
    
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante il ripristino: {str(e)}', 'error')
    
    return redirect(url_for('labels.manage_category_colors'))

@labels_bp.route('/api/category-color-preview')
@login_required
def api_category_color_preview():
    """API per l'anteprima dei colori delle categorie"""
    category_id = request.args.get('category_id', type=int)
    hue = request.args.get('hue', type=float)
    saturation = request.args.get('saturation', type=float)
    lightness = request.args.get('lightness', type=float)
    
    if not all([category_id, hue is not None, saturation is not None, lightness is not None]):
        return jsonify({'error': 'Parametri mancanti'}), 400
    
    try:
        from utils.color_palette import ColorPalette
        
        # Converti HSL in esadecimale
        new_color = ColorPalette.hsl_to_hex(hue, saturation / 100, lightness / 100)
        text_color = ColorPalette.get_contrasting_text_color(new_color)
        
        # Trova alcune etichette di esempio per l'anteprima
        category = Category.query.get_or_404(category_id)
        sample_labels = Label.query.filter(
            Label.category_id == category_id,
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).limit(3).all()
        
        return jsonify({
            'color': new_color,
            'text_color': text_color,
            'sample_labels': [{'id': label.id, 'name': label.name} for label in sample_labels],
            'valid': ColorPalette.validate_color(new_color)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
