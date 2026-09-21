"""Integracao ControlArt - modulos cabeados de iluminacao a rele.

Cada modulo vira um dispositivo com 10 luzes (as saidas), uma entidade de
evento por tecla de keypad, um sensor por entrada de interruptor e um sensor
de conexao. Tudo local, por TCP, sem nuvem.
"""

from __future__ import annotations

import importlib
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_MODULOS
from .protocolo import ControlArtHub
from .registro import limpa_registro

_LOGGER = logging.getLogger(__name__)

PLATAFORMAS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.LIGHT,
]

type ControlArtConfigEntry = ConfigEntry[ControlArtHub]


async def async_setup_entry(hass: HomeAssistant, entry: ControlArtConfigEntry) -> bool:
    modulos = entry.options.get(CONF_MODULOS, [])
    hub = ControlArtHub(hass, modulos)
    hub.iniciar()
    entry.runtime_data = hub
    limpa_registro(hass, entry, modulos)
    await hass.config_entries.async_forward_entry_setups(entry, PLATAFORMAS)
    entry.async_on_unload(entry.add_update_listener(_recarrega))
    return True


async def _recarrega(hass: HomeAssistant, entry: ControlArtConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ControlArtConfigEntry) -> bool:
    descarregou = await hass.config_entries.async_unload_platforms(entry, PLATAFORMAS)
    if descarregou:
        await entry.runtime_data.parar()
    return descarregou


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Versao 1: as versoes 0.x, que nunca foram publicadas, guardavam os
    modulos no codigo. Se houver um `legado.py` ao lado deste arquivo com a
    lista MODULOS, ela vira a configuracao; senao, e preciso cadastrar de novo.
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        try:
            legado = await hass.async_add_executor_job(
                importlib.import_module, f"{__package__}.legado"
            )
        except ImportError:
            _LOGGER.error(
                "ControlArt: esta entrada vem de uma versao de teste sem os modulos "
                "salvos. Remova a integracao e adicione de novo"
            )
            return False
        hass.config_entries.async_update_entry(
            entry, options={CONF_MODULOS: legado.MODULOS}, version=2
        )
        _LOGGER.info("ControlArt: %d modulos migrados da versao de teste", len(legado.MODULOS))
    return True
