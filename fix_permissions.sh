#!/bin/bash

echo "🔧 Fixing permissions for local and Docker environments..."

# Funzione per verificare se siamo in ambiente Docker
is_docker() {
    [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null
}

# Determina l'utente corretto
if is_docker; then
    TARGET_USER="ubuntu"
    TARGET_GROUP="ubuntu"
    echo "📦 Environment: Docker (user: ubuntu)"
else
    TARGET_USER="nugh75"
    TARGET_GROUP="nugh75"
    echo "💻 Environment: Local (user: nugh75)"
fi

# Cambia proprietario delle directory principali se necessario
echo "🏠 Setting ownership for main directories..."
sudo chown -R $TARGET_USER:$TARGET_GROUP instance/ 2>/dev/null || chown -R $TARGET_USER:$TARGET_GROUP instance/
sudo chown -R $TARGET_USER:$TARGET_GROUP uploads/ 2>/dev/null || chown -R $TARGET_USER:$TARGET_GROUP uploads/

# Imposta permessi per compatibilità cross-environment
echo "🔐 Setting cross-compatible permissions..."

# Directory permissions (775 = rwxrwxr-x)
chmod 775 instance/
chmod 775 uploads/

# Database files permissions (664 = rw-rw-r--)
find instance/ -name "*.db*" -exec chmod 664 {} \;

# Ensure .gitkeep files have correct permissions
find instance/ uploads/ -name ".gitkeep" -exec chmod 644 {} \;

echo "✅ Permissions fixed!"
echo ""
echo "📊 Current permissions:"
echo "Instance directory:"
ls -la | grep instance
echo ""
echo "Instance contents (first 3 files):"
ls -la instance/ | head -4
echo ""
echo "Uploads directory:"
ls -la | grep uploads
