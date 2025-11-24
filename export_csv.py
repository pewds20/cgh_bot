import csv
import datetime
import firebase_admin
from firebase_admin import credentials, db
import os
import sys

def init_firebase():
    # Initialize Firebase Admin SDK
    try:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred, {
            "databaseURL": os.getenv("FIREBASE_DATABASE_URL")
        })
        return True
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        return False

def export_year(year):
    if not init_firebase():
        print("Failed to initialize Firebase. Please check your credentials.")
        return

    try:
        ref = db.reference("listings")
        data = ref.get() or {}

        if not data:
            print("No listings found in the database.")
            return

        filename = f"redistribution_{year}.csv"

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "listing_id", "item_name", "status", "poster_id", "claimed_by",
                "created_at", "claimed_at", "quantity", "remaining", "location", "expiry"
            ])

            exported_count = 0
            for lid, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                    
                created = entry.get("timestamp")
                if not created:
                    continue

                try:
                    # Handle both ISO format and timestamp
                    if isinstance(created, (int, float)):
                        dt = datetime.datetime.fromtimestamp(created)
                    else:
                        dt = datetime.datetime.fromisoformat(created)
                    
                    if dt.year == year:
                        writer.writerow([
                            lid,
                            entry.get("item", ""),
                            entry.get("status", "unknown"),
                            entry.get("poster_id", ""),
                            entry.get("claimed_by", ""),
                            dt.isoformat(),
                            datetime.datetime.fromtimestamp(entry.get("claimed_at", 0)).isoformat() if entry.get("claimed_at") else "",
                            entry.get("qty", 1),
                            entry.get("remaining", 0),
                            entry.get("location", ""),
                            entry.get("expiry", "")
                        ])
                        exported_count += 1
                except Exception as e:
                    print(f"Error processing listing {lid}: {e}")

        print(f"✅ Exported {exported_count} listings to {filename}")

    except Exception as e:
        print(f"Error during export: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            year = int(sys.argv[1])
        except ValueError:
            print("Please provide a valid year as an argument")
            sys.exit(1)
    else:
        year = datetime.datetime.now().year
    
    export_year(year)
