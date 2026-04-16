"""Check Regio Cribas campaign stats from Instantly API."""
import asyncio
import httpx
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
API_KEY = os.getenv("INSTANTLY_API_KEY")
CAMPAIGN_ID = "ed81e355-716e-4a12-9175-9ae241e2ec05"
BASE = "https://api.instantly.ai/api/v1"

async def main():
    async with httpx.AsyncClient(timeout=15) as c:
        # Analytics summary
        r = await c.get(f"{BASE}/analytics/campaign/summary",
            params={"api_key": API_KEY, "campaign_id": CAMPAIGN_ID})
        print("=== ANALYTICS SUMMARY ===")
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"  Emails enviados:    {d.get('emails_sent_count', 0)}")
            print(f"  Emails abiertos:    {d.get('open_count', 0)}")
            print(f"  Clicks:             {d.get('link_click_count', 0)}")
            print(f"  Respuestas:         {d.get('reply_count', 0)}")
            print(f"  Bounces:            {d.get('bounced_count', 0)}")
            print(f"  Unsubscribes:       {d.get('unsubscribed_count', 0)}")
            print(f"  Open rate:          {d.get('open_rate', 0):.1%}")
            print(f"  Reply rate:         {d.get('reply_rate', 0):.1%}")
        else:
            print(r.text[:500])

        # Leads count
        r2 = await c.get(f"{BASE}/campaign/get/leads/count",
            params={"api_key": API_KEY, "campaign_id": CAMPAIGN_ID})
        print("\n=== LEADS EN CAMPAÑA ===")
        print(f"Status: {r2.status_code}")
        if r2.status_code == 200:
            d2 = r2.json()
            print(f"  Total leads: {d2.get('total', '?')}")
        else:
            print(r2.text[:300])

asyncio.run(main())
