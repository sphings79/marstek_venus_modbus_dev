"""
Repair flows for the issues this integration raises.

Only one issue exists today: the device leaving RS485 control mode on its own.
The flow asks for confirmation and then writes the register back, so the write
happens because somebody pressed a button — not silently in the background as a
reaction to a device state whose mechanism is still being worked out.
"""

import logging

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ISSUE_RS485_CONTROL_MODE_RESET

_LOGGER = logging.getLogger(__name__)


class RS485ControlModeRepairFlow(RepairsFlow):
    """Offer to switch RS485 control mode back on."""

    def __init__(self, entry_id: str) -> None:
        """Remember which config entry this issue belongs to."""
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, str] | None = None):
        """Start the flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None):
        """Confirm, then write the register."""
        if user_input is None:
            return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))

        coordinator = (self.hass.data.get(DOMAIN) or {}).get(self._entry_id)
        if coordinator is None:
            return self.async_abort(reason="entry_not_loaded")

        if not await coordinator.async_restore_rs485_control_mode():
            return self.async_abort(reason="write_failed")

        return self.async_create_entry(title="", data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the flow that repairs `issue_id`."""
    if issue_id.startswith(ISSUE_RS485_CONTROL_MODE_RESET):
        entry_id = (data or {}).get("entry_id")
        return RS485ControlModeRepairFlow(str(entry_id) if entry_id else "")

    raise ValueError(f"Unknown repair issue: {issue_id}")
