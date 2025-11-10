# API: Current State & Fetch Session Messages

## `GET /api/current_state`

- **Query parameters**
  - `timestamp` (required): ISO 8601 string. Represents the end of the 30-second window to inspect.
- **Window calculation**
  - `window_start = max(timestamp - 30s, session.start_time)`
  - `window_end = min(timestamp, session.end_time)`
  - The session chosen is the one where `session.start_time <= timestamp <= session.end_time`. If multiple sessions overlap, the earliest start time is used.
- **Response**
  - `session_id`: string
  - `window_start`: ISO 8601 string
  - `window_end`: ISO 8601 string
  - `highlight_message`: object with:
    - `discord_id`
    - `posted_at` (ISO 8601 string)
    - `driver` (nullable string)
    - `author_name` (nullable string)
    - `message_text`
    - `raw_content`
  - When no messages exist within the window, `highlight_message` is `null`.
- **Errors**
  - `400`: missing or invalid `timestamp` (non-parseable or non-timezone-aware).
  - `404`: no session spans the provided `timestamp`.

## `POST /api/fetch_session_messages`

- **Query parameters**
  - `session_id` (required): string matching `Session.session_id`.
- **Behaviour**
  - Invokes `import_messages` via `call_command`, targeting the full session (no explicit time filters).
  - Captures standard output and returns it in the response for observability.
- **Response**
  - `session_id`: string
  - `command_ran`: string (always `"import_messages"`)
  - `stdout`: string output from the management command
- **Errors**
  - `400`: missing `session_id`.
  - `404`: `Session` does not exist.
  - `500`: management command raises `CommandError` or any other runtime exception; response includes `error` message.
