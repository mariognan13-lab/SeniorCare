"""
Test script for verifying SOS push notifications and Firebase Admin SDK module.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.core.config import settings
from app.core.firebase import get_firebase_app, is_push_enabled
from app.db.models import (
    AssignmentStatus, Emergency, EmergencyAssignment, EmergencyStatus,
    NotificationLog, Relationship, RelationshipType, User, UserRole,
)
from app.services import notification_service, sos_service


async def test_sos_notification_flow():
    print("--- 1. Testing Firebase App Initialization status ---")
    app = get_firebase_app()
    print(f"Firebase app status: {app} (push enabled: {is_push_enabled()})")

    print("\n--- 2. Testing SOS Service Notifications ---")
    
    # Create mock IDs
    senior_id = uuid4()
    caregiver1_id = uuid4()
    caregiver2_id = uuid4()
    emergency_id = uuid4()

    # Create mock objects
    senior_user = User(id=senior_id, name="Test Senior", email="senior@test.com", role=UserRole.SENIOR)
    cg1_user = User(id=caregiver1_id, name="Nurse Caregiver 1", email="cg1@test.com", role=UserRole.CAREGIVER)
    cg2_user = User(id=caregiver2_id, name="Helper Caregiver 2", email="cg2@test.com", role=UserRole.CAREGIVER)

    emergency = Emergency(
        id=emergency_id,
        senior_id=senior_id,
        emergency_type="FALL_DETECTED",
        description="Fall detected in bathroom",
        status=EmergencyStatus.CREATED,
        senior=senior_user,
        assignments=[
            EmergencyAssignment(emergency_id=emergency_id, caregiver_id=caregiver1_id, caregiver=cg1_user),
            EmergencyAssignment(emergency_id=emergency_id, caregiver_id=caregiver2_id, caregiver=cg2_user),
        ]
    )

    relationships = [
        Relationship(senior_id=senior_id, related_user_id=caregiver1_id, relationship_type=RelationshipType.CAREGIVER),
        Relationship(senior_id=senior_id, related_user_id=caregiver2_id, relationship_type=RelationshipType.CAREGIVER),
    ]

    # Mock DB Session
    mock_db = AsyncMock()

    # Mock execute results
    def mock_execute_side_effect(stmt):
        mock_result = MagicMock()
        stmt_str = str(stmt)
        if "relationships" in stmt_str:
            mock_result.scalars.return_value.all.return_value = relationships
        elif "emergencies" in stmt_str:
            mock_result.scalars.return_value.first.return_value = emergency
            mock_result.scalar_one_or_none.return_value = emergency
            mock_result.scalar_one.return_value = emergency
        elif "users" in stmt_str:
            mock_result.scalar_one_or_none.return_value = cg1_user
            mock_result.scalars.return_value.all.return_value = [cg1_user, cg2_user]
        else:
            mock_result.scalars.return_value.all.return_value = []
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar_one.return_value = emergency
        return mock_result

    mock_db.execute.side_effect = mock_execute_side_effect

    with patch.object(notification_service, "send_push", new_callable=AsyncMock) as mock_send_push:
        mock_send_push.return_value = 2

        print("Testing trigger_sos push dispatch...")
        triggered = await sos_service.trigger_sos(
            db=mock_db,
            senior_id=senior_id,
            emergency_type="FALL_DETECTED",
            description="Fall detected in bathroom",
        )
        assert mock_send_push.called
        print(f"Trigger call count: {mock_send_push.call_count}")
        print(f"Trigger last call args: {mock_send_push.call_args}")

        mock_send_push.reset_mock()
        print("Testing accept_emergency push dispatch...")
        accepted = await sos_service.accept_emergency(
            db=mock_db,
            emergency_id=emergency_id,
            caregiver_id=caregiver1_id,
        )
        assert mock_send_push.called
        print(f"Accept call count: {mock_send_push.call_count}")
        print(f"Accept calls: {mock_send_push.call_args_list}")

        mock_send_push.reset_mock()
        print("Testing resolve_emergency push dispatch...")
        resolved = await sos_service.resolve_emergency(
            db=mock_db,
            emergency_id=emergency_id,
            user_id=caregiver1_id,
        )
        assert mock_send_push.called
        print(f"Resolve call count: {mock_send_push.call_count}")

        mock_send_push.reset_mock()
        print("Testing cancel_emergency push dispatch...")
        cancelled = await sos_service.cancel_emergency(
            db=mock_db,
            emergency_id=emergency_id,
            senior_id=senior_id,
        )
        assert mock_send_push.called
        print(f"Cancel call count: {mock_send_push.call_count}")

    print("\n[SUCCESS] All SOS push notification flows verified successfully!")


if __name__ == "__main__":
    asyncio.run(test_sos_notification_flow())
