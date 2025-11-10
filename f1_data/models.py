from django.db import models


class Session(models.Model):
    """F1 session model storing race weekend session information from FastF1"""

    session_id = models.CharField(max_length=50, unique=True, db_index=True)
    year = models.IntegerField()
    round_number = models.IntegerField()
    session_type = models.CharField(
        max_length=20
    )  # Race, Qualifying, FP1, FP2, FP3, Sprint, Sprint Qualifying
    start_time = models.DateTimeField()  # UTC
    end_time = models.DateTimeField()  # UTC
    event_name = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    country = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "round_number", "session_type"]
        indexes = [
            models.Index(fields=["year", "round_number"]),
            models.Index(fields=["start_time", "end_time"]),
        ]

    def __str__(self):
        return (
            f"{self.year} Round {self.round_number} - {self.session_type} "
            f"({self.event_name})"
        )


class Message(models.Model):
    """Discord-exported radio message associated with a Formula 1 session."""

    discord_id = models.CharField(max_length=32, unique=True, db_index=True)
    session = models.ForeignKey(
        Session, related_name="messages", on_delete=models.CASCADE
    )

    posted_at = models.DateTimeField(db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    driver = models.CharField(max_length=100, null=True, blank=True)

    author_id = models.CharField(max_length=32, null=True, blank=True)
    author_name = models.CharField(max_length=255, null=True, blank=True)
    author_nickname = models.CharField(max_length=255, null=True, blank=True)

    raw_content = models.TextField()
    message_text = models.TextField(blank=True)

    is_highlight_candidate = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["session", "posted_at"]
        indexes = [
            models.Index(fields=["session", "posted_at"]),
        ]

    def __str__(self):
        return (
            f"{self.session.session_id} @ {self.posted_at.isoformat()} - "
            f"{self.driver or 'Unknown'}"
        )
