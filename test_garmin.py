
import os
from datetime import date, timedelta
from garminconnect import Garmin

username = os.environ["GARMIN_EMAIL"]
password = os.environ["GARMIN_PASSWORD"]

print("Connecting to Garmin Connect...")

client = Garmin(username, password)
client.login()

print("Connection successful!")

today = date.today()
start = today - timedelta(days=7)

activities = client.get_activities_by_date(
    start.isoformat(),
    today.isoformat()
)

print(f"Activities found: {len(activities)}")

for activity in activities:
    print({
        "date": activity.get("startTimeLocal"),
        "type": activity.get("activityType", {}).get("typeKey"),
        "distance_km": round(
            (activity.get("distance") or 0) / 1000, 2
        ),
        "duration_min": round(
            (activity.get("duration") or 0) / 60, 1
        ),
        "elevation_gain_m": activity.get("elevationGain"),
        "average_hr": activity.get("averageHR"),
    })

print("Test completed.")
