"""
Common Pydantic schemas — reused across all routers.

PaginationParams  → query params for page/page_size
PaginatedResponse → wrapper returned by list endpoints
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="1-based page number")
    page_size: int = Field(50, ge=1, le=500, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated list response.

    Usage:
        return PaginatedResponse[LLMLogResponse](
            total=total, page=page, page_size=page_size, items=logs
        )
    """

    total: int
    page: int
    page_size: int
    items: list[T]
