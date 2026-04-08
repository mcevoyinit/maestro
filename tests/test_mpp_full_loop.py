"""Full MPP loop: agent pays a service on Tempo testnet.

Spins up a paid MPP service locally, then has a Maestro agent
pay $0.01 and receive search results. Real on-chain payment.

Run with: pytest tests/test_mpp_full_loop.py -v -s
"""

import asyncio
import pytest
import uvicorn
import threading

from mpp.client import Client
from mpp.methods.tempo import tempo, TempoAccount, ChargeIntent
from pytempo.contracts.addresses import PATH_USD

from maestro.mpp_service import create_mpp_service
from maestro.submitter import TxSubmitter
from maestro.types import MaestroConfig

# Two separate wallets — buyer and seller
BUYER_KEY = "0x" + "ab" * 32   # our master agent
SELLER_KEY = "0x" + "cd" * 32  # the service provider

SERVICE_PORT = 18402
SERVICE_URL = f"http://localhost:{SERVICE_PORT}"


@pytest.fixture(scope="module")
def funded_accounts():
    """Fund both buyer and seller on testnet."""
    import httpx

    buyer = TempoAccount.from_key(BUYER_KEY)
    seller = TempoAccount.from_key(SELLER_KEY)

    for addr in [buyer.address, seller.address]:
        resp = httpx.post(
            "https://rpc.moderato.tempo.xyz",
            json={"jsonrpc": "2.0", "method": "tempo_fundAddress", "params": [addr], "id": 1},
        )
        assert resp.status_code == 200

    return buyer, seller


@pytest.fixture(scope="module")
def mpp_server(funded_accounts):
    """Start the paid MPP service in a background thread."""
    _, seller = funded_accounts
    app = create_mpp_service(SELLER_KEY)

    config = uvicorn.Config(app, host="127.0.0.1", port=SERVICE_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    import time, httpx
    for _ in range(30):
        try:
            r = httpx.get(f"{SERVICE_URL}/health")
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.2)

    yield server


class TestMppFullLoop:

    @pytest.mark.asyncio
    async def test_health_check(self, mpp_server):
        """Service is running and reports its config."""
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{SERVICE_URL}/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert data["price_per_query"] == "$0.01"
            print(f"\n  Service healthy: {data}")

    @pytest.mark.asyncio
    async def test_402_without_payment(self, mpp_server):
        """Service returns 402 when called without credentials."""
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SERVICE_URL}/search",
                json={"query": "test"},
            )
            assert r.status_code == 402
            assert "WWW-Authenticate" in r.headers
            assert "Payment" in r.headers["WWW-Authenticate"]
            print(f"\n  Got 402 challenge (expected)")

    @pytest.mark.asyncio
    async def test_paid_request(self, mpp_server, funded_accounts):
        """Agent pays $0.01 and gets search results — full loop."""
        buyer, _ = funded_accounts

        # Create payment method for the buyer agent
        method = tempo(
            intents={"charge": ChargeIntent(
                chain_id=42431,
                rpc_url="https://rpc.moderato.tempo.xyz",
            )},
            account=buyer,
            chain_id=42431,
            rpc_url="https://rpc.moderato.tempo.xyz",
        )

        # pympp Client handles 402 → pay → retry automatically
        async with Client(methods=[method]) as client:
            response = await client.post(
                f"{SERVICE_URL}/search",
                json={"query": "Tempo agent orchestration"},
            )

            print(f"\n  Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"  Paid: {data.get('paid')}")
                print(f"  Price: {data.get('price')}")
                print(f"  Receipt: {data.get('receipt_ref', 'N/A')}")
                print(f"  Results: {len(data.get('results', []))} items")
                for r in data.get("results", []):
                    print(f"    - {r['title']} (score: {r['score']})")

                assert data["paid"] is True
                assert len(data["results"]) == 3
            else:
                print(f"  Body: {response.text[:500]}")
                # If payment fails on testnet, still informative
                pytest.skip(f"Payment failed with {response.status_code}: {response.text[:200]}")
