"""GlassFlow Rius tracing. Without RIUS_API_KEY the decorators are no-ops."""
import rius

from app.config import settings


def initialize() -> None:
    if settings.rius_api_key and not settings.rius_disabled:
        rius.init(api_key=settings.rius_api_key, service_name=settings.rius_service_name,
                  capture_content=settings.rius_capture_content)


def trace(name: str):
    # Never capture inputs/outputs: they hold document text and user questions.
    return rius.observe(name=name, capture_input=False, capture_output=False)
