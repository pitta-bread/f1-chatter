from datetime import datetime
from ninja import Router, Schema
from typing import Optional

from f1_data.models import Session

api = Router()


class SessionSchema(Schema):
    """Schema for session data in API responses"""
    session_id: str
    year: int
    round_number: int
    session_type: str
    start_time: datetime
    end_time: datetime
    event_name: str
    location: str
    country: str

    class Config:
        from_attributes = True


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
    
    return list(queryset)
