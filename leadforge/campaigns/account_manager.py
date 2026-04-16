"""
LeadForge — Account Manager (Gestión de Cuentas de Email)
Administra las cuentas de email calentadas de Instantly.ai.

Responsabilidades:
  - Obtener lista de cuentas desde Instantly.ai API
  - Rastrear cuántos emails se han enviado hoy por cuenta
  - Distribuir la carga entre cuentas (las que tienen más capacidad, más reciben)
  - NUNCA superar el daily_limit de ninguna cuenta
  - Alertar cuando una cuenta llega al 80% de su límite
  - Detectar y alertar sobre bounce/spam rates peligrosos por cuenta

Los 6 dominios calentados de Zenon son el activo más valioso del sistema.
Este módulo existe para protegerlos.
"""
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx

from ..config import cfg
from ..monitor.alerts import fire_alert, AlertSeverity

logger = logging.getLogger(__name__)

# Persistencia del uso diario (se resetea automáticamente al cambiar el día)
_USAGE_FILE = Path(__file__).parent.parent.parent / "data" / "account_usage.json"


# ============================================================
# MODELO DE CUENTA
# ============================================================
@dataclass
class EmailAccount:
    """Representa una cuenta de email en Instantly.ai."""
    email: str
    daily_limit: int           # límite configurado en Instantly
    sent_today: int = 0        # enviados hoy (rastreado localmente)
    status: str = "active"     # active | paused | warming | error
    bounce_rate: float = 0.0   # porcentaje de bounces
    spam_rate: float = 0.0     # porcentaje de spam

    @property
    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.sent_today)

    @property
    def usage_percent(self) -> float:
        return (self.sent_today / self.daily_limit * 100) if self.daily_limit else 0

    @property
    def is_available(self) -> bool:
        return (
            self.status == "active"
            and self.remaining_today > 0
            and self.bounce_rate < cfg.bounce_rate_threshold
            and self.spam_rate < cfg.spam_rate_threshold
        )

    @property
    def health_emoji(self) -> str:
        if not self.is_available:
            return "🔴"
        if self.usage_percent >= 80:
            return "🟡"
        return "🟢"

    def status_line(self) -> str:
        return (
            f"{self.health_emoji} {self.email:<35} "
            f"{self.sent_today:>3}/{self.daily_limit:<3} enviados "
            f"({self.remaining_today} restantes)"
        )


# ============================================================
# PERSISTENCIA DEL USO DIARIO
# ============================================================

def _load_usage() -> dict:
    """Carga el uso del día actual desde disco."""
    if not _USAGE_FILE.exists():
        return {}
    try:
        data = json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
        # Si los datos son de un día anterior, resetear
        if data.get("date") != str(date.today()):
            return {}
        return data.get("accounts", {})
    except Exception:
        return {}


def _save_usage(usage: dict) -> None:
    """Guarda el uso actualizado en disco."""
    _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USAGE_FILE.write_text(
        json.dumps({"date": str(date.today()), "accounts": usage}, indent=2),
        encoding="utf-8",
    )


# ============================================================
# CLIENTE DE INSTANTLY.AI PARA CUENTAS
# ============================================================

class AccountManager:
    """
    Gestiona todas las cuentas de email de Instantly.ai.
    Rastreo en memoria + disco. Se sincroniza con la API al iniciar.
    """
    INSTANTLY_API = "https://api.instantly.ai/api/v1"

    def __init__(self):
        self.accounts: dict[str, EmailAccount] = {}
        self._usage = _load_usage()
        self._last_sync: Optional[datetime] = None

    async def sync_from_instantly(self) -> None:
        """
        Sincroniza la lista de cuentas desde Instantly.ai API.
        Obtiene: email, daily_limit, status, bounce/spam rates.
        """
        if not cfg.instantly_api_key:
            logger.warning("INSTANTLY_API_KEY no configurado — usando cuentas manuales")
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.INSTANTLY_API}/account/list",
                    params={"api_key": cfg.instantly_api_key, "limit": 100, "skip": 0},
                )
                resp.raise_for_status()
                data = resp.json()
                accounts_raw = data if isinstance(data, list) else data.get("accounts", [])

                for acc in accounts_raw:
                    email = acc.get("email", "")
                    if not email:
                        continue

                    # Obtener uso guardado en disco para este email
                    sent_today = self._usage.get(email, 0)

                    self.accounts[email] = EmailAccount(
                        email=email,
                        daily_limit=acc.get("daily_limit", 50),
                        sent_today=sent_today,
                        status="active" if acc.get("status") == 1 else "paused",
                    )

                self._last_sync = datetime.now()
                logger.info(f"✅ Cuentas sincronizadas: {len(self.accounts)} cuentas")

        except Exception as e:
            logger.error(f"Error sincronizando cuentas de Instantly: {e}")

    def add_manual_accounts(self, accounts: list[dict]) -> None:
        """
        Agrega cuentas manualmente (si no se usa la API de Instantly).
        Format: [{"email": "...", "daily_limit": 50}, ...]
        """
        for acc in accounts:
            email = acc["email"]
            sent = self._usage.get(email, 0)
            self.accounts[email] = EmailAccount(
                email=email,
                daily_limit=acc.get("daily_limit", 50),
                sent_today=sent,
            )
        logger.info(f"✅ {len(accounts)} cuentas configuradas manualmente")

    def select_account(self) -> Optional[EmailAccount]:
        """
        Selecciona la cuenta óptima para el próximo envío.
        Estrategia: distribución ponderada por capacidad restante
        (más capacidad = más probabilidad de ser seleccionada).
        """
        available = [a for a in self.accounts.values() if a.is_available]

        if not available:
            return None

        # Ponderación por capacidad restante
        weights = [a.remaining_today for a in available]
        chosen = random.choices(available, weights=weights, k=1)[0]
        return chosen

    def register_send(self, account_email: str) -> None:
        """Registra que se envió un email desde esta cuenta."""
        if account_email in self.accounts:
            self.accounts[account_email].sent_today += 1

        # Actualizar persistencia
        self._usage[account_email] = self.accounts[account_email].sent_today
        _save_usage(self._usage)

        # Alertar si llega al 80% del límite
        acc = self.accounts.get(account_email)
        if acc and acc.usage_percent >= 80:
            logger.warning(
                f"⚠️ {account_email}: {acc.usage_percent:.0f}% del límite diario"
            )

    async def update_bounce_spam_rates(self) -> None:
        """
        Actualiza bounce/spam rates desde Instantly.ai.
        Si supera umbrales → alerta + marca cuenta como peligrosa.
        """
        if not cfg.instantly_api_key:
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.INSTANTLY_API}/campaign/list",
                    params={"api_key": cfg.instantly_api_key, "limit": 50, "skip": 0},
                )
                if resp.status_code != 200:
                    return

                campaigns = resp.json()
                if isinstance(campaigns, dict):
                    campaigns = campaigns.get("data", [])

                # Agregar bounces/spam por cuenta de email
                account_stats: dict[str, dict] = {}

                for c in campaigns:
                    if c.get("status") != 1:  # solo activas
                        continue
                    sent = c.get("emails_sent_count", 0)
                    if sent < 20:
                        continue

                    bounced = c.get("emails_bounced_count", 0)
                    spam = c.get("spam_block_count", 0)

                    # Las campañas no siempre indican la cuenta específica,
                    # pero podemos calcular tasas globales
                    for email_acc in self.accounts:
                        if email_acc not in account_stats:
                            account_stats[email_acc] = {"sent": 0, "bounced": 0, "spam": 0}
                        account_stats[email_acc]["sent"] += sent
                        account_stats[email_acc]["bounced"] += bounced
                        account_stats[email_acc]["spam"] += spam

                # Actualizar tasas
                for email, stats in account_stats.items():
                    if email not in self.accounts or stats["sent"] == 0:
                        continue
                    acc = self.accounts[email]
                    acc.bounce_rate = stats["bounced"] / stats["sent"] * 100
                    acc.spam_rate = stats["spam"] / stats["sent"] * 100

                    if acc.bounce_rate > cfg.bounce_rate_threshold:
                        await fire_alert(
                            tipo="cuenta_bounce_alto",
                            mensaje=(
                                f"🚨 *Cuenta con bounce rate peligroso*\n"
                                f"Cuenta: `{email}`\n"
                                f"Bounce: `{acc.bounce_rate:.1f}%` "
                                f"(límite: {cfg.bounce_rate_threshold}%)\n"
                                f"Esta cuenta está en PAUSA automática."
                            ),
                            severidad=AlertSeverity.CRITICAL,
                        )
                        acc.status = "paused"

                    if acc.spam_rate > cfg.spam_rate_threshold:
                        await fire_alert(
                            tipo="cuenta_spam_alto",
                            mensaje=(
                                f"🚨 *Cuenta con spam rate crítico*\n"
                                f"Cuenta: `{email}`\n"
                                f"Spam: `{acc.spam_rate:.2f}%` "
                                f"(límite: {cfg.spam_rate_threshold}%)\n"
                                f"⚠️ El dominio está en PELIGRO."
                            ),
                            severidad=AlertSeverity.CRITICAL,
                        )
                        acc.status = "paused"

        except Exception as e:
            logger.error(f"Error actualizando bounce/spam rates: {e}")

    def get_status_report(self) -> str:
        """Reporte en texto del estado de todas las cuentas."""
        if not self.accounts:
            return "Sin cuentas configuradas."

        total_remaining = sum(a.remaining_today for a in self.accounts.values())
        total_limit = sum(a.daily_limit for a in self.accounts.values())
        total_sent = sum(a.sent_today for a in self.accounts.values())

        lines = [
            "📧 ESTADO DE CUENTAS DE EMAIL",
            "─" * 55,
        ]
        for acc in sorted(self.accounts.values(), key=lambda x: x.email):
            lines.append(acc.status_line())

        lines.extend([
            "─" * 55,
            f"TOTAL: {total_sent}/{total_limit} enviados hoy | {total_remaining} disponibles",
        ])
        return "\n".join(lines)

    @property
    def total_available_today(self) -> int:
        return sum(a.remaining_today for a in self.accounts.values() if a.is_available)


# Instancia global
account_manager = AccountManager()
