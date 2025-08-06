#Anatema - Sistema di Etichettatura Collaborativa

**Anatema** è un sistema web avanzato per l'etichettatura collaborativa di risposte testuali estratte da file Excel. Progettato per ricercatori, analisti e team che necessitano di classificare e analizzare grandi volumi di testi in modo efficiente e collaborativo.

## 🎯 Caratteristiche principali

### 📊 **Gestione intelligente dei dati**
- **Importazione automatica**: Carica file Excel e estrae automaticamente le celle testuali
- **Navigazione intuitiva**: Interfaccia ottimizzata per la navigazione tra migliaia di risposte
- **Filtri avanzati**: Filtra per domande, annotatori, stato di completamento

### 🏷️ **Sistema di etichettatura flessibile**
- **Etichette personalizzate**: Crea etichette con colori e descrizioni custom
- **Categorie organizzate**: Raggruppa etichette per ambiti tematici
- **Annotazione multipla**: Assegna più etichette alla stessa cella
- **Annotazione collaborativa**: Più utenti possono lavorare sugli stessi dati

### 🤖 **Integrazione AI (Opzionale)**
- **Supporto multi-provider**: OpenAI, Anthropic, Ollama
- **Annotazione assistita**: Suggerimenti automatici basati su AI
- **Template personalizzabili**: Crea prompt specifici per il tuo dominio

### 📈 **Analytics e reportistica**
- **Dashboard interattiva**: Visualizzazioni in tempo reale delle annotazioni
- **Statistiche dettagliate**: Metriche per utente, file, etichette
- **Confronto inter-annotatori**: Analisi della concordanza tra annotatori
- **Esportazione dati**: Esporta risultati in vari formati

### � **Gestione utenti e permessi**
- **Ruoli differenziati**: Amministratori, annotatori, visualizzatori
- **Tracking delle attività**: Cronologia completa delle annotazioni
- **Controllo qualità**: Supervisione del lavoro degli annotatori

## 🛠️ Tecnologie utilizzate

- **Backend**: Flask (Python 3.13+)
- **Database**: SQLite con SQLAlchemy ORM
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5
- **AI**: Integrazione con OpenAI, Anthropic, Ollama
- **Containerizzazione**: Docker e Docker Compose
- **Sicurezza**: Flask-Login, CSRF protection, gestione sessioni

## 🚀 Installazione rapida

### Con Docker (Raccomandato)

```bash
# Clona il repository
git clone https://github.com/nugh75/anatema.git
cd anatema

# Avvia l'applicazione
docker compose up -d

# Accedi su http://localhost:5005
# Username: admin | Password: admin123
```

### Installazione locale

```bash
# Clona e configura
git clone https://github.com/nugh75/anatema.git
cd anatema

# Crea ambiente virtuale
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Installa dipendenze
pip install -r requirements.txt

# Configura ambiente
cp .env.example .env
# Modifica .env con le tue configurazioni

# Avvia l'applicazione
python app.py
```

## 📋 Guida rapida

### 1. **Primo accesso**
- Accedi con `admin/admin123`
- Cambia immediatamente la password
- Crea utenti per il tuo team

### 2. **Caricamento dati**
- Vai su "Gestione File" → "Carica Nuovo File"
- Seleziona un file Excel (.xlsx)
- Il sistema estrarrà automaticamente le celle testuali

### 3. **Configurazione etichette**
- Accedi a "Gestione Etichette"
- Crea categorie (es. "Sentiment", "Tematiche")
- Aggiungi etichette con colori distintivi

### 4. **Annotazione**
- Seleziona "Annotazioni" → "Inizia Annotazione"
- Usa i filtri per navigare efficacemente
- Clicca sulle etichette per assegnarle
- Utilizza le scorciatoie da tastiera per velocizzare

### 5. **Monitoraggio**
- Controlla i progressi nella dashboard
- Visualizza statistiche dettagliate
- Confronta il lavoro degli annotatori

## 🎨 Interfaccia

L'interfaccia è progettata per massimizzare la produttività:

- **Design responsivo**: Funziona su desktop, tablet e mobile
- **Navigazione intuitiva**: Breadcrumb e filtri sempre visibili
- **Feedback visivo**: Indicatori di stato e progress bar
- **Scorciatoie**: Controlli da tastiera per operazioni frequenti
- **Temi personalizzabili**: Interfaccia adattabile alle preferenze

## 🔧 Configurazione avanzata

### Variabili d'ambiente

```bash
# Sicurezza
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///instance/analisi_mu.db

# AI (Opzionale)
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
OLLAMA_BASE_URL=http://localhost:11434

# Configurazione file
MAX_CONTENT_LENGTH=16777216  # 16MB
UPLOAD_FOLDER=uploads
```

### Personalizzazione

- **Etichette predefinite**: Modifica `app.py` per le tue categorie
- **Template AI**: Personalizza i prompt in `routes/ai.py`
- **Stili**: Modifica `static/css/style.css` per il branding
- **Workflow**: Adatta le route in `routes/` per processi specifici

## � Casi d'uso

### **Ricerca accademica**
- Analisi di risposte a questionari
- Classificazione di feedback studenti
- Analisi del sentiment in interviste

### **Analisi aziendale**
- Categorizzazione di feedback clienti
- Analisi di survey dipendenti
- Classificazione di recensioni prodotti

### **Ricerca sociale**
- Analisi di risposte aperte in sondaggi
- Classificazione di contenuti social
- Analisi qualitativa di interviste

## � Struttura del progetto

```
anatema/
├── app.py                 # Applicazione Flask principale
├── models.py             # Modelli del database
├── forms.py              # Form WTForms
├── requirements.txt      # Dipendenze Python
├── Dockerfile           # Configurazione Docker
├── docker-compose.yml   # Orchestrazione Docker
├── routes/              # Blueprint delle route
│   ├── auth.py         # Autenticazione
│   ├── main.py         # Pagine principali
│   ├── excel.py        # Gestione file Excel
│   ├── labels.py       # Gestione etichette
│   ├── annotation.py   # Sistema di annotazione
│   ├── admin.py        # Pannello amministratore
│   ├── ai.py           # Integrazione AI
│   ├── statistics.py   # Statistiche e analytics
│   └── questions.py    # Gestione domande
├── templates/           # Template HTML
│   ├── base.html       # Template base
│   ├── auth/           # Template autenticazione
│   ├── main/           # Template principali
│   ├── excel/          # Template file Excel
│   ├── labels/         # Template etichette
│   ├── annotation/     # Template annotazioni
│   ├── admin/          # Template amministrazione
│   └── statistics/     # Template statistiche
├── static/             # File statici
│   ├── css/
│   │   └── style.css   # Stili personalizzati
│   └── js/
│       └── main.js     # JavaScript principale
├── uploads/            # File caricati
├── instance/           # Database e file di configurazione
└── backups/            # Backup del database
```

## 🔒 Sicurezza

- **Password hashate**: Utilizzando Werkzeug per l'hashing sicuro
- **Protezione CSRF**: Tutti i form protetti da attacchi CSRF
- **Gestione sessioni**: Sessioni sicure con Flask-Login
- **Validazione input**: Validazione sia lato server che client
- **Upload sicuri**: Controlli di sicurezza sui file caricati

## 🚀 Deploy in produzione

### Preparazione

1. **Configura l'ambiente**
```bash
export FLASK_ENV=production
export SECRET_KEY=your-production-secret
export DATABASE_URL=postgresql://user:pass@localhost/db
```

2. **Usa un database PostgreSQL**
```bash
pip install psycopg2-binary
```

3. **Configura un server web**
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

4. **Configura HTTPS con nginx**
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🤝 Contributi

Contributi benvenuti! Per contribuire:

1. **Fork** del repository
2. **Crea** un branch per la feature (`git checkout -b feature/amazing-feature`)
3. **Sviluppa** e testa le modifiche
4. **Commit** delle modifiche (`git commit -m 'Add amazing feature'`)
5. **Push** del branch (`git push origin feature/amazing-feature`)
6. **Apri** una Pull Request

### Linee guida per contributi

- Mantieni il codice pulito e commentato
- Scrivi test per le nuove funzionalità
- Segui le convenzioni Python (PEP 8)
- Aggiorna la documentazione se necessario

## 📝 Licenza

Distribuito sotto licenza MIT. Vedi `LICENSE` per dettagli.

## 🆘 Supporto

- **Issues**: Apri un'issue su GitHub per bug e richieste
- **Discussioni**: Partecipa alle discussioni della community
- **Wiki**: Consulta la documentazione dettagliata
- **Email**: Contatta il team di sviluppo per supporto prioritario

## 🙏 Ringraziamenti

Sviluppato con ❤️ per supportare la ricerca qualitativa e l'analisi tematica collaborativa.

Un ringraziamento speciale a tutti i ricercatori e analisti che hanno contribuito con feedback e suggerimenti per migliorare questo strumento.

---

**Anatema** - *Trasforma l'analisi qualitativa in un processo collaborativo e intelligente*
