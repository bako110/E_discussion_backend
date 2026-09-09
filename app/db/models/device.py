"""Cles publiques E2EE (Signal Protocol) — distribution des bundles.

Le backend ne stocke que des cles PUBLIQUES. Les cles privees ne quittent
jamais l'appareil. Portage du router `devices` de stream_mobile :
  - identity key + signing key (long terme)
  - signed prekey (rotation moyenne)
  - one-time prekeys (consommees a chaque nouvelle session X3DH)
"""
from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Device(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_device_user_devid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)  # genere par le client
    device_label: Mapped[str | None] = mapped_column(String(120))
    registration_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    identity_public_key: Mapped[str] = mapped_column(String(255), nullable=False)   # base64
    identity_signing_key: Mapped[str] = mapped_column(String(255), nullable=False)  # base64

    signed_prekey_id: Mapped[int] = mapped_column(Integer, nullable=False)
    signed_prekey: Mapped[str] = mapped_column(String(255), nullable=False)         # base64
    prekey_signature: Mapped[str] = mapped_column(String(512), nullable=False)      # base64

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OneTimePreKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "one_time_prekeys"
    __table_args__ = (
        UniqueConstraint("device_pk", "key_id", name="uq_otpk_device_keyid"),
    )

    device_pk: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("devices.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    key_id: Mapped[int] = mapped_column(Integer, nullable=False)
    public_key: Mapped[str] = mapped_column(String(255), nullable=False)  # base64
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
