# 📦 Container Guide -Anatema

Guida completa per l'utilizzo di **Anatema** in ambienti containerizzati. Include configurazioni per Docker, Kubernetes e orchestrazione avanzata.

## 🎯 Panoramica

Anatema è progettato per essere facilmente containerizzato e deployato in diversi ambienti:
- **Sviluppo locale**: Docker Compose per sviluppo rapido
- **Produzione**: Configurazioni ottimizzate per performance
- **Kubernetes**: Deployment scalabili e resilienti
- **Cloud**: Integrazioni con Azure, AWS, GCP

## 🐳 Docker

### Architettura Container

```
┌─────────────────────────────────────────────────────┐
│                    Load Balancer                    │
│                     (nginx)                         │
└─────────────────────┬───────────────────────────────┘
                      │
              ┌───────▼───────┐
              │   App Server  │
              │   (Python)    │
              └───────┬───────┘
                      │
          ┌───────────▼───────────┐
          │      Database         │
          │      (SQLite)         │
          └───────────────────────┘
```

### Configurazioni Disponibili

#### 1. **Development** (docker-compose.yml)
```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "5005:5005"
    environment:
      - FLASK_ENV=development
      - FLASK_DEBUG=1
    volumes:
      - .:/app
      - uploads:/app/uploads
      - instance:/app/instance
```

#### 2. **Production** (docker-compose.prod.yml)
```yaml
version: '3.8'
services:
  app:
    build: .
    restart: unless-stopped
    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
    volumes:
      - uploads:/app/uploads
      - instance:/app/instance
      - backups:/app/backups
    
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - app
```

### Dockerfile Ottimizzato

```dockerfile
# Multi-stage build per ottimizzazione
FROM python:3.13-slim as builder

# Installa dipendenze di build
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e installa dipendenze
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage finale
FROM python:3.13-slim

# Crea utente non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copia dipendenze Python dal builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copia codice applicazione
WORKDIR /app
COPY . .

# Crea directory e imposta permessi
RUN mkdir -p uploads instance backups logs \
    && chown -R appuser:appuser /app

# Cambio all'utente non-root
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Comando di avvio
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
```

## ☸️ Kubernetes

### Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: anatema
  labels:
    app: anatema
spec:
  replicas: 3
  selector:
    matchLabels:
      app: anatema
  template:
    metadata:
      labels:
        app: anatema
    spec:
      containers:
      - name: anatema
        image: anatema:latest
        ports:
        - containerPort: 5000
        env:
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: anatema-secret
              key: secret-key
        - name: DATABASE_URL
          valueFrom:
            configMapKeyRef:
              name: anatema-config
              key: database-url
        resources:
          limits:
            cpu: 500m
            memory: 512Mi
          requests:
            cpu: 250m
            memory: 256Mi
        livenessProbe:
          httpGet:
            path: /health
            port: 5000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 5000
          initialDelaySeconds: 5
          periodSeconds: 5
        volumeMounts:
        - name: uploads
          mountPath: /app/uploads
        - name: instance
          mountPath: /app/instance
      volumes:
      - name: uploads
        persistentVolumeClaim:
          claimName: anatema-uploads
      - name: instance
        persistentVolumeClaim:
          claimName: anatema-instance
```

### Service Configuration

```yaml
apiVersion: v1
kind: Service
metadata:
  name: anatema-service
spec:
  selector:
    app: anatema
  ports:
    - protocol: TCP
      port: 80
      targetPort: 5000
  type: LoadBalancer
```

### ConfigMap e Secrets

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: anatema-config
data:
  database-url: "sqlite:///instance/analisi_mu.db"
  upload-folder: "uploads"
  max-content-length: "16777216"

---
apiVersion: v1
kind: Secret
metadata:
  name: anatema-secret
type: Opaque
data:
  secret-key: <base64-encoded-secret>
  openai-api-key: <base64-encoded-api-key>
```

## 🚀 Orchestrazione Avanzata

### Docker Swarm

```yaml
version: '3.8'
services:
  app:
    image: anatema:latest
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
    networks:
      - app-network
    secrets:
      - source: app_secret
        target: /run/secrets/app_secret
    
  nginx:
    image: nginx:alpine
    deploy:
      replicas: 2
      placement:
        constraints:
          - node.role == manager
    ports:
      - "80:80"
      - "443:443"
    networks:
      - app-network

networks:
  app-network:
    driver: overlay
    attachable: true

secrets:
  app_secret:
    external: true
```

### Helm Chart

```yaml
# Chart.yaml
apiVersion: v2
name: anatema
description: A Helm chart forAnatema
type: application
version: 0.1.0
appVersion: "1.0.0"

# values.yaml
replicaCount: 3

image:
  repository: anatema
  pullPolicy: IfNotPresent
  tag: "latest"

service:
  type: LoadBalancer
  port: 80

ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: anatema.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: anatema-tls
      hosts:
        - anatema.example.com

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 250m
    memory: 256Mi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

## 🔧 Configurazione Avanzata

### Variabili d'Ambiente

```bash
# Applicazione
SECRET_KEY=your-secret-key
FLASK_ENV=production
FLASK_DEBUG=0

# Database
DATABASE_URL=postgresql://user:pass@postgres:5432/analisi_mu
REDIS_URL=redis://redis:6379/0

# Storage
STORAGE_TYPE=s3
S3_BUCKET=anatema-uploads
S3_REGION=us-west-2

# Monitoring
SENTRY_DSN=https://your-sentry-dsn
METRICS_ENABLED=true
LOG_LEVEL=INFO

# AI Services
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
OLLAMA_BASE_URL=http://ollama:11434
```

### Configurazione Nginx

```nginx
upstream analisi_mu {
    server app:5000;
}

server {
    listen 80;
    server_name anatema.example.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name anatema.example.com;
    
    # SSL Configuration
    ssl_certificate /etc/ssl/certs/anatema.crt;
    ssl_certificate_key /etc/ssl/private/anatema.key;
    
    # Security Headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    
    # Gzip Compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    
    # Client body size
    client_max_body_size 16M;
    
    location / {
        proxy_pass http://analisi_mu;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    location /static {
        alias /app/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    location /uploads {
        alias /app/uploads;
        expires 1d;
        add_header Cache-Control "public";
    }
}
```

## 📊 Monitoraggio e Logging

### Prometheus Metrics

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'anatema'
    static_configs:
      - targets: ['app:5000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Anatema Dashboard",
    "panels": [
      {
        "title": "Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(flask_http_requests_total[5m])",
            "legendFormat": "{{method}} {{endpoint}}"
          }
        ]
      },
      {
        "title": "Response Time",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(flask_http_request_duration_seconds_bucket[5m]))",
            "legendFormat": "95th percentile"
          }
        ]
      }
    ]
  }
}
```

### Centralized Logging

```yaml
# Fluentd configuration
version: '3.8'
services:
  fluentd:
    image: fluent/fluentd:latest
    ports:
      - "24224:24224"
    volumes:
      - ./fluentd.conf:/fluentd/etc/fluent.conf
    depends_on:
      - elasticsearch
  
  elasticsearch:
    image: elasticsearch:7.14.0
    environment:
      - discovery.type=single-node
  
  kibana:
    image: kibana:7.14.0
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch
```

## 🔒 Sicurezza

### Scan di Sicurezza

```bash
# Scan vulnerabilità immagine
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image anatema:latest

# Scan configurazione
docker run --rm -v $(pwd):/app \
  bridgecrew/checkov:latest -f /app/Dockerfile
```

### Hardening Container

```dockerfile
# Usa immagine minimal
FROM python:3.13-slim

# Rimuovi shell non necessarie
RUN rm -rf /bin/sh /bin/bash

# Imposta utente non-root
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# Monta filesystem read-only
# docker run --read-only --tmpfs /tmp --tmpfs /var/tmp anatema

# Limita capabilities
# docker run --cap-drop ALL --cap-add NET_BIND_SERVICE anatema
```

## 🚀 Deploy Multi-Cloud

### Azure Container Apps

```yaml
apiVersion: app.containerapp.io/v1beta2
kind: ContainerApp
metadata:
  name: anatema
spec:
  environmentId: /subscriptions/.../containerappsenvironments/anatema-env
  configuration:
    ingress:
      external: true
      targetPort: 5000
    secrets:
      - name: secret-key
        value: your-secret-key
  template:
    containers:
      - name: anatema
        image: anatema:latest
        env:
          - name: SECRET_KEY
            secretRef: secret-key
        resources:
          cpu: 0.5
          memory: 1Gi
```

### AWS ECS

```json
{
  "family": "anatema",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::account:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "anatema",
      "image": "anatema:latest",
      "portMappings": [
        {
          "containerPort": 5000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "FLASK_ENV",
          "value": "production"
        }
      ],
      "secrets": [
        {
          "name": "SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:anatema-secret"
        }
      ]
    }
  ]
}
```

## 🛠️ Troubleshooting

### Debug Container

```bash
# Accesso al container
docker exec -it anatema-app bash

# Verifica log
docker logs anatema-app --tail 100 -f

# Verifica risorse
docker stats anatema-app

# Verifica network
docker network ls
docker network inspect bridge
```

### Problemi Comuni

#### 1. **Container non si avvia**
```bash
# Verifica log di startup
docker logs anatema-app

# Verifica configurazione
docker inspect anatema-app
```

#### 2. **Problemi di rete**
```bash
# Testa connettività
docker exec anatema-app curl -f http://localhost:5000/health

# Verifica porte
docker port anatema-app
```

#### 3. **Problemi di storage**
```bash
# Verifica volumi
docker volume ls
docker volume inspect anatema_uploads

# Verifica permessi
docker exec anatema-app ls -la /app/uploads
```

## 🤝 Best Practices

### 1. **Immagini Ottimizzate**
- Usa immagini slim o alpine
- Multi-stage builds
- Minimizza layer
- Scansiona vulnerabilità

### 2. **Configurazione Sicura**
- Utenti non-root
- Secrets management
- Network policies
- Resource limits

### 3. **Monitoraggio**
- Health checks
- Metrics collection
- Centralized logging
- Alerting

### 4. **Backup e Recovery**
- Backup automatici
- Disaster recovery
- Testing restore
- Documentation

## 🆘 Supporto

Per problemi con i container:

- **Issues**: Usa tag `container` o `docker` su GitHub
- **Logs**: Includi sempre i log del container
- **Configurazione**: Condividi la configurazione (senza secrets)
- **Ambiente**: Specifica l'ambiente (Docker, K8s, etc.)

---

**Container Guide** - *Containerizzazione enterprise perAnatema*
