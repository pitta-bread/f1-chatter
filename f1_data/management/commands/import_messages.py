import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from f1_data.models import Message, Session

MAX_RUNTIME_SECONDS = 120
DEFAULT_CHANNEL_ID = "1101802452224856174"
DEFAULT_EXPORT_DIR = Path("tmp_transcripts_from_discord")
CLI_PATH = Path("discord_msg_fetcher/DiscordChatExporter.Cli")


class Command(BaseCommand):
    help = (
        "Fetch Discord radio messages via DiscordChatExporter and ingest them into "
        "the database. Supports full-session imports or bounded time window updates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--session-id",
            required=True,
            help=(
                "Session identifier (matches `Session.session_id`) to associate "
                "messages with."
            ),
        )
        parser.add_argument(
            "--channel-id",
            default=DEFAULT_CHANNEL_ID,
            help="Discord channel ID to export messages from.",
        )
        parser.add_argument(
            "--start",
            type=str,
            help=(
                "Optional ISO8601 timestamp. Only messages at or after this time are "
                "exported/imported."
            ),
        )
        parser.add_argument(
            "--end",
            type=str,
            help=(
                "Optional ISO8601 timestamp. Only messages at or before this time are "
                "exported/imported."
            ),
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=str(DEFAULT_EXPORT_DIR),
            help=(
                "Directory where the exported JSON file will be written "
                "(default: tmp_transcripts_from_discord)."
            ),
        )
        parser.add_argument(
            "--keep-file",
            action="store_true",
            help=(
                "If provided, keep the exported JSON file instead of deleting it after "
                "import."
            ),
        )

    def handle(self, *args, **options):
        start_time = time.perf_counter()
        session_id = options["session_id"]
        channel_id = options["channel_id"]
        output_dir = Path(options["output_dir"])
        keep_file = options["keep_file"]
        start_override, end_override = self._parse_time_filters(
            options["start"], options["end"]
        )

        try:
            session = Session.objects.get(session_id=session_id)
        except Session.DoesNotExist as exc:
            raise CommandError(
                f"Session with id '{session_id}' does not exist."
            ) from exc

        start_filter = start_override or session.start_time
        end_filter = end_override or session.end_time

        if start_filter and end_filter and start_filter > end_filter:
            raise CommandError(
                "Resolved time window has --start after --end. Check session timing."
            )

        export_path = self._export_messages(
            channel_id=channel_id,
            output_dir=output_dir,
            session_id=session_id,
            start_filter=start_filter,
            end_filter=end_filter,
            start_time=start_time,
        )

        messages_data = self._load_json(export_path)
        created = 0
        updated = 0
        skipped = 0
        missing_content = 0
        missing_timestamp = 0

        for payload in self._iter_messages(messages_data):
            self._enforce_runtime(start_time)

            content = payload.get("content")
            timestamp_raw = payload.get("timestamp")
            if not content:
                missing_content += 1
                continue
            if not timestamp_raw:
                missing_timestamp += 1
                continue

            posted_at = parse_datetime(timestamp_raw)
            edited_at_raw = payload.get("timestampEdited")
            edited_at = parse_datetime(edited_at_raw) if edited_at_raw else None

            if posted_at is None:
                self.stderr.write(
                    self.style.WARNING(
                        (
                            f"Skipping message {payload.get('id')} "
                            "with unparsable timestamp"
                        )
                    )
                )
                skipped += 1
                continue

            if start_filter and posted_at < start_filter:
                skipped += 1
                continue
            if end_filter and posted_at > end_filter:
                skipped += 1
                continue

            driver, message_text = self._normalise_message(content)
            author_info = payload.get("author", {})

            defaults = {
                "session": session,
                "posted_at": posted_at,
                "edited_at": edited_at,
                "driver": driver,
                "author_id": author_info.get("id"),
                "author_name": author_info.get("name"),
                "author_nickname": author_info.get("nickname"),
                "raw_content": content,
                "message_text": message_text,
            }

            obj, created_flag = Message.objects.update_or_create(
                discord_id=str(payload.get("id")),
                defaults=defaults,
            )

            if created_flag:
                created += 1
            else:
                updated += 1

        self._print_summary(
            session_id=session_id,
            total=len(messages_data),
            created=created,
            updated=updated,
            skipped=skipped,
            missing_content=missing_content,
            missing_timestamp=missing_timestamp,
            elapsed=time.perf_counter() - start_time,
        )

        if not keep_file:
            try:
                export_path.unlink()
            except OSError as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"Failed to remove temporary export file {export_path}: {exc}"
                    )
                )

    def _parse_time_filters(
        self, start: str | None, end: str | None
    ) -> tuple[datetime | None, datetime | None]:
        start_dt = parse_datetime(start) if start else None
        end_dt = parse_datetime(end) if end else None

        if start and start_dt is None:
            raise CommandError(f"Unable to parse --start timestamp: {start}")
        if end and end_dt is None:
            raise CommandError(f"Unable to parse --end timestamp: {end}")
        if start_dt and end_dt and start_dt > end_dt:
            raise CommandError("--start must be before --end.")

        return start_dt, end_dt

    def _export_messages(
        self,
        *,
        channel_id: str,
        output_dir: Path,
        session_id: str,
        start_filter: datetime | None,
        end_filter: datetime | None,
        start_time: float,
    ) -> Path:
        token = os.getenv("DISCORD_OAUTH_TOKEN")
        if not token:
            raise CommandError(
                (
                    "Environment variable DISCORD_OAUTH_TOKEN is required to export "
                    "messages."
                )
            )

        if not CLI_PATH.exists():
            raise CommandError(
                f"DiscordChatExporter CLI not found at {CLI_PATH}. "
                "Run start.sh or install the CLI before using this command."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_suffix = int(time.time())
        export_path = output_dir / f"{session_id}_{timestamp_suffix}.json"

        cmd = [
            str(CLI_PATH),
            "export",
            "-t",
            token,
            "-c",
            channel_id,
            "-f",
            "Json",
            "-o",
            str(export_path),
        ]

        if start_filter:
            cmd.extend(["--after", self._format_cli_timestamp(start_filter)])
        if end_filter:
            cmd.extend(["--before", self._format_cli_timestamp(end_filter)])

        self.stdout.write("📡 Exporting messages from Discord...")
        remaining_time = MAX_RUNTIME_SECONDS - (time.perf_counter() - start_time)
        if remaining_time <= 0:
            raise CommandError(
                "Import exceeded maximum runtime before exporting messages began."
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=remaining_time,
            )
        except subprocess.TimeoutExpired:
            raise CommandError(
                "DiscordChatExporter CLI exceeded the 120 second runtime limit."
            ) from None
        except OSError as exc:
            raise CommandError(
                f"Failed to invoke DiscordChatExporter CLI: {exc}"
            ) from exc

        if result.returncode != 0:
            error_message = result.stderr.strip() or result.stdout.strip()
            raise CommandError(
                (
                    "DiscordChatExporter CLI failed with exit code "
                    f"{result.returncode}: {error_message}"
                )
            )

        if not export_path.exists():
            raise CommandError(
                (
                    f"Expected export file {export_path} was not created by "
                    "DiscordChatExporter CLI."
                )
            )

        self._enforce_runtime(start_time)
        return export_path

    def _load_json(self, path: Path) -> Iterable[Dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Failed to decode JSON: {exc}") from exc

        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise CommandError("JSON payload missing 'messages' array.")
        return messages

    def _iter_messages(
        self, messages: Iterable[Dict[str, Any]]
    ) -> Iterable[Dict[str, Any]]:
        for message in messages:
            yield message

    def _normalise_message(self, content: str) -> tuple[str | None, str]:
        driver = None
        message_text = content.strip()

        # Extract driver name between first pair of backticks, e.g. `Leclerc`
        left_tick = content.find("`")
        if left_tick != -1:
            right_tick = content.find("`", left_tick + 1)
            if right_tick != -1:
                driver = content[left_tick + 1 : right_tick].strip() or None

        # Remove leading emoji markup like ":studio_microphone:"
        if message_text.startswith(":"):
            parts = message_text.split(" ", 1)
            if len(parts) == 2:
                message_text = parts[1]

        return driver, message_text.strip()

    def _enforce_runtime(self, start_time: float) -> None:
        elapsed = time.perf_counter() - start_time
        if elapsed > MAX_RUNTIME_SECONDS:
            raise CommandError(
                f"Import exceeded maximum runtime of {MAX_RUNTIME_SECONDS} seconds. "
                "Consider narrowing the time window or splitting the data file."
            )

    def _format_cli_timestamp(self, dt: datetime) -> str:
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    def _print_summary(
        self,
        *,
        session_id: str,
        total: int,
        created: int,
        updated: int,
        skipped: int,
        missing_content: int,
        missing_timestamp: int,
        elapsed: float,
    ) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(
            self.style.SUCCESS(f"Import summary for session {session_id}:")
        )
        self.stdout.write(self.style.SUCCESS(f"  Messages processed: {total}"))
        self.stdout.write(self.style.SUCCESS(f"  Created: {created}"))
        self.stdout.write(self.style.SUCCESS(f"  Updated: {updated}"))
        self.stdout.write(f"  Skipped (filters/time): {skipped}")
        if missing_content:
            self.stdout.write(
                self.style.WARNING(f"  Skipped (missing content): {missing_content}")
            )
        if missing_timestamp:
            self.stdout.write(
                self.style.WARNING(
                    f"  Skipped (missing timestamp): {missing_timestamp}"
                )
            )
        self.stdout.write(self.style.SUCCESS(f"  Runtime: {elapsed:.2f}s"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
