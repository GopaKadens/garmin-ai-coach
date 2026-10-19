import json
import os
from pathlib import Path

from supabase import create_client


def main():
    profile_path = Path(__file__).with_name("coach_profile.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    db.table("coach_memory").upsert({
        "id": profile["id"],
        "version": profile["version"],
        "content": json.dumps(profile, ensure_ascii=False, indent=2),
    }, on_conflict="id").execute()
    saved = db.table("coach_memory").select("id,version").eq("id", profile["id"]).single().execute()
    assert saved.data["version"] == profile["version"]
    print(f"Profile uploaded successfully: {saved.data['id']} v{saved.data['version']}")


if __name__ == "__main__":
    main()
