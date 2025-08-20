"""Sensor platform for LSTech Balance integration."""
from __future__ import annotations
import logging
from datetime import timedelta, datetime, timezone
from functools import partial
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass, DOMAIN as ENTITY_DOMAIN
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.exceptions import ConfigEntryAuthFailed
from . import MyEntries
from .const import (
    DOMAIN,
    CONF_ACCOUNT,
    CONF_NICKNAME,
    CONF_SCAN_INTERVAL,
    CONF_AUTO_OWN_DATA,
    CONF_MULTI_USERS,
    DEFAULT_SCAN_INTERVAL
)
from .api import LSTechAPI

_LOGGER = logging.getLogger(__name__)


async def goto_reauth(hass: HomeAssistant, entry: ConfigEntry):
        persistent_notification.async_create(
            hass=hass,
            message=f"帐号 {entry.data[CONF_ACCOUNT]} 的登录状态已失效,请重新登录\r\n[点击这里快速跳转](/config/integrations/integration/{DOMAIN})",
            title=f"需要重新验证",
            notification_id=f"{DOMAIN}_reauth_notification_{entry.data[CONF_ACCOUNT]}"
        )
        hass.add_job(entry.async_start_reauth, hass)

async def update_detail(hass: HomeAssistant, entry: ConfigEntry, api, rawDataId=None) -> None:
    try:
        if rawDataId and entry.options.get(CONF_AUTO_OWN_DATA, False):
            await hass.async_add_executor_job(api.own_data, rawDataId)
        coordinator_detail: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]['coordinator']['detail']
        await coordinator_detail.async_request_refresh()
    except ConfigEntryAuthFailed as err:
        await goto_reauth(hass, entry)
        raise
    except Exception as err:
        # 其他错误抛出UpdateFailed
        raise UpdateFailed(f"Error communicating with API: {err}") from err
    

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LSTech Balance sensor from config entry."""
    api = LSTechAPI()
    
    # Restore API state from config entry
    api.uid = entry.data["uid"]
    api.member_id = entry.data["member_id"]
    api.access_token = entry.data["access_token"]
    api.refresh_token = entry.data["refresh_token"]
    api.access_token_expire = entry.data["access_token_expire"]
    api.refresh_token_expire = entry.data["refresh_token_expire"]
    api.last_token_refresh = entry.data["last_token_refresh"]
    api.last_login_time = entry.data["last_login_time"]
    
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    # 自定义更新方法，处理token刷新失败
    async def async_update_data(step=None, memberId=None):
        """Fetch data from API endpoint."""
        try:
            o_last_token_refresh = api.last_token_refresh
            o_access_token = api.access_token
            if step == 'detail':
                data = await hass.async_add_executor_job(api.get_history, memberId)
                _LOGGER.debug(f"get_history {entry.data.get(CONF_NICKNAME)} {data}")
                if data and 'createTime' in data:
                    measureId = data.get("measureId")
                    data = await hass.async_add_executor_job(api.get_detail, measureId, memberId)
                    if data:
                        order_data = {"memberId":str(api.member_id)}
                        order_data.update(data)
                        data = order_data
                    _LOGGER.debug(f"get_detail {entry.data.get(CONF_NICKNAME)} {data}")
                if data is None:
                    data = {"memberId":str(memberId) if memberId else str(api.member_id)}
            else:
                data = await hass.async_add_executor_job(api.get_weight_data)
                _LOGGER.debug(f"get_weight_data {entry.data.get(CONF_NICKNAME)} {data}")
                if data and 'timestamp' in data:
                    ts = data.get("timestamp")/1000
                    data["timestamp"] = ts
                    data["iso_timestamp"] = datetime.utcfromtimestamp(ts).isoformat() + "Z" if ts else None
            if api.last_token_refresh != o_last_token_refresh or api.access_token != o_access_token:
                updated_data = {**entry.data}
                updated_data["last_token_refresh"] = api.last_token_refresh
                updated_data["access_token"] = api.access_token
                hass.config_entries.async_update_entry(entry, data=updated_data)
            return data
        except ConfigEntryAuthFailed as err:
            await goto_reauth(hass, entry)
            raise
        except Exception as err:
            # 其他错误抛出UpdateFailed
            raise UpdateFailed(f"Error communicating with API: {err}") from err
    
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="lstech_balance",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval) if scan_interval>0 else None
    )
    coordinator_detail = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="lstech_balance_detail",
        update_method=partial(async_update_data, "detail"),
        update_interval=None
    )
    
    hass.data[DOMAIN][entry.entry_id]['coordinator'] = {'weight':coordinator, 'detail':coordinator_detail}
    
    async_add_entities([
        LSTechWeightSensor(coordinator, entry, api),
        LSTechDetailSensor(coordinator_detail, entry, api, coordinator)
    ], False)
    
    await coordinator.async_config_entry_first_refresh()
    
    if entry.options.get(CONF_MULTI_USERS):
        async def add_members():
            if (members := await hass.async_add_executor_job(api.get_members)) is not None:
                member_entities = []
                for member in members:
                    if member.get("myself") == "1":
                        continue
                    #member_attr = {key: member[key] for key in ['memberId','nickname'] if key in member}
                    member_coordinator = DataUpdateCoordinator(
                        hass,
                        _LOGGER,
                        name="lstech_balance_detail",
                        update_method=partial(async_update_data, "detail", member.get("memberId")),
                        update_interval=None
                    )
                    member_entities.append(LSTechDetailSensor(
                        member_coordinator,entry, api, coordinator, member
                    ))
                if member_entities:
                    async_add_entities(member_entities, True)
        hass.async_create_task(add_members())
        

class LSTechWeightSensor(SensorEntity, RestoreEntity):
    """Representation of a LSTech Weight sensor."""
    
    _attr_icon = "mdi:weight"
    _attr_native_unit_of_measurement = "kg"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    
    def __init__(self, coordinator, entry, api):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.entry = entry
        self.api = api
        self._attr_has_entity_name = True
        #self._attr_name = "weight"
        self._attr_translation_key = "weight"
        self.entity_id = f'{ENTITY_DOMAIN}.{DOMAIN}_{entry.data["uid"]}_weight'
        self._attr_unique_id = f"{entry.entry_id}_weight"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": None,
            "translation_key": "smart_scale",
            "translation_placeholders": {"owner": entry.data[CONF_NICKNAME]},
            "manufacturer": "LSTech",
            "model": "Smart Scale"
        }
        # 本地存储状态和属性
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        attributes = { k: v for k, v in self._attr_extra_state_attributes.items() if k in {'timestamp','raw_data_id'} }
        rawDataId = None
        is_updated = False
        if self.coordinator.data:
            is_updated = True
            if 'timestamp' in self._attr_extra_state_attributes and 'timestamp' in self.coordinator.data:
                old_ts = datetime.strptime(self._attr_extra_state_attributes.get('timestamp'), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                if self.coordinator.data.get("timestamp") < old_ts:
                    is_updated = False
            if is_updated:
                if "weight" in self.coordinator.data:
                    self._attr_native_value = self.coordinator.data["weight"]
                if "iso_timestamp" in self.coordinator.data:
                    attributes["timestamp"] = self.coordinator.data["iso_timestamp"]
                if "rawDataId" in self.coordinator.data:
                    attributes["raw_data_id"] = str(self.coordinator.data["rawDataId"])
                    rawDataId = self.coordinator.data["rawDataId"]
                
        if self.api.error_state:
            attributes["error"] = self.api.error_state
            attributes["error_time"] = self.api.error_time
        if attributes:
            is_updated = True
            self._attr_extra_state_attributes = attributes
                
        if is_updated:
            self.async_write_ha_state()
        self.hass.async_create_task(update_detail(self.hass, self.entry, self.api, rawDataId))
        
    @property
    def available(self):
        """Return True if entity is available."""
        # 只有在coordinator最后更新成功并且没有严重错误时才可用
        return self.coordinator.last_update_success and not self.api.auth_error
    
    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state.lower() in ["unknown", "unavailable", "none", "null"]:
                self._attr_native_value = None
            else:
                self._attr_native_value = last_state.state
            if last_state.attributes:
                self._attr_extra_state_attributes = {
                    k: v
                    for k, v in last_state.attributes.items()
                    if k not in {"attribution", "unit_of_measurement", "friendly_name", "icon"}
                }
        # 添加 Coordinator 监听器
        self.async_on_remove(
            self.coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        )
        # 如果 Coordinator 已有数据（首次刷新已完成），立即处理
        if self.coordinator.data is not None:
            self._handle_coordinator_update()
    
    async def async_update(self):
        """Update the entity."""
        await self.coordinator.async_request_refresh()
        

class LSTechDetailSensor(SensorEntity):    
    _attr_icon = "mdi:account-details"
    _attr_native_unit_of_measurement = "kg"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.WEIGHT
    
    def __init__(self, coordinator, entry, api, coordinator_data, member=None):
        self.coordinator = coordinator
        self.coordinator_data = coordinator_data
        self.entry = entry
        self.api = api
        self.member_id = member.get("memberId") if member else entry.data.get("member_id")
        self.nickname = member.get("nickname") if member else entry.data.get(CONF_NICKNAME)
        self._attr_has_entity_name = True
        #self._attr_name = "detail"
        self._attr_translation_key = "detail"
        self._attr_translation_placeholders = {CONF_NICKNAME: self.nickname}
        if self.member_id == entry.data.get("member_id"):
            self.entity_id = f'{ENTITY_DOMAIN}.{DOMAIN}_{entry.data["uid"]}_detail'
            self._attr_unique_id = f"{entry.entry_id}_detail"
        else:
            self.entity_id = f'{ENTITY_DOMAIN}.{DOMAIN}_{entry.data["uid"]}_detail_{self.member_id}'
            self._attr_unique_id = f"{entry.entry_id}_detail_{self.member_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": None,
            "translation_key": "smart_scale",
            "translation_placeholders": {"owner": entry.data[CONF_NICKNAME]},
            "manufacturer": "LSTech",
            "model": "Smart Scale"
        }
    
    def own_data(self, rawDataId, MemberId=None):
        return self.api.own_data(rawDataId, self.member_id if MemberId is None else MemberId)
    
    @property
    def state(self):
        if self.coordinator.data and "weight" in self.coordinator.data:
            return self.coordinator.data["weight"]
        return None
    
    @property
    def extra_state_attributes(self):
        attrs = {}
        if self.coordinator.data:
            attrs = {k: v for k, v in self.coordinator.data.items() if k not in {"headPictureUrl"}}
        if self.api.error_state:
            attrs["error"] = self.api.error_state
            attrs["error_time"] = self.api.error_time
            
        return attrs
    
    @property
    def available(self):
        return self.coordinator_data.last_update_success and self.coordinator.last_update_success and not self.api.auth_error
    
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(
                self.async_write_ha_state
            )
        )
        MyEntries[self.entry.entry_id][self.entity_id] = self
    
    async def async_will_remove_from_hass(self):
        await super().async_will_remove_from_hass()
        if self.entry.entry_id in MyEntries and self.entity_id in MyEntries[self.entry.entry_id]:
            MyEntries[self.entry.entry_id].pop(self.entity_id)
    
    async def async_update(self):
        await self.coordinator.async_request_refresh()