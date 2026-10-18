
import os
import io
import base64
import zipfile
import tempfile
from pathlib import Path
from datetime import date, timedelta

from garminconnect import Garmin

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

    print("Loading Garmin tokens...")

    client = Garmin()
    client.login(str(token_dir))

    print("Garmin authentication successful!")

    today = date.today()
    start = today - timedelta(days=7)

    activities = client.get_activities_by_date(
        start.isoformat(),
        today.isoformat()
    )

    print(f"Activities found: {len(activities)}")

    for activity in activities:
        print(
            activity.get("startTimeLocal"),
            activity.get("activityName"),
            round((activity.get("distance") or 0) / 1000, 2),
            "km"
        )

    print("Cloud test completed successfully.")
