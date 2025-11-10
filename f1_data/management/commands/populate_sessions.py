from datetime import datetime, timedelta, timezone
from pathlib import Path

import fastf1
import pandas as pd
from django.core.management.base import BaseCommand

from f1_data.models import Session


class Command(BaseCommand):
    help = (
        "Populate sessions from FastF1 using actual session data. Only processes "
        "sessions that have occurred (past or currently live), not future events."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            help="Year to fetch sessions for (default: current year)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help=(
                "Clear all sessions for the target year from the database before "
                "populating. This ensures clean data and removes sessions that no "
                "longer exist in FastF1."
            ),
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

        clear_year = options.get("clear", False)

        self.stdout.write(
            self.style.SUCCESS(f"Fetching sessions for year {target_year}...")
        )

        # Clear existing sessions for this year if requested
        if clear_year:
            deleted_count = Session.objects.filter(year=target_year).count()
            Session.objects.filter(year=target_year).delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Cleared {deleted_count} existing sessions for year {target_year}"
                )
            )

        total_sessions = 0
        created_count = 0
        updated_count = 0
        error_count = 0
        skipped_count = 0

        try:
            # Get event schedule
            self.stdout.write("Fetching event schedule...")
            schedule = fastf1.get_event_schedule(target_year)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch event schedule: {e}"))
            return

        # Session identifiers to try (in order of preference)
        # Format: (identifier, expected_session_type)
        session_identifiers = [
            ("FP1", "Practice 1"),
            ("FP2", "Practice 2"),
            ("FP3", "Practice 3"),
            ("Q", "Qualifying"),
            ("SS", "Sprint Shootout"),  # Sprint Qualifying
            ("SQ", "Sprint Shootout"),  # Alternative name
            ("S", "Sprint"),
            ("SP", "Sprint"),  # Alternative
            ("R", "Race"),
        ]

        now_utc = datetime.now(timezone.utc)

        # Process each event in the schedule
        for _, event_row in schedule.iterrows():
            round_number = int(event_row["RoundNumber"])
            event_name = event_row.get("EventName", "Unknown Event")
            location = event_row.get("Location", "Unknown Location")
            country = event_row.get("Country", "Unknown Country")

            # Check if event is in the past or live (not future)
            # Use the event date or any session date to determine this
            event_date = event_row.get("EventDate")
            if event_date is not None and not pd.isna(event_date):
                if isinstance(event_date, pd.Timestamp):
                    if event_date.tzinfo is None:
                        event_date_utc = event_date.replace(tzinfo=timezone.utc)
                    else:
                        event_date_utc = event_date.astimezone(timezone.utc)
                    # Skip future events (allow a small buffer for live events)
                    if event_date_utc > now_utc + timedelta(hours=24):
                        self.stdout.write(
                            f"Skipping future event: {event_name} "
                            f"(Round {round_number})"
                        )
                        skipped_count += 1
                        continue

            try:
                event = fastf1.get_event(target_year, round_number)
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"Failed to get event object for {event_name}: {e}"
                    )
                )
                error_count += 1
                continue

            # Try to get each session type
            for session_ident, expected_type in session_identifiers:
                try:
                    # Try to get the session
                    session = event.get_session(session_ident)
                except (ValueError, AttributeError):
                    # Session doesn't exist for this event
                    continue
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Error getting session {session_ident} "
                            f"for {event_name}: {e}"
                        )
                    )
                    continue

                try:
                    # Load session data (laps for timing, minimal telemetry for t0_date)
                    session.load(laps=True, telemetry=False, weather=False)

                    # Get actual session type from session object
                    session_type_name = session.name
                    if not session_type_name:
                        # Fallback to session_info Name
                        session_type_name = session.session_info.get(
                            "Name", expected_type
                        )

                    # Map FastF1 session names to our session types
                    session_type_map = {
                        "Practice 1": "FP1",
                        "Practice 2": "FP2",
                        "Practice 3": "FP3",
                        "Qualifying": "Qualifying",
                        "Sprint Shootout": "Sprint Qualifying",
                        "Sprint Qualifying": "Sprint Qualifying",
                        "Sprint": "Sprint",
                        "Race": "Race",
                    }
                    session_type = session_type_map.get(
                        session_type_name, session_type_name
                    )

                    # Get start time from session_info
                    start_date = session.session_info.get("StartDate")
                    if start_date is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"No StartDate for {event_name} {session_type_name}"
                            )
                        )
                        skipped_count += 1
                        continue

                    # Convert to timezone-aware UTC datetime
                    if isinstance(start_date, datetime):
                        if start_date.tzinfo is None:
                            # Use GmtOffset from session_info if available
                            gmt_offset = session.session_info.get("GmtOffset")
                            if gmt_offset:
                                # Convert from local time to UTC
                                # GmtOffset is a timedelta, convert to hours
                                offset_hours = gmt_offset.total_seconds() / 3600
                                start_time = start_date.replace(
                                    tzinfo=timezone(timedelta(hours=offset_hours))
                                ).astimezone(timezone.utc)
                            else:
                                # Assume UTC if no offset
                                start_time = start_date.replace(tzinfo=timezone.utc)
                        else:
                            start_time = start_date.astimezone(timezone.utc)
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Invalid StartDate type for {event_name} "
                                f"{session_type_name}"
                            )
                        )
                        skipped_count += 1
                        continue

                    # Check if session is in the future
                    if start_time > now_utc:
                        # Skip future sessions
                        continue

                    # Get end time - try to use actual lap data first
                    end_time = None

                    # Try to get accurate end time from lap data
                    if not session.laps.empty:
                        sector3_times = session.laps["Sector3SessionTime"].dropna()
                        if not sector3_times.empty:
                            last_sector3 = sector3_times.max()
                            # Load minimal telemetry to get t0_date
                            try:
                                session.load(telemetry=True, weather=False)
                                # Get t0_date from telemetry
                                if session.car_data:
                                    first_driver = list(session.car_data.keys())[0]
                                    car_data = session.car_data[first_driver]
                                    if (
                                        not car_data.empty
                                        and "Date" in car_data.columns
                                        and "SessionTime" in car_data.columns
                                    ):
                                        first_date = car_data["Date"].iloc[0]
                                        first_session_time = car_data[
                                            "SessionTime"
                                        ].iloc[0]
                                        t0_date = first_date - first_session_time
                                        end_time = t0_date + last_sector3
                                        # Ensure timezone-aware
                                        if end_time.tzinfo is None:
                                            end_time = end_time.replace(
                                                tzinfo=timezone.utc
                                            )
                            except Exception as e:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"Could not load telemetry for accurate "
                                        f"end time ({event_name} {session_type_name}): "
                                        f"{e}. Using session_info EndDate."
                                    )
                                )

                    # Fallback to session_info EndDate
                    if end_time is None:
                        end_date = session.session_info.get("EndDate")
                        if end_date is None:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"No EndDate for {event_name} {session_type_name}"
                                )
                            )
                            skipped_count += 1
                            continue

                        # Convert to timezone-aware UTC datetime
                        if isinstance(end_date, datetime):
                            if end_date.tzinfo is None:
                                # Use GmtOffset from session_info if available
                                gmt_offset = session.session_info.get("GmtOffset")
                                if gmt_offset:
                                    # GmtOffset is a timedelta, convert to hours
                                    offset_hours = gmt_offset.total_seconds() / 3600
                                    end_time = end_date.replace(
                                        tzinfo=timezone(timedelta(hours=offset_hours))
                                    ).astimezone(timezone.utc)
                                else:
                                    end_time = end_date.replace(tzinfo=timezone.utc)
                            else:
                                end_time = end_date.astimezone(timezone.utc)
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Invalid EndDate type for {event_name} "
                                    f"{session_type_name}"
                                )
                            )
                            skipped_count += 1
                            continue

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
                            self.style.SUCCESS(
                                f"Created: {session_id} - {event_name} "
                                f"({start_time.isoformat()} to {end_time.isoformat()})"
                            )
                        )
                    else:
                        updated_count += 1
                        self.stdout.write(
                            f"Updated: {session_id} - {event_name} "
                            f"({start_time.isoformat()} to {end_time.isoformat()})"
                        )

                    total_sessions += 1

                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error processing {target_year} Round {round_number} "
                            f"{session_ident} ({event_name}): {e}"
                        )
                    )
                    import traceback

                    self.stdout.write(traceback.format_exc())
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
            self.stdout.write(f"  Skipped: {skipped_count}")
        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"  Errors: {error_count}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
