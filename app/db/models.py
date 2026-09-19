"""
SQLAlchemy ORM models for all database tables.

All tables are defined here even though some are used in later batches,
so the schema is created in full on startup.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Enum, Float,
    ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Enum types matching PostgreSQL enums ──

class UserRole(str, enum.Enum):
    SENIOR = "SENIOR"
    FAMILY = "FAMILY"
    CAREGIVER = "CAREGIVER"


class RelationshipType(str, enum.Enum):
    FAMILY = "FAMILY"
    CAREGIVER = "CAREGIVER"
    SPOUSE = "SPOUSE"
    PARTNER = "PARTNER"
    OTHER = "OTHER"


class EmergencyStatus(str, enum.Enum):
    CREATED = "CREATED"
    NOTIFIED = "NOTIFIED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    TIMED_OUT = "TIMED_OUT"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    TIMED_OUT = "TIMED_OUT"


class MedicationLogStatus(str, enum.Enum):
    TAKEN = "TAKEN"
    MISSED = "MISSED"
    SKIPPED = "SKIPPED"


class RequestStatus(str, enum.Enum):
    # CANCELLED has no endpoint yet — a requester cannot withdraw a request they
    # regret. It is defined now anyway because adding a value to an existing
    # Postgres enum later needs an ALTER TYPE that create_all() cannot do, which
    # is exactly the friction that made the ADMIN role expensive. Cheaper to
    # carry one unused label than to migrate for it.
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


# ── Models ──

class User(Base):
    __tablename__ = "users"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid = Column(String(128), unique=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    phone = Column(String(20))
    role = Column(Enum(UserRole, name="user_role", create_constraint=True), nullable=False)
    fcm_token = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    caregiver_profile = relationship("CaregiverProfile", back_populates="user", uselist=False)
    senior_relationships = relationship("Relationship", foreign_keys="Relationship.senior_id", back_populates="senior")
    related_relationships = relationship("Relationship", foreign_keys="Relationship.related_user_id", back_populates="related_user")
    devices = relationship("UserDevice", back_populates="user", cascade="all, delete-orphan")


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    senior_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    related_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(Enum(RelationshipType, name="relationship_type", create_constraint=True), nullable=False)
    label = Column(String(100))
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("senior_id", "related_user_id", name="uq_relationship"),
        CheckConstraint("senior_id != related_user_id", name="chk_not_self"),
    )

    senior = relationship("User", foreign_keys=[senior_id], back_populates="senior_relationships")
    related_user = relationship("User", foreign_keys=[related_user_id], back_populates="related_relationships")


class RelationshipRequest(Base):
    """
    A pending ask from one user to be connected to another.

    The direction is the whole point. `target_id` is the person who will become
    the eventual link's `senior_id`, and **only that person may accept or
    decline**. That is what stops any signed-in account from attaching itself to
    someone else's care record: a link is created by the person being cared for,
    never by the person who wants access.

    A separate table rather than a status column on `relationships`, because
    `create_all()` on startup creates missing tables but cannot alter existing
    ones — so this arrives with no migration.
    """

    __tablename__ = "relationship_requests"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(Enum(RelationshipType, name="relationship_type", create_constraint=True), nullable=False)
    label = Column(String(100))
    message = Column(Text)
    status = Column(Enum(RequestStatus, name="request_status", create_constraint=True), default=RequestStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    responded_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("requester_id", "target_id", name="uq_relationship_request"),
        CheckConstraint("requester_id != target_id", name="chk_request_not_self"),
    )

    requester = relationship("User", foreign_keys=[requester_id])
    target = relationship("User", foreign_keys=[target_id])


class CaregiverProfile(Base):
    __tablename__ = "caregiver_profiles"

    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    is_available = Column(Boolean, default=True, nullable=False)
    max_active_emergencies = Column(Integer, default=3, nullable=False)
    current_active_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "current_active_count >= 0 AND current_active_count <= max_active_emergencies",
            name="chk_capacity",
        ),
    )

    user = relationship("User", back_populates="caregiver_profile")


class Emergency(Base):
    __tablename__ = "emergencies"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    senior_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    emergency_type = Column(String(100), default="GENERAL", nullable=False)
    description = Column(Text)
    status = Column(Enum(EmergencyStatus, name="emergency_status", create_constraint=True), default=EmergencyStatus.CREATED, nullable=False)
    priority = Column(Integer, default=1, nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    senior = relationship("User")
    assignments = relationship("EmergencyAssignment", back_populates="emergency")
    events = relationship("EmergencyEvent", back_populates="emergency", order_by="EmergencyEvent.created_at")


class EmergencyAssignment(Base):
    __tablename__ = "emergency_assignments"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emergency_id = Column(Uuid(as_uuid=True), ForeignKey("emergencies.id", ondelete="CASCADE"), nullable=False, index=True)
    caregiver_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(AssignmentStatus, name="assignment_status", create_constraint=True), default=AssignmentStatus.PENDING, nullable=False)
    assigned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    responded_at = Column(DateTime(timezone=True))
    timeout_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("emergency_id", "caregiver_id", name="uq_assignment"),
    )

    emergency = relationship("Emergency", back_populates="assignments")
    caregiver = relationship("User")


class EmergencyEvent(Base):
    __tablename__ = "emergency_events"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emergency_id = Column(Uuid(as_uuid=True), ForeignKey("emergencies.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    actor_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"))
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    emergency = relationship("Emergency", back_populates="events")
    actor = relationship("User")


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    senior_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    dosage = Column(String(100))
    frequency = Column(String(100))
    schedule_times = Column(JSON, nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    senior = relationship("User")
    logs = relationship("MedicationLog", back_populates="medication")


class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    medication_id = Column(Uuid(as_uuid=True), ForeignKey("medications.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_time = Column(DateTime(timezone=True), nullable=False)
    taken_at = Column(DateTime(timezone=True))
    status = Column(Enum(MedicationLogStatus, name="medication_log_status", create_constraint=True), default=MedicationLogStatus.MISSED, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    medication = relationship("Medication", back_populates="logs")


class UserDevice(Base):
    __tablename__ = "user_devices"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    fcm_token = Column(Text, nullable=False)
    device_type = Column(String(50), default="android", nullable=False)
    device_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "fcm_token", name="uq_user_device"),
    )

    user = relationship("User", back_populates="devices")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    notification_type = Column(String(100), nullable=False)
    data = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User")

