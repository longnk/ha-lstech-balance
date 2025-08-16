"""Config flow for LSTech Balance integration."""
from __future__ import annotations
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.components import persistent_notification
from .const import (
    DOMAIN,
    CONF_NICKNAME,
    CONF_AUTHTYPE,
    CONF_ACCOUNT,
    CONF_PASSWD,
    CONF_VERIFICATION_CODE,
    CONF_SCAN_INTERVAL,
    CONF_AUTO_OWN_DATA,
    DEFAULT_SCAN_INTERVAL
)
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from .api import LSTechAPI

_LOGGER = logging.getLogger(__name__)

class LSTechBalanceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LSTech Balance."""
    
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL
    
    def __init__(self):
        """Initialize the config flow."""
        self.api = LSTechAPI()
        self.account = None
        self.password = None
        self.verification_code = None
        self.accounts = {}

    async def async_step_reauth(self, user_input=None):
        entry_id = self.context.get("entry_id")
        if not entry_id:
            return self.async_abort(reason="invalid_context")
        self.existing_entry = self.hass.config_entries.async_get_entry(entry_id)
        if not self.existing_entry:
            return self.async_abort(reason="entry_not_found")
        self.auth_type = self.existing_entry.data[CONF_AUTHTYPE]
        self.account = self.existing_entry.data[CONF_ACCOUNT]
        return await self.async_step_reauth_type()

    async def async_step_reauth_type(self, user_input=None):
        if user_input:
            if user_input["action"] == "login":
                return await self.async_step_reauth_login()
            elif user_input["action"] == "quickLogin":
                return await self.async_step_reauth_quickLogin()
            else:
                return self.async_abort(reason="invalid_auth_type")

        actions = {"login": "password(密码登录)", "quickLogin": "verification code(验证码登录)"}
        return self.async_show_form(
            step_id="reauth_type",
            data_schema=vol.Schema(
                {vol.Required("action", default=self.auth_type): vol.In(actions)}
            ),
            last_step=False
        )

    async def async_step_reauth_login(self, user_input=None):
        errors = {}
        if user_input is not None:
            self.password = user_input[CONF_PASSWD]
            options = {CONF_SCAN_INTERVAL:user_input[CONF_SCAN_INTERVAL], CONF_AUTO_OWN_DATA:user_input[CONF_AUTO_OWN_DATA]}
            # Attempt login
            result = await self.hass.async_add_executor_job(
                self.api.login, self.account, self.password
            )
            
            if result.get("code") == "0":                
                account_data = {
                    CONF_AUTHTYPE: "login",
                    CONF_ACCOUNT: self.account,
                    CONF_NICKNAME: self.api.nickname,
                    "uid": self.api.uid,
                    "access_token": self.api.access_token,
                    "refresh_token": self.api.refresh_token,
                    "access_token_expire": self.api.access_token_expire,
                    "refresh_token_expire": self.api.refresh_token_expire,
                    "member_id": self.api.member_id,
                    "last_token_refresh": self.api.last_token_refresh,
                    "last_login_time": self.api.last_login_time
                }
                
                persistent_notification.async_dismiss(
                    hass=self.hass,
                    notification_id=f"{DOMAIN}_reauth_notification_{self.account}"
                )
                return self.async_update_reload_and_abort(
                    self.existing_entry,
                    data_updates=account_data,
                    options=options
                )
            
            errors["base"] = result.get("msg", "login_failed")
        
        return self.async_show_form(
            step_id="reauth_login",
            data_schema=vol.Schema({
                vol.Optional(CONF_ACCOUNT,default=self.account): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT, read_only=True)
                ),
                vol.Required(CONF_PASSWD): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.existing_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): int,
                vol.Optional(CONF_AUTO_OWN_DATA, default=self.existing_entry.options.get(CONF_AUTO_OWN_DATA, False)): bool
            }),
            errors=errors
        )

    async def async_step_reauth_quickLogin(self, user_input=None):
        errors = {}
        if user_input is not None:            
            result = await self.hass.async_add_executor_job(
                self.api.send_verification_code, self.account
            )
            
            if result.get("code") == "0":
                return await self.async_step_reauth_quickLogin2()
            
            errors["base"] = result.get("msg", "unknown_error")
        
        return self.async_show_form(
            step_id="reauth_quickLogin",
            data_schema=vol.Schema({
                vol.Optional(CONF_ACCOUNT,default=self.account): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT, read_only=True)
                )
            }),
            errors=errors
        )

    async def async_step_reauth_quickLogin2(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            self.verification_code = user_input.get(CONF_VERIFICATION_CODE)
            if not self.verification_code or self.verification_code.strip() == "":
                result = await self.hass.async_add_executor_job(
                    self.api.send_verification_code, self.account
                )
                if result.get("code") != "0":
                    errors["base"] = result.get("msg", "unknown_error")
            else:
                options = {CONF_SCAN_INTERVAL:user_input[CONF_SCAN_INTERVAL], CONF_AUTO_OWN_DATA:user_input[CONF_AUTO_OWN_DATA]}
                # Attempt login
                result = await self.hass.async_add_executor_job(
                    self.api.quickLogin, self.account, self.verification_code
                )
                
                if result.get("code") == "0":                
                    account_data = {
                        CONF_AUTHTYPE: "quickLogin",
                        CONF_ACCOUNT: self.account,
                        CONF_NICKNAME: self.api.nickname,
                        "uid": self.api.uid,
                        "access_token": self.api.access_token,
                        "refresh_token": self.api.refresh_token,
                        "access_token_expire": self.api.access_token_expire,
                        "refresh_token_expire": self.api.refresh_token_expire,
                        "member_id": self.api.member_id,
                        "last_token_refresh": self.api.last_token_refresh,
                        "last_login_time": self.api.last_login_time
                    }
                    
                    await self.hass.services.async_call(
                        "persistent_notification",
                        "dismiss",
                        {"notification_id": f"{DOMAIN}_reauth_notification_{self.account}"}
                    )
                    
                    return self.async_update_reload_and_abort(
                        self.existing_entry,
                        data_updates=account_data,
                        options=options
                    )
                
                errors["base"] = result.get("msg", "login_failed")
        
        return self.async_show_form(
            step_id="reauth_quickLogin2",
            data_schema=vol.Schema({
                vol.Optional(CONF_VERIFICATION_CODE): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.existing_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): int,
                vol.Optional(CONF_AUTO_OWN_DATA, default=self.existing_entry.options.get(CONF_AUTO_OWN_DATA, False)): bool
            }),
            errors=errors
        )
    
    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        
        if user_input:
            if user_input["action"] == "login":
                return await self.async_step_login()
            elif user_input["action"] == "quickLogin":
                return await self.async_step_quickLogin()

        actions = {"login": "password(密码登录)", "quickLogin": "verification code(验证码登录)"}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("action", default="login"): vol.In(actions)}
            ),
            last_step=False
        )
        

    async def async_step_login(self, user_input=None):
        errors = {}
        
        if user_input is not None:
            self.account = user_input[CONF_ACCOUNT]
            await self.async_set_unique_id(self.account)
            self._abort_if_unique_id_configured()
            
            self.password = user_input[CONF_PASSWD]
            options = {CONF_SCAN_INTERVAL:user_input[CONF_SCAN_INTERVAL], CONF_AUTO_OWN_DATA:user_input[CONF_AUTO_OWN_DATA]}
            # Attempt login
            result = await self.hass.async_add_executor_job(
                self.api.login, self.account, self.password
            )
            
            if result.get("code") == "0":
                # Check if UID already exists
                for entry in self._async_current_entries():
                    if entry.data.get("uid") == self.api.uid:
                        return self.async_abort(reason="account_exists")
                
                # Create account data
                account_data = {
                    CONF_AUTHTYPE: "login",
                    CONF_ACCOUNT: self.account,
                    CONF_NICKNAME: self.api.nickname,
                    "uid": self.api.uid,
                    "access_token": self.api.access_token,
                    "refresh_token": self.api.refresh_token,
                    "access_token_expire": self.api.access_token_expire,
                    "refresh_token_expire": self.api.refresh_token_expire,
                    "member_id": self.api.member_id,
                    "last_token_refresh": self.api.last_token_refresh,
                    "last_login_time": self.api.last_login_time
                }
                
                return self.async_create_entry(
                    title=self.api.nickname,
                    data=account_data,
                    options=options
                )
            
            errors["base"] = result.get("msg", "login_failed")
        
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema({
                vol.Required(CONF_ACCOUNT,default=self.account): str,
                vol.Required(CONF_PASSWD,default=self.password): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_SCAN_INTERVAL
                ): int,
                vol.Optional(CONF_AUTO_OWN_DATA, default=False): bool
            }),
            errors=errors
        )

    async def async_step_quickLogin(self, user_input=None):
        """Handle phone number input."""
        errors = {}
        
        if user_input is not None:
            self.account = user_input[CONF_ACCOUNT]
            
            # Check if account already exists
            await self.async_set_unique_id(self.account)
            self._abort_if_unique_id_configured()
            
            # Send verification code
            result = await self.hass.async_add_executor_job(
                self.api.send_verification_code, self.account
            )
            
            if result.get("code") == "0":
                return await self.async_step_quickLogin2()
            
            errors["base"] = result.get("msg", "unknown_error")
        
        return self.async_show_form(
            step_id="quickLogin",
            data_schema=vol.Schema({
                vol.Required(CONF_ACCOUNT,default=self.account): str
            }),
            errors=errors
        )
    
    async def async_step_quickLogin2(self, user_input=None):
        """Handle verification code input."""
        errors = {}
        
        if user_input is not None:
            self.verification_code = user_input.get(CONF_VERIFICATION_CODE)
            if not self.verification_code or self.verification_code.strip() == "":
                result = await self.hass.async_add_executor_job(
                    self.api.send_verification_code, self.account
                )
                if result.get("code") != "0":
                    errors["base"] = result.get("msg", "unknown_error")
            else:
                options = {CONF_SCAN_INTERVAL:user_input[CONF_SCAN_INTERVAL], CONF_AUTO_OWN_DATA:user_input[CONF_AUTO_OWN_DATA]}
                # Attempt login
                result = await self.hass.async_add_executor_job(
                    self.api.quickLogin, self.account, self.verification_code
                )
                
                if result.get("code") == "0":
                    # Check if UID already exists
                    for entry in self._async_current_entries():
                        if entry.data.get("uid") == self.api.uid:
                            return self.async_abort(reason="account_exists")
                    
                    # Create account data
                    account_data = {
                        CONF_AUTHTYPE: "quickLogin",
                        CONF_ACCOUNT: self.account,
                        CONF_NICKNAME: self.api.nickname,
                        "uid": self.api.uid,
                        "access_token": self.api.access_token,
                        "refresh_token": self.api.refresh_token,
                        "access_token_expire": self.api.access_token_expire,
                        "refresh_token_expire": self.api.refresh_token_expire,
                        "member_id": self.api.member_id,
                        "last_token_refresh": self.api.last_token_refresh,
                        "last_login_time": self.api.last_login_time
                    }
                    
                    return self.async_create_entry(
                        title=self.api.nickname,
                        data=account_data,
                        options=options
                    )
                
                errors["base"] = result.get("msg", "login_failed")
        
        return self.async_show_form(
            step_id="quickLogin2",
            data_schema=vol.Schema({
                vol.Optional(CONF_VERIFICATION_CODE): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_SCAN_INTERVAL
                ): int,
                vol.Optional(CONF_AUTO_OWN_DATA, default=False): bool
            }),
            errors=errors
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return LSTechBalanceOptionsFlow(config_entry)

class LSTechBalanceOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for LSTech Balance."""
    
    def __init__(self, config_entry):
        """Initialize options flow."""
        pass
    
    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    )
                ): int,
                vol.Optional(CONF_AUTO_OWN_DATA, default=self.config_entry.options.get(
                        CONF_AUTO_OWN_DATA, False
                    )): bool
            })
        )