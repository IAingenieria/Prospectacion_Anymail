"""
LeadForge — Apify MCP HTTP Client
===================================
Llama a compass/crawler-google-places a través del servidor MCP oficial
de Apify (Streamable HTTP) en lugar de la REST API directa.

Ventajas sobre la API directa:
  ✅ Un solo endpoint — sin polling manual de status
  ✅ Protocolo estándar MCP (Model Context Protocol)
  ✅ Resultados sincrónicos para runs cortos
  ✅ Compatible con Claude Desktop MCP config
  ✅ Infraestructura gestionada por Apify

Protocolo:
  POST https://mcp.apify.com/?tools=actors,compass/crawler-google-places
  Content-Type: application/json
  Authorization: Bearer {APIFY_TOKEN}
  Body: JSON-RPC 2.0

Referencia: https://docs.apify.com/platform/integrations/mcp
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Optional

import httpx

from .config import cfg

logger = logging.getLogger(__name__)

# ── Constantes del protocolo ─────────────────────────────────────────────────
MCP_BASE_URL = "https://mcp.apify.com/"
ACTOR_ID = "compass/crawler-google-places"
MCP_URL = f"{MCP_BASE_URL}?tools=actors,docs,{ACTOR_ID}"
MCP_PROTOCOL_VERSION = "2024-11-05"

# Timeout generoso: los actors de Google Maps pueden tomar varios minutos
MCP_TIMEOUT_SECONDS = 600   # 10 minutos
POLL_INTERVAL = 8           # segundos entre polls al estado del run


# ============================================================
# CLIENTE MCP HTTP (Streamable HTTP / JSON-RPC 2.0)
# ============================================================

class ApifyMCPClient:
    """
    Cliente Python para el servidor MCP de Apify.
    Usa el transporte Streamable HTTP (POST con JSON-RPC 2.0).

    Cada instancia representa una sesión MCP con su propio session_id.
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token or cfg.apify_token
        self._session_id: Optional[str] = None
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    # ──────────────────────────────────────────────────────────
    # PROTOCOLO MCP: Handshake e Inicialización
    # ──────────────────────────────────────────────────────────

    async def _jsonrpc(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict,
        req_id: Optional[str] = None,
    ) -> dict:
        """Envía una petición JSON-RPC 2.0 al servidor MCP."""
        payload = {
            "jsonrpc": "2.0",
            "id": req_id or str(uuid.uuid4()),
            "method": method,
            "params": params,
        }

        # Si ya tenemos session_id, incluirlo en el header (MCP Streamable HTTP)
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = await client.post(MCP_URL, json=payload, headers=headers)

        # MCP puede responder con SSE o JSON plano
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 202:
            # 202 Accepted = petición encolada, no hay body
            return {"accepted": True}

        # Capturar session-id si el servidor lo devuelve
        new_session = resp.headers.get("Mcp-Session-Id")
        if new_session:
            self._session_id = new_session

        if "text/event-stream" in content_type:
            return self._parse_sse(resp.text)
        else:
            data = resp.json()
            if "error" in data:
                raise RuntimeError(
                    f"MCP error {data['error'].get('code')}: "
                    f"{data['error'].get('message')}"
                )
            return data.get("result", data)

    def _parse_sse(self, sse_text: str) -> dict:
        """Extrae el último resultado JSON de una respuesta SSE."""
        result = {}
        for line in sse_text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        data = json.loads(payload)
                        if "result" in data:
                            result = data["result"]
                        elif "error" in data:
                            raise RuntimeError(
                                f"MCP SSE error: {data['error'].get('message')}"
                            )
                    except json.JSONDecodeError:
                        pass
        return result

    async def initialize(self, client: httpx.AsyncClient) -> dict:
        """Handshake inicial MCP (obligatorio antes de cualquier tool call)."""
        result = await self._jsonrpc(
            client,
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "LeadForge", "version": "1.0.0"},
            },
        )
        logger.debug(f"MCP handshake OK — server: {result.get('serverInfo', {})}")

        # Notificar al servidor que estamos listos
        try:
            await self._jsonrpc(
                client,
                "notifications/initialized",
                {},
                req_id=None,
            )
        except Exception:
            pass  # Notificación es fire-and-forget

        return result

    # ──────────────────────────────────────────────────────────
    # TOOLS: call-actor / get-actor-run / get-dataset-items
    # ──────────────────────────────────────────────────────────

    async def call_actor(
        self, client: httpx.AsyncClient, actor_input: dict
    ) -> dict:
        """
        Llama a compass/crawler-google-places vía MCP tool 'call-actor'.
        Devuelve el resultado del tool (puede incluir runId y datasetId).
        """
        result = await self._jsonrpc(
            client,
            "tools/call",
            {
                "name": "call-actor",
                "arguments": {
                    "actorId": ACTOR_ID,
                    "runInput": actor_input,
                },
            },
        )
        return result

    async def get_actor_run(
        self, client: httpx.AsyncClient, run_id: str
    ) -> dict:
        """Obtiene el estado actual de un actor run."""
        result = await self._jsonrpc(
            client,
            "tools/call",
            {
                "name": "get-actor-run",
                "arguments": {"runId": run_id},
            },
        )
        return result

    async def get_dataset_items(
        self,
        client: httpx.AsyncClient,
        dataset_id: str,
        limit: int = 1000,
    ) -> list[dict]:
        """Obtiene los items del dataset del actor run."""
        result = await self._jsonrpc(
            client,
            "tools/call",
            {
                "name": "get-dataset-items",
                "arguments": {
                    "datasetId": dataset_id,
                    "limit": limit,
                    "format": "json",
                },
            },
        )

        # El resultado del tool MCP viene en content[0].text como JSON string
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "[]")
            try:
                items = json.loads(text)
                if isinstance(items, list):
                    return items
                elif isinstance(items, dict) and "items" in items:
                    return items["items"]
            except json.JSONDecodeError:
                logger.error(f"No se pudo parsear dataset items: {text[:200]}")

        return []

    # ──────────────────────────────────────────────────────────
    # FLUJO COMPLETO: run + poll + dataset
    # ──────────────────────────────────────────────────────────

    def _extract_run_info(self, call_result: dict) -> tuple[Optional[str], Optional[str]]:
        """
        Extrae runId y datasetId del resultado de call-actor.
        El server MCP los puede devolver de varias formas:
          - content[0].text con JSON embebido
          - Campos directos en el resultado
        """
        run_id = call_result.get("runId") or call_result.get("id")
        dataset_id = call_result.get("datasetId") or call_result.get("defaultDatasetId")

        # Intentar extraer del campo content (respuesta de tool MCP)
        content = call_result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "") if content else ""
            if text:
                # Buscar JSON embebido en el texto
                try:
                    import re
                    json_match = re.search(r'\{.*\}', text, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group())
                        run_id = run_id or parsed.get("id") or parsed.get("runId")
                        dataset_id = (
                            dataset_id
                            or parsed.get("defaultDatasetId")
                            or parsed.get("datasetId")
                        )
                except Exception:
                    pass

                # Buscar IDs en el texto plano (formato: "Run ID: abc123")
                if not run_id:
                    import re
                    m = re.search(r'[Rr]un.{0,5}[Ii][Dd][:\s]+([a-zA-Z0-9]+)', text)
                    if m:
                        run_id = m.group(1)
                if not dataset_id:
                    import re
                    m = re.search(r'[Dd]ataset.{0,5}[Ii][Dd][:\s]+([a-zA-Z0-9]+)', text)
                    if m:
                        dataset_id = m.group(1)

        return run_id, dataset_id

    async def _poll_until_done(
        self, client: httpx.AsyncClient, run_id: str
    ) -> bool:
        """Espera hasta que el run termine (máx TIMEOUT segundos)."""
        deadline = asyncio.get_event_loop().time() + MCP_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            run_result = await self.get_actor_run(client, run_id)
            content = run_result.get("content", [])
            text = content[0].get("text", "") if content else ""

            # Detectar status en el texto
            if "SUCCEEDED" in text or '"status":"SUCCEEDED"' in text:
                logger.debug(f"Run {run_id[:8]}... completado con SUCCEEDED")
                return True
            elif any(s in text for s in ("FAILED", "ABORTED", "TIMED-OUT")):
                logger.error(f"Run {run_id[:8]}... terminó con error: {text[:100]}")
                return False

            logger.debug(f"Run {run_id[:8]}... en progreso, esperando {POLL_INTERVAL}s")
            await asyncio.sleep(POLL_INTERVAL)

        logger.error(f"Run {run_id[:8]}... timeout después de {MCP_TIMEOUT_SECONDS}s")
        return False

    async def scrape(self, actor_input: dict) -> tuple[list[dict], str]:
        """
        Flujo completo de scraping via MCP:
          1. Handshake (initialize)
          2. call-actor → obtener runId + datasetId
          3. Si el run es async → poll con get-actor-run hasta SUCCEEDED
          4. get-dataset-items → items completos

        Returns:
          (items: list[dict], run_id: str)
        """
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=120, write=30, pool=10)
        ) as client:
            # 1. Handshake MCP
            await self.initialize(client)
            logger.info(f"MCP session iniciada: {self._session_id or 'sin session-id'}")

            # 2. Llamar al actor
            logger.info(f"MCP call-actor: {ACTOR_ID}")
            call_result = await self.call_actor(client, actor_input)

            run_id, dataset_id = self._extract_run_info(call_result)
            logger.info(
                f"MCP actor iniciado | runId={run_id or '?'} | "
                f"datasetId={dataset_id or '?'}"
            )

            # 3. Si el run es asíncrono (tenemos runId), esperar
            if run_id and not dataset_id:
                logger.info("Run asíncrono — esperando completación...")
                success = await self._poll_until_done(client, run_id)
                if not success:
                    return [], run_id or ""

                # Después de completar, el run_result debería tener el datasetId
                run_data = await self.get_actor_run(client, run_id)
                _, dataset_id = self._extract_run_info(run_data)

            # 4. Obtener items del dataset
            if not dataset_id:
                logger.error("No se pudo obtener datasetId del run. Sin resultados.")
                return [], run_id or ""

            logger.info(f"Descargando items del dataset {dataset_id[:8]}...")
            items = await self.get_dataset_items(client, dataset_id)
            logger.info(f"MCP devolvió {len(items)} items")
            return items, run_id or dataset_id


# ============================================================
# INSTANCIA GLOBAL
# ============================================================
apify_mcp = ApifyMCPClient()
