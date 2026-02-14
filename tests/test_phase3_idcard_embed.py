from __future__ import annotations

from types import SimpleNamespace

from bot.runtime import RewriteDiscordBot, _render_xp_progress_bar, _xp_progress_stats


def test_xp_progress_helpers_return_bounded_values():
    progress, total, percent = _xp_progress_stats(total_xp=250, level=2)
    assert total > 0
    assert 0 <= progress <= total
    assert 0 <= percent <= 100

    bar = _render_xp_progress_bar(progress=progress, total=total, width=12)
    assert bar.startswith("[")
    assert bar.endswith("]")
    assert len(bar) == 14


def test_build_user_id_card_embed_contains_avatar_and_xp_footer(repo):
    row = repo.get_or_create_user_level(1, 42, "Tester42")
    row.xp = 175
    row.level = 1

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    user = SimpleNamespace(
        id=42,
        mention="<@42>",
        display_name="Tester42",
        display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
    )

    embed = RewriteDiscordBot._build_user_id_card_embed(
        bot,
        guild_id=1,
        guild_name="GuildOne",
        user=user,
    )

    assert "Ausweis" in (embed.title or "")
    assert "GuildOne" in (embed.description or "")
    assert "XP [" in (embed.footer.text or "")
    assert embed.author.icon_url == "https://cdn.example/avatar.png"
    assert embed.thumbnail.url == "https://cdn.example/avatar.png"
    name_field = next((field for field in embed.fields if field.name == "Name"), None)
    assert name_field is not None
    assert "Tester42" in name_field.value
    assert "<@" not in name_field.value
