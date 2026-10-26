from sqlalchemy import Column, Integer, String, Index

from database import Base


class Appointment(Base):
    __tablename__ = "appointments"

    # A date + time can only be held by one active (non-cancelled) appointment.
    __table_args__ = (
        Index(
            "uq_active_appointment_date_time",
            "appointment_date",
            "appointment_time",
            unique=True,
            sqlite_where=(Column("status") != "cancelled"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False)
    appointment_date = Column(String(10), nullable=False)   # YYYY-MM-DD
    appointment_time = Column(String(5), nullable=False)    # HH:MM (24h, IST)
    service = Column(String(60), nullable=True)             # e.g. "Ultrasound / scan"
    reason = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(String(32), nullable=True)          # ISO 8601, IST


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True)
    created_at = Column(String(32), nullable=True)
