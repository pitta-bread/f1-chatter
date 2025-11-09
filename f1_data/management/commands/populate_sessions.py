from datetime import datetime, timedelta, timezone
from pathlib import Path

import fastf1
import pandas as pd
from django.core.management.base import BaseCommand

from f1_data.models import Session


class Command(BaseCommand):
    help = "Populate sessions from FastF1. By default fetches all sessions for the current year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            help="Year to fetch sessions for (default: current year)",
        )

    def handle(self, *args, **options):
        # Enable FastF1 cache for performance
        cache_dir = Path(".fastf1_cache")
        cache_dir.mkdir(exist_ok=True)
        fastf1.Cache.enable_cache(str(cache_dir))

        # Determine target year (default to current year)
        target_year = options.get("year")
        if target_year is None:
            target_year = datetime.now().year

        self.stdout.write(
            self.style.SUCCESS(f"Fetching sessions for year {target_year}...")
        )

        total_sessions = 0
        created_count = 0
        updated_count = 0
        error_count = 0
        skipped_count = 0

        try:
            # Get event schedule - this is much faster than loading individual sessions
            self.stdout.write("Fetching event schedule...")
            schedule = fastf1.get_event_schedule(target_year)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch event schedule: {e}"))
            return

        # Map FastF1 session column names to our session types
        # FastF1 schedule has columns like Session1, Session2, etc. with dates in Session1Date, etc.
        session_column_map = {
            "FP1": ("Session1", "Session1Date"),
            "FP2": ("Session2", "Session2Date"),
            "FP3": ("Session3", "Session3Date"),
            "Qualifying": ("Session4", "Session4Date"),
            "Sprint Qualifying": ("Session5", "Session5Date"),
            "Sprint": ("Session6", "Session6Date"),
            "Race": ("Session7", "Session7Date"),
        }

        # Duration estimates for each session type
        duration_map = {
            "FP1": timedelta(hours=1),
            "FP2": timedelta(hours=1),
            "FP3": timedelta(hours=1),
            "Qualifying": timedelta(hours=1),
            "Sprint": timedelta(hours=1),
            "Sprint Qualifying": timedelta(minutes=45),
            "Race": timedelta(hours=2),
        }

        # Process each event in the schedule
        for _, event_row in schedule.iterrows():
            round_number = int(event_row["RoundNumber"])
            event_name = event_row.get("EventName", "Unknown Event")
            location = event_row.get("Location", "Unknown Location")
            country = event_row.get("Country", "Unknown Country")

            # Process each session type
            for session_type, (session_col, date_col) in session_column_map.items():
                try:
                    # Check if this session exists for this event
                    session_name = event_row.get(session_col)
                    session_date = event_row.get(date_col)

                    if pd.isna(session_name) or pd.isna(session_date):
                        # Session doesn't exist for this event (e.g., no Sprint weekend)
                        skipped_count += 1
                        continue

                    # Convert pandas Timestamp to timezone-aware datetime
                    if isinstance(session_date, pd.Timestamp):
                        # FastF1 dates are typically in UTC
                        if session_date.tzinfo is None:
                            start_time = session_date.replace(tzinfo=timezone.utc)
                        else:
                            start_time = session_date
                    else:
                        # Fallback for other date types
                        if isinstance(session_date, datetime):
                            if session_date.tzinfo is None:
                                start_time = session_date.replace(tzinfo=timezone.utc)
                            else:
                                start_time = session_date
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Skipping {target_year} Round {round_number} {session_type} - invalid date type"
                                )
                            )
                            skipped_count += 1
                            continue

                    # Estimate end time based on session type
                    duration = duration_map.get(session_type, timedelta(hours=1))
                    end_time = start_time + duration

                    # Generate unique session_id
                    session_id = f"{target_year}_{round_number}_{session_type}"

                    # Create or update session
                    session_obj, created = Session.objects.update_or_create(
                        session_id=session_id,
                        defaults={
                            "year": target_year,
                            "round_number": round_number,
                            "session_type": session_type,
                            "start_time": start_time,
                            "end_time": end_time,
                            "event_name": event_name,
                            "location": location,
                            "country": country,
                        },
                    )

                    if created:
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"Created: {session_id} - {event_name}")
                        )
                    else:
                        updated_count += 1
                        self.stdout.write(f"Updated: {session_id} - {event_name}")

                    total_sessions += 1

                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error processing {target_year} Round {round_number} {session_type}: {e}"
                        )
                    )
                    continue

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS(f"Summary for year {target_year}:"))
        self.stdout.write(
            self.style.SUCCESS(f"  Total sessions processed: {total_sessions}")
        )
        self.stdout.write(self.style.SUCCESS(f"  Created: {created_count}"))
        self.stdout.write(self.style.SUCCESS(f"  Updated: {updated_count}"))
        if skipped_count > 0:
            self.stdout.write(f"  Skipped (not found): {skipped_count}")
        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"  Errors: {error_count}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
