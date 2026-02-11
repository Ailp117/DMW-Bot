from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, String, Text, DateTime, ForeignKey, func, UniqueConstraint


class Base(DeclarativeBase):
    pass


class Raid(Base):
    __tablename__ = "raids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)  # planner channel
    creator_id: Mapped[int] = mapped_column(BigInteger)
    dungeon: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open/closed
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_players: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RaidOption(Base):
    __tablename__ = "raid_options"
    __table_args__ = (UniqueConstraint("raid_id", "kind", "label", name="uq_raidopt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # day/time
    label: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RaidVote(Base):
    __tablename__ = "raid_votes"
    __table_args__ = (UniqueConstraint("raid_id", "kind", "option_label", "user_id", name="uq_vote"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # day/time
    option_label: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)


class RaidPostedSlot(Base):
    __tablename__ = "raid_posted_slots"
    __table_args__ = (UniqueConstraint("raid_id", "day_label", "time_label", name="uq_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id", ondelete="CASCADE"), index=True)
    day_label: Mapped[str] = mapped_column(String(64))
    time_label: Mapped[str] = mapped_column(String(64))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    planner_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    participants_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raidlist_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raidlist_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class Dungeon(Base):
    __tablename__ = "dungeons"
    short_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Integer, default=1)  # 1/0
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
