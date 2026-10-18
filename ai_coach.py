
import os
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from openai import OpenAI
from supabase import create_client


MODEL = "gpt-4.1-mini"
TZ = ZoneInfo("Europe/Prague")


def fetch_all(query, page_size=1000):
    rows = []
    start = 0

    while True:
        result = query.range(
            start, start + page_size - 1
        ).execute()

        batch = result.data or []
        rows.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return rows


def load_activities(db):
    since = (
        datetime.now(timezone.utc) - timedelta(days=42)
    ).isoformat()

    query = (
        db.table("garmin_activities")
        .select(
            "activity_date,activity_name,activity_type,"
            "distance_meters,duration_seconds,"
            "elevation_gain_meters,average_heart_rate,"
            "raw_data"
        )
        .gte("activity_date", since)
        .order("activity_date", desc=True)
    )

    rows = fetch_all(query)
    activities = []

    for row in rows:
        raw = row.get("raw_data") or {}

        activities.append({
            "date": row["activity_date"],
            "type": row.get("activity_type"),
            "name": row.get("activity_name"),
            "distance_km": round(
                (row.get("distance_meters") or 0) / 1000, 1
            ),
            "duration_min": round(
                (row.get("duration_seconds") or 0) / 60
            ),
            "elevation_m": row.get("elevation_gain_meters"),
            "avg_hr": row.get("average_heart_rate"),
            "exercise_load": raw.get("activityTrainingLoad"),
            "aerobic_te": raw.get("aerobicTrainingEffect"),
            "anaerobic_te": raw.get("anaerobicTrainingEffect"),
        })

    return activities


def load_recovery(db):
    since = (
        datetime.now(TZ).date() - timedelta(days=21)
    ).isoformat()

    query = (
        db.table("garmin_recovery")
        .select(
            "recovery_date,sleep_seconds,sleep_score,"
            "hrv_last_night,hrv_weekly_average,"
            "hrv_status,resting_heart_rate"
        )
        .gte("recovery_date", since)
        .order("recovery_date", desc=True)
    )

    rows = fetch_all(query)

    return [
        {
            "date": row["recovery_date"],
            "sleep_hours": (
                round(row["sleep_seconds"] / 3600, 2)
                if row.get("sleep_seconds") is not None
                else None
            ),
            "sleep_score": row.get("sleep_score"),
            "hrv": row.get("hrv_last_night"),
            "hrv_7d": row.get("hrv_weekly_average"),
            "hrv_status": row.get("hrv_status"),
            "resting_hr": row.get("resting_heart_rate"),
        }
        for row in rows
    ]


def telegram_send(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # Telegram limits text messages to 4096 characters.
    # Use smaller chunks to leave room for formatting.
    for start in range(0, len(message), 3500):
        chunk = message[start:start + 3500]

        payload = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
        }).encode("utf-8")

        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(
            request, timeout=30
        ) as response:
            result = json.load(response)

        if not result.get("ok"):
            raise RuntimeError("Telegram delivery failed")


def main():
    db = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )

    activities = load_activities(db)
    recovery = load_recovery(db)

    print(
        f"Loaded {len(activities)} activities "
        f"and {len(recovery)} recovery days"
    )

    if not activities:
        raise RuntimeError("No recent Garmin activities found")

    context = {
        "today": datetime.now(TZ).date().isoformat(),
        "timezone": "Europe/Prague",
        "athlete": {
            "goal": "Tor des Géants 2027",
            "experience": "Experienced mountain ultrarunner",
            "training": [
                "Trail running",
                "Road running",
                "Road cycling",
                "Zwift",
                "Strength training",
            ],
            "priority": (
                "Long-term mountain endurance, "
                "sustainable progression, recovery"
            ),
            "important_context": (
                "Previous ankle sprain and shoulder discomfort. "
                "Current symptoms are unknown; do not assume "
                "they have resolved or worsened."
            ),
        },
        "activities_last_42_days": activities,
        "recovery_last_21_days": recovery,
    }

    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"]
    )

    response = client.responses.create(
        model=MODEL,
        instructions=(
            "Ты опытный тренер по горному ультрабегу. "
            "Твоя задача — анализировать реальные данные Garmin "
            "и помогать готовиться к Tor des Géants 2027. "
            "Отвечай по-русски, конкретно, без общих фраз. "
            "Учитывай бег, велосипед, силовые тренировки, "
            "вертикальный набор и длительность нагрузки. "
            "Не путай Garmin Exercise Load с полной "
            "механической нагрузкой на мышцы. "
            "Оценивай HRV и пульс покоя по динамике, "
            "а не по универсальным порогам. "
            "Не придумывай отсутствующие показатели. "
            "Если данных недостаточно, явно скажи об этом. "
            "Не ставь медицинские диагнозы. "
            "Учитывай, что субъективное самочувствие "
            "спортсмена пока неизвестно. "
            "Дай короткий отчёт для Telegram, максимум "
            "2200 символов. Структура: "
            "1) состояние и нагрузка за последние недели; "
            "2) восстановление; "
            "3) рекомендация на следующие 24 часа; "
            "4) один важный риск или вопрос спортсмену. "
            "Не считай будущие запланированные тренировки "
            "фактически выполненными."
        ),
        input=json.dumps(context, ensure_ascii=False),
        max_output_tokens=1300,
        store=False,
    )

    report = response.output_text

    if not report or not report.strip():
        raise RuntimeError("OpenAI returned an empty report")

    telegram_send("🏔 AI Endurance Coach\n\n" + report)

    print("AI report successfully delivered to Telegram.")
    print(
        "OpenAI tokens:",
        response.usage.input_tokens,
        "input,",
        response.usage.output_tokens,
        "output",
    )


if __name__ == "__main__":
    main()
