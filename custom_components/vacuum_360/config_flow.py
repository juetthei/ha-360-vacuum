import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Api360, Api360AuthError, Api360Error
from .const import CONF_QID, CONF_SID, DOMAIN


class Robot360ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            qid = user_input[CONF_QID].strip()
            sid = user_input[CONF_SID].strip()

            session = async_get_clientsession(self.hass)
            api = Api360(session, qid, sid)

            try:
                devices = await api.get_devices()
            except Api360AuthError:
                errors["base"] = "invalid_auth"
            except Api360Error:
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    await self.async_set_unique_id(qid)
                    self._abort_if_unique_id_configured()
                    count = len(devices)
                    return self.async_create_entry(
                        title=f"360 Vacuum ({count} Gerät{'e' if count != 1 else ''})",
                        data={CONF_QID: qid, CONF_SID: sid},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_QID): str,
                vol.Required(CONF_SID): str,
            }),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict):
        """Erneute Authentifizierung wenn SID abgelaufen."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            qid = entry.data[CONF_QID]
            sid = user_input[CONF_SID].strip()

            session = async_get_clientsession(self.hass)
            api = Api360(session, qid, sid)

            try:
                await api.get_devices()
            except (Api360AuthError, Api360Error):
                errors["base"] = "invalid_auth"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_SID: sid}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_SID): str}),
            errors=errors,
        )
