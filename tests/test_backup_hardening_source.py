from pathlib import Path


def test_backup_export_uses_write_lock_and_atomic_replace():
    source = Path("backup_sql.py").read_text(encoding="utf-8")
    assert "_BACKUP_WRITE_LOCK = asyncio.Lock()" in source
    assert "async with _BACKUP_WRITE_LOCK" in source
    assert "temp_path = output_path.with_name" in source
    assert "temp_path.replace(output_path)" in source


def test_manual_backup_command_handles_export_failures():
    source = Path("commands_backup.py").read_text(encoding="utf-8")
    assert "try:" in source
    assert "except Exception:" in source
    assert "Backup fehlgeschlagen" in source


def test_backup_flows_emit_log_channel_notifications():
    backup_cmd_source = Path("commands_backup.py").read_text(encoding="utf-8")
    main_source = Path("main.py").read_text(encoding="utf-8")

    assert "_notify_log_channel" in backup_cmd_source
    assert "Manueller Backup-Start" in backup_cmd_source
    assert "Manueller Backup abgeschlossen" in backup_cmd_source
    assert "Auto-Backup gestartet" in main_source
    assert "Auto-Backup abgeschlossen" in main_source
