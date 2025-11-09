from django.db import models


class Session(models.Model):
    """F1 session model storing race weekend session information from FastF1"""
    
    session_id = models.CharField(max_length=50, unique=True, db_index=True)
    year = models.IntegerField()
    round_number = models.IntegerField()
    session_type = models.CharField(max_length=20)  # Race, Qualifying, FP1, FP2, FP3, Sprint, Sprint Qualifying
    start_time = models.DateTimeField()  # UTC
    end_time = models.DateTimeField()  # UTC
    event_name = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    country = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-year', 'round_number', 'session_type']
        indexes = [
            models.Index(fields=['year', 'round_number']),
            models.Index(fields=['start_time', 'end_time']),
        ]
    
    def __str__(self):
        return f"{self.year} Round {self.round_number} - {self.session_type} ({self.event_name})"
