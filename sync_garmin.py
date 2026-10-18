
import os
import io
import base64
import zipfile
import tempfile
from pathlib import Path
from datetime import date, timedelta

from garminconnect import Garmin
from supabase import create_client
from cryptography.fernet import Fernet


def load_saved_tokens(supabase):
    result = (
        supabase.table("garmin_auth_tokens")
        .select("token_data")
        .eq("id", 1)
        .execute()
    )

    if not result.data:
        return None

    cipher = Fernet(os.environ["TOKEN_ENCRYPTION_KEY"].encode())
    encrypted = result.data[0]["token_data"].encode()
    return cipher.decrypt(encrypted)


def save_tokens(supabase, token_dir):
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in token_dir.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(token_dir))

    cipher = Fernet(os.environ["TOKEN_ENCRYPTION_KEY"].encode())
    encrypted = cipher.encrypt(buffer.getvalue()).decode()

    supabase.table("garmin_auth_tokens").upsert({
        "id": 1,
        "token_data": encrypted,
        "updated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
    }).execute()

    print("Encrypted Garmin tokens saved")

def sync_activities():
    # Connect to Supabase
    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

    # Restore Garmin authentication tokens
    saved_tokens = load_saved_tokens(supabase)

if saved_tokens is not None:
    archive_bytes = saved_tokens
    print("Using encrypted tokens from Supabase")
else:
    archive_bytes = base64.b64decode(os.environ["GARMIN_TOKENS"])
    print("Using initial tokens from GitHub Secrets")

    with tempfile.TemporaryDirectory() as temp_dir:
        token_dir = Path(temp_dir) / "tokens"
        token_dir.mkdir()


        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for item in archive.infolist():
                target = (token_dir / item.filename).resolve()
                if not target.is_relative_to(token_dir.resolve()):
                    raise ValueError("Unsafe archive path")
            archive.extractall(token_dir)

        garmin = Garmin()
        garmin.login(str(token_dir))
        print("Garmin connected successfully")

        # Import the last 30 days of activities
        today = date.today()
        start = today - timedelta(days=30)

        activities = garmin.get_activities_by_date(
            start.isoformat(),
            today.isoformat()
        )

        print(f"Found {len(activities)} activities")

        for activity in activities:
            activity_id = activity.get("activityId")

            if activity_id is None:
                print("Skipping activity without ID")
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

            supabase.table("garmin_activities").upsert(
                row,
                on_conflict="activity_id"
            ).execute()

            print(f"Saved activity {activity_id}")

        print("Synchronization completed")
        garmin.garth.dump(str(token_dir))
        save_tokens(supabase, token_dir)


if __name__ == "__main__":
    sync_activities()
