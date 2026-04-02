"""
LeadForge — Configuración central
Carga y valida todas las variables de entorno.
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env", override=True)


def _require(key: str) -> str:
    """Obtiene variable de entorno requerida. Falla si no está definida."""
    value = os.getenv(key)
    if not value:
        print(f"[ERROR] Variable de entorno requerida no encontrada: {key}")
        print(f"        Revisa tu archivo .env (usa .env.example como guía)")
        sys.exit(1)
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass
class Config:
    # Identificación
    cliente_id: str = field(default_factory=lambda: _require("CLIENTE_ID"))

    # Supabase
    supabase_url: str = field(default_factory=lambda: _require("SUPABASE_URL"))
    supabase_anon_key: str = field(default_factory=lambda: _require("SUPABASE_ANON_KEY"))
    supabase_service_key: str = field(default_factory=lambda: _require("SUPABASE_SERVICE_KEY"))

    # Apify — actor: compass/google-maps-extractor ($4.00/1,000 lugares)
    # Slug con tilde para URL de API: compass~google-maps-extractor
    apify_token: str = field(default_factory=lambda: _require("APIFY_TOKEN"))
    apify_actor_id: str = field(default_factory=lambda: _optional(
        "APIFY_ACTOR_ID", "compass~google-maps-extractor"
    ))

    # Anymail Finder (opcional — requerido solo para enriquecimiento de emails)
    anymail_api_key: str = field(default_factory=lambda: _optional("ANYMAIL_API_KEY"))

    # Anthropic (Claude) (opcional — requerido solo para Campaign Wizard y análisis AI)
    anthropic_api_key: str = field(default_factory=lambda: _optional("ANTHROPIC_API_KEY"))

    # Instantly.ai
    instantly_api_key: str = field(default_factory=lambda: _optional("INSTANTLY_API_KEY"))
    instantly_webhook_secret: str = field(default_factory=lambda: _optional("INSTANTLY_WEBHOOK_SECRET"))

    # Telegram
    telegram_bot_token: str = field(default_factory=lambda: _optional("TELEGRAM_BOT_TOKEN"))
    telegram_master_chat_id: str = field(default_factory=lambda: _optional("TELEGRAM_MASTER_CHAT_ID"))

    # DENUE — API oficial INEGI (directorio de negocios en México)
    denue_api_key: str = field(default_factory=lambda: _optional("DENUE_API_KEY"))

    # yCloud
    ycloud_api_key: str = field(default_factory=lambda: _optional("YCLOUD_API_KEY"))

    # Encriptación
    encryption_key: str = field(default_factory=lambda: _optional("ENCRYPTION_KEY"))

    # Pipeline
    apify_max_places: int = field(default_factory=lambda: int(_optional("APIFY_MAX_PLACES", "50")))
    max_emails_per_company: int = field(default_factory=lambda: int(_optional("MAX_EMAILS_PER_COMPANY", "2")))
    cache_expiry_days: int = field(default_factory=lambda: int(_optional("CACHE_EXPIRY_DAYS", "45")))
    anymail_concurrent_calls: int = field(default_factory=lambda: int(_optional("ANYMAIL_CONCURRENT_CALLS", "3")))
    queue_delay_seconds: int = field(default_factory=lambda: int(_optional("QUEUE_DELAY_SECONDS", "5")))

    # Protección de dominios
    bounce_rate_threshold: float = field(default_factory=lambda: float(_optional("BOUNCE_RATE_THRESHOLD", "3.0")))
    spam_rate_threshold: float = field(default_factory=lambda: float(_optional("SPAM_RATE_THRESHOLD", "0.1")))
    anymail_credits_alert: int = field(default_factory=lambda: int(_optional("ANYMAIL_CREDITS_ALERT_THRESHOLD", "100")))

    # Servidor
    dashboard_port: int = field(default_factory=lambda: int(_optional("DASHBOARD_PORT", "5000")))
    secret_key: str = field(default_factory=lambda: _optional("SECRET_KEY", "dev-secret-change-in-production"))
    environment: str = field(default_factory=lambda: _optional("ENVIRONMENT", "development"))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_phase1(self) -> bool:
        """Valida que las credenciales del núcleo estén configuradas."""
        # Credenciales requeridas para scraping básico
        required = [
            ("CLIENTE_ID", self.cliente_id),
            ("SUPABASE_URL", self.supabase_url),
            ("SUPABASE_SERVICE_KEY", self.supabase_service_key),
            ("APIFY_TOKEN", self.apify_token),
        ]
        # Credenciales opcionales (necesarias para funciones avanzadas)
        optional = [
            ("ANYMAIL_API_KEY", self.anymail_api_key, "enriquecimiento de emails"),
            ("ANTHROPIC_API_KEY", self.anthropic_api_key, "Campaign Wizard + IA"),
            ("INSTANTLY_API_KEY", self.instantly_api_key, "inyeccion a campanas"),
            ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token, "notificaciones Telegram"),
            ("DENUE_API_KEY", self.denue_api_key, "enriquecimiento DENUE/INEGI"),
        ]
        all_ok = True
        for name, value in required:
            if not value:
                print(f"  [X] {name}: no configurado")
                all_ok = False
            else:
                masked = value[:8] + "..." if len(value) > 8 else "***"
                print(f"  [OK] {name}: {masked}")

        print("\n  -- Opcionales --")
        for name, value, uso in optional:
            if not value:
                print(f"  [--] {name}: pendiente ({uso})")
            else:
                masked = value[:8] + "..." if len(value) > 8 else "***"
                print(f"  [OK] {name}: {masked}")

        return all_ok


# Instancia global — importar desde cualquier módulo
cfg = Config()
