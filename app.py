#!/usr/bin/env python3
"""
Applicazione Flask per la gestione collaborativa dell'etichettatura tematica
di risposte testuali contenute in file Excel.
"""

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
import os
from sqlalchemy import inspect, text

# Importa l'istanza db dai modelli
from models import db

# Inizializzazione delle altre estensioni
login_manager = LoginManager()
csrf = CSRFProtect()

def create_app():
    """Factory function per creare l'applicazione Flask"""
    app = Flask(__name__)
    
    # Configurazione con supporto per ambienti multipli
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Database URL - supporta sia sviluppo che produzione
    default_db = 'sqlite:///instance/analisi_mu.db'
    if os.environ.get('DEV_MODE') == '1':
        default_db = 'sqlite:///analisi_mu_dev.db'
    
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', default_db)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    
    # Configurazioni specifiche per ambiente
    if os.environ.get('DEV_MODE') == '1':
        app.config['DEBUG'] = True
        print("🔧 Modalità sviluppo attivata")
    elif os.environ.get('DOCKER_MODE') == '1':
        app.config['DEBUG'] = False
        print("🐳 Modalità Docker attivata")
    
    # Inizializzazione estensioni
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    
    # Esenzione CSRF per route specifiche
    csrf.exempt('labels.update_category_colors')
    csrf.exempt('labels.reset_category_color')
    
    # Configurazione Flask-Login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Effettua il login per accedere a questa pagina.'
    login_manager.login_message_category = 'info'
    
    # Registrazione blueprints
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.excel import excel_bp
    from routes.labels import labels_bp
    from routes.annotation import annotation_bp
    from routes.admin import admin_bp
    from routes.ai import ai_bp
    from routes.statistics import statistics_bp
    from routes.questions import questions_bp
    from routes.text_documents import text_documents_bp
    from routes.forum import forum_bp
    from routes.diary import diary_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')
    app.register_blueprint(excel_bp, url_prefix='/excel')
    app.register_blueprint(labels_bp, url_prefix='/labels')
    app.register_blueprint(annotation_bp, url_prefix='/annotation')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(ai_bp, url_prefix='/ai')
    app.register_blueprint(statistics_bp, url_prefix='/statistics')
    app.register_blueprint(questions_bp, url_prefix='/questions')
    app.register_blueprint(text_documents_bp)
    app.register_blueprint(forum_bp)
    app.register_blueprint(diary_bp, url_prefix='/diary')
    
    # Creazione delle cartelle necessarie con permessi corretti
    upload_folder = app.config['UPLOAD_FOLDER']
    instance_folder = 'instance'
    
    os.makedirs(upload_folder, mode=0o755, exist_ok=True)
    os.makedirs(instance_folder, mode=0o755, exist_ok=True)
    
    # Assicuriamoci che le cartelle abbiano i permessi corretti
    try:
        os.chmod(upload_folder, 0o755)
        os.chmod(instance_folder, 0o755)
    except OSError:
        pass  # Ignora errori di permessi se l'utente non ha privilegi sufficienti
    
    # User loader per Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from models import User, db
        return db.session.get(User, int(user_id))
    
    # Context processor per il token CSRF
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)
    
    # Filtro personalizzato per escapare JavaScript
    @app.template_filter('escapejs')
    def escapejs_filter(text):
        """
        Filtra il testo per renderlo sicuro per JavaScript
        Sostituisce caratteri problematici come apostrofi, virgolette, ecc.
        """
        if text is None:
            return ''
        
        # Converti in stringa se non lo è già
        text = str(text)
        
        # Escape dei caratteri speciali per JavaScript
        replacements = {
            '\\': '\\\\',
            "'": "\\'",
            '"': '\\"',
            '\n': '\\n',
            '\r': '\\r',
            '\t': '\\t',
            '\b': '\\b',
            '\f': '\\f',
            '\v': '\\v',
            '\0': '\\0'
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        return text
    
    # Creazione delle tabelle del database
    with app.app_context():
        from models import (User, Label, ExcelFile, TextCell, CellAnnotation, 
                           TextDocument, TextAnnotation, Category,
                           TaxonomyAlias, TaxonomyMergeAudit)
        db.create_all()

        # Migrazione leggera backward-compatible per campi tassonomia aggiunti su DB esistenti
        def ensure_taxonomy_schema():
            inspector = inspect(db.engine)

            def has_column(table_name, column_name):
                cols = [col['name'] for col in inspector.get_columns(table_name)]
                return column_name in cols

            # Label.merged_into_label_id
            if not has_column('label', 'merged_into_label_id'):
                db.session.execute(text("ALTER TABLE label ADD COLUMN merged_into_label_id INTEGER"))
                db.session.commit()

            # Category.merged_into_category_id
            inspector = inspect(db.engine)
            if not has_column('category', 'merged_into_category_id'):
                db.session.execute(text("ALTER TABLE category ADD COLUMN merged_into_category_id INTEGER"))
                db.session.commit()

            # Crea eventuali tabelle nuove mancanti
            db.create_all()

        ensure_taxonomy_schema()
        
        # Creazione utente admin di default se non esiste
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', role='amministratore')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        
        # Creazione categorie e etichette di default se non esistono
        if Label.query.count() == 0:
            # Dati seed: categoria -> (descrizione, colore, [(nome_etichetta, descrizione, colore)])
            seed_data = [
                ('Prospettiva', 'Punto di vista espresso nella risposta', '#6f42c1', [
                    ('Studente', 'Punto di vista dello studente', '#007bff'),
                    ('Insegnante', 'Punto di vista del docente', '#28a745'),
                    ('Istituzione', 'Prospettiva istituzionale', '#6f42c1'),
                    ('Genitore', 'Punto di vista dei genitori', '#fd7e14'),
                ]),
                ('Sentiment', 'Tono emotivo o atteggiamento verso l\'AI', '#ffc107', [
                    ('Positivo', 'Atteggiamento favorevole verso l\'AI', '#20c997'),
                    ('Negativo', 'Atteggiamento contrario all\'AI', '#dc3545'),
                    ('Neutro', 'Posizione neutra/equilibrata', '#6c757d'),
                    ('Ambivalente', 'Posizione con aspetti pro e contro', '#ffc107'),
                ]),
                ('Utilizzo AI', 'Modalità d\'uso dell\'intelligenza artificiale', '#17a2b8', [
                    ('Ricerca e Studio', 'Uso per ricerche e apprendimento', '#17a2b8'),
                    ('Scrittura', 'Aiuto nella produzione di testi', '#6610f2'),
                    ('Problem Solving', 'Risoluzione di problemi', '#155724'),
                    ('Creatività', 'Usi creativi e artistici', '#e83e8c'),
                    ('Programmazione', 'Coding e sviluppo', '#343a40'),
                    ('Traduzione', 'Traduzione di testi', '#20c997'),
                    ('Tutoring', 'AI come tutor personale', '#004085'),
                ]),
                ('Benefici', 'Vantaggi e aspetti positivi dell\'AI nell\'educazione', '#32cd32', [
                    ('Personalizzazione', 'Apprendimento personalizzato', '#32cd32'),
                    ('Accessibilità', 'Miglioramento dell\'accessibilità', '#4169e1'),
                    ('Efficienza', 'Risparmio di tempo e risorse', '#ffd700'),
                    ('Motivazione', 'Aumento della motivazione', '#ff00ff'),
                    ('Feedback Istantaneo', 'Feedback immediato agli studenti', '#00ffff'),
                    ('Inclusività', 'Supporto a diversi stili di apprendimento', '#e6e6fa'),
                ]),
                ('Rischi e Preoccupazioni', 'Rischi, limiti e preoccupazioni sull\'uso dell\'AI', '#dc3545', [
                    ('Dipendenza', 'Eccessiva dipendenza dall\'AI', '#8b0000'),
                    ('Plagio', 'Questioni di originalità e onestà accademica', '#8b4513'),
                    ('Perdita Competenze', 'Perdita di abilità fondamentali', '#2f4f4f'),
                    ('Privacy', 'Preoccupazioni sulla privacy dei dati', '#4b0082'),
                    ('Bias', 'Pregiudizi e distorsioni negli algoritmi', '#ff4500'),
                    ('Superficialità', 'Rischio di apprendimento superficiale', '#f5f5dc'),
                ]),
                ('Aspetti Etici', 'Considerazioni etiche legate all\'AI in ambito educativo', '#9acd32', [
                    ('Trasparenza', 'Necessità di trasparenza nell\'uso dell\'AI', '#b0e0e6'),
                    ('Equità', 'Equità nell\'accesso e utilizzo', '#9acd32'),
                    ('Responsabilità', 'Responsabilità nell\'uso dell\'AI', '#800020'),
                    ('Consenso Informato', 'Necessità di consenso consapevole', '#b0c4de'),
                ]),
                ('Regolamentazione', 'Proposte e bisogni di regole e linee guida', '#000080', [
                    ('Necessità Linee Guida', 'Richiesta di regolamentazione chiara', '#000080'),
                    ('Divieti', 'Indicazione di usi da vietare', '#dc143c'),
                    ('Formazione Necessaria', 'Necessità di formazione specifica', '#808000'),
                    ('Controllo Qualità', 'Necessità di controllo sulla qualità dei contenuti AI', '#c0c0c0'),
                ]),
                ('Ambito Disciplinare', 'Area disciplinare di riferimento della risposta', '#0080ff', [
                    ('STEM', 'Scienze, Tecnologia, Ingegneria, Matematica', '#0080ff'),
                    ('Umanistico', 'Materie umanistiche', '#b22222'),
                    ('Linguistico', 'Lingue straniere', '#228b22'),
                    ('Artistico', 'Arte e creatività', '#da70d6'),
                    ('Sociale', 'Scienze sociali', '#d2691e'),
                ]),
            ]

            for cat_name, cat_desc, cat_color, labels_def in seed_data:
                # Crea la categoria se non esiste
                cat = Category.query.filter_by(name=cat_name).first()
                if not cat:
                    cat = Category(name=cat_name, description=cat_desc, color=cat_color, is_active=True)
                    db.session.add(cat)
                    db.session.flush()  # ottieni l'ID prima di usarlo

                for lbl_name, lbl_desc, lbl_color in labels_def:
                    if not Label.query.filter_by(name=lbl_name).first():
                        db.session.add(Label(
                            name=lbl_name,
                            description=lbl_desc,
                            category=cat_name,       # campo legacy per retrocompatibilità
                            category_id=cat.id,      # FK corretto
                            color=lbl_color,
                            is_active=True,
                        ))

            db.session.commit()
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
