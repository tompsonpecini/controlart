"""As 10 saidas de cada modulo como luzes liga/desliga.

O rele e liga/desliga (o dimmer ControlArt e outro produto), entao entram
como `light` com ColorMode.ONOFF. Isso permite "apagar as luzes da cozinha"
por area, voz e cartoes de luz.

O estado vem sempre do modulo: apos o comando esperamos o setcmd de
confirmacao, que chega em milissegundos. Sem estado otimista.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import N_SAIDAS
from .entidade import EntidadeControlArt
from .protocolo import ControlArtHub, ModuloConexao


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ControlArtHub = entry.runtime_data
    async_add_entities(
        Saida(modulo, canal)
        for modulo in hub.modulos.values()
        for canal in range(1, N_SAIDAS + 1)
    )


class Saida(EntidadeControlArt, LightEntity):
    """Um circuito."""

    _attr_translation_key = "saida"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, modulo: ModuloConexao, canal: int) -> None:
        super().__init__(modulo)
        self._canal = canal
        self._attr_translation_placeholders = {"numero": str(canal)}
        self._attr_unique_id = f"controlart_{modulo.mac}_luz_{canal:02d}"

    @property
    def is_on(self) -> bool:
        return bool(self._modulo.saidas[self._canal - 1])

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._modulo.envia_rele(self._canal, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._modulo.envia_rele(self._canal, False)
