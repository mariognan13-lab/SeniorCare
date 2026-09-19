"""
Test script for verifying Medication schedule creation, log response, and FCM missed-dose alert dispatch.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.db.models import (
    Medication, MedicationLog, MedicationLogStatus, Relationship, RelationshipType, User, UserRole,
)
from app.services import medication_service, notification_service


async def test_medication_service_flow():
    print("--- Testing Medication Services & FCM Alerts ---")

    senior_id = uuid4()
    caregiver_id = uuid4()
    medication_id = uuid4()
    log_id = uuid4()

    senior_user = User(id=senior_id, name="Senior Ramesh", email="ramesh@demo.com", role=UserRole.SENIOR)
    cg_user = User(id=caregiver_id, name="Nurse Anita", email="anita@demo.com", role=UserRole.CAREGIVER)

    med_obj = Medication(
        id=medication_id,
        senior_id=senior_id,
        name="Aspirin 100mg",
        dosage="1 Tablet",
        frequency="Once Daily",
        schedule_times=["08:00"],
        is_active=True,
    )

    log_obj = MedicationLog(
        id=log_id,
        medication_id=medication_id,
        scheduled_time=med_obj.created_at,
        status=MedicationLogStatus.MISSED,
        medication=med_obj,
    )

    rel_obj = Relationship(
        id=uuid4(),
        senior_id=senior_id,
        related_user_id=caregiver_id,
        relationship_type=RelationshipType.CAREGIVER,
        related_user=cg_user,
    )

    with patch.object(notification_service, "send_push", new_callable=AsyncMock) as mock_send_push:
        mock_send_push.return_value = 1

        mock_db = AsyncMock()

        mock_res_log = MagicMock()
        mock_res_log.scalar_one_or_none.return_value = log_obj

        mock_res_med = MagicMock()
        mock_res_med.scalar_one_or_none.return_value = med_obj

        mock_res_senior = MagicMock()
        mock_res_senior.scalar_one_or_none.return_value = senior_user

        mock_res_rel = MagicMock()
        mock_res_rel.scalars.return_value.all.return_value = [rel_obj]

        mock_db.execute.side_effect = [
            mock_res_log,     # select log
            mock_res_med,     # select medication
            mock_res_senior,  # select senior user
            mock_res_rel,     # select relationships
        ]

        print("Testing MISSED medication response & FCM push notification dispatch...")
        result = await medication_service.respond_to_medication_log(
            db=mock_db,
            log_id=log_id,
            status_str="MISSED",
            notes="User did not respond within alarm window",
        )

        assert result.status == MedicationLogStatus.MISSED
        assert mock_send_push.called
        print(f"FCM Push call args: {mock_send_push.call_args}")

    print("\n[SUCCESS] Medication service & FCM alerts verified successfully!")


if __name__ == "__main__":
    asyncio.run(test_medication_service_flow())
