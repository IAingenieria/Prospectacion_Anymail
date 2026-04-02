"""
LeadForge — Anymail Finder Enricher
Enriquece leads con emails usando Anymail Finder.
Soporta 2 rutas:
  - Verificar email existente (/verify-email) → más barato (0.1 crédito)
  - Buscar email por empresa (/find-email/company) → más caro (1 crédito)

Usa llamadas asíncronas paralelas para acelerar el proceso.
Protege contra fallo por cuota/pago detectado.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import cfg

logger = logging.getLogger(__name__)

ANYMAIL_BASE = "https://api.anymailfinder.com/v5.1"


@dataclass
class AnymailResult:
    """Resultado de Anymail Finder para una empresa."""
    company_name: str
    emails: list[dict]       # Lista de {email, email_status, ...}
    route_used: str          # "verify" | "find_company"
    credits_used: float
    error: Optional[str] = None

    @property
    def tiene_emails_validos(self) -> bool:
        return any(e.get("email_status") == "valid" for e in self.emails)


class AnymailEnricher:
    def __init__(self):
        self.api_key = cfg.anymail_api_key
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._account_ok: bool = True  # False si hay error de cuota/pago

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Semáforo para controlar llamadas paralelas (configurable en .env)."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(cfg.anymail_concurrent_calls)
        return self._semaphore

    async def check_account_status(self) -> dict:
        """
        Verifica el estado de la cuenta Anymail Finder.
        Detecta problemas de pago o créditos agotados.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{ANYMAIL_BASE}/account",
                    headers=self.headers,
                )
                if resp.status_code == 401:
                    self._account_ok = False
                    return {"ok": False, "error": "API key inválida o cuenta no pagada"}
                if resp.status_code == 402:
                    self._account_ok = False
                    return {"ok": False, "error": "Cuenta Anymail Finder sin créditos o pago vencido"}

                data = resp.json()
                # Anymail Finder API devuelve "credits_left" (no "credits_remaining")
                credits = data.get("credits_left", data.get("credits_remaining", 0))

                if credits < cfg.anymail_credits_alert:
                    logger.warning(
                        f"Anymail Finder: solo {credits} creditos restantes. "
                        f"Recargar antes de continuar."
                    )

                self._account_ok = True
                return {
                    "ok": True,
                    "credits_remaining": credits,
                    "plan": data.get("plan_name", data.get("plan", "unknown")),
                }

        except httpx.ConnectError:
            self._account_ok = False
            return {"ok": False, "error": "No se puede conectar a Anymail Finder"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def verify_email(self, email: str) -> AnymailResult:
        """
        Verifica un email existente.
        Ruta: POST /verify-email
        Costo: ~0.1 crédito (verificación)
        """
        if not self._account_ok:
            return AnymailResult(
                company_name="", emails=[], route_used="verify",
                credits_used=0, error="Cuenta Anymail inactiva"
            )

        async with self._get_semaphore():
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{ANYMAIL_BASE}/verify-email",
                        headers=self.headers,
                        json={"email": email},
                    )

                    if resp.status_code in (401, 402):
                        self._account_ok = False
                        logger.error(f"Anymail Finder: error {resp.status_code} — verificar pago/cuota")
                        return AnymailResult(
                            company_name="", emails=[], route_used="verify",
                            credits_used=0, error=f"HTTP {resp.status_code}"
                        )

                    data = resp.json()
                    email_status = data.get("email_status", "unknown")

                    return AnymailResult(
                        company_name="",
                        emails=[{"email": email, "email_status": email_status}],
                        route_used="verify",
                        credits_used=0.1,
                    )

            except Exception as e:
                logger.error(f"Error verificando {email}: {e}")
                return AnymailResult(
                    company_name="", emails=[], route_used="verify",
                    credits_used=0, error=str(e)
                )

    async def find_by_company(self, company_name: str) -> AnymailResult:
        """
        Busca emails de una empresa por nombre.
        Ruta: POST /find-email/company
        Costo: ~1 crédito (búsqueda completa)
        """
        if not self._account_ok:
            return AnymailResult(
                company_name=company_name, emails=[], route_used="find_company",
                credits_used=0, error="Cuenta Anymail inactiva"
            )

        async with self._get_semaphore():
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.post(
                        f"{ANYMAIL_BASE}/find-email/company",
                        headers=self.headers,
                        json={"company_name": company_name},
                    )

                    if resp.status_code in (401, 402):
                        self._account_ok = False
                        logger.error(f"Anymail Finder: error {resp.status_code}")
                        return AnymailResult(
                            company_name=company_name, emails=[],
                            route_used="find_company", credits_used=0,
                            error=f"HTTP {resp.status_code}"
                        )

                    data = resp.json()
                    emails = data.get("emails", [])

                    # Normalizar estructura si viene como strings simples
                    normalized = []
                    for e in emails:
                        if isinstance(e, str):
                            normalized.append({"email": e, "email_status": "unknown"})
                        elif isinstance(e, dict):
                            normalized.append(e)

                    return AnymailResult(
                        company_name=company_name,
                        emails=normalized,
                        route_used="find_company",
                        credits_used=1.0,
                    )

            except Exception as e:
                logger.error(f"Error buscando emails de '{company_name}': {e}")
                return AnymailResult(
                    company_name=company_name, emails=[],
                    route_used="find_company", credits_used=0, error=str(e)
                )

    async def enrich_negocio(
        self,
        company_name: str,
        existing_email: Optional[str] = None,
    ) -> AnymailResult:
        """
        Lógica inteligente de enriquecimiento:
        - Si Apify ya trajo email → verificar (0.1 crédito)
        - Si no hay email → buscar por empresa (1 crédito)

        Esto puede ahorrar hasta 90% de créditos cuando Apify trae emails.
        """
        if existing_email and "@" in existing_email:
            logger.debug(f"Verificando email existente: {existing_email}")
            return await self.verify_email(existing_email)
        else:
            logger.debug(f"Buscando email para empresa: {company_name}")
            return await self.find_by_company(company_name)

    async def enrich_batch(
        self,
        companies: list[dict],  # [{company_name, existing_email}, ...]
    ) -> list[AnymailResult]:
        """
        Enriquece un lote de empresas en paralelo.
        Respeta el semáforo de concurrencia (MAX_CONCURRENT del .env).
        """
        tasks = [
            self.enrich_negocio(
                company_name=c["company_name"],
                existing_email=c.get("existing_email"),
            )
            for c in companies
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Manejar excepciones que se escaparon
        final = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Excepción no capturada en enrich_batch: {r}")
                final.append(AnymailResult(
                    company_name="unknown", emails=[], route_used="error",
                    credits_used=0, error=str(r)
                ))
            else:
                final.append(r)

        return final


# Instancia global
anymail = AnymailEnricher()
