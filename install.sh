#!/bin/bash
# install.sh — instala plugin.video.turecomendador en LibreELEC / Raspberry Pi
#
# Uso:
#   bash install.sh                   # última release de GitHub
#   bash install.sh 0.4.0             # versión específica
#
# Requiere: curl, unzip (disponibles en LibreELEC por defecto)

set -e

ADDON_ID="plugin.video.turecomendador"
GITHUB_REPO="iolalo/kodi-turecomendador"
VERSION="${1:-latest}"

# Resolver "latest" a tag concreto
if [ "$VERSION" = "latest" ]; then
    VERSION=$(curl -sf "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" \
        | grep '"tag_name"' | head -1 | sed 's/.*"v\([^"]*\)".*/\1/')
    if [ -z "$VERSION" ]; then
        echo "ERROR: no se pudo obtener la última versión de GitHub" >&2
        exit 1
    fi
fi

ZIP_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}/${ADDON_ID}-${VERSION}.zip"
TMP_ZIP="/tmp/${ADDON_ID}-${VERSION}.zip"

# Detectar directorio de addons de Kodi
if [ -d "/storage/.kodi/addons" ]; then
    ADDONS_DIR="/storage/.kodi/addons"
elif [ -d "$HOME/.kodi/addons" ]; then
    ADDONS_DIR="$HOME/.kodi/addons"
else
    echo "ERROR: no se encontró el directorio de addons de Kodi" >&2
    exit 1
fi

echo "==> Descargando ${ADDON_ID} v${VERSION}..."
curl -L -o "$TMP_ZIP" "$ZIP_URL"

echo "==> Instalando en ${ADDONS_DIR}..."
# Eliminar versión anterior si existe
rm -rf "${ADDONS_DIR}/${ADDON_ID}"
unzip -q "$TMP_ZIP" -d "$ADDONS_DIR"
rm "$TMP_ZIP"

echo "==> Instalado correctamente."
echo ""
echo "PRÓXIMOS PASOS:"
echo "  1. Reiniciar Kodi"
echo "  2. Configurar API keys en: Addons → Mi Recomendador Personal → Configurar"
echo "     - Trakt Client ID / Secret"
echo "     - TMDB API Key"
echo "     - DeepSeek API Key (opcional)"
echo "  3. Autenticar Trakt desde el menú principal del addon"
