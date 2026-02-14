from __future__ import annotations

from datetime import date, datetime, time

from db.session import _redact_sql_parameters


def test_redact_sql_parameters_for_mapping_values():
    out = _redact_sql_parameters(
        {
            "user_id": 12345,
            "username": "SecretName",
            "active": True,
            "created_at": datetime(2026, 2, 13, 12, 0, 0),
            "birthday": date(2026, 2, 13),
            "alarm": time(12, 15),
            "none_value": None,
        }
    )
    assert out == {
        "user_id": "<int>",
        "username": "<redacted>",
        "active": "<bool>",
        "created_at": "<datetime>",
        "birthday": "<date>",
        "alarm": "<time>",
        "none_value": None,
    }


def test_redact_sql_parameters_for_nested_sequence_payloads():
    out = _redact_sql_parameters(
        [
            {"a": "text", "b": 42},
            ("token", 9.5, None),
        ]
    )
    assert out == [
        {"a": "<redacted>", "b": "<int>"},
        ("<redacted>", "<float>", None),
    ]
