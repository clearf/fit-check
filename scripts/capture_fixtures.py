"""
Capture real Garmin API responses and save them as test fixtures.

Run this script on a machine with a valid Garmin session:

    python scripts/capture_fixtures.py [--activity-id ACTIVITY_ID]

If no activity ID is given, the most recent running activity is used.

Outputs (overwrite tests/fixtures/):
    garmin_activity_summary.json    — from get_activity_evaluation()
    garmin_activity_list_item.json  — one item from get_activities() list
    garmin_activity_splits.json     — from get_activity_splits()
    garmin_sleep.json               — from get_sleep_data()
    garmin_hrv.json                 — from get_hrv_data()

These fixtures are used by the normalizer tests to ensure the normalizer
handles real API response schemas, not hand-crafted guesses.
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fitness.garmin.auth import GarminAuth


FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def _save(name: str, data: object) -> None:
    path = FIXTURES_DIR / name
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"  ✅ Saved {path.relative_to(Path.cwd())} ({path.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture real Garmin API fixtures")
    parser.add_argument("--activity-id", help="Garmin activity ID (default: most recent run)")
    args = parser.parse_args()

    print("🔑 Connecting to Garmin...")
    auth = GarminAuth()
    if not auth.has_session():
        print("❌ No Garmin session found. Run: python -m fitness setup")
        sys.exit(1)

    api = auth.build_client()
    print(f"   Connected as: {api.display_name}\n")

    # ── Activity ID ────────────────────────────────────────────────────────────
    activity_id = args.activity_id
    if not activity_id:
        print("🔍 Fetching most recent running activity...")
        activities = api.get_activities(0, 10)
        runs = [a for a in activities if a.get("activityType", {}).get("typeKey") == "running"]
        if not runs:
            print("❌ No running activities found in last 10 activities.")
            sys.exit(1)
        activity_id = str(runs[0]["activityId"])
        print(f"   Using activity: {runs[0].get('activityName', 'Unknown')} ({activity_id})\n")

        # Save one list item as a separate fixture (different schema from evaluation)
        print("💾 Saving fixtures...")
        _save("garmin_activity_list_item.json", runs[0])
    else:
        print(f"   Using provided activity ID: {activity_id}\n")
        print("💾 Saving fixtures...")

    # ── Activity evaluation (detail) ───────────────────────────────────────────
    print("   Fetching get_activity_evaluation()...")
    evaluation = api.get_activity_evaluation(activity_id)
    _save("garmin_activity_summary.json", evaluation)

    # ── Activity splits ────────────────────────────────────────────────────────
    print("   Fetching get_activity_splits()...")
    splits = api.get_activity_splits(activity_id)
    _save("garmin_activity_splits.json", splits)

    # ── Sleep data ─────────────────────────────────────────────────────────────
    # Use activity date for sleep lookup
    start_time_str = evaluation.get("startTimeGMT") or evaluation.get("startTimeLocal", "")
    try:
        activity_date = datetime.strptime(start_time_str[:10], "%Y-%m-%d").date()
    except ValueError:
        activity_date = datetime.now().date() - timedelta(days=1)

    print(f"   Fetching get_sleep_data() for {activity_date}...")
    sleep = api.get_sleep_data(str(activity_date))
    _save("garmin_sleep.json", sleep)

    # ── HRV data ───────────────────────────────────────────────────────────────
    print(f"   Fetching get_hrv_data() for {activity_date}...")
    hrv = api.get_hrv_data(str(activity_date))
    _save("garmin_hrv.json", hrv)

    print(f"\n✅ All fixtures saved to tests/fixtures/")
    print("\n⚠️  Check the saved files for any PII before committing.")
    print("   The fixtures contain real activity data — review before git add.\n")

    # Print key fields so user can verify the data looks right
    print("📊 Summary:")
    print(f"   Activity:    {evaluation.get('activityName', 'N/A')}")
    print(f"   Date (GMT):  {evaluation.get('startTimeGMT', 'N/A')}")
    print(f"   Date (Local):{evaluation.get('startTimeLocal', 'N/A')}")
    print(f"   Distance:    {evaluation.get('distance', 'N/A')} m")
    print(f"   Duration:    {evaluation.get('duration', 'N/A')} s")
    print(f"   Splits:      {len(splits.get('lapDTOs', splits if isinstance(splits, list) else []))} laps")


if __name__ == "__main__":
    main()
