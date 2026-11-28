"""Pydantic models for configuration checking."""

from typing import Any, Optional
from pydantic import BaseModel, field_validator

from shippy.core import models as core_models
from shippy.core.postage import easypost_address
from shippy.gui.core.constants import (
    DEFAULT_FONT_SIZE,
    DEFAULT_WEIGHT_LBS,
    FONT_SIZE_MIN,
    FONT_SIZE_MAX,
    WEIGHT_MIN_LBS,
    WEIGHT_MAX_LBS,
)


class UiConfig(BaseModel):
    """Model for UI configuration."""

    font_size: int = DEFAULT_FONT_SIZE
    log_file: Optional[str] = None
    default_weight: int = DEFAULT_WEIGHT_LBS

    @field_validator("font_size")
    @classmethod
    def validate_font_size(cls, v: int) -> int:
        """Validate font size is within reasonable bounds."""
        if v < FONT_SIZE_MIN:
            raise ValueError(f"Font size must be at least {FONT_SIZE_MIN}")
        if v > FONT_SIZE_MAX:
            raise ValueError(f"Font size must be at most {FONT_SIZE_MAX}")
        return v

    @field_validator("default_weight")
    @classmethod
    def validate_default_weight(cls, v: int) -> int:
        """Validate default weight is within bounds."""
        if v < WEIGHT_MIN_LBS:
            raise ValueError(f"Weight must be at least {WEIGHT_MIN_LBS}")
        if v > WEIGHT_MAX_LBS:
            raise ValueError(f"Weight must be at most {WEIGHT_MAX_LBS}")
        return v


class AddressBase(BaseModel):
    """Base model for address configuration."""

    name: str
    company: Optional[str] = None
    street1: str
    street2: str = ""
    city: str
    state: str
    zipcode: str

    @field_validator("name", "street1", "city", "state", "zipcode")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        """Ensure required address fields are not empty."""
        if not v.strip():
            raise ValueError("Required address fields cannot be empty")
        return v

    def to_easypost_dict(self) -> dict:
        """Convert to EasyPost address dictionary."""
        return easypost_address(self.model_dump(exclude_none=True))


class ReturnAddressConfig(AddressBase):
    """Model for return address configuration."""


class RecipientAddress(AddressBase):
    """Model for recipient address."""


class ParsedAddress(BaseModel):
    """Model for address parsed from external service (fields optional)."""

    street1: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    country: Optional[str] = None


class AutocompletePrediction(BaseModel):
    """Structured Google autocomplete prediction used for follow-up lookup."""

    description: str
    place_id: Optional[str] = None
    # Retained for future UI refinements even though the current flow only needs place_id.
    structured_formatting: Optional[dict[str, Any]] = None
    types: list[str] = []


# The [parcel] and [ibp] sections are read exactly as the shippy CLI reads them.
ParcelConfig = core_models.ParcelConfig
IbpConfig = core_models.IbpConfig


class EasypostConfig(core_models.EasypostConfig):
    """Model for Easypost configuration (the key may not be blank)."""

    @field_validator("apikey")
    @classmethod
    def validate_apikey(cls, v: str) -> str:
        """Ensure API key is not empty."""
        if not v.strip():
            raise ValueError("EasyPost API key is required")
        return v


class GoogleMapsConfig(core_models.GoogleMapsConfig):
    """Model for Google Maps configuration (the key may not be blank)."""

    @field_validator("apikey")
    @classmethod
    def validate_apikey(cls, v: str) -> str:
        """Ensure API key is not empty."""
        if not v.strip():
            raise ValueError("Google Maps API key is required")
        return v


class Config(core_models.Config):
    """Model for application configuration: the CLI's plus ``[ui]``."""

    ui: Optional[UiConfig] = None
    easypost: EasypostConfig
    googlemaps: GoogleMapsConfig

    def get_font_size(self) -> int:
        """Get font size with default fallback."""
        return self.ui.font_size if self.ui else DEFAULT_FONT_SIZE

    def get_log_file(self, fallback: str) -> str:
        """Get log file path with fallback."""
        if self.ui and self.ui.log_file:
            return self.ui.log_file
        return fallback

    def get_default_weight(self) -> int:
        """Get default weight with fallback."""
        return self.ui.default_weight if self.ui else DEFAULT_WEIGHT_LBS
