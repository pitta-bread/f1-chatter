
from django.contrib import admin

from f1_data.models import Message, Session


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_id",
        "year",
        "round_number",
        "session_type",
        "start_time",
        "end_time",
        "event_name",
    )
    list_filter = (
        "year",
        "session_type",
        "country",
    )
    search_fields = (
        "session_id",
        "event_name",
        "location",
        "country",
    )
    ordering = ("-year", "round_number", "session_type")
    date_hierarchy = "start_time"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "discord_id",
        "session",
        "posted_at",
        "driver",
        "author_name",
        "message_preview",
        "is_highlight_candidate",
    )
    list_filter = (
        "session",
        "driver",
        "is_highlight_candidate",
        "posted_at",
    )
    search_fields = (
        "discord_id",
        "driver",
        "author_name",
        "author_nickname",
        "raw_content",
    )
    ordering = ("-posted_at",)
    date_hierarchy = "posted_at"
    autocomplete_fields = ("session",)
    list_select_related = ("session",)

    def message_preview(self, obj: Message) -> str:
        preview_length = 60
        text = obj.message_text or obj.raw_content
        if len(text) > preview_length:
            return f"{text[:preview_length]}…"
        return text

    message_preview.short_description = "Message"
