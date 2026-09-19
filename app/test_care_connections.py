"""
Test script for verifying Care Connections workflow and notification logging.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.db.models import (
    NotificationLog, Relationship, RelationshipRequest, RelationshipType,
    RequestStatus, User, UserRole,
)
from app.services import (
    notification_service, relationship_request_service, relationship_service,
)


async def test_care_connections_flow():
    print("--- Testing Care Connections Services ---")

    senior_id = uuid4()
    caregiver_id = uuid4()
    request_id = uuid4()

    senior_user = User(id=senior_id, name="Senior Ramesh", email="ramesh@demo.com", role=UserRole.SENIOR)
    cg_user = User(id=caregiver_id, name="Nurse Anita", email="anita@demo.com", role=UserRole.CAREGIVER)

    req_obj = RelationshipRequest(
        id=request_id,
        requester_id=caregiver_id,
        target_id=senior_id,
        relationship_type=RelationshipType.CAREGIVER,
        label="Primary Caregiver",
        status=RequestStatus.PENDING,
        requester=cg_user,
        target=senior_user,
    )

    with patch.object(notification_service, "send_push", new_callable=AsyncMock) as mock_send_push:
        mock_send_push.return_value = 1

        # 1. Test create_request
        mock_db1 = AsyncMock()
        mock_result_user = MagicMock()
        mock_result_user.scalar_one_or_none.return_value = senior_user
        mock_result_user.scalar_one.return_value = senior_user

        mock_result_empty = MagicMock()
        mock_result_empty.scalar_one_or_none.return_value = None

        mock_result_req = MagicMock()
        mock_result_req.scalar_one.return_value = req_obj

        mock_db1.execute.side_effect = [
            mock_result_user,   # _find_user lookup
            mock_result_empty,  # existing_link lookup
            mock_result_empty,  # existing request lookup
            mock_result_user,   # requester lookup
            mock_result_req,    # _reload lookup
        ]

        print("Testing create_request push dispatch & logging...")
        await relationship_request_service.create_request(
            db=mock_db1,
            requester_id=caregiver_id,
            target_identifier="ramesh@demo.com",
            relationship_type="CAREGIVER",
            label="Primary Caregiver",
        )
        assert mock_send_push.called
        print(f"create_request push called: {mock_send_push.call_args}")

        # 2. Test respond (accept)
        mock_send_push.reset_mock()
        mock_db2 = AsyncMock()

        mock_result_req_found = MagicMock()
        mock_result_req_found.scalar_one_or_none.return_value = req_obj

        mock_db2.execute.side_effect = [
            mock_result_req_found,  # select request
            mock_result_user,       # select target user
            mock_result_req,        # _reload lookup
        ]

        print("Testing respond (accept) push dispatch & logging...")
        await relationship_request_service.respond(
            db=mock_db2,
            request_id=request_id,
            user_id=senior_id,
            accept=True,
        )
        assert mock_send_push.called
        print(f"respond accept push called: {mock_send_push.call_args}")

        # 3. Test connect_users
        mock_send_push.reset_mock()
        mock_db3 = AsyncMock()

        mock_result_cg = MagicMock()
        mock_result_cg.scalar_one_or_none.return_value = cg_user
        mock_result_cg.scalar_one.return_value = cg_user

        mock_result_rel = MagicMock()
        mock_result_rel.scalar_one.return_value = Relationship(
            id=uuid4(), senior_id=senior_id, related_user_id=caregiver_id, related_user=cg_user
        )

        mock_db3.execute.side_effect = [
            mock_result_cg,     # target_user lookup (Nurse Anita)
            mock_result_empty,  # existing relationship check
            mock_result_user,   # senior_user lookup (Senior Ramesh)
            mock_result_rel,    # reload relationship
        ]

        print("Testing connect_users direct connection push dispatch...")
        await relationship_service.connect_users(
            db=mock_db3,
            current_user_id=senior_id,
            related_identifier="anita@demo.com",
            relationship_type="CAREGIVER",
            label="Direct Caregiver",
        )
        assert mock_send_push.called
        print(f"connect_users push called: {mock_send_push.call_args}")

    print("\n[SUCCESS] Care connections workflow verified successfully!")


if __name__ == "__main__":
    asyncio.run(test_care_connections_flow())
