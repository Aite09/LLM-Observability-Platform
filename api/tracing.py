"""
OpenTelemetry setup — no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set.

Free default: without an endpoint no exporter is registered, zero overhead,
no collector container required. Set the env var to any OTLP gRPC endpoint
(Jaeger, Tempo, honeycomb...) and traces flow with no code change.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from api.config import get_settings

logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        logger.info("OTEL endpoint not set — tracing disabled (free default)")
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from api.dependencies import engine

    provider = TracerProvider(resource=Resource.create({"service.name": settings.app_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    logger.info("OTEL tracing → %s", settings.otel_exporter_otlp_endpoint)
