"""
verify_personal_emails.py
═══════════════════════════════════════════════════════════════
Verifica emails personales (Gmail/Hotmail/etc) almacenados en
leads_master que vienen de DENUE y nunca pasaron por Anymail.

- Lee leads con email personal y anymail_procesado=False
- Llama a Anymail verify-email para cada uno
- Si válido  → verificado=True, canal_recomendado="brevo"
- Si inválido → anymail_procesado=True, verificado=False (no reenviar)

Uso:
    venv/bin/python -m leadforge.verify_personal_emails
"""
import asyncio
import logging

import httpx

from .config import cfg
from .supabase_client import get_db, update_lead_email_personal_verificado
from .validation_cascade import DOMINIOS_PERSONALES

logger = logging.getLogger(__name__)

ANYMAIL_VERIFY_URL = "https://api.anymailfinder.com/v5.1/verify-email"


async def _verificar_email(
    client: httpx.AsyncClient,
    email: str,
    semaphore: asyncio.Semaphore,
) -> str:
    """Llama a Anymail verify-email. Retorna el email_status."""
    async with semaphore:
        try:
            resp = await client.post(
                ANYMAIL_VERIFY_URL,
                headers={"X-API-Key": cfg.anymail_api_key},
                json={"email": email},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("email_status", "unknown")
            logger.warning(f"  Anymail HTTP {resp.status_code} para {email}")
            return "unknown"
        except Exception as e:
            logger.warning(f"  Error verificando {email}: {e}")
            return "unknown"


async def run_verify_personal_emails(cliente_id: str | None = None) -> dict:
    """
    Verifica todos los emails personales no procesados.
    Retorna stats del proceso.
    """
    cliente_id = cliente_id or cfg.cliente_id
    db = get_db()

    # Obtener leads con email personal sin procesar
    result = db.table("leads_master").select(
        "id, nombre_negocio, email, ciudad"
    ).eq("cliente_id", cliente_id).eq(
        "anymail_procesado", False
    ).not_.is_("email", "null").execute()

    todos = result.data or []

    # Filtrar solo dominios personales
    personales = [
        l for l in todos
        if l.get("email", "").split("@")[-1].lower() in DOMINIOS_PERSONALES
    ]

    if not personales:
        logger.info("No hay emails personales pendientes de verificar.")
        return {"procesados": 0, "validos": 0, "invalidos": 0, "creditos": 0}

    logger.info(f"📧 Emails personales a verificar: {len(personales)}")

    # Verificar créditos antes de empezar
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.anymailfinder.com/v5.1/account",
            headers={"X-API-Key": cfg.anymail_api_key},
            timeout=10,
        )
        if resp.status_code == 200:
            creditos = resp.json().get("credits_remaining", "?")
            logger.info(f"  Anymail créditos disponibles: {creditos}")

    stats = {"procesados": 0, "validos": 0, "invalidos": 0, "creditos": len(personales)}
    semaphore = asyncio.Semaphore(cfg.anymail_concurrent_calls)

    async with httpx.AsyncClient() as client:
        async def procesar(lead: dict):
            email = lead["email"]
            status = await _verificar_email(client, email, semaphore)

            update_lead_email_personal_verificado(
                lead_id=lead["id"],
                email=email,
                email_status=status,
                canal="brevo",
            )

            stats["procesados"] += 1
            if status == "valid":
                stats["validos"] += 1
            else:
                stats["invalidos"] += 1

        await asyncio.gather(*[procesar(l) for l in personales])

    logger.info(
        f"\n{'='*45}\n"
        f"EMAILS PERSONALES VERIFICADOS\n"
        f"{'='*45}\n"
        f"  Total procesados:  {stats['procesados']}\n"
        f"  Válidos (→ Brevo): {stats['validos']}\n"
        f"  Inválidos:         {stats['invalidos']}\n"
        f"  Créditos usados:   ~{stats['creditos']}\n"
        f"{'='*45}"
    )
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run_verify_personal_emails())
