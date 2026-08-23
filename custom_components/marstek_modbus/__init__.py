"""
Main integration setup for Marstek Venus Modbus component.

Handles setting up and unloading config entries, initializing
the data coordinator, and forwarding setup to sensor and select platforms.
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import MarstekCoordinator
from .const import SUPPORTED_VERSIONS

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "sensor",
    "switch",
    "select",
    "button",
    "number",
    "binary_sensor",
] 


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """
    General setup of the integration.

    This is called once when Home Assistant starts.
    It does not perform any configuration and always returns True.

    Args:
        hass: Home Assistant instance.
        config: Configuration dict.

    Returns:
        True always.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up a config entry.

    Initializes the coordinator for this entry and stores it in hass.data.
    Forwards setup to platforms (e.g., sensor, select) used by this integration.

    Args:
        hass: Home Assistant instance.
        entry: ConfigEntry to setup.

    Returns:
        True if setup successful.

    Raises:
        ConfigEntryNotReady: if the device cannot be reached, so Home Assistant
            retries the setup later instead of leaving the entry unloaded.
        ConfigEntryError: if the entry itself is unusable and needs the user.
    """
    # Migrate legacy device_version tokens in existing config entries to
    # the canonical SUPPORTED_VERSIONS strings. This handles older
    # installations that used tokens like 'v1/v2' or 'v3'.
    raw_version = (entry.data.get("device_version") or "").strip()
    if raw_version:
        normalized = raw_version.lower()
        # Consider anything not listed in SUPPORTED_VERSIONS as legacy/unsupported.
        allowed = {s.lower() for s in SUPPORTED_VERSIONS}
        if normalized not in allowed:
            _LOGGER.warning(
                "Config entry %s uses unsupported device_version '%s'. Please remove and re-add the device with the correct device version. Supported versions: %s",
                entry.entry_id,
                raw_version,
                ", ".join(SUPPORTED_VERSIONS),
            )

    # Create the coordinator for data management and attempt an initial
    # connection before forwarding platform setup so the client is ready.
    try:
        coordinator = MarstekCoordinator(hass, entry)
    except ValueError as err:
        # Missing host/port: retrying will not help, the user has to reconfigure.
        raise ConfigEntryError(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    platforms_forwarded = False
    try:
        # Load register definitions off the event loop to avoid blocking
        try:
            await coordinator.async_load_registers(entry.data.get("device_version"))
        except Exception as err:
            _LOGGER.warning("Failed loading register definitions for entry %s: %s", entry.entry_id, err)

        # Establish the Modbus connection upfront so the first refresh does not
        # lazily reconnect on individual sensor reads, and failure is properly
        # tracked from the start.
        if not await coordinator.async_init():
            raise ConfigEntryNotReady(
                f"Cannot connect to Modbus device at {coordinator.host}:{coordinator.port}"
            )

        # Forward setup to all platforms defined in PLATFORMS
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        platforms_forwarded = True

        # Perform first refresh to ensure coordinator has up-to-date data.
        # Raises ConfigEntryNotReady by itself if the first poll fails.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Do not leave a half-set-up entry (platforms, an open socket) behind
        # when Home Assistant retries the setup later.
        if platforms_forwarded:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        await coordinator.async_close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry and its associated platforms.

    Args:
        hass: Home Assistant instance.
        entry: ConfigEntry to unload.

    Returns:
        True if unload successful, False otherwise.
    """
    try:
        # Unload all platforms for the entry
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

        if unload_ok:
            # Retrieve the coordinator and close it before removing
            coordinator = hass.data[DOMAIN][entry.entry_id]
            await coordinator.async_close()
            # Remove coordinator reference from hass data
            hass.data[DOMAIN].pop(entry.entry_id, None)

        return unload_ok
    except Exception as err:
        _LOGGER.error("Error unloading entry %s: %s", entry.entry_id, err)
        return False