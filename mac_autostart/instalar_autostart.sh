#!/bin/bash
# ============================================================
# LeadForge / ZenonFinder — Instalador de Autostart Mac Mini
# ============================================================
# Uso: bash mac_autostart/instalar_autostart.sh
# Actualizado: 2026-03-13
# ============================================================

set -e

# ─── Detectar rutas ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
USUARIO=$(whoami)
PLIST_NAME="com.leadforge.system"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$PROJECT_DIR/logs"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
ENTRY_POINT="$PROJECT_DIR/start_monitor.py"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   ZenonFinder — Instalación de Autostart Mac Mini   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Usuario:     $USUARIO"
echo "  Proyecto:    $PROJECT_DIR"
echo "  Entrada:     $ENTRY_POINT"
echo "  Plist dest:  $PLIST_DEST"
echo ""

# ─── Verificar entorno virtual ───────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
  echo "❌ No se encontró el entorno virtual en: $PROJECT_DIR/venv"
  echo ""
  echo "   Ejecuta primero:"
  echo "   cd $PROJECT_DIR"
  echo "   python3 -m venv venv"
  echo "   source venv/bin/activate"
  echo "   pip install -r requirements.txt"
  exit 1
fi
echo "✅ Entorno virtual: $VENV_PYTHON"

# ─── Verificar start_monitor.py ──────────────────────────────
if [ ! -f "$ENTRY_POINT" ]; then
  echo "❌ No se encontró: $ENTRY_POINT"
  echo "   Verifica que copiaste todos los archivos del proyecto."
  exit 1
fi
echo "✅ Punto de entrada: $ENTRY_POINT"

# ─── Verificar .env ──────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "❌ No se encontró el archivo .env en: $PROJECT_DIR"
  echo "   Copia el .env desde tu laptop Windows antes de continuar."
  exit 1
fi
echo "✅ Archivo .env encontrado"

# ─── Crear directorio de logs ────────────────────────────────
mkdir -p "$LOG_DIR"
echo "✅ Directorio de logs: $LOG_DIR"

# ─── Crear directorio LaunchAgents si no existe ──────────────
mkdir -p "$HOME/Library/LaunchAgents"

# ─── Generar el .plist con rutas absolutas ───────────────────
cat > "$PLIST_DEST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

  <key>Label</key>
  <string>$PLIST_NAME</string>

  <!-- Python del venv + start_monitor.py (punto de entrada correcto) -->
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PYTHON</string>
    <string>$ENTRY_POINT</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>PYTHONDONTWRITEBYTECODE</key>
    <string>1</string>
    <key>PYTHONIOENCODING</key>
    <string>utf-8</string>
    <key>LANG</key>
    <string>es_MX.UTF-8</string>
  </dict>

  <!-- Reiniciar automáticamente si el proceso muere -->
  <key>KeepAlive</key>
  <true/>

  <!-- Arrancar al cargar el agente (login o launchctl load) -->
  <key>RunAtLoad</key>
  <true/>

  <!-- Esperar 10 segundos antes de reiniciar si falla -->
  <key>ThrottleInterval</key>
  <integer>10</integer>

  <!-- Logs separados para stdout y stderr -->
  <key>StandardOutPath</key>
  <string>$LOG_DIR/stdout.log</string>

  <key>StandardErrorPath</key>
  <string>$LOG_DIR/stderr.log</string>

  <key>ProcessType</key>
  <string>Background</string>

</dict>
</plist>
EOF

echo "✅ Archivo .plist generado: $PLIST_DEST"

# ─── Cargar el LaunchAgent ───────────────────────────────────
# Descargar versión anterior si existe
launchctl unload "$PLIST_DEST" 2>/dev/null || true
sleep 1

# Cargar nueva versión
launchctl load "$PLIST_DEST"
echo "✅ LaunchAgent cargado"

# ─── Verificar que está corriendo ────────────────────────────
sleep 4
if launchctl list | grep -q "$PLIST_NAME"; then
  echo "✅ ZenonFinder está corriendo como servicio 24/7"
else
  echo "⚠️  El LaunchAgent se registró pero puede estar iniciando..."
  echo "   Revisa errores con: tail -20 $LOG_DIR/stderr.log"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo ""
echo "  ✅ Instalación completada"
echo ""
echo "  Comandos útiles:"
echo "  Ver logs:     tail -f $LOG_DIR/stdout.log"
echo "  Ver errores:  tail -f $LOG_DIR/stderr.log"
echo "  Estado:       launchctl list | grep leadforge"
echo "  Detener:      launchctl unload $PLIST_DEST"
echo "  Reiniciar:    launchctl kickstart -k gui/$(id -u)/$PLIST_NAME"
echo ""
echo "  Recuperar runs Apify pagados:"
echo "  cd $PROJECT_DIR && python recover_apify_runs.py --all"
echo ""
