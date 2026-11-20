"""Products, feedback sources and tags."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, AdminCtx, ReadCtx, WriteCtx
from app.models import SOURCE_KINDS, FeedbackRecord, FeedbackSource, Product, Tag
from app.services.activity import log_activity
from app.services.feedback import owned
from app.services.serialize import iso

router = APIRouter(tags=["catalog"])


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="other")


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _counts(db, ws_id, column) -> dict:
    return dict(
        db.execute(select(column, func.count()).where(FeedbackRecord.workspace_id == ws_id, FeedbackRecord.is_archived.is_(False)).group_by(column)).all()
    )


@router.get("/products")
def list_products(ctx: ReadCtx, db: DB) -> list[dict]:
    counts = _counts(db, ctx.workspace_id, FeedbackRecord.product_id)
    return [
        {"id": str(p.id), "name": p.name, "description": p.description, "feedback_count": counts.get(p.id, 0), "created_at": iso(p.created_at)}
        for p in db.scalars(select(Product).where(Product.workspace_id == ctx.workspace_id).order_by(Product.name))
    ]


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(body: ProductIn, ctx: WriteCtx, db: DB) -> dict:
    p = Product(workspace_id=ctx.workspace_id, name=body.name.strip(), description=body.description)
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A product with this name already exists.") from None
    return {"id": str(p.id), "name": p.name, "description": p.description, "feedback_count": 0}


@router.patch("/products/{product_id}")
def update_product(product_id: uuid.UUID, body: ProductIn, ctx: WriteCtx, db: DB) -> dict:
    p = owned(db, Product, ctx.workspace_id, product_id, "Product")
    p.name, p.description = body.name.strip(), body.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A product with this name already exists.") from None
    return {"id": str(p.id), "name": p.name, "description": p.description}


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: uuid.UUID, ctx: AdminCtx, db: DB) -> Response:
    p = owned(db, Product, ctx.workspace_id, product_id, "Product")
    db.delete(p)  # feedback keeps existing with product unset (ON DELETE SET NULL)
    log_activity(db, ctx.workspace_id, ctx.user.id, "product.deleted", f"Deleted product {p.name}", "product", p.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources")
def list_sources(ctx: ReadCtx, db: DB) -> list[dict]:
    counts = _counts(db, ctx.workspace_id, FeedbackRecord.source_id)
    return [
        {"id": str(s.id), "name": s.name, "kind": s.kind, "feedback_count": counts.get(s.id, 0), "created_at": iso(s.created_at)}
        for s in db.scalars(select(FeedbackSource).where(FeedbackSource.workspace_id == ctx.workspace_id).order_by(FeedbackSource.name))
    ]


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def create_source(body: SourceIn, ctx: WriteCtx, db: DB) -> dict:
    if body.kind not in SOURCE_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"kind must be one of {', '.join(SOURCE_KINDS)}.")
    s = FeedbackSource(workspace_id=ctx.workspace_id, name=body.name.strip(), kind=body.kind)
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A source with this name already exists.") from None
    return {"id": str(s.id), "name": s.name, "kind": s.kind, "feedback_count": 0}


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: uuid.UUID, ctx: AdminCtx, db: DB) -> Response:
    s = owned(db, FeedbackSource, ctx.workspace_id, source_id, "Source")
    db.delete(s)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tags")
def list_tags(ctx: ReadCtx, db: DB) -> list[dict]:
    return [{"id": str(t.id), "name": t.name} for t in db.scalars(select(Tag).where(Tag.workspace_id == ctx.workspace_id).order_by(Tag.name))]


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag(body: TagIn, ctx: WriteCtx, db: DB) -> dict:
    t = Tag(workspace_id=ctx.workspace_id, name=body.name.strip())
    db.add(t)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This tag already exists.") from None
    return {"id": str(t.id), "name": t.name}


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: uuid.UUID, ctx: WriteCtx, db: DB) -> Response:
    t = owned(db, Tag, ctx.workspace_id, tag_id, "Tag")
    db.delete(t)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
