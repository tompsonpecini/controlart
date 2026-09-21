"""Teclas de keypad como entidades de evento.

Tecla de keypad e pulsador: cada toque produz um pulso curto na entrada.
Publicamos so a borda de subida, como evento "press" - que e o gatilho
natural para cenas e automacoes no Home Assistant.

Quais entradas sao teclas e escolha do usuario, nas opcoes da integracao;
as demais viram sensores binarios (ver binary_sensor.py).
"""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_CONEXAO, SIGNAL_TECLA
from .entidade import EntidadeControlArt
from .protocolo import ControlArtHub, ModuloConexao

TOQUE = "press"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ControlArtHub = entry.runtime_data
    async_add_entities(
        Tecla(modulo, entrada)
        for modulo in hub.modulos.values()
        for entrada in sorted(modulo.teclas)
    )


class Tecla(EntidadeControlArt, EventEntity):
    """Uma tecla de keypad."""

    _attr_translation_key = "tecla"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [TOQUE]

    def __init__(self, modulo: ModuloConexao, entrada: int) -> None:
        super().__init__(modulo)
        self._entrada = entrada
        self._attr_translation_placeholders = {"numero": str(entrada)}
        self._attr_unique_id = f"controlart_{modulo.mac}_tecla_{entrada:02d}"

    @property
    def available(self) -> bool:
        return self._modulo.conectado

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_TECLA.format(self._modulo.mac, self._entrada), self._toque
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONEXAO.format(self._modulo.mac), self._atualiza
            )
        )

    @callback
    def _toque(self) -> None:
        self._trigger_event(TOQUE)
        self.async_write_ha_state()
