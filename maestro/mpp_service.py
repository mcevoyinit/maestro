"""A minimal paid MPP service running on Tempo testnet.

Demonstrates the server side: an API endpoint that requires payment
via the Machine Payments Protocol. Agents pay $0.01 per request.
"""

from __future__ import annotations

import json
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mpp.server import Mpp
from mpp import Challenge
from mpp.methods.tempo import tempo, TempoAccount, ChargeIntent
from pytempo.contracts.addresses import PATH_USD


def create_mpp_service(
    recipient_key: str,
    chain_id: int = 4217,
    rpc_url: str = "https://rpc.moderato.tempo.xyz",
    secret_key: str = "maestro-demo-secret",
    price: str = "10000",  # $0.01 pathUSD in base units (6 decimals)
) -> Starlette:
    """Create a Starlette app with MPP-gated endpoints."""
    if secret_key == "maestro-demo-secret":
        import logging
        logging.getLogger("maestro").warning(
            "Using demo secret_key 'maestro-demo-secret' — do NOT use in production"
        )

    recipient = TempoAccount.from_key(recipient_key)

    mpp = Mpp.create(
        secret_key=secret_key,
        method=tempo(
            intents={"charge": ChargeIntent(
                chain_id=chain_id,
                rpc_url=rpc_url,
            )},
            recipient=recipient.address,
            currency=PATH_USD,
            chain_id=chain_id,
            rpc_url=rpc_url,
        ),
    )

    async def search(request: Request) -> JSONResponse:
        """Paid search endpoint — $0.01 per query."""
        auth = request.headers.get("authorization")

        result = await mpp.charge(
            authorization=auth,
            amount=price,
            description="Maestro demo search - $0.01",
        )

        if isinstance(result, Challenge):
            # Return 402 with payment challenge
            from mpp import format_www_authenticate
            www_auth = format_www_authenticate(result, realm="maestro-demo")
            return JSONResponse(
                {"error": "Payment Required", "detail": "Pay $0.01 pathUSD to search"},
                status_code=402,
                headers={"WWW-Authenticate": www_auth},
            )

        # Payment verified — serve the result
        credential, receipt = result
        body = await request.json()
        query = body.get("query", "")

        return JSONResponse({
            "query": query,
            "results": [
                {"title": f"Result 1 for: {query}", "score": 0.95},
                {"title": f"Result 2 for: {query}", "score": 0.87},
                {"title": f"Result 3 for: {query}", "score": 0.72},
            ],
            "paid": True,
            "price": "$0.01",
            "receipt_ref": receipt.reference,
            "timestamp": int(time.time()),
        })

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "maestro-demo-search",
            "price_per_query": "$0.01",
            "recipient": recipient.address,
            "chain_id": chain_id,
        })

    return Starlette(routes=[
        Route("/search", search, methods=["POST"]),
        Route("/health", health),
    ])
