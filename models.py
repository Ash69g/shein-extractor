from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Price(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str | None = None
    amount: str | None = None
    amountWithSymbol: str | None = None
    currency: str | None = None


class Variant(BaseModel):
    model_config = ConfigDict(extra="allow")

    goods_id: str
    goods_sn: str | None = None
    sku_code: str | None = None
    goods_attr: str | None = None
    color: str | None = None
    size: str | None = None
    stock: int | None = None
    sold_out: bool | None = None
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    display_price: Price | None = None
    amountWithSymbol: str | None = None


class Product(BaseModel):
    model_config = ConfigDict(extra="allow")

    goods_id: str
    goods_sn: str | None = None
    goods_name: str | None = None
    goods_img: str | None = None
    product_url: str | None = None
    variants: list[Variant] = Field(default_factory=list)


class CartShare(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_url: str
    final_url: str | None = None
    bridge_url: str | None = None
    group_id: str | None = None
    local_country: str = "SA"
    share_title: str | None = None
    share_comment: str | None = None
    share_image: str | None = None
    products: list[Product] = Field(default_factory=list)


class ExtractedCartItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    goods_id: str | None = None
    goods_sn: str | None = None
    sku_code: str | None = None
    goods_name: str | None = None
    goods_img: str | None = None
    goods_attr: str | None = None
    stock: int | None = None
    sold_out: bool | None = None
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    source_group: str
    display_price: Price | None = None
    amountWithSymbol: str | None = None
    is_on_sale: int | None = None


class CartExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_url: str
    final_url: str
    group_id: str | None = None
    local_country: str = "SA"
    all_product_size: int
    counts: dict[str, int]
    products: list[ExtractedCartItem]
    customer_name: str | None = None
    order_number: str | None = None
    analyzed_at: datetime | None = None
    output_file: str | None = None
