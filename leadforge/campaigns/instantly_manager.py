"""
LeadForge — Instantly Manager
Gestiona campañas y la inyección inteligente de leads en Instantly.ai.

Principios de diseño:
  1. NUNCA importar todos los leads de golpe — inyección gradual
  2. Priorizar leads por hierarchy_score (ceo@ primero, info@ al final)
  3. Sincronizar el ritmo de inyección con el daily_limit de la campaña
  4. Respetar la rotación de cuentas (no sobrecargar una sola)
  5. Registrar cada lead inyectado en Supabase para trazabilidad

Instantly.ai API v1:
  GET  /api/v1/campaign/list               → listar campañas
  GET  /api/v1/campaign/get?id=...         → detalles de campaña
  POST /api/v1/lead/add                    → agregar leads
  POST /api/v1/campaign/set/paused         → pausar campaña
  POST /api/v1/campaign/set/active         → activar campaña
  GET  /api/v1/campaign/analytics/overview → stats de campaña
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import httpx

from ..config import cfg
from ..supabase_client import get_db
from ..monitor.alerts import fire_alert, AlertSeverity
from .email_builder import CampaignConfig, InstantlyLead, prepare_lead_for_instantly
from .account_manager import AccountManager

logger = logging.getLogger(__name__)

INSTANTLY_API = "https://api.instantly.ai/api/v1"


# ============================================================
# ESTADÍSTICAS DE CAMPAÑA
# ============================================================
@dataclass
class CampaignStats:
    campaign_id: str
    name: str
    status: str           # active | paused | completed
    leads_total: int
    leads_contacted: int
    opens: int
    replies: int
    bounces: int
    open_rate: float
    reply_rate: float
    bounce_rate: float


# ============================================================
# CLIENTE DE INSTANTLY.AI
# ============================================================
class InstantlyManager:
    def __init__(self):
        self.api_key = cfg.instantly_api_key
        self._headers = {"Content-Type": "application/json"}

    def _params(self, extra: dict = None) -> dict:
        p = {"api_key": self.api_key}
        if extra:
            p.update(extra)
        return p

    async def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{INSTANTLY_API}/{endpoint}",
                    params=self._params(params),
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.error(f"Instantly GET {endpoint}: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Instantly GET {endpoint}: {e}")
        return None

    async def _post(self, endpoint: str, body: dict) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{INSTANTLY_API}/{endpoint}",
                    params={"api_key": self.api_key},
                    json=body,
                )
                if resp.status_code in (200, 201):
                    return resp.json()
                logger.error(f"Instantly POST {endpoint}: HTTP {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Instantly POST {endpoint}: {e}")
        return None

    # ── Campañas ────────────────────────────────────────────────

    async def list_campaigns(self) -> list[dict]:
        """Lista todas las campañas."""
        data = await self._get("campaign/list", {"limit": 100, "skip": 0})
        if isinstance(data, list):
            return data
        return data.get("data", []) if data else []

    async def get_campaign(self, campaign_id: str) -> Optional[dict]:
        """Obtiene detalles de una campaña específica."""
        return await self._get("campaign/get", {"id": campaign_id})

    async def get_campaign_stats(self, campaign_id: str) -> Optional[CampaignStats]:
        """Obtiene estadísticas de rendimiento de una campaña."""
        data = await self._get(
            "campaign/analytics/overview",
            {"campaign_id": campaign_id}
        )
        if not data:
            return None

        sent = data.get("emails_sent_count", 0)
        opens = data.get("open_count", 0)
        replies = data.get("reply_count", 0)
        bounces = data.get("emails_bounced_count", 0)

        return CampaignStats(
            campaign_id=campaign_id,
            name=data.get("name", ""),
            status=data.get("status_name", "unknown"),
            leads_total=data.get("lead_count", 0),
            leads_contacted=sent,
            opens=opens,
            replies=replies,
            bounces=bounces,
            open_rate=opens / sent * 100 if sent else 0,
            reply_rate=replies / sent * 100 if sent else 0,
            bounce_rate=bounces / sent * 100 if sent else 0,
        )

    async def pause_campaign(self, campaign_id: str) -> bool:
        """Pausa una campaña de emergencia."""
        result = await self._post("campaign/set/paused", {"campaign_id": campaign_id})
        if result:
            logger.warning(f"Campaña {campaign_id} PAUSADA")
            return True
        return False

    async def resume_campaign(self, campaign_id: str) -> bool:
        """Reactiva una campaña pausada."""
        result = await self._post("campaign/set/active", {"campaign_id": campaign_id})
        return bool(result)

    # ── Leads ────────────────────────────────────────────────────

    async def add_leads_to_campaign(
        self,
        campaign_id: str,
        leads: list[InstantlyLead],
    ) -> int:
        """
        Agrega leads a una campaña en Instantly.ai.
        Envía en lotes de 100 (límite de la API).
        Returns: cantidad de leads agregados exitosamente.
        """
        if not leads:
            return 0

        total_added = 0
        BATCH_SIZE = 100

        for i in range(0, len(leads), BATCH_SIZE):
            batch = leads[i: i + BATCH_SIZE]
            payload = {
                "campaign_id": campaign_id,
                "leads": [l.to_instantly_payload() for l in batch],
                "skip_if_in_workspace": True,  # no duplicar emails
            }

            result = await self._post("lead/add", payload)
            if result:
                added = result.get("total_new_leads", len(batch))
                total_added += added
                logger.info(f"Instantly: +{added} leads en campaña {campaign_id}")
            else:
                logger.error(f"Fallo al agregar batch de {len(batch)} leads")

            # Pequeña pausa entre batches
            if i + BATCH_SIZE < len(leads):
                await asyncio.sleep(1)

        return total_added

    async def get_lead_count_in_campaign(self, campaign_id: str) -> int:
        """Cuántos leads tiene actualmente la campaña."""
        data = await self.get_campaign(campaign_id)
        if data:
            return data.get("lead_count", 0)
        return 0

    # ── Inyección Gradual ─────────────────────────────────────────

    async def inject_leads_gradually(
        self,
        config: CampaignConfig,
        db_leads: list[dict],
        account_mgr: AccountManager,
        buffer_days: int = 3,
    ) -> dict:
        """
        Inyecta leads de forma inteligente: solo lo que la campaña puede
        enviar en los próximos `buffer_days` días.

        Estrategia:
          - Calcular cuántos leads ya están en la campaña
          - Calcular capacidad de envío en `buffer_days` días
          - Inyectar solo la diferencia (buffer_size - ya_en_campana)
          - Priorizar por hierarchy_score (los de mayor jerarquía primero)

        Args:
            config: Configuración de la campaña
            db_leads: Lista de leads desde Supabase (con email, scores, etc.)
            account_mgr: Para conocer la capacidad total de envío
            buffer_days: Días de buffer hacia adelante

        Returns: dict con estadísticas de la inyección
        """
        campaign_id = config.instantly_campaign_id

        # Calcular capacidad del buffer
        buffer_size = config.daily_limit * buffer_days

        # Cuántos leads ya están en Instantly
        already_in_campaign = await self.get_lead_count_in_campaign(campaign_id)
        to_inject_count = max(0, buffer_size - already_in_campaign)

        logger.info(
            f"Campaña {config.nombre_campana}:\n"
            f"  En Instantly: {already_in_campaign}\n"
            f"  Buffer ({buffer_days} días × {config.daily_limit}/día): {buffer_size}\n"
            f"  A inyectar ahora: {to_inject_count}"
        )

        if to_inject_count == 0:
            return {
                "injected": 0,
                "reason": f"Buffer lleno ({already_in_campaign} leads en cola)",
            }

        # Ordenar leads por score descendente (ceo@ primero)
        sorted_leads = sorted(
            db_leads,
            key=lambda x: x.get("hierarchy_score", 0),
            reverse=True,
        )
        batch_to_inject = sorted_leads[:to_inject_count]

        # Preparar leads con personalización
        instantly_leads: list[InstantlyLead] = []
        for lead in batch_to_inject:
            try:
                il = await prepare_lead_for_instantly(lead, config)
                instantly_leads.append(il)
            except Exception as e:
                logger.error(f"Error preparando lead {lead.get('email')}: {e}")

        if not instantly_leads:
            return {"injected": 0, "reason": "No se pudieron preparar leads"}

        # Inyectar en Instantly.ai
        injected = await self.add_leads_to_campaign(campaign_id, instantly_leads)

        # Marcar en Supabase como inyectados
        if injected > 0:
            await self._mark_leads_injected(
                leads=batch_to_inject[:injected],
                campaign_id=campaign_id,
                cliente_id=config.cliente_id,
            )

        result = {
            "injected": injected,
            "buffer_size": buffer_size,
            "already_in_campaign": already_in_campaign,
            "queued_for_later": len(db_leads) - injected,
            "top_lead_score": instantly_leads[0].personalization if instantly_leads else "",
        }

        # Alerta si hay leads esperando
        if result["queued_for_later"] > 0:
            logger.info(
                f"✅ {injected} leads inyectados | "
                f"{result['queued_for_later']} en cola para próximas inyecciones"
            )

        return result

    async def _mark_leads_injected(
        self,
        leads: list[dict],
        campaign_id: str,
        cliente_id: Optional[str],
    ) -> None:
        """Actualiza estado en Supabase de los leads inyectados."""
        db = get_db()
        for lead in leads:
            try:
                db.table("email_leads").update({
                    "campania_id": campaign_id,
                    "estado_campania": "en_campana",
                }).eq("id", lead.get("id")).execute()
            except Exception as e:
                logger.debug(f"Error marcando lead como inyectado: {e}")


# ============================================================
# FUNCIÓN PRINCIPAL DE CAMPAÑA COMPLETA
# ============================================================

async def launch_campaign(
    config: CampaignConfig,
    account_mgr: AccountManager,
    max_leads: Optional[int] = None,
) -> dict:
    """
    Orquesta el lanzamiento/actualización de una campaña:
    1. Verificar que la campaña exista en Instantly
    2. Obtener leads aptos de Supabase (por categoría/ciudad)
    3. Inyectar de forma gradual
    4. Reportar resultado

    Args:
        config: Configuración de la campaña
        account_mgr: Gestor de cuentas para verificar capacidad
        max_leads: Límite máximo de leads a inyectar en esta ejecución

    Returns: dict con resumen del lanzamiento
    """
    manager = InstantlyManager()

    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 Lanzando campaña: {config.nombre_campana}")
    logger.info(f"{'='*50}")

    # Verificar que la campaña existe
    campaign = await manager.get_campaign(config.instantly_campaign_id)
    if not campaign:
        await fire_alert(
            tipo="campana_no_encontrada",
            mensaje=(
                f"❌ *Campaña no encontrada en Instantly.ai*\n"
                f"ID: `{config.instantly_campaign_id}`\n"
                f"Verifica que el campaign_id en tu config YAML sea correcto."
            ),
            severidad=AlertSeverity.CRITICAL,
        )
        return {"error": "Campaña no encontrada en Instantly.ai"}

    logger.info(f"✅ Campaña verificada: {campaign.get('name', 'Sin nombre')}")

    # Obtener leads aptos desde Supabase
    db = get_db()
    query = (
        db.table("email_leads")
        .select("id, email, nombre_negocio, owner_name, ciudad, categoria, "
                "hierarchy_score, lead_score")
        .eq("cliente_id", config.cliente_id or cfg.cliente_id)
        .eq("email_status", "valid")
        .eq("do_not_contact", False)
        .is_("campania_id", "null")     # solo los que NO están en campaña
        .order("hierarchy_score", desc=True)
    )

    if max_leads:
        query = query.limit(max_leads * 3)  # pedir más de los necesarios (algunos serán buffer)

    result = query.execute()
    available_leads = result.data or []

    logger.info(f"Leads disponibles en DB: {len(available_leads)}")

    if not available_leads:
        return {
            "injected": 0,
            "reason": "Sin leads nuevos disponibles en Supabase",
        }

    # Inyección gradual
    injection_result = await manager.inject_leads_gradually(
        config=config,
        db_leads=available_leads,
        account_mgr=account_mgr,
    )

    # Reporte por Telegram
    from ..monitor.alerts import send_telegram
    await send_telegram(
        f"🚀 *Campaña lanzada: {config.nombre_campana}*\n\n"
        f"📧 Leads inyectados: *{injection_result.get('injected', 0)}*\n"
        f"📋 En cola (próximas inyecciones): {injection_result.get('queued_for_later', 0)}\n"
        f"🏦 Buffer configurado: {injection_result.get('buffer_size', 0)} leads\n\n"
        f"El pipeline está activo en Instantly.ai."
    )

    return injection_result


# Instancia global
instantly = InstantlyManager()
