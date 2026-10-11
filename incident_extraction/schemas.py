"""Shared, strict schema for independently extracted incident documents."""
import re
from datetime import date as calendar_date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Vehicle(StrictModel):
    id: str = Field(min_length=1, pattern=r"^vehicle_[1-9][0-9]*$")
    make: Optional[str] = None
    color: Optional[str] = None
    driver: Optional[str] = None


class Impact(StrictModel):
    source_vehicle_id: Optional[str] = None
    target_vehicle_id: Optional[str] = None
    target_region: Optional[Literal["front", "rear", "left", "right"]] = None


class IncidentData(StrictModel):
    date: Optional[str] = None
    time: Optional[str] = None
    time_approximate: Optional[bool] = None
    location: Optional[str] = None
    vehicle_count: Optional[int] = Field(default=None, ge=1)
    vehicles: list[Vehicle] = Field(default_factory=list)
    claimant_vehicle_id: Optional[str] = None
    fault_vehicle_id: Optional[str] = None
    incident_type: Optional[Literal[
        "rear_end", "head_on", "side_impact", "sideswipe", "multi_vehicle"
    ]] = None
    impacts: list[Impact] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("date must be YYYY-MM-DD or null")
            calendar_date.fromisoformat(value)
        return value

    @field_validator("time")
    @classmethod
    def valid_time(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            raise ValueError("time must be HH:MM in 24-hour format or null")
        return value

    @model_validator(mode="after")
    def consistent_references(self) -> "IncidentData":
        ids = [vehicle.id for vehicle in self.vehicles]
        if len(ids) != len(set(ids)):
            raise ValueError("vehicle IDs must be unique")
        references = [self.claimant_vehicle_id, self.fault_vehicle_id]
        for impact in self.impacts:
            references.extend([impact.source_vehicle_id, impact.target_vehicle_id])
            if (impact.source_vehicle_id is not None
                    and impact.source_vehicle_id == impact.target_vehicle_id):
                raise ValueError("an impact cannot reference the same source and target")
        if any(ref is not None and ref not in ids for ref in references):
            raise ValueError("all vehicle references must refer to existing vehicles")
        if self.vehicle_count is not None and self.vehicle_count < len(ids):
            raise ValueError("vehicle_count cannot be less than the listed vehicles")
        if self.time is None and self.time_approximate is not None:
            raise ValueError("time_approximate must be null when time is null")
        return self
