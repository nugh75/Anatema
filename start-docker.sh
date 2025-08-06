#!/bin/bash
# Script di avvio perAnatema Docker

set -e

echo "🚀 AvvioAnatema Docker..."

# Verifica che Docker sia in esecuzione
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker non è in esecuzione. Avvia Docker e riprova."
    exit 1
fi

# Funzione per controllare se il container è healthy
check_health() {
    local container_name="anatema"
    local max_attempts=30
    local attempt=1
    
    echo "🔍 Verifica stato del container..."
    
    while [ $attempt -le $max_attempts ]; do
        if docker ps --filter "name=$container_name" --filter "status=running" | grep -q $container_name; then
            health_status=$(docker inspect --format='{{.State.Health.Status}}' $container_name 2>/dev/null || echo "no-health")
            
            if [ "$health_status" = "healthy" ]; then
                echo "✅ Container avviato e healthy!"
                return 0
            elif [ "$health_status" = "no-health" ]; then
                # Se non c'è health check, verifica che il container sia running
                echo "✅ Container avviato (no health check configurato)!"
                return 0
            else
                echo "⏳ Tentativo $attempt/$max_attempts - Stato: $health_status"
            fi
        else
            echo "⏳ Tentativo $attempt/$max_attempts - Container non ancora pronto..."
        fi
        
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo "❌ Container non ha raggiunto lo stato healthy entro il timeout"
    return 1
}

# Stop e rimuovi container esistenti
echo "🛑 Fermando container esistenti..."
docker-compose down

# Build dell'immagine
echo "🏗️ Building nuova immagine..."
docker-compose build --no-cache

# Avvio dei servizi
echo "🎯 Avvio servizi..."
docker-compose up -d

# Verifica che tutto sia partito correttamente
if check_health; then
    echo ""
    echo "🎉Anatema è pronto!"
    echo "📊 Dashboard: http://localhost:5000"
    echo "🔑 Login: admin / admin123"
    echo ""
    echo "📋 Comandi utili:"
    echo "   docker-compose logs -f web  # Visualizza i logs"
    echo "   docker-compose down         # Ferma i servizi"
    echo "   docker-compose ps           # Stato dei container"
    echo ""
else
    echo "❌ Errore nell'avvio. Controlla i logs:"
    echo "   docker-compose logs web"
    exit 1
fi
