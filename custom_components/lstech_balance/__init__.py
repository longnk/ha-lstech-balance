"""The LSTech Balance integration."""
from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall, SupportsResponse
from homeassistant.helpers.event import async_call_later
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
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    MyEntries.pop(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
    
async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle update."""
    await hass.config_entries.async_reload(config_entry.entry_id)

def setup_service_own_data(hass: HomeAssistant):
    async def service(call: ServiceCall):
        entity_ids = call.data.get(ATTR_ENTITY_ID)
        if not entity_ids:
            return {"code": "-1", "msg": "no entity id"}
        rawDataId = call.data.get("raw_data_id")
        MemberId = call.data.get("member_id")
        update_immediately = call.data.get("update_immediately", False)
        for entry in MyEntries.values():
            for entity_id, entity in entry.items():
                if entity_id != entity_ids:
                    continue
                result = await hass.async_add_executor_job(entity.service_own_data, rawDataId, MemberId)
                if result and update_immediately:
                    if MemberId is None:
                        async_call_later(hass, 1, entity.service_async_update)
                    else:
                        is_updated = False
                        for _entry in MyEntries.values():
                            for _entity in _entry.values():
                                if _entity.member_id == MemberId:
                                    async_call_later(hass, 1, _entity.service_async_update)
                                    is_updated = True
                                    break
                            if is_updated:
                                break
                return {"code": "0", "msg": "success"} if result else {"code": "-1", "msg": entity.api.error_state}
        return {"code": "-1", "msg": "unknown error"}
    hass.services.async_register(
        DOMAIN, "own_data", service,
        supports_response=SupportsResponse.OPTIONAL,
    )