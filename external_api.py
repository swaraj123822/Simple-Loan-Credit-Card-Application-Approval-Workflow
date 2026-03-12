"""
external_api.py — Mock external credit data service.

Simulates a real-world dependency that is slow and unreliable.
"""

import asyncio
import random


class ExternalAPIError(Exception):
    """Raised when the external credit service fails."""
    pass


async def fetch_credit_data(application_id: str) -> dict:
    """
    Simulate fetching enriched credit data from an external provider.

    - Takes ~1 second to respond (network latency simulation).
    - Fails randomly 30 % of the time.
    """
    # Simulate network latency
    await asyncio.sleep(1)

    # 30 % failure rate
    if random.random() < 0.30:
        raise ExternalAPIError(
            f"External credit service unavailable for application {application_id}"
        )

    # Return mock enriched data on success
    return {
        "application_id": application_id,
        "credit_bureau": "MockBureau",
        "debt_to_income_ratio": round(random.uniform(0.1, 0.6), 2),
        "open_accounts": random.randint(1, 12),
        "delinquencies": random.randint(0, 3),
    }
