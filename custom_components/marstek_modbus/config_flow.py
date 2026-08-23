"""Config flow for Marstek Venus Modbus integration."""
import asyncio
import logging
import socket

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.translation import async_get_translations

from .const import (
    CONF_DEV_REGISTERS_DUPLICATE,
    CONF_DEV_REGISTERS_LEGACY,
    CONF_DEV_REGISTERS_UNKNOWN,
    CONF_MESSAGE_WAIT_MS,
    DEFAULT_DEV_REGISTERS,
    DEFAULT_MESSAGE_WAIT_MS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVALS,
    DEFAULT_UNIT_ID,
    DOMAIN,
    SUPPORTED_VERSIONS,
)
from .helpers.modbus_client import MarstekModbusClient

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_VERSION = "device_version"
CONF_UNIT_ID = "unit_id"

# Schema constants for reusable form definitions
SCHEMA_HOST_BASE = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.Coerce(int),
    }
)

# Connection options: the host fields plus the request pacing. The pacing is
# deliberately absent from the initial setup form - the default is right for
# every device tested, and it only needs raising when a gateway chokes.
SCHEMA_CONNECTION = SCHEMA_HOST_BASE.extend(
    {
        vol.Optional(
            CONF_MESSAGE_WAIT_MS, default=DEFAULT_MESSAGE_WAIT_MS
        ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=1000)),
    }
)

# Schema for polling intervals
SCHEMA_POLLING = vol.Schema(
    {
        vol.Required("high"): vol.All(vol.Coerce(int), vol.Clamp(min=1, max=3600)),
        vol.Required("low"): vol.All(vol.Coerce(int), vol.Clamp(min=1, max=3600)),
    }
)


class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for the Marstek Venus Modbus integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user inputs connection details.

        Validates user input and attempts connection to the Modbus device.
        """
        errors = {}

        # Determine user language, fallback to English
        language = self.context.get("language", "en")

        # Load translations for localized messages
        translations = await async_get_translations(
            self.hass,
            language,
            category="config",
            integrations=[DOMAIN]
        )

        if user_input is not None:
            host = user_input.get(CONF_HOST)
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            device_version = user_input.get(
                CONF_DEVICE_VERSION, SUPPORTED_VERSIONS[0]
            )
            unit_id = user_input.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)

            # Validate port and unit_id ranges
            if not (1 <= port <= 65535):
                errors["base"] = "invalid_port"
            elif not (1 <= unit_id <= 255):
                errors["base"] = "invalid_unit_id"

            if errors:
                # Re-show form with preserved user input
                user_schema = SCHEMA_HOST_BASE.extend(
                    {vol.Required(CONF_DEVICE_VERSION): vol.In(SUPPORTED_VERSIONS)}
                )
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.add_suggested_values_to_schema(
                        user_schema, user_input
                    ),
                    errors=errors,
                )

            # Validate the host by resolving it to an IP address
            try:
                socket.gethostbyname(host)
            except (socket.gaierror, TypeError):
                errors["base"] = "invalid_host"
            else:
                # Prevent duplicate entries for same host, port and unit_id
                for entry in self._async_current_entries():
                    if (
                        entry.data.get(CONF_HOST) == host
                        and entry.data.get(CONF_PORT) == port
                        and entry.data.get(CONF_UNIT_ID) == unit_id
                    ):
                        return self.async_abort(reason="already_configured")

                # Test Modbus connection including unit_id validation
                errors["base"] = await async_test_modbus_connection(
                    host, port, unit_id
                )

                # Create configuration entry if no errors
                if not errors["base"]:
                    title = translations.get(
                        "config.step.user.title", "Marstek Venus Modbus"
                    )
                    data = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_DEVICE_VERSION: device_version,
                        CONF_UNIT_ID: unit_id,
                    }
                    return self.async_create_entry(title=title, data=data)

        # Show form for user input with description placeholders
        description_placeholders = {
            "device_version_choices": ", ".join(
                f"{v}: {translations.get(f'config.step.user.data.device_version|{v}', v)}"
                for v in SUPPORTED_VERSIONS
            )
        }

        # Extend base schema with device_version for initial config
        user_schema = SCHEMA_HOST_BASE.extend(
            {vol.Required(CONF_DEVICE_VERSION): vol.In(SUPPORTED_VERSIONS)}
        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                user_schema, user_input or {}
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )
    
    async def async_step_reauth(self, data=None):
        """Re-authentication step for missing device_version."""
        errors = {}
        language = self.context.get("language", self.hass.config.language)
        translations = await async_get_translations(
            self.hass, language, category="config", integrations=[DOMAIN]
        )

        if data is not None:
            entry = (
                self._async_current_entries()[0]
                if self._async_current_entries()
                else None
            )
            if entry:
                try:
                    new_data = dict(entry.data)
                    new_data[CONF_DEVICE_VERSION] = data.get(CONF_DEVICE_VERSION)
                    await self.hass.config_entries.async_update_entry(
                        entry, data=new_data
                    )
                    return self.async_create_entry(
                        title=entry.title or DOMAIN, data={}
                    )
                except Exception as exc:
                    _LOGGER.error(
                        "Failed to update config entry during reauth: %s", exc
                    )
                    errors["base"] = "unknown"

        description_placeholders = {
            "device_version_choices": ", ".join(
                f"{v}: {translations.get(f'config.step.user.data.device_version|{v}', v)}"
                for v in SUPPORTED_VERSIONS
            )
        }

        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_VERSION, default=SUPPORTED_VERSIONS[0]
                    ): vol.In(SUPPORTED_VERSIONS)
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MarstekOptionsFlow(config_entry)


class MarstekOptionsFlow(config_entries.OptionsFlow):
    """Handle Marstek Venus Modbus options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options flow by delegating to a menu step."""
        return await self.async_step_menu()

    async def async_step_menu(self, user_input=None):
        """Show the options menu."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=["connection", "polling", "dev"],
        )

    async def async_step_polling(self, user_input=None):
        """Configure polling scan intervals."""
        errors = {}
        config = self._config_entry

        legacy_options = config.options or {}
        normalized_options = dict(legacy_options)
        if "high" not in normalized_options and "medium" in normalized_options:
            normalized_options["high"] = normalized_options["medium"]
        if "low" not in normalized_options and "very_low" in normalized_options:
            normalized_options["low"] = normalized_options["very_low"]

        # Get defaults from options, then data, then constants
        defaults = {
            key: normalized_options.get(
                key, config.data.get(key, DEFAULT_SCAN_INTERVALS[key])
            )
            for key in ("high", "low")
        }

        # Calculate lowest scan interval for description
        lowest = min((user_input or defaults).values())

        if user_input is not None:
            coordinator = self.hass.data.get(DOMAIN, {}).get(config.entry_id)
            if coordinator:
                coordinator._update_scan_intervals(user_input)

            # Save and return to menu
            self.hass.config_entries.async_update_entry(
                config,
                options={
                    **{
                        key: value
                        for key, value in config.options.items()
                        if key not in {"medium", "very_low"}
                    },
                    **user_input,
                },
            )
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="polling",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_POLLING, defaults
            ),
            errors=errors,
            description_placeholders={"lowest": str(lowest)},
            last_step=True,
        )

    async def async_step_dev(self, user_input=None):
        """DEV-Register ein- oder ausschalten.

        Zwei getrennte Gruppen zusaetzlicher Diagnose-Sensoren:

        unbekannt   Register, deren Bedeutung nicht geklaert ist - teils mit
                    Konfidenz niedrig/mittel aus der Firmware-Analyse, teils
                    Register aus dem 40000er-Bereich, die nachweislich auf
                    einen Lesezugriff antworten.
        Doppelungen Register, die denselben Wert liefern wie ein bereits
                    integrierter Sensor: Aliase auf dieselbe SRAM-Quelle,
                    Spiegelregister, Folgeregister eines mehrteiligen Blocks.

        Beide heissen "DEV <register> (<verdacht>?)" und liegen in der Kategorie
        Diagnose. Nach dem Umschalten wird der Config-Entry neu geladen, weil die
        Registerdefinitionen beim Start eingelesen werden.
        """
        config = self._config_entry
        options = config.options or {}
        # Migration: der alte Sammelschalter schaltet beide Gruppen, solange die
        # neuen Schluessel fehlen.
        legacy = bool(options.get(CONF_DEV_REGISTERS_LEGACY, DEFAULT_DEV_REGISTERS))
        current = {
            CONF_DEV_REGISTERS_UNKNOWN: bool(
                options.get(CONF_DEV_REGISTERS_UNKNOWN, legacy)
            ),
            CONF_DEV_REGISTERS_DUPLICATE: bool(
                options.get(CONF_DEV_REGISTERS_DUPLICATE, legacy)
            ),
        }

        if user_input is not None:
            new = {
                key: bool(user_input.get(key, DEFAULT_DEV_REGISTERS))
                for key in current
            }
            merged = {
                key: value
                for key, value in options.items()
                if key != CONF_DEV_REGISTERS_LEGACY
            }
            merged.update(new)
            self.hass.config_entries.async_update_entry(config, options=merged)
            if new != current:
                # Definitionen werden nur beim Setup geladen -> Reload noetig.
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(config.entry_id)
                )
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="dev",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DEV_REGISTERS_UNKNOWN,
                        default=current[CONF_DEV_REGISTERS_UNKNOWN],
                    ): bool,
                    vol.Optional(
                        CONF_DEV_REGISTERS_DUPLICATE,
                        default=current[CONF_DEV_REGISTERS_DUPLICATE],
                    ): bool,
                }
            ),
            last_step=True,
        )

    async def async_step_connection(self, user_input=None):
        """Configure host, port and unit id."""
        errors = {}
        config = self._config_entry

        # Get defaults from config data
        defaults = {
            CONF_HOST: config.data.get(CONF_HOST, ""),
            CONF_PORT: config.data.get(CONF_PORT, DEFAULT_PORT),
            CONF_UNIT_ID: config.options.get(
                CONF_UNIT_ID, config.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ),
            CONF_MESSAGE_WAIT_MS: config.data.get(
                CONF_MESSAGE_WAIT_MS, DEFAULT_MESSAGE_WAIT_MS
            ),
        }

        if user_input is not None:
            host = user_input.get(CONF_HOST)
            port = user_input.get(CONF_PORT)
            unit_id = user_input.get(CONF_UNIT_ID)
            message_wait_ms = int(
                user_input.get(CONF_MESSAGE_WAIT_MS, DEFAULT_MESSAGE_WAIT_MS)
            )

            # Validate ranges
            if not (1 <= int(port) <= 65535):
                errors["base"] = "invalid_port"
            elif not (1 <= int(unit_id) <= 255):
                errors["base"] = "invalid_unit_id"

            if not errors:
                coordinator = self.hass.data.get(DOMAIN, {}).get(config.entry_id)

                # Close existing client to free resources
                if coordinator:
                    try:
                        await coordinator.async_close()
                    except Exception:
                        _LOGGER.debug(
                            "Existing coordinator client close failed or was not connected"
                        )

                # Test connection with new parameters
                try:
                    test_client = MarstekModbusClient(
                        host,
                        int(port),
                        message_wait_ms=message_wait_ms,
                        timeout=getattr(coordinator, "timeout", 3),
                        unit_id=int(unit_id),
                    )
                    connected = await test_client.async_connect()
                except Exception as exc:
                    _LOGGER.debug(
                        "Error while testing new Modbus connection: %s", exc
                    )
                    connected = False

                if not connected:
                    try:
                        await test_client.async_close()
                    except Exception:
                        pass
                    errors["base"] = "cannot_connect"
                else:
                    # Connection successful, update config and coordinator
                    try:
                        new_data = dict(config.data)
                        new_data[CONF_HOST] = host
                        new_data[CONF_PORT] = int(port)
                        new_data[CONF_UNIT_ID] = int(unit_id)
                        new_data[CONF_MESSAGE_WAIT_MS] = message_wait_ms
                        self.hass.config_entries.async_update_entry(
                            config, data=new_data
                        )

                        if coordinator:
                            coordinator.client = test_client
                            coordinator.host = host
                            coordinator.port = int(port)
                            coordinator.unit_id = int(unit_id)
                            coordinator.message_wait_ms = message_wait_ms
                            _LOGGER.info(
                                "Reconnected Modbus client to %s:%d (unit %d, %d ms between messages)",
                                host,
                                int(port),
                                int(unit_id),
                                message_wait_ms,
                            )

                            try:
                                await coordinator.async_refresh()
                            except Exception:
                                _LOGGER.debug(
                                    "Coordinator refresh after reconnect failed"
                                )

                        # Return to menu after successful connection update
                        return await self.async_step_menu()
                    except Exception as exc:
                        _LOGGER.error(
                            "Failed to update config entry for host/port/unit: %s",
                            exc,
                        )
                        errors["base"] = "unknown"

        return self.async_show_form(
            step_id="connection",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_CONNECTION, defaults
            ),
            errors=errors,
            last_step=True,
        )


async def async_test_modbus_connection(host: str, port: int, unit_id: int = 1):
    """Test Modbus connection.

    Returns error key string or None if successful.
    """
    _LOGGER.debug(
        "Testing Modbus connection to %s:%d with unit %d", host, port, unit_id
    )

    client = MarstekModbusClient(host, int(port), timeout=3, unit_id=int(unit_id))
    try:
        connected = await client.async_connect()
        if not connected:
            _LOGGER.debug("Failed to connect to %s:%d", host, port)
            return "cannot_connect"

        await asyncio.sleep(0.1)

        # Validate unit_id by reading a known register
        try:
            result = await client.async_read_register(
                register=32104,
                data_type="uint16",
                count=1,
                sensor_key="_test_unit_id",
            )
            if result is None:
                _LOGGER.debug("No response when reading register for unit_id test")
                return "unit_id_no_response"
            if isinstance(result, (int, float, bool)):
                _LOGGER.debug("Unit ID %d test succeeded (value=%s)", unit_id, result)
                return None
            _LOGGER.debug(
                "Unit ID %d returned non-numeric response: %r", unit_id, result
            )
            return None

        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout testing unit_id %d", unit_id)
            return "unit_id_no_response"
        except Exception as exc:
            _LOGGER.debug("Error during unit_id test: %s", exc)
            return None

    except Exception as exc:
        _LOGGER.debug("Exception during Modbus client connect test: %s", exc)
        return "cannot_connect"
    finally:
        try:
            await client.async_close()
        except Exception:
            pass
    return None