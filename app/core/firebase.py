"""
Firebase Admin SDK initialisation, used for sending push notifications and Realtime Database sync.

The rest of the backend deliberately avoids the Admin SDK: ``firebase_auth.py``
verifies ID tokens against Google's rotating public certificates precisely so
that *no service-account key is required*. Sending a message is different — FCM
will not accept a send without a service account — so this module exists to hold
that one credential.

It is deliberately optional. With credentials unset or unavailable, the application
logs a warning once and runs with push disabled rather than refusing to boot. Every other
feature works without it; only notifications stop.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials

from app.core.config import settings

logger = logging.getLogger(__name__)

_app: Any = None
_init_attempted = False


def get_firebase_app() -> Any | None:
    """
    Return the initialised Firebase app, or None when credentials are missing.

    Initialisation is attempted at most once per process. Retrying on every send
    would add a filesystem stat and a log line to the emergency path for no gain,
    and the credentials cannot appear while the process is running.
    """
    global _app, _init_attempted

    if _app is not None:
        return _app
    if _init_attempted:
        return _app

    _init_attempted = True

    # 1. Try existing initialized app
    try:
        _app = firebase_admin.get_app()
        logger.info("Retrieved default Firebase Admin SDK app.")
        return _app
    except ValueError:
        pass  # No default app exists yet

    options = {"databaseURL": settings.FIREBASE_DATABASE_URL}

    # 2. Try JSON string from settings or env
    json_str = (settings.FIREBASE_CREDENTIALS_JSON or os.getenv("FIREBASE_CREDENTIALS_JSON", "")).strip()
    if json_str:
        try:
            cred_dict = json.loads(json_str)
            cred = credentials.Certificate(cred_dict)
            _app = firebase_admin.initialize_app(cred, options=options)
            logger.info("Firebase Admin SDK initialised via FIREBASE_CREDENTIALS_JSON — push notifications enabled.")
            return _app
        except Exception:
            logger.exception("Failed to parse or initialize Firebase Admin SDK from FIREBASE_CREDENTIALS_JSON.")

    # 3. Try service-account file path or fallback JSON
    path = (settings.FIREBASE_CREDENTIALS_PATH or os.getenv("FIREBASE_CREDENTIALS_PATH", "")).strip()
    if path:
        if path.startswith("{"):
            try:
                cred_dict = json.loads(path)
                cred = credentials.Certificate(cred_dict)
                _app = firebase_admin.initialize_app(cred, options=options)
                logger.info("Firebase Admin SDK initialised via inline JSON — push notifications enabled.")
                return _app
            except Exception:
                logger.exception("Failed to parse inline JSON credentials from FIREBASE_CREDENTIALS_PATH.")
        elif len(path) < 260:
            try:
                if Path(path).is_file():
                    cred = credentials.Certificate(path)
                    _app = firebase_admin.initialize_app(cred, options=options)
                    logger.info("Firebase Admin SDK initialised from %s — push notifications enabled.", path)
                    return _app
            except Exception:
                logger.exception("Failed to initialise Firebase Admin SDK from file %s.", path)

    # 4. Try Google Application Default Credentials if GOOGLE_APPLICATION_CREDENTIALS is set
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        try:
            cred = credentials.ApplicationDefault()
            _app = firebase_admin.initialize_app(cred, options=options)
            logger.info("Firebase Admin SDK initialised via Application Default Credentials.")
            return _app
        except Exception:
            logger.exception("Failed to initialise Firebase Admin SDK via Application Default Credentials.")

    logger.warning(
        "Firebase credentials not provided — push notifications disabled. "
        "Set FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_JSON to enable FCM."
    )
    return None


def is_push_enabled() -> bool:
    """Whether push notifications can actually be sent from this process."""
    return get_firebase_app() is not None
