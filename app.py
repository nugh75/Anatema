#!/usr/bin/env python3
"""
Applicazione Flask per la gestione collaborativa dell'etichettatura tematica
di risposte testuali contenute in file Excel.
"""

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
import os

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
                           TextDocument, TextAnnotation)
        db.create_all()
        
        # Creazione utente admin di default se non esiste
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', role='amministratore')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        
        # Creazione etichette di default se non esistono
        if Label.query.count() == 0:
            default_labels = [
                # Categoria: Prospettiva
                Label(name='Studente', description='Punto di vista dello studente', category='Prospettiva', color='#007bff'),
                Label(name='Insegnante', description='Punto di vista del docente', category='Prospettiva', color='#28a745'),
                Label(name='Istituzione', description='Prospettiva istituzionale', category='Prospettiva', color='#6f42c1'),
                Label(name='Genitore', description='Punto di vista dei genitori', category='Prospettiva', color='#fd7e14'),
                
                # Categoria: Sentiment
                Label(name='Positivo', description='Atteggiamento favorevole verso l\'AI', category='Sentiment', color='#20c997'),
                Label(name='Negativo', description='Atteggiamento contrario all\'AI', category='Sentiment', color='#dc3545'),
                Label(name='Neutro', description='Posizione neutra/equilibrata', category='Sentiment', color='#6c757d'),
                Label(name='Ambivalente', description='Posizione con aspetti pro e contro', category='Sentiment', color='#ffc107'),
                
                # Categoria: Utilizzo AI
                Label(name='Ricerca e Studio', description='Uso per ricerche e apprendimento', category='Utilizzo AI', color='#17a2b8'),
                Label(name='Scrittura', description='Aiuto nella produzione di testi', category='Utilizzo AI', color='#6610f2'),
                Label(name='Problem Solving', description='Risoluzione di problemi', category='Utilizzo AI', color='#155724'),
                Label(name='Creatività', description='Usi creativi e artistici', category='Utilizzo AI', color='#e83e8c'),
                Label(name='Programmazione', description='Coding e sviluppo', category='Utilizzo AI', color='#343a40'),
                Label(name='Traduzione', description='Traduzione di testi', category='Utilizzo AI', color='#20c997'),
                Label(name='Tutoring', description='AI come tutor personale', category='Utilizzo AI', color='#004085'),
                
                # Categoria: Benefici
                Label(name='Personalizzazione', description='Apprendimento personalizzato', category='Benefici', color='#32cd32'),
                Label(name='Accessibilità', description='Miglioramento dell\'accessibilità', category='Benefici', color='#4169e1'),
                Label(name='Efficienza', description='Risparmio di tempo e risorse', category='Benefici', color='#ffd700'),
                Label(name='Motivazione', description='Aumento della motivazione', category='Benefici', color='#ff00ff'),
                Label(name='Feedback Istantaneo', description='Feedback immediato', category='Benefici', color='#00ffff'),
                Label(name='Inclusività', description='Supporto a diversi stili di apprendimento', category='Benefici', color='#e6e6fa'),
                
                # Categoria: Rischi e Preoccupazioni
                Label(name='Dipendenza', description='Eccessiva dipendenza dall\'AI', category='Rischi e Preoccupazioni', color='#8b0000'),
                Label(name='Plagio', description='Questioni di originalità e onestà accademica', category='Rischi e Preoccupazioni', color='#8b4513'),
                Label(name='Perdita Competenze', description='Perdita di abilità fondamentali', category='Rischi e Preoccupazioni', color='#2f4f4f'),
                Label(name='Privacy', description='Preoccupazioni sulla privacy dei dati', category='Rischi e Preoccupazioni', color='#4b0082'),
                Label(name='Bias', description='Pregiudizi negli algoritmi', category='Rischi e Preoccupazioni', color='#ff4500'),
                Label(name='Superficialità', description='Apprendimento superficiale', category='Rischi e Preoccupazioni', color='#f5f5dc'),
                
                # Categoria: Aspetti Etici
                Label(name='Trasparenza', description='Necessità di trasparenza nell\'uso', category='Aspetti Etici', color='#b0e0e6'),
                Label(name='Equità', description='Equità nell\'accesso e utilizzo', category='Aspetti Etici', color='#9acd32'),
                Label(name='Responsabilità', description='Responsabilità nell\'uso dell\'AI', category='Aspetti Etici', color='#800020'),
                Label(name='Consenso Informato', description='Consenso consapevole', category='Aspetti Etici', color='#b0c4de'),
                
                # Categoria: Regolamentazione
                Label(name='Necessità Linee Guida', description='Serve regolamentazione', category='Regolamentazione', color='#000080'),
                Label(name='Divieti', description='Cose da vietare', category='Regolamentazione', color='#dc143c'),
                Label(name='Formazione Necessaria', description='Necessità di formazione', category='Regolamentazione', color='#808000'),
                Label(name='Controllo Qualità', description='Controllo della qualità', category='Regolamentazione', color='#c0c0c0'),
                
                # Categoria: Ambito Disciplinare
                Label(name='STEM', description='Scienze, Tecnologia, Ingegneria, Matematica', category='Ambito Disciplinare', color='#0080ff'),
                Label(name='Umanistico', description='Materie umanistiche', category='Ambito Disciplinare', color='#b22222'),
                Label(name='Linguistico', description='Lingue straniere', category='Ambito Disciplinare', color='#228b22'),
                Label(name='Artistico', description='Arte e creatività', category='Ambito Disciplinare', color='#da70d6'),
                Label(name='Sociale', description='Scienze sociali', category='Ambito Disciplinare', color='#d2691e'),
            ]
            
            for label in default_labels:
                db.session.add(label)
            
            db.session.commit()
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
