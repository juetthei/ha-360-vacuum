from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Robot360Coordinator


_CONSUMABLE_LIFETIME_HOURS = {
    "filter": 150,
    "mainBrush": 300,
    "sideBrush": 200,
    "sensors": 30,
}


def _get(data: dict, *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _consumable_percent(data: dict, key: str) -> int | None:
    used_seconds = _as_int(_get(data, "consumables", key))
    lifetime_hours = _CONSUMABLE_LIFETIME_HOURS[key]
    if used_seconds is None:
        return None
    used_hours = (used_seconds + 1800) // 3600
    return max(0, min(100, round(((lifetime_hours - used_hours) / lifetime_hours) * 100)))


def _consumable_used_hours(data: dict, key: str) -> int | None:
    used_seconds = _as_int(_get(data, "consumables", key))
    if used_seconds is None:
        return None
    return round(used_seconds / 3600)


def _bool_int(data: dict, key: str) -> int | None:
    value = _as_int(data.get(key))
    if value is None:
        return None
    return 1 if value else 0


def _battery_value(data: dict) -> int | None:
    for key in ("elecReal", "batteryUse", "elec", "battery", "batteryLevel", "power"):
        value = _as_int(data.get(key))
        if value is not None:
            return max(0, min(100, value))

    return None


def _battery_extra(data: dict) -> dict[str, Any]:
    for key in ("elecReal", "batteryUse", "elec", "battery", "batteryLevel", "power"):
        value = _as_int(data.get(key))
        if value is not None:
            attrs = {"source": key, "fallback": False}
            if data.get("external_status_source"):
                attrs["external_status_source"] = data.get("external_status_source")
                attrs["external_status_age"] = data.get("external_status_age")
            return attrs
    return {
        "source": "unavailable",
        "fallback": False,
        "reason": "live_status_missing",
    }


@dataclass(frozen=True, kw_only=True)
class Robot360SensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any]
    extra_fn: Callable[[dict], dict[str, Any]] | None = None


def _material_extra(key: str) -> Callable[[dict], dict[str, Any]]:
    def _extra(data: dict) -> dict[str, Any]:
        used_seconds = _as_int(_get(data, "consumables", key))
        lifetime = _CONSUMABLE_LIFETIME_HOURS[key]
        return {
            "used_seconds": used_seconds,
            "used_hours": _consumable_used_hours(data, key),
            "lifetime_hours": lifetime,
            "remaining_hours": None
            if used_seconds is None
            else max(0, lifetime - round(used_seconds / 3600)),
        }

    return _extra


SENSORS: tuple[Robot360SensorDescription, ...] = (
    Robot360SensorDescription(
        key="battery",
        name="Batterie",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_battery_value,
        extra_fn=_battery_extra,
    ),
    Robot360SensorDescription(
        key="filter_remaining",
        translation_key="filter_remaining",
        name="Filter Rest",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _consumable_percent(data, "filter"),
        extra_fn=_material_extra("filter"),
    ),
    Robot360SensorDescription(
        key="main_brush_remaining",
        translation_key="main_brush_remaining",
        name="Hauptbuerste Rest",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _consumable_percent(data, "mainBrush"),
        extra_fn=_material_extra("mainBrush"),
    ),
    Robot360SensorDescription(
        key="side_brush_remaining",
        translation_key="side_brush_remaining",
        name="Seitenbuerste Rest",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brush-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _consumable_percent(data, "sideBrush"),
        extra_fn=_material_extra("sideBrush"),
    ),
    Robot360SensorDescription(
        key="sensors_remaining",
        translation_key="sensors_remaining",
        name="Sensoren Rest",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radar",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _consumable_percent(data, "sensors"),
        extra_fn=_material_extra("sensors"),
    ),
    Robot360SensorDescription(
        key="total_clean_area",
        name="Gesamt gereinigte Flaeche",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:floor-plan",
        value_fn=lambda data: _as_int(_get(data, "statistics", "cleanArea")),
    ),
    Robot360SensorDescription(
        key="total_clean_count",
        name="Reinigungen gesamt",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda data: _as_int(_get(data, "statistics", "cleanCount")),
    ),
    Robot360SensorDescription(
        key="total_clean_time",
        name="Reinigungszeit gesamt",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        value_fn=lambda data: _as_int(_get(data, "statistics", "cleanTime")),
    ),
    Robot360SensorDescription(
        key="week_clean_area",
        name="Reinigung diese Woche",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-week",
        value_fn=lambda data: _as_int(_get(data, "recent_stats", "weekAreaSum")),
    ),
    Robot360SensorDescription(
        key="month_clean_area",
        name="Reinigung diesen Monat",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-month",
        value_fn=lambda data: _as_int(_get(data, "recent_stats", "monthAreaSum")),
    ),
    Robot360SensorDescription(
        key="firmware_version_code",
        name="Firmware Version Code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
        value_fn=lambda data: _as_int(data.get("versionCode") or data.get("firmwareVersionCode")),
    ),
    Robot360SensorDescription(
        key="online",
        name="Online",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi-check",
        value_fn=lambda data: _bool_int(data, "online"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        Robot360Sensor(coord, description)
        for coord in coordinators.values()
        for description in SENSORS
    )


class Robot360Sensor(CoordinatorEntity[Robot360Coordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Robot360Coordinator, description: Robot360SensorDescription) -> None:
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
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_fn is None:
            return None
        return self.entity_description.extra_fn(self.coordinator.data or {})
