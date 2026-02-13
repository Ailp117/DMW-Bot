from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    func,
    ForeignKey,
    Index,
    UniqueConstraint,
)

class Base(DeclarativeBase):
    pass


# === dungeons ===
# CSV:
# id integer NOT NULL
# name text NOT NULL
# short_code text NOT NULL
# is_active boolean NOT NULL
# sort_order integer NOT NULL
# created_at timestamp without time zone NOT NULL
class Dungeon(Base):
    __tablename__ = "dungeons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    short_code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


# === guild_settings ===
# guild_id bigint NOT NULL (PK)
# participants_channel_id bigint NULL
# raidlist_channel_id bigint NULL
# raidlist_message_id bigint NULL
# created_at timestamptz NOT NULL
# updated_at timestamptz NOT NULL
# planner_channel_id bigint NULL
class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_name: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    default_min_players: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    templates_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    template_manager_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    planner_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    participants_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raidlist_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raidlist_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# === raids ===
# id integer NOT NULL
# guild_id bigint NOT NULL
# channel_id bigint NOT NULL
# creator_id bigint NOT NULL
# dungeon text NOT NULL
# status text NOT NULL
# created_at timestamp without time zone NOT NULL
# message_id bigint NULL
# min_players integer NOT NULL
# participants_posted boolean NOT NULL
# temp_role_id bigint NULL
# temp_role_created boolean NOT NULL
class Raid(Base):
    __tablename__ = "raids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)   # planner channel
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    dungeon: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # open/closed
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_players: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    participants_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temp_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    temp_role_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

Index("ix_raids_guild_status_created", Raid.guild_id, Raid.status, Raid.created_at)
Index("ix_raids_guild_display_id_unique", Raid.guild_id, Raid.display_id, unique=True)


# === raid_options ===
# id integer NOT NULL
# raid_id integer NOT NULL
# kind text NOT NULL  (day/time)
# label text NOT NULL
# created_at timestamptz NOT NULL
class RaidOption(Base):
    __tablename__ = "raid_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(Integer, ForeignKey("raids.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

Index("ix_raid_options_raid_kind", RaidOption.raid_id, RaidOption.kind)


# === raid_votes ===
# id integer NOT NULL
# raid_id integer NOT NULL
# kind text NOT NULL
# option_label text NOT NULL
# user_id bigint NOT NULL
# created_at timestamptz NOT NULL
class RaidVote(Base):
    __tablename__ = "raid_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(Integer, ForeignKey("raids.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    option_label: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

Index("ix_raid_votes_raid_kind_label", RaidVote.raid_id, RaidVote.kind, RaidVote.option_label)


# === raid_posted_slots ===
# id bigint NOT NULL
# raid_id bigint NOT NULL
# day_label text NOT NULL
# time_label text NOT NULL
# channel_id bigint NOT NULL
# message_id bigint NOT NULL
# posted_at timestamptz NOT NULL
# updated_at timestamptz NOT NULL
class RaidPostedSlot(Base):
    __tablename__ = "raid_posted_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raid_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raids.id", ondelete="CASCADE"), nullable=False, index=True)
    day_label: Mapped[str] = mapped_column(Text, nullable=False)
    time_label: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

Index("ix_posted_slots_raid_day_time", RaidPostedSlot.raid_id, RaidPostedSlot.day_label, RaidPostedSlot.time_label)


# === user_levels ===
# guild_id bigint NOT NULL (PK part)
# user_id bigint NOT NULL (PK part)
# username text NULL
# xp integer NOT NULL
# level integer NOT NULL
# updated_at timestamptz NOT NULL
class UserLevel(Base):
    __tablename__ = "user_levels"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

Index("ix_user_levels_guild_level", UserLevel.guild_id, UserLevel.level)


class RaidTemplate(Base):
    __tablename__ = "raid_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guild_settings.guild_id", ondelete="CASCADE"), nullable=False, index=True)
    dungeon_id: Mapped[int] = mapped_column(Integer, ForeignKey("dungeons.id", ondelete="CASCADE"), nullable=False, index=True)
    template_name: Mapped[str] = mapped_column(String(80), nullable=False)
    template_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("guild_id", "dungeon_id", "template_name", name="uq_raid_templates_guild_dungeon_name"),
    )


class RaidAttendance(Base):
    __tablename__ = "raid_attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    raid_display_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    dungeon: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    marked_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


Index("ix_raid_attendance_lookup", RaidAttendance.guild_id, RaidAttendance.raid_display_id)
Index("ix_raid_attendance_unique_user", RaidAttendance.guild_id, RaidAttendance.raid_display_id, RaidAttendance.user_id, unique=True)


# === debug_mirror_cache ===
class DebugMirrorCache(Base):
    __tablename__ = "debug_mirror_cache"

    cache_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    raid_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


Index("ix_debug_mirror_cache_kind_guild_raid", DebugMirrorCache.kind, DebugMirrorCache.guild_id, DebugMirrorCache.raid_id)
