from functools import cache
from pathlib import Path

import yaml

from app.business_schema.registry_models import BusinessProfile

REGISTRY_DIR = Path(__file__).resolve().parent
_PROFILE_FILES = {"product_and_price": "product_and_price.yaml"}


class BusinessProfileNotFoundError(ValueError):
    """Raised when a caller requests a profile that was never published."""


@cache
def load_profile(profile_name: str) -> BusinessProfile:
    filename = _PROFILE_FILES.get(profile_name)
    if filename is None:
        raise BusinessProfileNotFoundError(f"Unknown business import profile: {profile_name}.")

    path = REGISTRY_DIR / filename
    try:
        raw_profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise BusinessProfileNotFoundError(
            f"The business import profile {profile_name!r} could not be loaded."
        ) from error
    return BusinessProfile.model_validate(raw_profile)
