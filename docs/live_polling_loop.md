## Live Polling Loop

### Purpose
- Keep `Message` records fresh during an active `Session` by ingesting Discord exports every 30 seconds.
- Prevent unnecessary work when no session is active; the loop must be effectively idle outside live windows.

### Trigger and Ownership
- Entry point: `start.sh` orchestrates the backend, frontend, and polling loop.
- Polling runs via `uv run python manage.py poll_recent_messages` on a repeating schedule (every 30 seconds).
- The loop is resilient: failures log to stderr/stdout but never crash the overall stack.

### Live Session Detection
- Only one `Session` is live at a time; guard by querying `Session` where `start_time <= now (UTC) < end_time`.
- Abort immediately when no live session exists. `start.sh`’s scheduler reruns the command so it will try again later.
- If multiple sessions ever matched (unexpected), log a warning and pick the earliest `start_time`.

### Message Fetch Window
- Poll command captures the trailing 30-second window using `start = now - 30s`, `end = now`.
- These timestamps are passed to `import_messages` via `--start` / `--end` (ISO strings).
- `import_messages` continues to upsert by `discord_id`, so re-fetching overlapping windows is safe.

### Operational Flow
1. Start script launches `poll_recent_messages` in the background (looping sleep + invoke).
2. Poll command resolves the live `Session`.
3. When live, it invokes the importer bounded by the trailing 30 seconds.
4. Importer runs DiscordChatExporter, loads JSON, upserts Messages, prints stats.
5. Command exits; `start.sh` waits 30 seconds and triggers it again.

### Logging and Observability
- Each poll prints session id, window bounds, and summary from importer.
- When no session is live, command emits a concise info message and exits with code 0.
- Errors from the importer bubble up; `start.sh` captures and logs stderr.

### Failure Handling
- Discord exporter failures, DB errors, or runtime caps cause a non-zero exit. `start.sh` logs and continues looping.
- Since the window overlaps, missing a single poll simply means the next run will catch up (assuming <30s outage).

### Future Enhancements
- Replace fixed sleep with a more robust scheduler (e.g., asyncio loop, cron-ish job runner).
- Add exponential backoff when repeated exporter failures occur.
- Emit Prometheus-style metrics or structured logs for dashboarding.
