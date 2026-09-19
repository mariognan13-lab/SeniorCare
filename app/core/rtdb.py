"""
Firebase Realtime Database (RTDB) sync helper.
Used for real-time coordination of emergency alerts and care state across the care network.
"""

import logging
from typing import Any, Dict
from firebase_admin import db
from app.core.firebase import get_firebase_app

logger = logging.getLogger(__name__)


def sync_emergency_to_rtdb(senior_id: str, payload: Dict[str, Any]) -> None:
    """
    Sync emergency status to Firebase Realtime Database node: /emergencies/{senior_id}
    This enables instant state synchronization across all connected Android devices in the care network.
    """
    app = get_firebase_app()
    if not app:
        logger.warning("Firebase Admin SDK not initialized — skipping RTDB sync.")
        return

    try:
        ref = db.reference(f"emergencies/{senior_id}")
        ref.set(payload)
        logger.info(f"Synced emergency for senior {senior_id} to RTDB: status={payload.get('status')}")
    except Exception as e:
        logger.warning(f"Failed to sync emergency to RTDB for senior {senior_id}: {e}")
