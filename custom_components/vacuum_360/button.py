from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Robot360Coordinator


@dataclass(frozen=True, kw_only=True)
class Robot360ButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[Robot360Coordinator], Awaitable[None]]
    support_key: str | None = None
    refresh_after_press: bool = True


BUTTONS: tuple[Robot360ButtonDescription, ...] = (
    Robot360ButtonDescription(
        key="edge_clean",
        name="Kantenreinigung starten",
        icon="mdi:border-outside",
        press_fn=lambda coord: coord.api.edge_clean(coord.sn),
    ),
    Robot360ButtonDescription(
        key="quick_mapping",
        name="Schnellkartierung starten",
        icon="mdi:map-plus",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coord: coord.api.quick_mapping(coord.sn),
    ),
    Robot360ButtonDescription(
        key="reboot",
        name="Roboter neu starten",
        icon="mdi:restart",
        entity_category=EntityCategory.CONFIG,
        support_key="reboot",
        press_fn=lambda coord: coord.api.reboot(coord.sn),
    ),
    Robot360ButtonDescription(
        key="reset_filter",
        name="Filter Zaehler zuruecksetzen",
        icon="mdi:air-filter",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coord: coord.api.reset_consumable(coord.sn, "filter"),
    ),
    Robot360ButtonDescription(
        key="reset_main_brush",
        name="Hauptbuerste Zaehler zuruecksetzen",
        icon="mdi:brush",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coord: coord.api.reset_consumable(coord.sn, "mainBrush"),
    ),
    Robot360ButtonDescription(
        key="reset_side_brush",
        name="Seitenbuerste Zaehler zuruecksetzen",
        icon="mdi:brush-variant",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coord: coord.api.reset_consumable(coord.sn, "sideBrush"),
    ),
    Robot360ButtonDescription(
        key="reset_sensors",
        name="Sensoren Zaehler zuruecksetzen",
        icon="mdi:radar",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coord: coord.api.reset_consumable(coord.sn, "sensors"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        Robot360Button(coord, description)
        for coord in coordinators.values()
        for description in BUTTONS
    )


class Robot360Button(CoordinatorEntity[Robot360Coordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Robot360Coordinator, description: Robot360ButtonDescription) -> None:
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
        support_key = self.entity_description.support_key
        if not support_key:
            return True
        return bool(((self.coordinator.data or {}).get("support_flags") or {}).get(support_key))

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
        if self.entity_description.refresh_after_press:
            await self.coordinator.async_request_refresh()
