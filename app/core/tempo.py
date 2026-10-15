from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def agora() -> datetime:
    """Data/hora local (Brasília) sem fuso, como o MySQL DATETIME guarda."""
    fuso = ZoneInfo(get_settings().fuso_horario)
    return datetime.now(fuso).replace(tzinfo=None, microsecond=0)
