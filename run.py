"""
LeadForge — Punto de entrada principal
Ejecutar: python run.py

Modos de uso:
  python run.py                           → Menú interactivo
  python run.py --check                   → Verificar configuración
  python run.py --categoria "taller mecánico" --ciudad "Monterrey" --perfil media_densidad
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Forzar UTF-8 en Windows para que los emojis y símbolos funcionen
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent / "logs" / "leadforge.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("leadforge.main")

# Crear carpeta de logs si no existe
(Path(__file__).parent / "logs").mkdir(exist_ok=True)


def check_setup() -> bool:
    """Verifica que todas las credenciales estén configuradas."""
    print("\n" + "=" * 50)
    print("LEADFORGE — Verificación de Configuración")
    print("=" * 50)

    try:
        from leadforge.config import cfg
        ok = cfg.validate_phase1()
        if ok:
            print("\n✅ Todas las credenciales de Fase 1 están configuradas.")
            print(f"   Cliente ID: {cfg.cliente_id[:8]}...")
            print(f"   Supabase: {cfg.supabase_url}")
        else:
            print("\n❌ Configuración incompleta. Revisa tu archivo .env")
        return ok
    except SystemExit:
        return False


def interactive_menu() -> dict:
    """Menú interactivo para configurar una búsqueda."""
    print("\n" + "=" * 50)
    print("🚀 LEADFORGE — Generador de Leads")
    print("=" * 50)

    print("\n📌 CATEGORÍA DE BÚSQUEDA")
    categoria = input("  ¿Qué tipo de negocio buscas en Google Maps?\n  > ").strip()

    print("\n📍 SINÓNIMOS (separados por coma, o Enter para continuar)")
    print("  Ejemplo: taller automotriz, servicio mecánico, reparación de autos")
    sinonimos_raw = input("  > ").strip()
    terminos = [categoria]
    if sinonimos_raw:
        terminos += [s.strip() for s in sinonimos_raw.split(",") if s.strip()]

    print("\n🌍 UBICACIÓN")
    ciudad = input("  Ciudad: ").strip() or "Monterrey"
    estado = input("  Estado (Enter para omitir): ").strip()
    pais = input("  País [Mexico]: ").strip() or "Mexico"

    location = ciudad
    if estado:
        location += f", {estado}"
    location += f", {pais}"

    print("\n📊 PERFIL DE SCRAPING")
    print("  1. alta_densidad  — restaurantes, farmacias, salones (50 resultados)")
    print("  2. media_densidad — talleres, clínicas, despachos (30 resultados) [default]")
    print("  3. baja_densidad  — contratistas, industria, CNC (100 resultados)")
    perfil_raw = input("  Selecciona [1/2/3] o Enter para media: ").strip()
    perfiles = {"1": "alta_densidad", "2": "media_densidad", "3": "baja_densidad"}
    perfil = perfiles.get(perfil_raw, "media_densidad")

    print(f"\n{'='*50}")
    print(f"Configuración:")
    print(f"  Términos:  {terminos}")
    print(f"  Ubicación: {location}")
    print(f"  Perfil:    {perfil}")
    confirmar = input("\n¿Iniciar? [s/N]: ").strip().lower()

    if confirmar != "s":
        print("Cancelado.")
        sys.exit(0)

    return {"terminos": terminos, "location": location, "perfil": perfil}


async def main():
    parser = argparse.ArgumentParser(description="LeadForge — Generador de Leads")
    parser.add_argument("--check", action="store_true", help="Verificar configuración")
    parser.add_argument("--categoria", type=str, help="Categoría de búsqueda")
    parser.add_argument("--ciudad", type=str, help="Ciudad de búsqueda")
    parser.add_argument("--estado", type=str, default="", help="Estado (opcional)")
    parser.add_argument("--pais", type=str, default="Mexico", help="País")
    parser.add_argument(
        "--perfil",
        choices=["alta_densidad", "media_densidad", "baja_densidad"],
        default="media_densidad",
    )
    parser.add_argument(
        "--sinonimos", type=str, default="",
        help="Términos sinónimos separados por coma"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Ignorar caché y hacer scraping siempre"
    )
    args = parser.parse_args()

    # --- Modo verificación ---
    if args.check:
        ok = check_setup()
        sys.exit(0 if ok else 1)

    # --- Verificar configuración antes de cualquier cosa ---
    if not check_setup():
        sys.exit(1)

    from leadforge.config import cfg
    from leadforge.pipeline import run_pipeline

    # --- Modo CLI directo ---
    if args.categoria:
        terminos = [args.categoria]
        if args.sinonimos:
            terminos += [s.strip() for s in args.sinonimos.split(",") if s.strip()]

        location = args.ciudad or "Mexico"
        if args.estado:
            location += f", {args.estado}"
        location += f", {args.pais}"

        config = {"terminos": terminos, "location": location, "perfil": args.perfil}
    else:
        # --- Modo interactivo ---
        config = interactive_menu()

    # --- Ejecutar pipeline ---
    print(f"\n🔄 Iniciando pipeline...")
    stats = await run_pipeline(
        terminos=config["terminos"],
        location=config["location"],
        cliente_id=cfg.cliente_id,
        perfil_apify=config["perfil"],
        force_scrape=args.force,
    )

    print(stats.resumen())
    print("\n✅ Pipeline completado. Revisa tus leads en Supabase.")


if __name__ == "__main__":
    asyncio.run(main())
