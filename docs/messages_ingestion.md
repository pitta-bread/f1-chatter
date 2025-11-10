# Message Ingestion Design

## Discord Export Format
- Source: DiscordChatExporter JSON (`messages` array under top-level metadata).
- Each message includes:
  - `id` (Discord snowflake) — unique per message.
  - `timestamp` / `timestampEdited`.
  - `content` (string with prefixed emoji and driver inline code blocks).
  - `author` (id, name, nickname, roles).
  - `attachments`, `embeds`, `reactions`, `inlineEmojis`.
- Command must gracefully skip entries lacking `content` or `timestamp` while logging counts.

## Message Model Summary
- `discord_id` (char, unique) for upserts.
- `session` FK to `Session`.
- `posted_at` (DateTime, from `timestamp`).
- Parsed driver identifier (nullable; derived from backticked portion of content).
- `author_name`, `author_id`, `author_nickname`.
- `raw_content` (full text) plus normalised `message_text`.
- Boolean `is_highlight_candidate` placeholder for future AI.
- Auto timestamps (`created_at`, `updated_at`).
- Indexing on `(session, posted_at)` and `discord_id`.

## Management Command Behaviour
- Location: `f1_data/management/commands/import_messages.py`.
- Required args:
  - `--session-id` linking messages to an existing `Session`.
  - `--channel-id` Discord channel identifier to export from (defaults to `1101802452224856174`).
- Optional filters:
  - `--start` / `--end` ISO8601 to bound ingest; defaults to exporter timeframe. Seconds
    precision is supported so short windows (e.g. 30 seconds) can be targeted.
  - `--output-dir` to override default temp directory (`tmp_transcripts_from_discord/`).
- Execution flow:
  1. Validate session metadata and ensure DiscordChatExporter CLI is present (`discord_msg_fetcher/DiscordChatExporter.Cli`).
  2. Use CLI to export JSON directly (command mirrors manual usage, e.g. `DiscordChatExporter.Cli export -t $DISCORD_OAUTH_TOKEN -c <channel> --after ... --before ... -f Json -o <dir>`).
  3. Load generated JSON, iterate messages, normalise text, derive driver name.
  4. Apply time window filters before DB work.
  5. Upsert by `discord_id`; update mutable fields on duplicates.
  6. Collect stats for created/updated/skipped and emit summary.
  7. Clean up temporary JSON on success unless `--keep-file` is specified.
- Command exits non-zero on timeout, missing session, malformed JSON, exporter failures, or if CLI is unavailable.

## Environment & Runtime Notes
- `.env` must define `DISCORD_OAUTH_TOKEN` for fetching exports; add documentation referencing existing `.env.example` if needed.
- Update `start.sh` to:
  - load `.env` (e.g., `set -a; source .env; set +a`) so child processes receive secrets.
  - bootstrap/update the DiscordChatExporter CLI (download ZIP, unzip into `discord_msg_fetcher/`, mark binary executable).
- Management command now depends on network access to Discord when exporting live; consider retry/backoff in future automation.
- Default exports land in `tmp_transcripts_from_discord/`; ensure directory exists and is gitignored.

## Outstanding Considerations
- Decide where Discord export files live (currently `tmp_transcripts_from_discord/`).
- Potential future fields: attachment URLs, reaction counts, message classifications.
- Coordination with future polling loop (Phase 2 step 3) once CLI automation defined.

## Automated Polling Loop
- `f1_data/management/commands/poll_recent_messages.py` determines whether a session is live by checking UTC `start_time`/`end_time`. Only one session should ever be live, but if multiple are detected the earliest start is used.
- When live, the command ingests the trailing window (`--window-seconds`, default 30) by delegating to `import_messages` with matching `--start`/`--end` bounds.
- `start.sh` launches a background loop that invokes the poll command every 30 seconds. Failures are logged to the console; the loop keeps running so transient exporter issues do not halt the stack.
- If no live session exists the command exits immediately with a friendly log message, and the next interval attempt (30 seconds later) will re-check.
- Adjust the poll cadence by setting `POLL_INTERVAL_SECONDS` in the environment before running `start.sh`.
