#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
# setup_macos.sh — Instalación completa LeadForge en Mac Mini
# Ejecutar UNA sola vez después de copiar los archivos:
#   chmod +x setup_macos.sh && ./setup_macos.sh
# ══════════════════════════════════════════════════════════════════════

set -e  # Detener si cualquier comando falla

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAC_USER=$(whoami)
echo "══════════════════════════════════════════════════"
echo "  LeadForge Setup — Mac Mini"
echo "  Usuario: $MAC_USER"
echo "  Directorio: $SCRIPT_DIR"
echo "══════════════════════════════════════════════════"

# ── 1. Verificar Python 3.12 ──────────────────────────────
echo ""
echo "1️⃣  Verificando Python..."
if command -v python3.12 &>/dev/null; then
    echo "   ✅ Python 3.12 encontrado: $(python3.12 --version)"
    PYTHON=python3.12
elif command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
    echo "   ⚠️  Python 3.12 no encontrado, usando python3 ($PY_VER)"
    PYTHON=python3
else
    echo "   ❌ Python no encontrado. Instala con: brew install python@3.12"
    exit 1
fi

# ── 2. Crear virtualenv ───────────────────────────────────
echo ""
echo "2️⃣  Creando entorno virtual..."
cd "$SCRIPT_DIR"
if [ -d "venv" ]; then
    echo "   ℹ️  venv ya existe, saltando..."
else
    $PYTHON -m venv venv
    echo "   ✅ venv creado"
fi

# ── 3. Instalar dependencias ──────────────────────────────
echo ""
echo "3️⃣  Instalando dependencias..."
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "   ✅ Dependencias instaladas"

# ── 4. Crear .env si no existe ────────────────────────────
echo ""
echo "4️⃣  Configurando .env..."
if [ -f ".env" ]; then
    echo "   ℹ️  .env ya existe, no se sobreescribe"
else
    cp .env.template .env
    echo "   ✅ .env creado desde template"
    echo "   ⚠️  IMPORTANTE: Edita .env con tus keys reales antes de arrancar el bot"
fi

# ── 5. Crear carpeta de logs ──────────────────────────────
mkdir -p logs
echo "   ✅ Carpeta logs/ lista"

# ── 6. Instalar launchd (servicio 24/7) ───────────────────
echo ""
echo "5️⃣  Configurando servicio launchd 24/7..."
PLIST_SRC="$SCRIPT_DIR/mac_autostart/com.zenon.leadforge.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.zenon.leadforge.plist"

if [ -f "$PLIST_SRC" ]; then
    # Reemplazar placeholder con usuario real
    sed "s/AQUI_VA_TU_USUARIO/$MAC_USER/g" "$PLIST_SRC" > /tmp/leadforge_temp.plist

    mkdir -p "$HOME/Library/LaunchAgents"
    cp /tmp/leadforge_temp.plist "$PLIST_DST"
    rm /tmp/leadforge_temp.plist

    # Descargar si ya estaba cargado (para evitar error)
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"

    echo "   ✅ Servicio launchd instalado y arrancado"
    echo "   Ver logs: tail -f $SCRIPT_DIR/logs/launchd.log"
else
    echo "   ⚠️  No se encontró el plist. Arranca manualmente: python start_monitor.py"
fi

# ── Resumen final ─────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ Setup completado"
echo ""
echo "  Próximos pasos:"
echo "  1. Edita .env con tus keys reales (si aún no lo hiciste)"
echo "     nano $SCRIPT_DIR/.env"
echo ""
echo "  2. Verifica que el bot esté corriendo:"
echo "     launchctl list | grep leadforge"
echo "     tail -f $SCRIPT_DIR/logs/launchd.log"
echo ""
echo "  3. Prueba en Telegram: envía /leads al bot @ZenonFinder"
echo "══════════════════════════════════════════════════"
