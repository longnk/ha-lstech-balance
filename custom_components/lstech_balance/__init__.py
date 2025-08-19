"""The LSTech Balance integration."""
from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall, SupportsResponse
from .const import DOMAIN, PLATFORMS, ATTR_ENTITY_ID

_LOGGER = logging.getLogger(__name__)

MyEntries: dict = {}

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    setup_service_own_data(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LSTech Balance from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]['data'] = entry.data
    MyEntries.setdefault(entry.entry_id, {})
    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    MyEntries.pop(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
    
def setup_service_own_data(hass: HomeAssistant):
    async def service(call: ServiceCall):
        entity_ids = call.data.get(ATTR_ENTITY_ID)
        if not entity_ids:
            return {"code": -1, "msg": "no entity id"}
        rawDataId = call.data.get("raw_data_id")
        MemberId = call.data.get("member_id")
        for entry in MyEntries.values():
            for entity_id, entity in entry.items():
                if entity_id not in entity_ids:
                    continue
                result = await hass.async_add_executor_job(entity.api.own_data, rawDataId, MemberId)
                return {"code": 0, "msg": "success"} if result else {"code": -1, "msg": entity.api.error_state}
        return {"code": -1, "msg": "unknown error"}
    hass.services.async_register(
        DOMAIN, "own_data", service,
        supports_response=SupportsResponse.OPTIONAL,
    )