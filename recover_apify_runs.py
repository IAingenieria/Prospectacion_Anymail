"""
recover_apify_runs.py — Recupera runs de Apify ya pagados y los inserta en Supabase.

Uso:
    python -X utf8 recover_apify_runs.py              # muestra los últimos 10 runs
    python -X utf8 recover_apify_runs.py --all        # recupera todos los runs exitosos sin procesar
    python -X utf8 recover_apify_runs.py --run RUN_ID # recupera un run específico
"""
import asyncio
import argparse
import logging
import sys
from datetime import datetime

import httpx

# Configurar logging básico
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def listar_runs(token: str, actor_id: str, limit: int = 20) -> list[dict]:
    """Lista los runs recientes del actor."""
    url = f"https://api.apify.com/v2/acts/{actor_id}/runs"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params={"limit": limit, "desc": "1"})
        resp.raise_for_status()
        return resp.json()["data"]["items"]


async def get_dataset_items(token: str, run_id: str) -> list[dict]:
    """Descarga todos los items del dataset de un run."""
    url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(
            url, headers=headers,
            params={"format": "json", "clean": "true"}
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items") or []
        return []


async def procesar_run(run_id: str, items: list[dict], cliente_id: str) -> dict:
    """Procesa los items de un run a través del pipeline y los inserta en Supabase."""
    from leadforge.apify_scraper import ApifyScraper
    from leadforge.pipeline import process_negocio, PipelineStats
    from leadforge.anymail_enricher import AnymailEnricher
    from leadforge.supabase_client import get_existing_emails
    from leadforge.config import cfg

    scraper = ApifyScraper()
    stats = PipelineStats(
        terminos=["recovery"],
        location="Nuevo León, Mexico",
        perfil_apify="recovery"
    )

    # Parsear items a NegocioRaw
    negocios = [
        n for item in items
        if (n := scraper._parse_item(item, item.get("searchString", "recovery"), run_id))
    ]
    logger.info(f"  {len(negocios)} negocios parseados de {len(items)} items raw")

    if not negocios:
        return {"procesados": 0, "email": 0, "social": 0}

    # Verificar Anymail
    anymail = AnymailEnricher()
    account_status = await anymail.check_account_status()
    anymail_disponible = account_status["ok"]
    if not anymail_disponible:
        logger.warning("  Anymail no disponible — leads irán como social leads")

    existing_emails = get_existing_emails(cliente_id)
    semaphore = asyncio.Semaphore(cfg.anymail_concurrent_calls)

    async def process_one(negocio):
        async with semaphore:
            await process_negocio(
                negocio=negocio,
                cliente_id=cliente_id,
                existing_emails=existing_emails,
                anymail=anymail if anymail_disponible else None,
                stats=stats,
            )

    await asyncio.gather(*[process_one(n) for n in negocios])

    return {
        "procesados": len(negocios),
        "email": stats.email_leads_insertados,
        "social": stats.social_leads_insertados,
        "duplicados": stats.duplicados,
    }


def formatear_run(run: dict) -> str:
    """Muestra info de un run en una línea."""
    run_id = run.get("id", "?")
    status = run.get("status", "?")
    # itemCount puede estar en stats.itemCount o en usage.DATASET_WRITES
    stats = run.get("stats") or {}
    items = stats.get("itemCount") or stats.get("outputItemCount") or "?"
    costo = run.get("usageTotalUsd", 0)
    started = run.get("startedAt", "")[:19].replace("T", " ")
    return f"  {run_id}  |  {status:<12}  |  {str(items):>5} items  |  ${costo:.4f}  |  {started}"


async def main():
    parser = argparse.ArgumentParser(description="Recupera runs de Apify a Supabase")
    parser.add_argument("--all", action="store_true", help="Recuperar todos los runs SUCCEEDED")
    parser.add_argument("--run", type=str, help="Recuperar un run_id específico")
    parser.add_argument("--limit", type=int, default=15, help="Cuántos runs listar (default: 15)")
    args = parser.parse_args()

    # Importar config después de parsear args
    from leadforge.config import cfg

    token = cfg.apify_token
    actor_id = cfg.apify_actor_id
    cliente_id = cfg.cliente_id

    logger.info(f"Actor: {actor_id}")
    logger.info(f"Cliente ID: {cliente_id}")

    # ── Modo: run específico ──────────────────────────────────────────────────
    if args.run:
        run_id = args.run
        logger.info(f"\nDescargando run {run_id}...")
        items = await get_dataset_items(token, run_id)
        logger.info(f"  {len(items)} items encontrados")
        if not items:
            logger.error("  El run no tiene items. Verifica el run_id.")
            return
        logger.info(f"  Procesando e insertando en Supabase...")
        resultado = await procesar_run(run_id, items, cliente_id)
        logger.info(
            f"\n  RESULTADO:"
            f"\n    Negocios parseados : {resultado['procesados']}"
            f"\n    Email leads nuevos : {resultado['email']}"
            f"\n    Social leads nuevos: {resultado['social']}"
            f"\n    Duplicados saltados: {resultado['duplicados']}"
        )
        return

    # ── Listar runs ───────────────────────────────────────────────────────────
    logger.info(f"\nObteniendo últimos {args.limit} runs...")
    runs = await listar_runs(token, actor_id, args.limit)

    if not runs:
        logger.info("No se encontraron runs.")
        return

    print(f"\n{'─'*80}")
    print(f"  {'RUN ID':<25}  {'STATUS':<12}  {'ITEMS':>5}  {'COSTO':>8}  FECHA")
    print(f"{'─'*80}")
    for run in runs:
        print(formatear_run(run))
    print(f"{'─'*80}")

    # Runs exitosos con costo real > $0.01 (excluye health-checks de $0.0002)
    runs_exitosos = [
        r for r in runs
        if r.get("status") == "SUCCEEDED" and r.get("usageTotalUsd", 0) > 0.01
    ]
    print(f"\n{len(runs_exitosos)} run(s) exitosos con datos encontrados.")

    # ── Modo: recuperar todos ─────────────────────────────────────────────────
    if args.all:
        if not runs_exitosos:
            logger.info("No hay runs exitosos para recuperar.")
            return

        total_email = 0
        total_social = 0

        for run in runs_exitosos:
            run_id = run["id"]
            items_count = run.get("stats", {}).get("itemCount", 0)
            logger.info(f"\nProcesando run {run_id} ({items_count} items)...")
            items = await get_dataset_items(token, run_id)
            if not items:
                logger.warning(f"  Sin items — saltando")
                continue
            resultado = await procesar_run(run_id, items, cliente_id)
            total_email += resultado["email"]
            total_social += resultado["social"]
            logger.info(
                f"  Email: {resultado['email']} | Social: {resultado['social']} | Duplicados: {resultado['duplicados']}"
            )

        print(f"\n{'='*50}")
        print(f"TOTAL RECUPERADO:")
        print(f"  Email leads  : {total_email}")
        print(f"  Social leads : {total_social}")
        print(f"{'='*50}")

    else:
        print(f"\nUso:")
        print(f"  Recuperar un run:      python -X utf8 recover_apify_runs.py --run RUN_ID")
        print(f"  Recuperar todos:       python -X utf8 recover_apify_runs.py --all")


if __name__ == "__main__":
    asyncio.run(main())
