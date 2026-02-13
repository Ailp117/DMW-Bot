from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Dungeon(Base):
    __tablename__ = "dungeons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    short_code: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    participants_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raidlist_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raidlist_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    planner_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    guild_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_min_players: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    templates_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    template_manager_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Raid(Base):
    __tablename__ = "raids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dungeon: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_players: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    participants_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temp_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    temp_role_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RaidOption(Base):
    __tablename__ = "raid_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(Integer, ForeignKey("raids.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RaidVote(Base):
    __tablename__ = "raid_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[int] = mapped_column(Integer, ForeignKey("raids.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    option_label: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RaidPostedSlot(Base):
    __tablename__ = "raid_posted_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raid_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raids.id", ondelete="CASCADE"), nullable=False)
    day_label: Mapped[str] = mapped_column(Text, nullable=False)
    time_label: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    posted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RaidTemplate(Base):
    __tablename__ = "raid_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guild_settings.guild_id", ondelete="CASCADE"), nullable=False)
    dungeon_id: Mapped[int] = mapped_column(Integer, ForeignKey("dungeons.id", ondelete="CASCADE"), nullable=False)
    template_name: Mapped[str] = mapped_column(String(80), nullable=False)
    template_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RaidAttendance(Base):
    __tablename__ = "raid_attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raid_display_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dungeon: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    marked_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class UserLevel(Base):
    __tablename__ = "user_levels"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    username: Mapped[str | None] = mapped_column(Text, nullable=True)


class DebugMirrorCache(Base):
    __tablename__ = "debug_mirror_cache"

    cache_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raid_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


def mapped_public_table_names() -> tuple[str, ...]:
    return tuple(table.name for table in Base.metadata.sorted_tables)


REQUIRED_BOOT_TABLES = mapped_public_table_names()
