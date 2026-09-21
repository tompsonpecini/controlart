"""Sensores binarios do ControlArt.

 - a posicao de cada entrada que nao e tecla de keypad (diagnostico,
   desligada por padrao)
 - a conectividade de cada modulo
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import N_ENTRADAS, SIGNAL_CONEXAO
from .entidade import EntidadeControlArt
from .protocolo import ControlArtHub, ModuloConexao


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ControlArtHub = entry.runtime_data
    entidades: list[BinarySensorEntity] = []
    for modulo in hub.modulos.values():
        entidades.append(Conexao(modulo))
        entidades.extend(
            Entrada(modulo, entrada)
            for entrada in range(1, N_ENTRADAS + 1)
            if entrada not in modulo.teclas
        )
    async_add_entities(entidades)


class Entrada(EntidadeControlArt, BinarySensorEntity):
    """Posicao da alavanca de um interruptor retentivo.

    Diagnostico. A alavanca NAO indica se a luz esta acesa: o modulo inverte
    a saida a cada transicao, entao as duas coisas andam soltas uma da outra.
    Para reagir ao interruptor numa automacao, dispare em qualquer mudanca.
    """

    _attr_translation_key = "entrada"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, modulo: ModuloConexao, entrada: int) -> None:
        super().__init__(modulo)
        self._entrada = entrada
        self._attr_translation_placeholders = {"numero": str(entrada)}
        self._attr_unique_id = f"controlart_{modulo.mac}_entrada_{entrada:02d}"

    @property
    def is_on(self) -> bool:
        return bool(self._modulo.entradas[self._entrada - 1])


class Conexao(EntidadeControlArt, BinarySensorEntity):
    """O modulo esta respondendo?"""

    _attr_translation_key = "conexao"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, modulo: ModuloConexao) -> None:
        super().__init__(modulo)
        self._attr_unique_id = f"controlart_{modulo.mac}_conexao"

    def _sinais(self) -> tuple[str, ...]:
        return (SIGNAL_CONEXAO.format(self._modulo.mac),)

    @property
    def available(self) -> bool:
        return True                     # existe justamente para relatar a queda

    @property
    def is_on(self) -> bool:
        return self._modulo.conectado

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"host": self._modulo.host, "mac": self._modulo.mac}
