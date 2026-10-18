
import os
import io
import base64
import zipfile
import tempfile
import time
import sys
from pathlib import Path
from datetime import date, timedelta, datetime, timezone

from cryptography.fernet import Fernet
from garminconnect import Garmin
from supabase import create_client


def get_cipher():
    return Fernet(os.environ["TOKEN_ENCRYPTION_KEY"].encode())


def load_tokens(db):
    result = db.table("garmin_auth_tokens").select(
        "token_data"
    ).eq("id", 1).execute()

    if result.data:
        print("Using encrypted tokens from Supabase")
        return get_cipher().decrypt(
            result.data[0]["token_data"].encode()
        )

    print("Using initial tokens from GitHub Secrets")
    return base64.b64decode(os.environ["GARMIN_TOKENS"])


def save_tokens(db, token_dir):
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for file in token_dir.rglob("*"):
            if file.is_file():
                z.write(file, file.relative_to(token_dir))

    encrypted = get_cipher().encrypt(
        buffer.getvalue()
    ).decode()

    db.table("garmin_auth_tokens").upsert({
        "id": 1,
        "token_data": encrypted,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    print("Encrypted Garmin tokens saved")


def extract_tokens(data, folder):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = folder.resolve()

        for member in archive.infolist():
            target = (folder / member.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Unsafe token archive")

        archive.extractall(folder)


def fetch_optional(label, function):
    try:
        return function()
    except Exception as exc:
        print(f"WARNING: {label}: {type(exc).__name__}: {exc}")
        return None


def sync_recovery():
    db = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

    # Default: update last 7 days.
    # Manual history run: HISTORY_DAYS=365.
    days = int(os.getenv("HISTORY_DAYS", "7"))
    if not 1 <= days <= 366:
        raise ValueError("HISTORY_DAYS must be between 1 and 366")

    with tempfile.TemporaryDirectory() as tmp:
        token_dir = Path(tmp) / "tokens"
        token_dir.mkdir()

        extract_tokens(load_tokens(db), token_dir)

        garmin = Garmin()
        garmin.login(str(token_dir))
        print("Garmin connected")

        try:
            today = date.today()
            success = 0
            failures = 0

            for offset in range(days - 1, -1, -1):
                day = today - timedelta(days=offset)
                day_str = day.isoformat()

                sleep = fetch_optional(
                    "sleep " + day_str,
                    lambda: garmin.get_sleep_data(day_str)
                )
                hrv = fetch_optional(
                    "HRV " + day_str,
                    lambda: garmin.get_hrv_data(day_str)
                )
                stats = fetch_optional(
                    "stats " + day_str,
                    lambda: garmin.get_user_summary(day_str)
                )

                if not any(isinstance(x, dict) for x in (sleep, hrv, stats)):
                    print(f"No data for {day_str}; skipping")
                    failures += 1
                    continue

                sleep = sleep if isinstance(sleep, dict) else None
                hrv = hrv if isinstance(hrv, dict) else None
                stats = stats if isinstance(stats, dict) else None

                sleep_dto = (sleep or {}).get("dailySleepDTO") or {}
                sleep_scores = sleep_dto.get("sleepScores") or {}
                overall = sleep_scores.get("overall") or {}
                hrv_summary = (hrv or {}).get("hrvSummary") or {}

                row = {
                    "recovery_date": day_str,
                    "sleep_seconds": sleep_dto.get("sleepTimeSeconds"),
                    "sleep_score": overall.get("value"),
                    "deep_sleep_seconds": sleep_dto.get("deepSleepSeconds"),
                    "rem_sleep_seconds": sleep_dto.get("remSleepSeconds"),
                    "light_sleep_seconds": sleep_dto.get("lightSleepSeconds"),
                    "hrv_last_night": hrv_summary.get("lastNightAvg"),
                    "hrv_weekly_average": hrv_summary.get("weeklyAvg"),
                    "hrv_status": hrv_summary.get("status"),
                    "resting_heart_rate": (
                        (stats or {}).get("restingHeartRate")
                    ),
                    "raw_sleep": sleep,
                    "raw_hrv": hrv,
                    "raw_daily_stats": stats,
                    "synced_at": datetime.now(timezone.utc).isoformat()
                }

                try:
                    db.table("garmin_recovery").upsert(
                        row, on_conflict="recovery_date"
                    ).execute()
                    success += 1
                    print(f"Saved recovery {day_str}")
                except Exception as exc:
                    failures += 1
                    print(f"ERROR saving {day_str}: {exc}")

                # Avoid sending requests too rapidly.
                time.sleep(1)

            print(f"Finished: {success} saved, {failures} skipped/failed")

            if failures:
                raise RuntimeError(
                    f"Recovery sync incomplete: {failures} dates"
                )

        finally:
            garmin.client.dump(str(token_dir))
            save_tokens(db, token_dir)


if __name__ == "__main__":
    sync_recovery()
