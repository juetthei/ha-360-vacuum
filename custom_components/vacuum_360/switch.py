from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Robot360Coordinator


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class Robot360SwitchDescription(SwitchEntityDescription):
    state_key: str
    support_key: str | None
    set_fn: Callable[[Robot360Coordinator, bool], Awaitable[None]]


SWITCHES: tuple[Robot360SwitchDescription, ...] = (
    Robot360SwitchDescription(
        key="led",
        name="LED",
        icon="mdi:led-on",
        entity_category=EntityCategory.CONFIG,
        state_key="led",
        support_key="led",
        set_fn=lambda coord, value: coord.api.set_led(coord.sn, value),
    ),
    Robot360SwitchDescription(
        key="auto_boost",
        name="Teppich Turbo",
        icon="mdi:fan-chevron-up",
        entity_category=EntityCategory.CONFIG,
        state_key="autoBoost",
        support_key="carpetMode",
        set_fn=lambda coord, value: coord.api.set_auto_boost(coord.sn, value),
    ),
    Robot360SwitchDescription(
        key="carpet_auto_recognize",
        name="Teppich automatisch erkennen",
        icon="mdi:rug",
        entity_category=EntityCategory.CONFIG,
        state_key="carpetAutoRecognize",
        support_key="supportCarpetAdjust",
        set_fn=lambda coord, value: coord.api.set_carpet_auto_recognize(coord.sn, value),
    ),
    Robot360SwitchDescription(
        key="carpet_depth_clean",
        name="Teppich Tiefenreinigung",
        icon="mdi:rug",
        entity_category=EntityCategory.CONFIG,
        state_key="carpetDepthClean",
        support_key="supportCarpetDepthClean",
        set_fn=lambda coord, value: coord.api.set_carpet_depth_clean(coord.sn, value),
    ),
    Robot360SwitchDescription(
        key="avoid_falling_down",
        name="Sturzschutz",
        icon="mdi:stairs-down",
        entity_category=EntityCategory.CONFIG,
        state_key="avoidFallingDown",
        support_key="supportPreventDropSwitch",
        set_fn=lambda coord, value: coord.api.set_avoid_falling_down(coord.sn, value),
    ),
    Robot360SwitchDescription(
        key="battery_protection",
        name="Akkuschutz",
        icon="mdi:battery-heart-variant",
        entity_category=EntityCategory.CONFIG,
        state_key="BPSwitch",
        support_key="batteryProtection",
        set_fn=lambda coord, value: coord.api.set_battery_protection(coord.sn, value),
    ),
    Robot360SwitchDescription(
        key="firmware_auto_update",
        name="Firmware Auto Update",
        icon="mdi:update",
        entity_category=EntityCategory.CONFIG,
        state_key="firmwareAutoUpdateStatus",
        support_key="firmwareAutoUpdateSet",
        set_fn=lambda coord, value: coord.api.set_firmware_auto_update(coord.sn, value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        Robot360Switch(coord, description)
        for coord in coordinators.values()
        for description in SWITCHES
    )


class Robot360Switch(CoordinatorEntity[Robot360Coordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Robot360Coordinator, description: Robot360SwitchDescription) -> None:
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
    def is_on(self) -> bool | None:
        return _as_bool((self.coordinator.data or {}).get(self.entity_description.state_key))

    async def async_turn_on(self, **kwargs) -> None:
        await self.entity_description.set_fn(self.coordinator, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.entity_description.set_fn(self.coordinator, False)
        await self.coordinator.async_request_refresh()
