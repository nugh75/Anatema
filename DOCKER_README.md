# 🐳 Docker Deployment Guide -Anatema

Questa guida ti aiuterà a configurare e deployare **Anatema** utilizzando Docker e Docker Compose per un ambiente di produzione robusto e scalabile.

## 📋 Prerequisiti

- **Docker** 20.10+
- **Docker Compose** 2.0+
- **Git** per clonare il repository
- **Almeno 2GB di RAM** disponibile
- **Almeno 10GB di spazio disco** per dati e log

## 🚀 Quick Start

### 1. Clona il repository
```bash
git clone https://github.com/nugh75/anatema.git
cd anatema
```

### 2. Configura l'ambiente
```bash
# Copia il file di configurazione
cp .env.example .env

# Modifica le configurazioni (opzionale)
nano .env
```

### 3. Avvia l'applicazione
```bash
# Modalità development
docker compose up -d

# Modalità production
docker compose -f docker-compose.prod.yml up -d
```

### 4. Accedi all'applicazione
- **URL**: http://localhost:5005
- **Username**: admin
- **Password**: admin123

⚠️ **IMPORTANTE**: Cambia immediatamente la password dell'admin!

## 📁 Struttura dei file Docker

```
anatema/
├── Dockerfile                 # Immagine principale dell'applicazione
├── docker-compose.yml         # Configurazione development
├── docker-compose.prod.yml    # Configurazione production
├── docker-init.sh            # Script di inizializzazione
├── start-docker.sh           # Script di avvio rapido
└── .env.example              # Template delle variabili d'ambiente
```

## 🔧 Configurazione

### Variabili d'ambiente (.env)

```bash
# === APPLICAZIONE ===
SECRET_KEY=your-super-secret-key-here
FLASK_ENV=production
FLASK_DEBUG=0

# === DATABASE ===
DATABASE_URL=sqlite:///instance/analisi_mu.db

# === UPLOAD ===
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216

# === AI (Opzionale) ===
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
OLLAMA_BASE_URL=http://localhost:11434

# === SICUREZZA ===
CSRF_ENABLED=true
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_HTTPONLY=true
```

### Configurazione Development vs Production

#### Development (docker-compose.yml)
- Hot reload abilitato
- Debug mode attivo
- Porte esposte direttamente
- Volumi per sviluppo

#### Production (docker-compose.prod.yml)
- Ottimizzazioni per performance
- Logging strutturato
- Sicurezza avanzata
- Backup automatici

## 🏗️ Dockerfile Spiegato

```dockerfile
# Immagine base Python slim
FROM python:3.13-slim

# Etichette per metadata
LABEL maintainer="anatema@example.com"
LABEL version="1.0.0"
LABEL description="Sistema di etichettatura collaborativa"

# Creazione utente non-root per sicurezza
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Dipendenze di sistema
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Directory di lavoro
WORKDIR /app

# Copia e installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia codice applicazione
COPY . .

# Creazione directory necessarie
RUN mkdir -p uploads instance backups \
    && chown -R appuser:appuser /app

# Cambio all'utente non-root
USER appuser

# Esposizione porta
EXPOSE 5005

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5005/health || exit 1

# Comando di avvio
CMD ["python", "app.py"]
```

## 🔒 Sicurezza

### Configurazioni di sicurezza implementate:

1. **Utente non-root**: L'applicazione gira con utente dedicato
2. **Secrets management**: Variabili sensibili tramite .env
3. **Network isolation**: Comunicazione tra container isolata
4. **File permissions**: Permessi corretti sui file critici
5. **Healthcheck**: Monitoraggio dello stato dell'applicazione

### Raccomandazioni aggiuntive:

```bash
# Genera una chiave sicura
openssl rand -hex 32

# Imposta permessi corretti
chmod 600 .env
chmod 755 uploads/ instance/

# Configura firewall (esempio con ufw)
sudo ufw allow 5005/tcp
sudo ufw enable
```

## 📊 Monitoraggio e Logging

### Visualizzazione dei log
```bash
# Log in tempo reale
docker compose logs -f

# Log di un servizio specifico
docker compose logs -f app

# Ultimi 100 log
docker compose logs --tail=100

# Log con timestamp
docker compose logs -t
```

### Metriche container
```bash
# Statistiche risorse
docker stats

# Informazioni dettagliate
docker inspect anatema-app

# Processi in esecuzione
docker compose top
```

## 🛠️ Operazioni di Manutenzione

### Backup del database
```bash
# Backup manuale
docker compose exec app python -c "
from app import create_app
from models import db
import shutil
import datetime

app = create_app()
with app.app_context():
    backup_name = f'backup_{datetime.datetime.now().strftime(\"%Y%m%d_%H%M%S\")}.db'
    shutil.copy('instance/analisi_mu.db', f'backups/{backup_name}')
    print(f'Backup creato: {backup_name}')
"
```

### Aggiornamento dell'applicazione
```bash
# Ferma l'applicazione
docker compose down

# Aggiorna il codice
git pull origin main

# Ricostruisci l'immagine
docker compose build --no-cache

# Riavvia l'applicazione
docker compose up -d
```

### Pulizia del sistema
```bash
# Rimuovi container, volumi e immagini inutilizzate
docker system prune -a --volumes

# Rimuovi solo i container fermati
docker container prune

# Rimuovi solo le immagini non utilizzate
docker image prune -a
```

## 🔧 Risoluzione dei Problemi

### Container non si avvia
```bash
# Controlla i log
docker compose logs app

# Verifica lo stato
docker compose ps

# Ispeziona il container
docker inspect anatema-app
```

### Problemi di permessi
```bash
# Correggi i permessi
docker compose exec app chown -R appuser:appuser /app

# Verifica i permessi
docker compose exec app ls -la
```

### Database locked
```bash
# Ferma l'applicazione
docker compose down

# Rimuovi il file di lock
rm -f instance/analisi_mu.db-wal instance/analisi_mu.db-shm

# Riavvia
docker compose up -d
```

### Problemi di connessione AI
```bash
# Testa la connessione OpenAI
docker compose exec app python -c "
import openai
import os
openai.api_key = os.getenv('OPENAI_API_KEY')
print('OpenAI connection OK' if openai.api_key else 'No API key')
"
```

## 🚀 Deploy in Produzione

### 1. Configurazione server
```bash
# Aggiorna il sistema
sudo apt update && sudo apt upgrade -y

# Installa Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Installa Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. Configurazione produzione
```bash
# Usa la configurazione di produzione
docker compose -f docker-compose.prod.yml up -d

# Configura nginx come reverse proxy
sudo apt install nginx

# Configura SSL con Let's Encrypt
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

### 3. Monitoraggio produzione
```bash
# Installa strumenti di monitoraggio
docker run -d \
  --name watchtower \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --schedule "0 0 2 * * *"
```

## 📈 Scaling

### Scaling orizzontale
```bash
# Scala l'applicazione
docker compose up -d --scale app=3

# Usa un load balancer
docker compose -f docker-compose.prod.yml up -d
```

### Ottimizzazioni performance
```bash
# Configura memoria e CPU
docker compose up -d --memory="1g" --cpus="2"

# Usa un database esterno
# Modifica DATABASE_URL in .env per PostgreSQL
```

## 🤝 Contributi

Per contribuire al setup Docker:

1. Testa le modifiche localmente
2. Documenta le nuove configurazioni
3. Aggiorna questo README
4. Apri una Pull Request

## 🆘 Supporto

Per problemi specifici di Docker:

- **Issues**: Apri un'issue su GitHub con tag `docker`
- **Logs**: Includi sempre i log del container
- **Configurazione**: Condividi la tua configurazione (senza secrets)

---

**Docker Deployment** - *Containerizzazione professionale perAnatema*
