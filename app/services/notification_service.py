"""
Push notification delivery.

Every notification in the application goes through :func:`send_push`, so the
failure policy lives in exactly one place: **a push that cannot be delivered must
never take down the action that triggered it.**

That is not defensive habit, it is the requirement. When an SOS fires, the
emergency row and its assignments are already committed by the time a
notification is attempted. If FCM is unreachable, or the credentials are absent,
or one device token is stale, the alert must still stand — it is the thing that
summons help. So this module counts what it delivered and swallows the rest.
"""

import asyncio
import logging
from typing import Iterable
from uuid import UUID

from firebase_admin import messaging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firebase import get_firebase_app
from app.db.models import UserDevice

logger = logging.getLogger(__name__)

# FCM's ceiling on tokens per multicast send.
_MAX_BATCH = 500


async def send_push(
    db: AsyncSession,
    user_ids: Iterable[UUID],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> int:
    """
    Push to every device belonging to each of ``user_ids``.

    Returns how many devices the send was accepted for. Never raises.
    """
    if get_firebase_app() is None:
        return 0

    recipients = list(user_ids)
    if not recipients:
        return 0

    try:
        tokens = await _tokens_for(db, recipients)
    except Exception:
        logger.exception("Could not load device tokens — no push sent.")
        return 0

    if not tokens:
        return 0

    payload = {key: str(value) for key, value in (data or {}).items()}
    sent = 0
    stale: list[str] = []

    for start in range(0, len(tokens), _MAX_BATCH):
        batch = tokens[start : start + _MAX_BATCH]
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=payload,
            tokens=batch,
        )

        try:
            # Off the event loop: this is a blocking HTTP call to FCM, and awaiting
            # it inline would stall every other in-flight request in the process —
            # including another user's SOS, on the one path that must never be
            # slow. The thread hop costs nothing next to the round trip.
            response = await asyncio.to_thread(messaging.send_each_for_multicast, message)
        except Exception:
            # A transport-level failure for this batch. The remaining batches are
            # still attempted, and the caller is unaffected either way.
            logger.exception("FCM send failed for a batch of %d device(s).", len(batch))
            continue

        sent += response.success_count

        for token, result in zip(batch, response.responses):
            if result.exception is None:
                continue
            # A token FCM no longer recognises will never work again, so drop it
            # rather than retrying it on every future alert. Anything else —
            # quota, transient network — is kept and simply logged.
            if isinstance(result.exception, messaging.UnregisteredError):
                stale.append(token)
            else:
                logger.warning("Push to %s… rejected: %s", token[:12], result.exception)

    if stale:
        await _forget_tokens(db, stale)

    return sent


async def _tokens_for(db: AsyncSession, user_ids: list[UUID]) -> list[str]:
    """
    Every registered device token for these users.

    Reads ``user_devices`` rather than ``users.fcm_token``. The column on
    ``users`` only ever holds the most recent device, so relying on it would
    silently stop notifying someone on whichever device they registered first —
    the wrong failure mode for an alert that needs to reach a person.
    """
    res = await db.execute(
        select(UserDevice.fcm_token).where(UserDevice.user_id.in_(user_ids))
    )
    return [token for token in res.scalars().all() if token]


async def _forget_tokens(db: AsyncSession, tokens: list[str]) -> None:
    """Prune tokens FCM has reported as unregistered."""
    try:
        res = await db.execute(select(UserDevice).where(UserDevice.fcm_token.in_(tokens)))
        for device in res.scalars().all():
            await db.delete(device)
        await db.flush()
    except Exception:
        # Housekeeping only — never worth surfacing to whoever triggered the alert.
        logger.exception("Could not prune %d unregistered device token(s).", len(tokens))
