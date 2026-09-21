"""Cadastro dos modulos pela interface.

So o IP e pedido: o modulo e perguntado pelo endereco de difusao e responde
com o proprio MAC, que e o endereco dos comandos. O primeiro modulo entra no
fluxo de configuracao; os demais, pelas opcoes (Configurar).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_MODULOS, CONF_TECLAS, DOMAIN, N_ENTRADAS, PORTA_PADRAO
from .protocolo import SemConexao, SemResposta, sonda

SELETOR_TECLAS = SelectSelector(
    SelectSelectorConfig(
        options=[str(n) for n in range(1, N_ENTRADAS + 1)],
        multiple=True,
        mode=SelectSelectorMode.LIST,
    )
)


def _esquema(padrao: dict[str, Any]) -> vol.Schema:
    host = {"default": padrao[CONF_HOST]} if padrao.get(CONF_HOST) else {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, **host): str,
            vol.Required(CONF_PORT, default=padrao.get(CONF_PORT, PORTA_PADRAO)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_NAME, default=padrao.get(CONF_NAME, "")): str,
            vol.Optional(
                CONF_TECLAS, default=[str(n) for n in padrao.get(CONF_TECLAS, [])]
            ): SELETOR_TECLAS,
        }
    )


async def _monta_modulo(
    dados: dict[str, Any],
    outros: list[dict[str, Any]],
    atual: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Valida o formulario e devolve (modulo, None) ou (None, erro)."""
    host = dados[CONF_HOST].strip()
    porta = int(dados[CONF_PORT])
    if atual and host == atual[CONF_HOST] and porta == atual[CONF_PORT]:
        mac = atual[CONF_MAC]                 # so mudou nome ou teclas: nao precisa perguntar
    else:
        try:
            mac = await sonda(host, porta)
        except SemConexao:
            return None, "cannot_connect"
        except SemResposta:
            return None, "sem_resposta"
        if atual and mac != atual[CONF_MAC]:
            return None, "mac_diferente"
    if any(m[CONF_MAC] == mac for m in outros):
        return None, "ja_cadastrado"
    return {
        CONF_HOST: host,
        CONF_PORT: porta,
        CONF_MAC: mac,
        CONF_NAME: dados[CONF_NAME].strip() or f"ControlArt {mac}",
        CONF_TECLAS: sorted(int(n) for n in dados.get(CONF_TECLAS, [])),
    }, None


class ControlArtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Uma entrada so, com todos os modulos dentro."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OpcoesControlArt()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        erros: dict[str, str] = {}
        if user_input is not None:
            modulo, erro = await _monta_modulo(user_input, [])
            if erro:
                erros["base"] = erro
            else:
                return self.async_create_entry(
                    title="ControlArt", data={}, options={CONF_MODULOS: [modulo]}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_esquema(user_input or {CONF_NAME: "ControlArt 01"}),
            errors=erros,
        )


class OpcoesControlArt(OptionsFlow):
    """Adicionar, editar e remover modulos."""

    def __init__(self) -> None:
        self._mac: str | None = None

    def _modulos(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_MODULOS, []))

    def _seletor_modulo(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_MAC): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=m[CONF_MAC], label=f"{m[CONF_NAME]} · {m[CONF_HOST]}")
                            for m in self._modulos()
                        ]
                    )
                )
            }
        )

    def _salva(self, modulos: list[dict[str, Any]]) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_MODULOS: modulos})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opcoes = ["adicionar"]
        if self._modulos():
            opcoes += ["escolher_editar", "remover"]
        return self.async_show_menu(step_id="init", menu_options=opcoes)

    async def async_step_adicionar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        modulos = self._modulos()
        erros: dict[str, str] = {}
        if user_input is not None:
            modulo, erro = await _monta_modulo(user_input, modulos)
            if erro:
                erros["base"] = erro
            else:
                return self._salva(modulos + [modulo])
        padrao = user_input or {CONF_NAME: f"ControlArt {len(modulos) + 1:02d}"}
        return self.async_show_form(step_id="adicionar", data_schema=_esquema(padrao), errors=erros)

    async def async_step_escolher_editar(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._mac = user_input[CONF_MAC]
            return await self.async_step_editar()
        return self.async_show_form(step_id="escolher_editar", data_schema=self._seletor_modulo())

    async def async_step_editar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        modulos = self._modulos()
        atual = next(m for m in modulos if m[CONF_MAC] == self._mac)
        erros: dict[str, str] = {}
        if user_input is not None:
            outros = [m for m in modulos if m[CONF_MAC] != self._mac]
            modulo, erro = await _monta_modulo(user_input, outros, atual)
            if erro:
                erros["base"] = erro
            else:
                return self._salva([modulo if m[CONF_MAC] == self._mac else m for m in modulos])
        return self.async_show_form(
            step_id="editar",
            data_schema=_esquema(user_input or atual),
            errors=erros,
            description_placeholders={"mac": atual[CONF_MAC]},
        )

    async def async_step_remover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._salva([m for m in self._modulos() if m[CONF_MAC] != user_input[CONF_MAC]])
        return self.async_show_form(step_id="remover", data_schema=self._seletor_modulo())
