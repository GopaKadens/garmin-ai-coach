
import os
import io
import base64
import zipfile
import tempfile
import time
from pathlib import Path
from datetime import date, timedelta, datetime, timezone

from cryptography.fernet import Fernet
from garminconnect import Garmin
from supabase import create_client


def load_tokens(db):
    result = (
        db.table("garmin_auth_tokens")
        .select("token_data")
        .eq("id", 1)
        .execute()
    )

    if result.data:
        print("Using encrypted tokens from Supabase")
        cipher = Fernet(os.environ["TOKEN_ENCRYPTION_KEY"].encode())
        return cipher.decrypt(result.data[0]["token_data"].encode())

    print("Using initial tokens from GitHub Secrets")
    return base64.b64decode(os.environ["GARMIN_TOKENS"])


def save_tokens(db, token_dir):
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in token_dir.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(token_dir))

    cipher = Fernet(os.environ["TOKEN_ENCRYPTION_KEY"].encode())
    encrypted = cipher.encrypt(buffer.getvalue()).decode()

    db.table("garmin_auth_tokens").upsert({
        "id": 1,
        "token_data": encrypted,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    print("Encrypted Garmin tokens saved")


def import_history():
    db = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        token_dir = Path(temp_dir) / "tokens"
        token_dir.mkdir()

        token_bytes = load_tokens(db)

        with zipfile.ZipFile(io.BytesIO(token_bytes)) as archive:
            root = token_dir.resolve()
            for item in archive.infolist():
                target = (token_dir / item.filename).resolve()
                if not target.is_relative_to(root):
                    raise ValueError("Unsafe token archive")
            archive.extractall(token_dir)

        garmin = Garmin()
        garmin.login(str(token_dir))
        print("Garmin connected successfully", flush=True)

        today = date.today()
        start = today - timedelta(days=730)

        saved = 0

        try:
            # Download in 30-day chunks
            chunk_start = start

            while chunk_start <= today:
                chunk_end = min(
                    chunk_start + timedelta(days=29),
                    today
                )

                print(
                    f"Fetching {chunk_start} to {chunk_end}",
                    flush=True
                )

                activities = garmin.get_activities_by_date(
                    chunk_start.isoformat(),
                    chunk_end.isoformat()
                )

                for activity in activities:
                    activity_id = activity.get("activityId")

                    if activity_id is None:
                        continue

                    activity_type = activity.get("activityType") or {}

                    row = {
                        "activity_id": activity_id,
                        "activity_date": activity.get("startTimeGMT"),
                        "activity_name": activity.get("activityName"),
                        "activity_type": activity_type.get("typeKey"),
                        "distance_meters": activity.get("distance"),
                        "duration_seconds": activity.get("duration"),
                        "moving_duration_seconds": activity.get("movingDuration"),
                        "elevation_gain_meters": activity.get("elevationGain"),
                        "average_heart_rate": activity.get("averageHR"),
                        "max_heart_rate": activity.get("maxHR"),
                        "average_speed_mps": activity.get("averageSpeed"),
                        "calories": activity.get("calories"),
                        "raw_data": activity
                    }

                    db.table("garmin_activities").upsert(
                        row,
                        on_conflict="activity_id"
                    ).execute()

                    saved += 1

                print(
                    f"Imported {len(activities)} activities; "
                    f"total processed: {saved}",
                    flush=True
                )

                chunk_start = chunk_end + timedelta(days=1)
                time.sleep(2)

            print(
                f"History import completed: {saved} activities processed",
                flush=True
            )

        finally:
            garmin.client.dump(str(token_dir))
            save_tokens(db, token_dir)


if __name__ == "__main__":
    import_history()
