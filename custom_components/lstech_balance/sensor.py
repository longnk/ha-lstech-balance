"""Sensor platform for LSTech Balance integration."""
from __future__ import annotations
import logging
from datetime import timedelta, datetime, timezone
from homeassistant.components.sensor import SensorEntity
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DOMAIN, ATTRIBUTION, CONF_ACCOUNT, CONF_NICKNAME, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .api import LSTechAPI

_LOGGER = logging.getLogger(__name__)

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    new_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator: CustomCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.set_update_interval(new_interval)
    #await coordinator.async_request_refresh()

class CustomCoordinator(DataUpdateCoordinator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args,**kwargs)

    def set_update_interval(self, new_interval) -> None:
        self.update_interval = timedelta(seconds=new_interval) if new_interval>0 else None
        # 取消当前定时器并立即启动新定时器
        self._schedule_refresh()

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
    async def async_update_data():
        """Fetch data from API endpoint."""
        try:
            o_last_token_refresh = api.last_token_refresh
            o_access_token = api.access_token
            data = await hass.async_add_executor_job(api.get_weight_data)
            if api.last_token_refresh != o_last_token_refresh or api.access_token != o_access_token:
                updated_data = {**entry.data}
                updated_data["last_token_refresh"] = api.last_token_refresh
                updated_data["access_token"] = api.access_token
                hass.config_entries.async_update_entry(entry, data=updated_data)
            if data and 'timestamp' in data:
                ts = data.get("timestamp")/1000
                data["timestamp"] = ts
                data["iso_timestamp"] = datetime.utcfromtimestamp(ts).isoformat() + "Z" if ts else None
            return data
        except ConfigEntryAuthFailed as err:
            persistent_notification.async_create(
                hass=hass,
                message=f"帐号 {entry.data[CONF_ACCOUNT]} 的登录状态已失效,请重新登录\r\n[点击这里快速跳转](/config/integrations/integration/{DOMAIN})",
                title=f"需要重新验证",
                notification_id=f"{DOMAIN}_reauth_notification_{entry.data[CONF_ACCOUNT]}"
            )
            hass.add_job(entry.async_start_reauth, hass)
            raise
        except Exception as err:
            # 其他错误抛出UpdateFailed
            raise UpdateFailed(f"Error communicating with API: {err}") from err
    
    coordinator = CustomCoordinator(
        hass,
        _LOGGER,
        name="lstech_balance",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval) if scan_interval>0 else None,
    )   
    await coordinator.async_config_entry_first_refresh()
    
    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    async_add_entities([
        LSTechWeightSensor(coordinator, entry, api)
    ], False)

class LSTechWeightSensor(SensorEntity, RestoreEntity):
    """Representation of a LSTech Weight sensor."""
    
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:weight"
    _attr_native_unit_of_measurement = "kg"
    _attr_should_poll = False
    
    def __init__(self, coordinator, entry, api):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.entry = entry
        self.api = api
        self._attr_name = f"{entry.data[CONF_NICKNAME]}的体脂秤 Weight"
        self._attr_unique_id = f"{entry.entry_id}_weight"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"{entry.data[CONF_NICKNAME]}的体脂秤",
            "manufacturer": "LSTech",
            "model": "Smart Scale"
        }
        # 本地存储状态和属性
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data:
            if 'timestamp' in self._attr_extra_state_attributes and 'timestamp' in self.coordinator.data:
                old_ts = datetime.strptime(self._attr_extra_state_attributes.get('timestamp'), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                if self.coordinator.data.get("timestamp") < old_ts:
                    return
            
            if "weight" in self.coordinator.data:
                self._attr_native_value = self.coordinator.data["weight"]
            
            attributes = {}
            if "iso_timestamp" in self.coordinator.data:
                attributes["timestamp"] = self.coordinator.data["iso_timestamp"]
            if "rawDataId" in self.coordinator.data:
                attributes["raw_data_id"] = self.coordinator.data["rawDataId"]
            
            if self.api.error_state:
                attributes["error"] = self.api.error_state
                attributes["error_time"] = self.api.error_time
            
            self._attr_extra_state_attributes = attributes
        # 触发状态写入
        self.async_write_ha_state()
        
    @property
    def available(self):
        """Return True if entity is available."""
        # 只有在coordinator最后更新成功并且没有严重错误时才可用
        return self.coordinator.last_update_success and not self.api.auth_error
    
    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_native_value = last_state.state
            if last_state.attributes:
                self._attr_extra_state_attributes = dict(last_state.attributes)
                for attr in ["attribution", "unit_of_measurement", "friendly_name", "icon"]:
                    self._attr_extra_state_attributes.pop(attr, None)
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