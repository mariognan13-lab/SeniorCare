"""
Seed helper to populate database with demo users and relationships.
"""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import CaregiverProfile, Relationship, RelationshipType, User, UserRole

DEMO_USERS_SEED = [
    {
        "id": UUID("a1111111-1111-1111-1111-111111111111"),
        "name": "Ramesh Kumar",
        "email": "ramesh@demo.com",
        "phone": "+91-9876543210",
        "role": UserRole.SENIOR,
    },
    {
        "id": UUID("e5555555-5555-5555-5555-555555555555"),
        "name": "Sunita Kumar",
        "email": "sunita@demo.com",
        "phone": "+91-9876543214",
        "role": UserRole.SENIOR,
    },
    {
        "id": UUID("b2222222-2222-2222-2222-222222222222"),
        "name": "Priya Kumar",
        "email": "priya@demo.com",
        "phone": "+91-9876543211",
        "role": UserRole.FAMILY,
    },
    {
        "id": UUID("c3333333-3333-3333-3333-333333333333"),
        "name": "Nurse Anita",
        "email": "anita@demo.com",
        "phone": "+91-9876543212",
        "role": UserRole.CAREGIVER,
    },
    {
        "id": UUID("d4444444-4444-4444-4444-444444444444"),
        "name": "Helper Suresh",
        "email": "suresh@demo.com",
        "phone": "+91-9876543213",
        "role": UserRole.CAREGIVER,
    },
    {
        "id": UUID("4d2eb64a-6992-4a2f-ba26-6c78bb2e0ee3"),
        "name": "Ram Kalyan",
        "email": "ramkalyan13@gmail.com",
        "phone": None,
        "role": UserRole.SENIOR,
    },
]


async def seed_demo_data(db: AsyncSession) -> None:
    res = await db.execute(select(User))
    if res.scalars().first() is not None:
        return  # Data already exists

    pwd_hash = hash_password("demo1234")
    user_map = {}

    for u_data in DEMO_USERS_SEED:
        user = User(
            id=u_data["id"],
            name=u_data["name"],
            email=u_data["email"],
            phone=u_data["phone"],
            password_hash=pwd_hash,
            role=u_data["role"],
        )
        db.add(user)
        user_map[u_data["email"]] = user
        if u_data["role"] == UserRole.CAREGIVER:
            db.add(CaregiverProfile(user_id=u_data["id"], is_available=True))

    await db.flush()

    # Default relationships
    ramesh_id = UUID("a1111111-1111-1111-1111-111111111111")
    sunita_id = UUID("e5555555-5555-5555-5555-555555555555")
    priya_id = UUID("b2222222-2222-2222-2222-222222222222")
    anita_id = UUID("c3333333-3333-3333-3333-333333333333")
    suresh_id = UUID("d4444444-4444-4444-4444-444444444444")

    relationships = [
        Relationship(senior_id=ramesh_id, related_user_id=sunita_id, relationship_type=RelationshipType.SPOUSE, label="Spouse Caregiver", is_primary=True),
        Relationship(senior_id=ramesh_id, related_user_id=priya_id, relationship_type=RelationshipType.FAMILY, label="Daughter", is_primary=False),
        Relationship(senior_id=ramesh_id, related_user_id=anita_id, relationship_type=RelationshipType.CAREGIVER, label="Primary Nurse", is_primary=True),
        Relationship(senior_id=ramesh_id, related_user_id=suresh_id, relationship_type=RelationshipType.CAREGIVER, label="Helper", is_primary=False),
    ]

    for rel in relationships:
        db.add(rel)

    await db.commit()
