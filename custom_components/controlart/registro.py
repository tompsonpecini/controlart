"""Limpeza do registro quando a configuracao muda.

Tirar um modulo, ou trocar uma entrada de interruptor para tecla (e
vice-versa), deixa para tras entidades que nenhuma plataforma vai mais
criar. Aqui elas saem do registro, e o dispositivo de um modulo removido
deixa de pertencer a esta integracao.

Nao renomeia nada e nao mexe em area: o que o usuario ajustou fica.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_TECLAS, DOMAIN, N_ENTRADAS, N_SAIDAS

_LOGGER = logging.getLogger(__name__)


def esperado(modulos: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """(dominio, unique_id) de todas as entidades que a configuracao produz."""
    alvo: set[tuple[str, str]] = set()
    for cfg in modulos:
        mac, teclas = cfg[CONF_MAC], set(cfg.get(CONF_TECLAS, ()))
        alvo.add(("binary_sensor", f"controlart_{mac}_conexao"))
        for canal in range(1, N_SAIDAS + 1):
            alvo.add(("light", f"controlart_{mac}_luz_{canal:02d}"))
        for entrada in range(1, N_ENTRADAS + 1):
            if entrada in teclas:
                alvo.add(("event", f"controlart_{mac}_tecla_{entrada:02d}"))
            else:
                alvo.add(("binary_sensor", f"controlart_{mac}_entrada_{entrada:02d}"))
    return alvo


@callback
def limpa_registro(hass: HomeAssistant, entry: ConfigEntry, modulos: list[dict[str, Any]]) -> None:
    ents = er.async_get(hass)
    alvo = esperado(modulos)
    removidas = 0
    for ent in list(er.async_entries_for_config_entry(ents, entry.entry_id)):
        if (ent.domain, ent.unique_id) not in alvo:
            ents.async_remove(ent.entity_id)
            removidas += 1

    devs = dr.async_get(hass)
    macs = {cfg[CONF_MAC] for cfg in modulos}
    for dev in dr.async_entries_for_config_entry(devs, entry.entry_id):
        if not any(dom == DOMAIN and ident in macs for dom, ident in dev.identifiers):
            devs.async_update_device(dev.id, remove_config_entry_id=entry.entry_id)

    if removidas:
        _LOGGER.info("ControlArt: %d entidades que a configuracao nao produz mais foram removidas",
                     removidas)
