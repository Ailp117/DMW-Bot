from __future__ import annotations
from typing import Optional
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class GuildSettings(Base):
    __tablename__ = "guild_settings"
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    participants_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    planner_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    raidlist_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    raidlist_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Dungeon(Base):
    __tablename__ = "dungeons"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    short_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Raid(Base):
    __tablename__ = "raids"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dungeon: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    min_players: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    participants_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temp_role_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    temp_role_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    options = relationship("RaidOption", back_populates="raid", cascade="all, delete-orphan")
    votes = relationship("RaidVote", back_populates="raid", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status in ('open','finalized','canceled')", name="ck_raids_status"),
        CheckConstraint("min_players >= 0", name="ck_raids_min_players"),
    )

class RaidOption(Base):
    __tablename__ = "raid_options"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raid = relationship("Raid", back_populates="options")

    __table_args__ = (
        CheckConstraint("kind in ('day','time')", name="ck_raid_options_kind"),
        UniqueConstraint("raid_id", "kind", "label", name="uq_raid_options"),
    )

class RaidVote(Base):
    __tablename__ = "raid_votes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    option_label: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raid = relationship("Raid", back_populates="votes")

    __table_args__ = (
        CheckConstraint("kind in ('day','time')", name="ck_raid_votes_kind"),
        UniqueConstraint("raid_id", "kind", "option_label", "user_id", name="uq_raid_vote"),
    )

class RaidPostedSlot(Base):
    __tablename__ = "raid_posted_slots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id", ondelete="CASCADE"), nullable=False)
    day_label: Mapped[str] = mapped_column(Text, nullable=False)
    time_label: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    posted_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("raid_id", "day_label", "time_label", name="uq_raid_posted_slot"),)
