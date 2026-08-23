"""
Marstek Venus Modbus sensor entities.

All sensors now derive their values from the shared coordinator data.
No separate async_update needed; coordinator handles polling.
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MarstekCoordinator
from .const import DOMAIN, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all Marstek sensors from definitions."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Create sensor entities from coordinator-provided definitions
    entities = []
    sensor_groups = (
        (MarstekSensor, coordinator.SENSOR_DEFINITIONS),
        (MarstekEfficiencySensor, coordinator.EFFICIENCY_SENSOR_DEFINITIONS),
        (MarstekSolarPowerSensor, coordinator.SOLAR_POWER_SENSOR_DEFINITIONS),
        (MarstekVersionSensor, coordinator.VERSION_SENSOR_DEFINITIONS),
        (MarstekStoredEnergySensor, coordinator.STORED_ENERGY_SENSOR_DEFINITIONS),
        (MarstekBatteryCycleSensor, coordinator.CYCLE_SENSOR_DEFINITIONS),
        (MarstekCellVoltageDeltaSensor, coordinator.CELL_VOLTAGE_DELTA_SENSOR_DEFINITIONS),
        (MarstekBitfieldTextSensor, coordinator.BITFIELD_TEXT_SENSOR_DEFINITIONS),
        (MarstekGridPowerSensor, coordinator.GRID_POWER_SENSOR_DEFINITIONS),
        (MarstekBmsBatteryPowerSensor, coordinator.BMS_POWER_SENSOR_DEFINITIONS),
        # getattr: Die DEV-Sektionen sind optional. Fehlt ein Attribut (z. B. weil
        # eine aeltere Coordinator-Version geladen ist), soll das nicht die gesamte
        # Sensor-Plattform scheitern lassen.
        (MarstekDevSensor, getattr(coordinator, "DEV_UNKNOWN_SENSOR_DEFINITIONS", []) or []),
        (MarstekDevSensor, getattr(coordinator, "DEV_DUPLICATE_SENSOR_DEFINITIONS", []) or []),
    )
    for entity_cls, definitions in sensor_groups:
        entities.extend(entity_cls(coordinator, definition) for definition in definitions)

    # Add all entities to Home Assistant
    async_add_entities(entities)


class MarstekSensor(CoordinatorEntity, SensorEntity):
    """Generic Modbus sensor reading from the coordinator."""

    def __init__(self, coordinator: MarstekCoordinator, definition: dict):
        super().__init__(coordinator)

        # Store the key and definition
        self._key = definition["key"]
        self.definition = definition     

        # Assign the entity type to the coordinator mapping
        self.coordinator._entity_types[self._key] = self.entity_type

        # Set entity attributes from definition
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.definition['key']}"
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]

        # Set basic attributes from definition
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")

        # Optional: entity category and icon
        if "category" in definition:
            self._attr_entity_category = EntityCategory(definition["category"])
        if "icon" in definition:
            self._attr_icon = definition["icon"]
        if definition.get("enabled_by_default") is False:
            self._attr_entity_registry_enabled_default = False

        # Optional states mapping for int → label conversion
        self.states = definition.get("states")

    @property
    def entity_type(self) -> str:
        """
        Return the type of this entity for logging purposes.
        This allows the coordinator to show more descriptive messages.
        """
        return "sensor"

    @property
    def available(self) -> bool:
        """Return True if coordinator has valid data for this sensor."""
        # Consider the sensor available when coordinator has provided a value
        # for this key. This avoids sensors remaining 'unknown' when the
        # coordinator had transient update failures but still supplies data.
        data = getattr(self.coordinator, "data", None)
        return isinstance(data, dict) and self._key in data

    @property
    def native_value(self):
        """Return the value from coordinator data with scaling and states applied."""
        if self._key not in self.coordinator.data:
            return None
        value = self.coordinator.data[self._key]

        # Special handling for schedule data type: the sensor state should
        # represent whether the schedule is enabled (boolean). The raw
        # register list is exposed in attributes under `raw` and all decoding
        # / interpretation is performed in `extra_state_attributes`.
        if self.definition.get("data_type") == "schedule":
            data = getattr(self.coordinator, "data", {}) or {}
            # Prefer decoded attrs if coordinator provided them, otherwise
            # attempt to decode from the raw register list.
            attrs = data.get(f"{self._key}_attrs") or {}
            enabled = None

            if isinstance(attrs, dict) and "enabled" in attrs:
                try:
                    enabled = bool(int(attrs.get("enabled") or 0))
                except Exception:
                    enabled = bool(attrs.get("enabled"))
            else:
                # Try to decode from raw registers stored at data[self._key]
                raw = data.get(self._key)
                if isinstance(raw, (list, tuple)) and len(raw) >= 5:
                    try:
                        enabled = bool(int(raw[4]))
                    except Exception:
                        enabled = bool(raw[4])

            # If we couldn't determine enabled state, return None (unknown)
            if enabled is None:
                return None

            return enabled

        if isinstance(value, (int, float)):
            # Special-case: EMS version is encoded as an integer where
            # values with 4 digits encode a decimal in the last digit
            # (e.g. 1573 -> 157.3), while 3-digit values are whole numbers
            # (e.g. 158 -> 158). Handle that before applying generic scale.
            if self._key == "ems_version":
                try:
                    iv = int(value)
                except Exception:
                    iv = None

                if iv is not None:
                    if iv >= 1000:
                        # interpret last digit as decimal (tenths)
                        value = round(iv / 10.0, 1)
                    else:
                        value = int(iv)
                    # return early after mapping; skip generic scaling
                    if isinstance(value, float) and value.is_integer():
                        value = int(value)
                    # apply states mapping below
                else:
                    # fall back to generic handling if conversion fails
                    pass
            else:
                # Apply scaling/offset and round according to precision.
                scale = self.definition.get("scale", 1)
                offset = self.definition.get("offset", 0)
                precision = int(self.definition.get("precision", 0) or 0)

                value = float(value) * scale + offset
                value = round(value, precision)

                # If the rounded value has no fractional component, return int
                # so Home Assistant does not render an unnecessary trailing .0.
                if isinstance(value, float) and value.is_integer():
                    value = int(value)

        if self.states and value in self.states:
            return self.states[value]

        return value


    @property
    def suggested_display_precision(self) -> int | None:
        """Suggest display precision based on definition, but only if not a string or mapped state."""
        if self.states:
            return None
        return self.definition.get("precision")

    @property
    def suggested_display_unit(self) -> str | None:
        """Suggest display unit based on definition, but only if not a string or mapped state."""
        if self.states:
            return None
        return self.definition.get("unit")

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }

    @property
    def extra_state_attributes(self) -> dict:
        """Return attributes for packed schedule sensors from coordinator data."""
        data = self.coordinator.data or {}
        attrs = data.get(f"{self._key}_attrs") or {}

        # For schedule types, enrich attributes with human-readable fields.
        # If `_attrs` is not present but the coordinator stored the raw
        # 5-register list in `data[key]`, decode that here so we don't
        # duplicate decoding in the coordinator.
        if self.definition.get("data_type") == "schedule":
            if not isinstance(attrs, dict) or not attrs:
                raw = data.get(self._key)
                if isinstance(raw, (list, tuple)) and len(raw) >= 5:
                    try:
                        attrs = {
                            "days": int(raw[0]),
                            "start": int(raw[1]),
                            "end": int(raw[2]),
                            "mode": int(raw[3]) - 0x10000 if int(raw[3]) >= 0x8000 else int(raw[3]),
                            "enabled": int(raw[4]),
                        }
                    except Exception:
                        attrs = {}

            if isinstance(attrs, dict) and attrs:
                def _fmt_time(t):
                    try:
                        t = int(t)
                        # Heuristic: device encodes times as HHMM (e.g. 200 -> 02:00,
                        # 610 -> 06:10) when the low two digits are < 60 and the
                        # value is within 0..2359. Otherwise treat value as
                        # minutes-since-midnight.
                        if 0 <= t <= 2359 and (t % 100) < 60:
                            hh = t // 100
                            mm = t % 100
                        else:
                            hh = t // 60
                            mm = t % 60
                        return f"{hh:02d}:{mm:02d}"
                    except Exception:
                        return t

                # Debug logging for raw schedule data from coordinator
                _LOGGER.warning(
                    "Raw schedule data for %s: value=%s attrs=%s",
                    self._key,
                    data.get(self._key),
                    attrs,
                )

                days = attrs.get("days")
                try:
                    dmask = int(days) if days is not None else 0
                except Exception:
                    dmask = 0
                # Bits are encoded with Monday at bit 0 (device ordering), but
                # display should start with Sunday. Compute set using Monday-first
                # mapping, then reorder to Sunday-first for presentation.
                weekday_names_mon = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                selected_mon = [weekday_names_mon[i] for i in range(7) if (dmask >> i) & 1]
                display_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                selected = [d for d in display_order if d in selected_mon]

                # Build a minimal enriched dict — do not duplicate raw fields.
                enriched = {}
                enriched["days_list"] = selected
                enriched["start_time"] = _fmt_time(attrs.get("start"))
                enriched["end_time"] = _fmt_time(attrs.get("end"))

                # Interpret mode into a human-friendly type and a separate watt attribute.
                # NOTE: device uses signed mode where -1 == self consumption and
                # signed values represent magnitude. Empirically the device
                # uses negative -> charge and positive -> discharge (inverse
                # of earlier assumption), so map accordingly.
                mode_raw = attrs.get("mode")
                mode = None
                power = None
                try:
                    if mode_raw is None:
                        mode = None
                    else:
                        m = int(mode_raw)
                        if m == -1:
                            mode = "self consumption"
                        elif m < 0:
                            mode = "charge"
                            power = abs(m)
                        else:
                            mode = "discharge"
                            power = m
                except Exception:
                    mode = None
                    power = None

                enriched["mode"] = mode
                enriched["power"] = power
                enriched["enabled"] = bool(attrs.get("enabled"))
                return enriched

        return attrs or {}


class MarstekCalculatedSensor(CoordinatorEntity, SensorEntity):
    """
    Base class for calculated sensors that depend on multiple coordinator keys.

    Handles registration of dependency keys and provides update handling.
    """

    def __init__(self, coordinator: MarstekCoordinator, definition: dict):
        """Initialize the calculated sensor and register dependencies."""
        super().__init__(coordinator)

        # Store the key and definition
        self._key = definition["key"]
        self.definition = definition

        # Assign the entity type to the coordinator mapping
        self.coordinator._entity_types[self._key] = self.entity_type

        # Set entity attributes from definition
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.definition['key']}"
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]

        # Set basic attributes from definition
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")

        # Display precision. MarstekSensor exposes this through a property, but
        # the calculated sensors never read the key their definitions already
        # carry - so a cell voltage delta of 0.0 rendered as "0" instead of
        # "0.000", which reads like a missing value rather than a perfectly
        # balanced pack.
        precision = definition.get("precision")
        if precision is not None:
            self._attr_suggested_display_precision = precision

        # Optional: entity category and icon
        if "category" in definition:
            self._attr_entity_category = EntityCategory(definition["category"])
        if "icon" in definition:
            self._attr_icon = definition["icon"]
        if definition.get("enabled_by_default") is False:
            self._attr_entity_registry_enabled_default = False

        # Register dependency keys in coordinator and set scales
        for alias, dep_key in self.get_dependency_keys().items():
            if not dep_key:
                continue

            self.coordinator._entity_types[dep_key] = "sensor"

            # Combine all definitions for iteration using coordinator-provided lists
            if not hasattr(self, "_all_definitions"):
                self._all_definitions = (
                    self.coordinator.SENSOR_DEFINITIONS + self.coordinator.BINARY_SENSOR_DEFINITIONS
                )
            all_definitions = self._all_definitions

            # Get scale from all definitions or fallback to current sensor dependency_defs
            scale = next((d.get("scale", 1) for d in all_definitions if d.get("key") == dep_key), None)
            scale = scale or self.definition.get("dependency_defs", {}).get(alias, 1)

            self.coordinator._scales[dep_key] = scale

    def get_dependency_keys(self):
        """Return the keys this sensor depends on."""
        return self.definition.get("dependency_keys", {})

    @property
    def entity_type(self) -> str:
        """
        Return the type of this entity for logging purposes.
        This allows the coordinator to show more descriptive messages.
        """
        return "sensor"

    @property
    def device_info(self) -> dict:
        """Return device info so sensor is linked to the integration/device."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }

    def _handle_coordinator_update(self) -> None:
        """
        Handle coordinator update by recalculating the sensor value.

        Calls the subclass's calculate_value method and updates state.
        """
        if not getattr(self.coordinator, "last_update_success", False):
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        data = self.coordinator.data if isinstance(self.coordinator.data, dict) else {}

        self._calculate(data)
        self.async_write_ha_state()

    def _calculate(self, data: dict) -> None:
        """
        Centralized method to check dependencies, log missing values,
        calculate value, and update native_value attribute.
        """
        dependency_keys = self.get_dependency_keys()
        dep_values = {}
        missing = []

        # dependency_keys is a dict alias -> actual key
        for alias, actual_key in dependency_keys.items():
            val = data.get(actual_key)
            scale = self.coordinator._scales.get(actual_key, 1)
            if val is None:
                missing.append(alias)
            else:
                dep_values[alias] = float(val) * scale

        if missing:
            _LOGGER.warning(
                "%s missing required value(s): %s. Current data: %s. Cannot calculate value.",
                self._key, ", ".join(missing), {k: data.get(v) for k, v in dependency_keys.items()},
            )
            self._attr_native_value = None
            return

        try:
            value = self.calculate_value(dep_values)
            _LOGGER.debug(
                "Calculated value for %s: %s (input values: %s)",
                self._key,
                value,
                dep_values
            )
            self._attr_native_value = value
        except Exception as ex:
            _LOGGER.warning(
                "Error calculating value for sensor %s: %s", self._key, ex
            )
            self._attr_native_value = None

    def calculate_value(self, dep_values: dict):
        """
        Calculate the sensor value from scaled dependency values.

        Must be implemented by subclasses.
        """
        raise NotImplementedError


class MarstekSolarPowerSensor(MarstekCalculatedSensor):
    """Calculate total solar generation by summing all configured dependency values."""

    def calculate_value(self, dep_values: dict):
        aliases = list(self.get_dependency_keys().keys())
        values = [dep_values.get(alias) for alias in aliases]
        if any(value is None for value in values):
            return None

        total = round(sum(float(value) for value in values), 2)
        self._attr_native_value = total
        return total


class MarstekCellVoltageDeltaSensor(MarstekCalculatedSensor):
    """
    Spread between the highest and lowest cell voltage of one battery pack.

    Both dependencies come from the pack's own registers (34005/34006 plus
    0x100 per pack), so the value is per pack and never mixes packs. A rising
    delta is the usual early sign of a weakening cell.
    """

    def calculate_value(self, dep_values: dict):
        """Return max - min in volts, or None if either side is missing."""
        max_voltage = dep_values.get("max")
        min_voltage = dep_values.get("min")
        if max_voltage is None or min_voltage is None:
            return None

        delta = round(float(max_voltage) - float(min_voltage), 3)
        if delta < 0:
            # The two registers are read in separate transactions, so a sample
            # taken across a BMS update can invert them. Report nothing rather
            # than a negative spread.
            _LOGGER.debug(
                "Negative cell voltage delta for %s (max=%s, min=%s), skipping",
                self._key, max_voltage, min_voltage,
            )
            return None

        self._attr_native_value = delta
        return delta


class MarstekBitfieldTextSensor(MarstekCalculatedSensor):
    """
    Plain-text companion to a numeric bitfield sensor.

    Reads the same word through a dependency key and renders the bits that are
    set, so the numeric sensor keeps reporting a number and automations that
    compare against it are unaffected.
    """

    def __init__(self, coordinator, definition):
        super().__init__(coordinator, definition)
        raw_bits = definition.get("bit_descriptions") or {}
        self._bit_descriptions = {int(bit): str(text) for bit, text in raw_bits.items()}

    @staticmethod
    def _active_bits(value) -> list[int]:
        """Return the indices of the bits set in value, lowest first."""
        try:
            raw = int(value)
        except (TypeError, ValueError):
            return []
        if raw <= 0:
            return []
        return [bit for bit in range(raw.bit_length()) if raw >> bit & 1]

    def calculate_value(self, dep_values: dict):
        """Render the source word as "<raw> - <text>, <text>"."""
        source = dep_values.get("source")
        if source is None:
            return None
        try:
            raw = int(source)
        except (TypeError, ValueError):
            return None

        bits = self._active_bits(raw)
        if not bits:
            value = f"{raw} - OK"
        else:
            value = f"{raw} - " + ", ".join(
                self._bit_descriptions.get(bit, f"unknown bit {bit}") for bit in bits
            )

        self._attr_native_value = value
        return value

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the raw word and the decoded bits for automations."""
        data = self.coordinator.data or {}
        source_key = self.get_dependency_keys().get("source")
        raw = data.get(source_key)
        bits = self._active_bits(raw)
        return {
            "raw_value": raw,
            "active_bits": bits,
            "active_faults": [
                self._bit_descriptions.get(bit, f"unknown bit {bit}") for bit in bits
            ],
            "undecoded_bits": [bit for bit in bits if bit not in self._bit_descriptions],
        }


class MarstekGridPowerSensor(MarstekCalculatedSensor):
    """
    Power at the grid connection point, reproducing what the device itself computes.

    The firmware builds this value for its Bluetooth payload but exposes no register
    for it, so it is rebuilt here from the registers the formula reads. Positive means
    export to the grid, negative means import.

    Decompiled from the BLE payload builder (FUN_0800b024, offset 0x90):

        if grid_sample_power == 0:
            base = off_grid_power if inverter_state == 4 else 0
        else:
            base = grid_sample_power
        grid_power = base - off_grid_power

    The distinction matters in bypass, where the backup output is fed straight from the
    grid: the inverter's own grid sample reads zero there, so the backup load is what
    the grid is actually carrying.
    """

    #: Inverter state 4 = Backup Mode, the only state where a zero grid sample still
    #: means the grid is carrying the backup load.
    _BACKUP_MODE = 4

    def calculate_value(self, dep_values: dict):
        grid = dep_values.get("grid")
        offgrid = dep_values.get("offgrid")
        state = dep_values.get("state")
        if grid is None or offgrid is None or state is None:
            return None

        grid = int(grid)
        offgrid = int(offgrid)

        if grid == 0:
            base = offgrid if int(state) == self._BACKUP_MODE else 0
        else:
            base = grid

        value = base - offgrid
        self._attr_native_value = value
        return value


class MarstekBmsBatteryPowerSensor(MarstekCalculatedSensor):
    """
    Battery power as the BMS sees it: pack voltage times pack current.

    This is the second value the firmware computes for its Bluetooth payload
    (FUN_0800b024, offset 0x8C) without exposing a register for it. VenusControl
    shows it as "Battery Power".

    It is deliberately not the same as `battery_power` (30001), which is the
    inverter's own measurement. Under load the two agree closely; at idle they
    differ by the device's own consumption, which only one side sees. Having both
    makes that difference visible.

    The device discharges one pack at a time, so the current is the sum over all
    packs — the inactive ones contribute zero. Summing rather than following
    `bms_active_pack_index` also stays correct if a firmware ever drives several
    packs at once.

    The firmware reads the current from the BMS aggregate at `0x20014F90`, which
    Modbus exposes as 32101. That register is not usable: `Read_Serializer`
    sign-extends the i16 into an unsigned word before applying its divide-by-ten
    scale, so negative currents come back corrupted (-122 arrives as 39309). The
    per-pack current registers carry no scale code and are unaffected.
    """

    def calculate_value(self, dep_values: dict):
        voltage = dep_values.get("voltage")
        if voltage is None:
            return None

        current = 0.0
        for alias in self.get_dependency_keys():
            if alias == "voltage":
                continue
            value = dep_values.get(alias)
            if value is None:
                return None
            current += float(value)

        power = round(float(voltage) * current)
        self._attr_native_value = power
        return power


class MarstekStoredEnergySensor(MarstekCalculatedSensor):
    """
    Sensor calculating stored battery energy (kWh).

    Uses SOC (%) and battery total energy (kWh) from coordinator data.
    """
    def calculate_value(self, dep_values: dict):
        """Calculate stored energy based on SOC and capacity dynamically."""
        soc = dep_values.get("soc")
        capacity = dep_values.get("capacity")
        stored_energy = round((soc / 100) * capacity, 2)
        self._attr_native_value = stored_energy
        return stored_energy


class MarstekEfficiencySensor(MarstekCalculatedSensor):
    """
    Calculate either Round Trip Efficiency (RTE) or Actual Conversion Efficiency.

    Mode is determined by 'mode' in the sensor definition:
    - "round_trip": uses charge / discharge energy
    - "conversion": uses battery_power / ac_power
    """
    def calculate_value(self, dep_values: dict):
        mode = self.definition.get("mode", "round_trip")
        if mode == "round_trip":
            charge = dep_values.get("charge")
            discharge = dep_values.get("discharge")
            if charge in (None, 0):
                return None
            efficiency = (discharge / charge) * 100

        elif mode == "conversion":
            battery_power = dep_values.get("battery_power")
            ac_power = dep_values.get("ac_power")
            if battery_power is None or ac_power is None:
                return None
            if battery_power > 0:
                if ac_power == 0:
                    return None
                efficiency = abs(battery_power) / abs(ac_power) * 100
            else:
                if battery_power == 0:
                    return None
                efficiency = abs(ac_power) / abs(battery_power) * 100

        else:
            _LOGGER.warning("%s unknown efficiency mode '%s'", self._key, mode)
            return None

        efficiency_rounded = round(min(efficiency, 100.0), 1)
        self._attr_native_value = efficiency_rounded
        return efficiency_rounded


class MarstekBatteryCycleSensor(MarstekCalculatedSensor):
    """Calculate estimated battery cycles from discharge energy and capacity."""

    def calculate_value(self, dep_values: dict):
        discharge = dep_values.get("discharge")
        capacity = dep_values.get("capacity")
        if discharge is None or capacity in (None, 0):
            return None

        cycles = round(discharge / capacity, 2)
        self._attr_native_value = cycles
        return cycles


class MarstekVersionSensor(MarstekCalculatedSensor):
    """Sensor that formats multiple version registers into a human-readable version string.

    Supported modes:
                - "ems_bms": combines ems_version + bms_version
                    into a string like "V147.6.112"
                - "ems_vms_bms": combines ems_version + vms_version + bms_version
                    into a string like "V147.6.117.112"
                - "ems_vms_mppt_bms": combines ems_version + vms_version + mppt_version
                    + bms_version into a string like "V149.2.115.104.118" (for models
                    with an MPPT stage, e.g. Venus D)
    """

    def _calculate(self, data: dict) -> None:
        """Build version string from raw register values without float-scaling."""
        dependency_keys = self.get_dependency_keys()
        raw_values = {}
        for alias, actual_key in dependency_keys.items():
            val = data.get(actual_key)
            if val is None:
                return
            raw_values[alias] = val

        try:
            self._attr_native_value = self.calculate_value(raw_values)
        except Exception as ex:
            _LOGGER.warning("Error building version string for %s: %s", self._key, ex)
            self._attr_native_value = None

    def calculate_value(self, raw_values: dict):
        mode = self.definition.get("mode")
        if mode in ("ems_bms", "ems_vms_bms", "ems_vms_mppt_bms"):
            ems_raw = int(raw_values["ems"])
            bms = int(raw_values["bms"])
            vms_raw = raw_values.get("vms")
            # ems_version: 4-digit encodes tenths (1476 -> 147.6), 3-digit = whole
            if ems_raw >= 1000:
                ems_str = f"{ems_raw // 10}.{ems_raw % 10}"
            else:
                ems_str = str(ems_raw)

            if mode == "ems_bms":
                return f"V{ems_str}.{bms}"

            # ems_vms_bms / ems_vms_mppt_bms expect a vms part.
            if vms_raw is None:
                _LOGGER.warning("%s missing vms for mode '%s'", self._key, mode)
                return None
            vms = int(vms_raw)

            if mode == "ems_vms_bms":
                return f"V{ems_str}.{vms}.{bms}"

            # ems_vms_mppt_bms adds the MPPT firmware version (Venus D/A).
            mppt_raw = raw_values.get("mppt")
            if mppt_raw is None:
                _LOGGER.warning("%s missing mppt for mode '%s'", self._key, mode)
                return None
            mppt = int(mppt_raw)
            return f"V{ems_str}.{vms}.{mppt}.{bms}"
        _LOGGER.warning("%s unknown version mode '%s'", self._key, mode)
        return None


class MarstekDevSensor(MarstekSensor):
    """Diagnose-Sensor fuer noch nicht gedeutete Register.

    Unterschied zu MarstekSensor: Der Name kommt direkt aus der Definition statt
    aus einem Uebersetzungsschluessel. Fuer DEV-Register gibt es keine
    Uebersetzungen -- mit translation_key blieben die Entitaeten namenlos.

    Das Schema ist "DEV <register> (<verdacht>?)". Alle DEV-Entitaeten beginnen
    mit "DEV" und stehen dadurch in der Oberflaeche beieinander; das Fragezeichen
    macht deutlich, dass der Name eine Vermutung ist und kein Befund.
    """

    def __init__(self, coordinator: MarstekCoordinator, definition: dict):
        super().__init__(coordinator, definition)
        # translation_key entfernen, sonst sucht HA eine Uebersetzung, findet
        # keine und zeigt die Entitaet ohne Namen an.
        self._attr_translation_key = None
        self._attr_name = definition.get("name") or f"DEV {definition.get('register')}"
        self._attr_has_entity_name = True
