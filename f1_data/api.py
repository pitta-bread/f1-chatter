import logging
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional

from django.core.management import CommandError, call_command
from django.utils.dateparse import parse_datetime
from ninja import ModelSchema, Router, Schema
from ninja.errors import HttpError

from f1_data.models import Message, Session

api = Router()


class SessionSchema(ModelSchema):
    class Meta:
        model = Session
        fields = [
            "session_id",
            "year",
            "round_number",
            "session_type",
            "start_time",
            "end_time",
            "event_name",
            "location",
            "country",
        ]


class HighlightMessageSchema(ModelSchema):
    class Meta:
        model = Message
        fields = [
            "discord_id",
            "posted_at",
            "driver",
            "author_name",
            "message_text",
            "raw_content",
        ]


class CurrentStateResponse(Schema):
    session_id: str
    window_start: datetime
    window_end: datetime
    highlight_message: Optional[HighlightMessageSchema]


class FetchSessionMessagesResponse(Schema):
    session_id: str
    command_ran: str
    stdout: str
    stderr: str


@api.get("/health")
def health_check(request):
    """Basic health check endpoint"""
    return {"status": "ok"}


@api.get("/sessions", response=list[SessionSchema])
def list_sessions(request, year: Optional[int] = None):
    """
    List all sessions in one long list response.
    Optionally filter by year using the ?year=YYYY query parameter.
    Returns all sessions ordered by year (descending), round number, and session type.
    """
    queryset = Session.objects.all()

    # Filter by year if provided
    if year is not None:
        queryset = queryset.filter(year=year)

    # Order by year (descending), round number, and session type
    queryset = queryset.order_by("-year", "round_number", "session_type")

    logging.info("list_sessions: returning %d sessions", queryset.count())

    return list(queryset)


@api.get("/current_state", response=CurrentStateResponse)
def current_state(request, timestamp: str):
    """
    Return the highlight message for the 30-second window ending at the provided
    timestamp.
    """
    parsed_timestamp = parse_datetime(timestamp)
    if parsed_timestamp is None:
        logging.warning("current_state: invalid timestamp '%s'", timestamp)
        raise HttpError(400, "Invalid timestamp format; provide ISO 8601.")
    if parsed_timestamp.tzinfo is None:
        logging.warning("current_state: missing tzinfo for timestamp '%s'", timestamp)
        raise HttpError(400, "Timestamp must include timezone information.")

    parsed_timestamp = parsed_timestamp.astimezone(timezone.utc)

    session = (
        Session.objects.filter(
            start_time__lte=parsed_timestamp,
            end_time__gte=parsed_timestamp,
        )
        .order_by("start_time")
        .first()
    )

    if session is None:
        logging.info(
            "current_state: no session found for timestamp %s", parsed_timestamp
        )
        raise HttpError(404, "No session covers the provided timestamp.")

    window_end = min(parsed_timestamp, session.end_time)
    window_start = max(session.start_time, window_end - timedelta(seconds=30))

    highlight_message = (
        Message.objects.filter(
            session=session,
            posted_at__gte=window_start,
            posted_at__lte=window_end,
        )
        .order_by("-posted_at")
        .first()
    )

    logging.info(
        "current_state: session=%s window_start=%s window_end=%s highlight_found=%s",
        session.session_id,
        window_start.isoformat(),
        window_end.isoformat(),
        bool(highlight_message),
    )

    return {
        "session_id": session.session_id,
        "window_start": window_start,
        "window_end": window_end,
        "highlight_message": highlight_message,
    }


@api.post("/fetch_session_messages", response=FetchSessionMessagesResponse)
def fetch_session_messages(request, session_id: str):
    """
    Trigger a full import of messages for the given session via the import_messages
    command.
    """
    if not session_id:
        logging.warning("fetch_session_messages called without session_id")
        raise HttpError(400, "session_id is required.")

    session_exists = Session.objects.filter(session_id=session_id).exists()
    if not session_exists:
        logging.info("fetch_session_messages: session '%s' not found", session_id)
        raise HttpError(404, f"Session '{session_id}' does not exist.")

    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    try:
        call_command(
            "import_messages",
            session_id=session_id,
            stdout=stdout_buffer,
            stderr=stderr_buffer,
        )
    except CommandError as exc:
        stdout_value = stdout_buffer.getvalue()
        stderr_value = stderr_buffer.getvalue()
        logging.exception(
            "fetch_session_messages: import_messages CommandError for session '%s'. "
            "stdout=%s stderr=%s",
            session_id,
            stdout_value,
            stderr_value,
        )
        raise HttpError(
            500,
            {
                "error": str(exc),
                "stdout": stdout_value,
                "stderr": stderr_value,
            },
        ) from exc
    except SystemExit as exc:
        stdout_value = stdout_buffer.getvalue()
        stderr_value = stderr_buffer.getvalue()
        exit_code = exc.code if isinstance(exc.code, int) else 1
        logging.exception(
            "fetch_session_messages: import_messages exited unexpectedly for session "
            "'%s' with code %s. stdout=%s stderr=%s",
            session_id,
            exit_code,
            stdout_value,
            stderr_value,
        )
        raise HttpError(
            500,
            {
                "error": f"import_messages exited with code {exit_code}",
                "stdout": stdout_value,
                "stderr": stderr_value,
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - unexpected runtime failure
        stdout_value = stdout_buffer.getvalue()
        stderr_value = stderr_buffer.getvalue()
        logging.exception(
            "fetch_session_messages: unexpected error for session '%s'. stdout=%s "
            "stderr=%s",
            session_id,
            stdout_value,
            stderr_value,
        )
        raise HttpError(
            500,
            {
                "error": f"Unexpected error: {exc}",
                "stdout": stdout_value,
                "stderr": stderr_value,
            },
        ) from exc

    output = stdout_buffer.getvalue()
    error_output = stderr_buffer.getvalue()
    logging.info(
        "fetch_session_messages: import_messages completed for session '%s'",
        session_id,
    )

    return {
        "session_id": session_id,
        "command_ran": "import_messages",
        "stdout": output,
        "stderr": error_output,
    }
