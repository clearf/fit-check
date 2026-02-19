"""
Interactive setup wizard for the fitness app.

Prompts for Garmin credentials once, exchanges them for OAuth tokens,
and saves the tokens to ~/.fitness/garmin_session/ with owner-only
permissions (0700 dir / 0600 files).

After setup, the main app and all scripts connect to Garmin using the
saved tokens — credentials are never stored on disk.

Usage:
    python -m fitness setup
    python -m fitness.scripts.setup   (direct invocation)

Re-run any time the session expires (typically every few weeks/months).
"""
import getpass
import sys

from fitness.garmin.auth import GarminAuth, TOKENS_DIR_DEFAULT


def run_setup() -> None:
    auth = GarminAuth()

    print("\n🏃 Fitness App — Garmin Setup\n")
    print("Your credentials will NOT be saved to disk.")
    print(f"OAuth tokens will be stored in: {auth._tokens_dir}\n")

    if auth.has_session():
        print("⚠️  An existing session was found.")
        overwrite = input("Overwrite it with a new login? [y/N] ").strip().lower()
        if overwrite != "y":
            print("Setup cancelled. Existing session unchanged.")
            sys.exit(0)

    email = input("Garmin Connect email: ").strip()
    if not email:
        print("Error: email cannot be empty.")
        sys.exit(1)

    password = getpass.getpass("Garmin Connect password: ")
    if not password:
        print("Error: password cannot be empty.")
        sys.exit(1)

    print("\nAuthenticating with Garmin Connect...")
    try:
        auth.authenticate_and_save(email, password)
    except Exception as exc:
        print(f"\n❌ Authentication failed: {exc}")
        print("Check your email and password and try again.")
        sys.exit(1)

    print(f"\n✅ Tokens saved to {auth._tokens_dir}")
    print(f"   Permissions: dir={oct(auth._tokens_dir.stat().st_mode)[-3:]}")
    print("\nYou won't need to enter your password again until the session expires.")
    print("If it does expire, just re-run:  python -m fitness setup\n")


if __name__ == "__main__":
    run_setup()
