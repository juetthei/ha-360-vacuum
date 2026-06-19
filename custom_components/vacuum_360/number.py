from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Robot360Coordinator


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class Robot360NumberDescription(NumberEntityDescription):
    state_key: str
    support_key: str | None
    set_fn: Callable[[Robot360Coordinator, float], Awaitable[None]]


NUMBERS: tuple[Robot360NumberDescription, ...] = (
    Robot360NumberDescription(
        key="volume",
        name="Lautstaerke",
        icon="mdi:volume-high",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        state_key="vol",
        support_key="volume",
        set_fn=lambda coord, value: coord.api.set_volume(coord.sn, int(value)),
    ),
    Robot360NumberDescription(
        key="water_pump",
        name="Wasserpumpe",
        icon="mdi:water-pump",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=3,
        native_step=1,
        mode=NumberMode.SLIDER,
        state_key="water",
        support_key="waterPump",
        set_fn=lambda coord, value: coord.api.set_water_pump(coord.sn, int(value)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        Robot360Number(coord, description)
        for coord in coordinators.values()
        for description in NUMBERS
    )


class Robot360Number(CoordinatorEntity[Robot360Coordinator], NumberEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Robot360Coordinator, description: Robot360NumberDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.sn}_{description.key}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.sn)},
            "name": self.coordinator.device_name,
            "manufacturer": "Qihoo 360",
            "model": "360 AI CleanRobot S6",
        }

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        support_flags = data.get("support_flags") or {}
        desc = self.entity_description
        return desc.state_key in data or bool(desc.support_key and support_flags.get(desc.support_key))

    @property
    def native_value(self) -> float | None:
        return _as_float((self.coordinator.data or {}).get(self.entity_description.state_key))

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, value)
        await self.coordinator.async_request_refresh()
