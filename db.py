import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from config import DATABASE_URL

log = logging.getLogger("dmw-raid-bot")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_session() -> AsyncSession:
    return SessionLocal()

async def ensure_schema():
    statements = [
        """
        create table if not exists guild_settings (
          guild_id bigint primary key,
          participants_channel_id bigint not null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );
        """,
        "alter table guild_settings add column if not exists created_at timestamptz not null default now();",
        "alter table guild_settings add column if not exists updated_at timestamptz not null default now();",
        "alter table guild_settings add column if not exists raidlist_channel_id bigint;",
        "alter table guild_settings add column if not exists raidlist_message_id bigint;",
        "alter table guild_settings add column if not exists planner_channel_id bigint;",

        """
        create table if not exists dungeons (
          id bigserial primary key,
          name text not null,
          short_code text not null unique,
          is_active boolean not null default true,
          sort_order int not null default 0,
          created_at timestamptz not null default now()
        );
        """,
        "create index if not exists idx_dungeons_active_sort on dungeons (is_active desc, sort_order asc, name asc);",

        """
        create table if not exists raids (
          id bigserial primary key,
          guild_id bigint not null,
          channel_id bigint not null,
          creator_id bigint not null,
          dungeon text not null,
          status text not null default 'open' check (status in ('open','finalized','canceled')),
          message_id bigint,
          min_players int not null default 0 check (min_players >= 0),
          participants_posted boolean not null default false,
          created_at timestamptz not null default now()
        );
        """,
        "create index if not exists idx_raids_guild_status on raids (guild_id, status);",
        "create index if not exists idx_raids_channel on raids (channel_id);",
        "alter table raids add column if not exists temp_role_id bigint;",
        "alter table raids add column if not exists temp_role_created boolean not null default false;",

        """
        create table if not exists raid_options (
          id bigserial primary key,
          raid_id bigint not null references raids(id) on delete cascade,
          kind text not null check (kind in ('day','time')),
          label text not null,
          created_at timestamptz not null default now(),
          unique (raid_id, kind, label)
        );
        """,
        "create index if not exists idx_raid_options_raid_kind on raid_options (raid_id, kind);",
        "alter table raid_options add column if not exists created_at timestamptz not null default now();",

        """
        create table if not exists raid_votes (
          id bigserial primary key,
          raid_id bigint not null references raids(id) on delete cascade,
          kind text not null check (kind in ('day','time')),
          option_label text not null,
          user_id bigint not null,
          created_at timestamptz not null default now(),
          unique (raid_id, kind, option_label, user_id)
        );
        """,
        "create index if not exists idx_raid_votes_raid_kind_user on raid_votes (raid_id, kind, user_id);",
        "create index if not exists idx_raid_votes_raid_kind_label on raid_votes (raid_id, kind, option_label);",
        "alter table raid_votes add column if not exists created_at timestamptz not null default now();",

        """
        create table if not exists raid_posted_slots (
          id bigserial primary key,
          raid_id bigint not null references raids(id) on delete cascade,
          day_label text not null,
          time_label text not null,
          channel_id bigint,
          message_id bigint,
          posted_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique (raid_id, day_label, time_label)
        );
        """,
        "create index if not exists idx_raid_posted_slots_raid on raid_posted_slots (raid_id);",
        "create index if not exists idx_raid_posted_slots_message on raid_posted_slots (message_id);",
        "alter table raid_posted_slots add column if not exists posted_at timestamptz not null default now();",
        "alter table raid_posted_slots add column if not exists updated_at timestamptz not null default now();",

        """
        create or replace function set_updated_at()
        returns trigger as $$
        begin
          new.updated_at = now();
          return new;
        end;
        $$ language plpgsql;
        """,
        "drop trigger if exists trg_guild_settings_updated_at on guild_settings;",
        """
        create trigger trg_guild_settings_updated_at
        before update on guild_settings
        for each row execute function set_updated_at();
        """,
        "drop trigger if exists trg_raid_posted_slots_updated_at on raid_posted_slots;",
        """
        create trigger trg_raid_posted_slots_updated_at
        before update on raid_posted_slots
        for each row execute function set_updated_at();
        """,
    ]

    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))

    log.info("DB schema ensured (create/migrate).")
