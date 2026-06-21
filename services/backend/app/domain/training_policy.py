from __future__ import annotations


def default_training_policy(timezone: str, retention_days: int) -> dict[str, object]:
    return {
        "windows": [
            {
                "days": [0, 1, 2, 3, 4, 5, 6],
                "start": "09:00",
                "end": "21:00",
            }
        ],
        "quiet_hours": [
            {
                "start": "22:00",
                "end": "08:00",
            }
        ],
        "daily_max": 2,
        "retention_days": retention_days,
        "timezone": timezone,
    }
