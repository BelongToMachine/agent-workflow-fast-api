from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from app.db.knowledge_provenance import KnowledgeFileImport

MOCK_PRICE_SOURCE_NAME = "Mock Product Pricing Demo.csv"
MOCK_PRICE_SHEET = "Product Pricing"
MOCK_PRICE_VERSION = "asianode-product-price-mock-v1"
MOCK_PRODUCT_CATALOG = (
    ("Aurora 65W USB-C Charger", "Electronics", "Northstar", Decimal("8.50")),
    ("Foldable Solar Panel 100W", "Outdoor", "Sunpeak", Decimal("42.00")),
    ("Insulated Travel Mug 500ml", "Home & Kitchen", "Terra", Decimal("4.25")),
    ("Compact Air Purifier", "Home & Kitchen", "BreezeWorks", Decimal("31.50")),
    ("Magnetic Phone Mount", "Automotive", "RoadReady", Decimal("3.80")),
    ("Portable Bluetooth Speaker", "Electronics", "SoundPeak", Decimal("14.20")),
    ("Smart LED Desk Lamp", "Electronics", "Luma", Decimal("11.75")),
    ("Travel Packing Cube Set", "Travel", "Wayfarer", Decimal("5.60")),
    ("Stainless Steel Water Bottle", "Outdoor", "Terra", Decimal("6.40")),
    ("Wireless Presentation Remote", "Office", "Northstar", Decimal("7.90")),
    ("Rechargeable Hand Warmer", "Outdoor", "WarmTrail", Decimal("9.15")),
    ("Foldable Laptop Stand", "Office", "WorkForm", Decimal("12.80")),
    ("Pet GPS Tracker", "Pet Supplies", "PawPath", Decimal("18.60")),
    ("Mini Label Printer", "Office", "PrintLab", Decimal("16.25")),
    ("Reusable Food Storage Set", "Home & Kitchen", "Terra", Decimal("7.35")),
    ("Cycling Safety Light", "Outdoor", "RoadReady", Decimal("4.90")),
    ("USB-C Hub 8-in-1", "Electronics", "Northstar", Decimal("13.40")),
    ("Compact Garment Steamer", "Travel", "Wayfarer", Decimal("19.75")),
)
PRICE_VARIANTS = (
    ("Standard", Decimal("0.00")),
    ("Bulk carton", Decimal("2.50")),
    ("OEM packaging", Decimal("4.00")),
)
CURRENCIES = ("USD", "CNY", "EUR")


def build_product_price_mock_seed(
    workspace_id: UUID,
    knowledge_base_id: UUID,
) -> tuple[KnowledgeFileImport, dict[str, list[dict[str, object]]]]:
    """Build stable demo quotes and only the parent product rows they reference."""
    file_hash = sha256(MOCK_PRICE_VERSION.encode("ascii")).hexdigest()
    source = KnowledgeFileImport(
        workspace_id=workspace_id,
        display_name=MOCK_PRICE_SOURCE_NAME,
        source_type="csv",
        knowledge_base_id=knowledge_base_id,
        file_hash=file_hash,
        mime_type="text/csv",
        byte_size=0,
    )

    research_rows: list[dict[str, object]] = []
    price_rows: list[dict[str, object]] = []
    for product_index, (product_name, category, brand, base_price) in enumerate(
        MOCK_PRODUCT_CATALOG,
        start=1,
    ):
        research_id = uuid5(
            NAMESPACE_URL,
            f"asianode/business-table/mock/{knowledge_base_id}/product/{product_index}",
        )
        research_rows.append(
            {
                "id": research_id,
                "productName": product_name,
                "category": category,
                "brand": brand,
                "rawData": {
                    "demo": True,
                    "purpose": "ProductPrice table preview",
                    "version": MOCK_PRICE_VERSION,
                },
                "sourceSheet": MOCK_PRICE_SHEET,
                "sourceRow": product_index + 1,
            }
        )

        currency = CURRENCIES[(product_index - 1) % len(CURRENCIES)]
        for variant_index, (variant, surcharge) in enumerate(PRICE_VARIANTS):
            price_min = (base_price + surcharge + Decimal(product_index % 4) / 4).quantize(
                Decimal("0.01")
            )
            price_max = (price_min + Decimal("3.25")).quantize(Decimal("0.01"))
            price_rows.append(
                {
                    "researchId": research_id,
                    "sourceSheet": MOCK_PRICE_SHEET,
                    "sourceRow": 2 + (product_index - 1) * len(PRICE_VARIANTS) + variant_index,
                    "variant": variant,
                    "priceMin": price_min,
                    "priceMax": price_max,
                    "currency": currency,
                    "priceType": "mock_quote",
                    "rawText": f"Demo only · {currency} {price_min:.2f}–{price_max:.2f}",
                }
            )

    return source, {
        "realProductResearch": research_rows,
        "productPrices": price_rows,
    }
