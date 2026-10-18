
import os
import io
import base64
import zipfile
import tempfile
from pathlib import Path
from datetime import date, timedelta

from garminconnect import Garmin
from supabase import create_client


def sync_activities():
    # Connect to Supabase
    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

    # Restore Garmin authentication tokens
    encoded = os.environ["GARMIN_TOKENS"]

    with tempfile.TemporaryDirectory() as temp_dir:
        token_dir = Path(temp_dir) / "tokens"
        token_dir.mkdir()

        archive_bytes = base64.b64decode(encoded)

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for item in archive.infolist():
                target = (token_dir / item.filename).resolve()
                if not target.is_relative_to(token_dir.resolve()):
                    raise ValueError("Unsafe archive path")
            archive.extractall(token_dir)

        garmin = Garmin()
        garmin.login(str(token_dir))
        garmin.garth.dump(str(token_dir))
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


if __name__ == "__main__":
    sync_activities()
