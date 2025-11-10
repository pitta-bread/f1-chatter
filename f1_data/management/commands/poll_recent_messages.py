from datetime import datetime, timedelta, timezone

from django.core.management import CommandError, call_command
from django.core.management.base import BaseCommand

from f1_data.models import Session

POLL_WINDOW_SECONDS = 30


class Command(BaseCommand):
    help = (
        "Fetch Discord messages for the currently live session within the trailing "
        "time window (30 seconds by default). Exits immediately when no session is live."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-seconds",
            type=int,
            default=POLL_WINDOW_SECONDS,
            help=(
                "Size of the trailing window to ingest in seconds "
                "(default: %(default)s seconds)."
            ),
        )
        parser.add_argument(
            "--channel-id",
            type=str,
            help=(
                "Optional override for the Discord channel id. If omitted, the default "
                "from import_messages is used."
            ),
        )

    def handle(self, *args, **options):
        window_seconds: int = options["window_seconds"]
        if window_seconds <= 0:
            raise CommandError("--window-seconds must be greater than zero.")

        now = datetime.now(timezone.utc)
        session_qs = Session.objects.filter(
            start_time__lte=now,
            end_time__gt=now,
        ).order_by("start_time")

        if not session_qs.exists():
            self.stdout.write(
                f"No live session detected at {now.isoformat()}. Poll skipped."
            )
            return

        if session_qs.count() > 1:
            self.stderr.write(
                self.style.WARNING(
                    "Multiple live sessions detected. Using the earliest start time."
                )
            )

        session = session_qs.first()
        assert session is not None  # for type checkers

        window_end = now
        window_start = now - timedelta(seconds=window_seconds)
        if session.start_time > window_start:
            window_start = session.start_time

        start_iso = window_start.isoformat()
        end_iso = window_end.isoformat()

        self.stdout.write(
            self.style.SUCCESS(
                f"Live session {session.session_id} detected. "
                f"Importing messages between {start_iso} and {end_iso}."
            )
        )

        call_kwargs = {
            "session_id": session.session_id,
            "start": start_iso,
            "end": end_iso,
        }
        if options.get("channel_id"):
            call_kwargs["channel_id"] = options["channel_id"]

        call_command("import_messages", **call_kwargs)

