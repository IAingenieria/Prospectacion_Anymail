"""
LeadForge — Validación en Cascada de Emails (5 Niveles)
Protege los dominios calentados de Instantly.ai rechazando emails de riesgo.

Nivel 1: email_status ESTRICTO (solo "valid")
Nivel 2: Filtro de jerarquía (top 2 por empresa)
Nivel 3: MX Record Check (¿el dominio recibe emails?)
Nivel 4: Catch-all Detection (¿acepta cualquier email?)
Nivel 5: Deduplicación global (¿ya está en campaña activa?)
"""
import asyncio
import logging
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .hierarchy_filter import EmailScore, filter_top_emails

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    APROBADO = "aprobado"
    APROBADO_PERSONAL = "aprobado_personal"     # Gmail/Hotmail/Yahoo verificado → va a Brevo
    RECHAZADO_STATUS = "rechazado_status_invalido"
    RECHAZADO_SIN_MX = "rechazado_sin_mx"
    CATCH_ALL = "catch_all_revisar_manual"
    DUPLICADO = "rechazado_duplicado"
    APROBADO_CON_ADVERTENCIA = "aprobado_con_advertencia"


DOMINIOS_PERSONALES = {
    "gmail.com", "hotmail.com", "hotmail.com.mx",
    "yahoo.com", "yahoo.com.mx", "yahoo.es",
    "outlook.com", "outlook.com.mx",
    "live.com", "live.com.mx",
    "icloud.com", "me.com",
    "protonmail.com", "pm.me",
}


@dataclass
class ValidationResult:
    email: str
    status: ValidationStatus
    score: int
    motivo: str
    es_catch_all: bool = False
    tiene_mx: bool = True
    es_duplicado: bool = False
    datos_originales: dict = field(default_factory=dict)

    @property
    def es_apto_para_campana(self) -> bool:
        """¿Este email puede enviarse automáticamente a campaña (Instantly.ai)?"""
        return self.status == ValidationStatus.APROBADO

    @property
    def es_apto_para_brevo(self) -> bool:
        """¿Este email va al track de Brevo (emails personales verificados)?"""
        return self.status == ValidationStatus.APROBADO_PERSONAL

    @property
    def requiere_revision_manual(self) -> bool:
        """¿Requiere que Zenon lo revise antes de enviar?"""
        return self.status == ValidationStatus.CATCH_ALL


# ============================================================
# NIVEL 3: MX Record Check
# ============================================================
async def check_mx_record(dominio: str) -> bool:
    """
    Verifica que el dominio tenga un servidor de correo (registro MX).
    Un dominio sin MX = los emails nunca llegarán.
    """
    try:
        # Usar socket para resolver MX via DNS
        import dns.resolver  # dnspython
        try:
            answers = dns.resolver.resolve(dominio, "MX", lifetime=5)
            return len(answers) > 0
        except Exception:
            return False
    except ImportError:
        # Fallback si dnspython no está instalado
        try:
            socket.getaddrinfo(dominio, None)
            return True  # Al menos el dominio existe
        except socket.gaierror:
            return False


# ============================================================
# NIVEL 4: Catch-all Detection
# ============================================================
async def check_catch_all(
    dominio: str,
    anymail_api_key: str,
) -> bool:
    """
    Detecta si un dominio acepta CUALQUIER email (catch-all).
    Los dominios catch-all aceptan emails a direcciones inexistentes.
    Enviar a catch-all = riesgo de bounce y daño al dominio de envío.

    Método: Verificar un email aleatorio que definitivamente no existe.
    Si Anymail dice "valid" → es catch-all.
    """
    import httpx
    test_email = f"leadforge_test_xq9z7_{dominio.split('.')[0]}@{dominio}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.anymailfinder.com/v5.1/verify-email",
                headers={"X-API-Key": anymail_api_key},
                json={"email": test_email},
            )
            if resp.status_code == 200:
                status = resp.json().get("email_status", "unknown")
                return status == "valid"  # Si el email fantasma es "valid" → catch-all
    except Exception as e:
        logger.warning(f"Error en catch-all check para {dominio}: {e}")

    return False


# ============================================================
# VALIDACIÓN COMPLETA POR EMPRESA
# ============================================================
async def validate_company_emails(
    emails_raw: list[dict],
    anymail_api_key: str,
    existing_emails: set[str],
    max_per_company: int = 2,
) -> list[ValidationResult]:
    """
    Aplica los 5 niveles de validación a los emails de una empresa.

    Args:
        emails_raw: Lista de emails de Anymail Finder (con email_status)
        anymail_api_key: Clave de Anymail para catch-all check
        existing_emails: Set de emails ya en campañas activas
        max_per_company: Máximo de emails a aprobar por empresa

    Returns:
        Lista de ValidationResult (todos los niveles, aprobados y rechazados)
    """
    results: list[ValidationResult] = []

    # --- NIVEL 1: Filtro por status estricto ---
    validos_nivel1 = [e for e in emails_raw if e.get("email_status") == "valid"]
    rechazados_n1 = [e for e in emails_raw if e.get("email_status") != "valid"]

    for e in rechazados_n1:
        results.append(ValidationResult(
            email=e.get("email", ""),
            status=ValidationStatus.RECHAZADO_STATUS,
            score=0,
            motivo=f"email_status={e.get('email_status')} — solo se aceptan 'valid'",
            datos_originales=e,
        ))

    if not validos_nivel1:
        return results

    # --- NIVEL 2: Filtro de jerarquía (top 2) ---
    top_emails: list[EmailScore] = filter_top_emails(
        validos_nivel1,
        max_count=max_per_company,
        only_valid=True,
    )

    if not top_emails:
        return results

    # --- NIVELES 3, 4 y 5: Por cada email seleccionado ---
    for email_score in top_emails:
        email_str = email_score.email
        dominio = email_str.split("@")[-1].lower() if "@" in email_str else ""

        # --- NIVEL 2.5: Email personal (Gmail/Hotmail/etc) → track Brevo ---
        if dominio in DOMINIOS_PERSONALES:
            results.append(ValidationResult(
                email=email_str,
                status=ValidationStatus.APROBADO_PERSONAL,
                score=email_score.score,
                motivo=f"Email personal ({dominio}) — enviar por Brevo, no Instantly",
                tiene_mx=True,
                datos_originales=email_score.raw_data,
            ))
            continue

        # --- NIVEL 3: MX Record ---
        tiene_mx = await check_mx_record(dominio)
        if not tiene_mx:
            results.append(ValidationResult(
                email=email_str,
                status=ValidationStatus.RECHAZADO_SIN_MX,
                score=email_score.score,
                motivo=f"El dominio '{dominio}' no tiene registro MX",
                tiene_mx=False,
                datos_originales=email_score.raw_data,
            ))
            continue

        # --- NIVEL 4: Catch-all ---
        es_catch_all = await check_catch_all(dominio, anymail_api_key)
        if es_catch_all:
            # No rechazamos automáticamente — enviamos a revisión manual
            results.append(ValidationResult(
                email=email_str,
                status=ValidationStatus.CATCH_ALL,
                score=email_score.score,
                motivo=f"El dominio '{dominio}' es catch-all — verificar manualmente",
                es_catch_all=True,
                datos_originales=email_score.raw_data,
            ))
            continue

        # --- NIVEL 5: Deduplicación global ---
        if email_str.lower() in {e.lower() for e in existing_emails}:
            results.append(ValidationResult(
                email=email_str,
                status=ValidationStatus.DUPLICADO,
                score=email_score.score,
                motivo="Email ya existe en una campaña activa",
                es_duplicado=True,
                datos_originales=email_score.raw_data,
            ))
            continue

        # ✅ APROBADO: Pasó todos los niveles
        results.append(ValidationResult(
            email=email_str,
            status=ValidationStatus.APROBADO,
            score=email_score.score,
            motivo=f"Válido — jerarquía: {email_score.reason}",
            tiene_mx=True,
            es_catch_all=False,
            datos_originales=email_score.raw_data,
        ))

    return results


def summarize_validation(results: list[ValidationResult]) -> dict:
    """Resumen estadístico de la validación de una empresa."""
    aprobados = [r for r in results if r.es_apto_para_campana]
    manuales = [r for r in results if r.requiere_revision_manual]
    rechazados = [r for r in results if r.status not in (
        ValidationStatus.APROBADO, ValidationStatus.CATCH_ALL
    )]
    return {
        "total": len(results),
        "aprobados": len(aprobados),
        "revision_manual": len(manuales),
        "rechazados": len(rechazados),
        "emails_aprobados": [r.email for r in aprobados],
        "emails_revision": [r.email for r in manuales],
    }
