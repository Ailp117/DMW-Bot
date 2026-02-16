-- DMW Rewrite SQL Backup
-- generated_at_utc: 2026-02-15T13:10:49.554760+00:00
BEGIN;

DELETE FROM "debug_mirror_cache";
DELETE FROM "user_levels";
DELETE FROM "raid_attendance";
DELETE FROM "raid_templates";
DELETE FROM "raid_posted_slots";
DELETE FROM "raid_votes";
DELETE FROM "raid_options";
DELETE FROM "raids";
DELETE FROM "dungeons";
DELETE FROM "guild_settings";

INSERT INTO "guild_settings" ("guild_id", "guild_name", "participants_channel_id", "raidlist_channel_id", "raidlist_message_id", "planner_channel_id", "default_min_players", "templates_enabled", "template_manager_role_id") VALUES (1471638702316060836, 'Bot Log Server', NULL, NULL, NULL, NULL, 0, TRUE, NULL);

INSERT INTO "dungeons" ("id", "name", "short_code", "is_active", "sort_order") VALUES (1, 'Nanos', 'NAN', TRUE, 1);
INSERT INTO "dungeons" ("id", "name", "short_code", "is_active", "sort_order") VALUES (2, 'Skull', 'SKL', TRUE, 2);

COMMIT;
