"""Home Assistant falso, so o bastante para importar a integracao.

Os testes rodam sem o Home Assistant instalado: cada modulo que a integracao
importa vira um modulo minimo aqui, e o pacote e carregado sem o __init__.py.
Os sinais do dispatcher ficam em `sinais`, na ordem em que foram enviados.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

PACOTE = Path(__file__).resolve().parent.parent / "custom_components" / "controlart"

sinais: list[str] = []


class HomeAssistantError(Exception):
    """Distinta de ValueError, para os testes saberem qual erro subiu."""


class ColorMode:
    ONOFF = "onoff"
    BRIGHTNESS = "brightness"


class _Base:
    """Entity e LightEntity: so precisam existir como classes."""


def _modulo(nome: str, **atributos) -> types.ModuleType:
    mod = types.ModuleType(nome)
    mod.__dict__.update(atributos)
    sys.modules[nome] = mod
    pai, _, filho = nome.rpartition(".")
    if pai in sys.modules:
        setattr(sys.modules[pai], filho, mod)
    return mod


_modulo("homeassistant")
_modulo(
    "homeassistant.const",
    CONF_HOST="host",
    CONF_MAC="mac",
    CONF_NAME="name",
    CONF_PORT="port",
    EntityCategory=type("EntityCategory", (), {"DIAGNOSTIC": "diagnostic"}),
)
_modulo("homeassistant.core", HomeAssistant=object, callback=lambda funcao: funcao)
_modulo("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)


class _Fluxo:
    def __init_subclass__(cls, **kwargs) -> None:   # ConfigFlow recebe domain=
        super().__init_subclass__()


_modulo(
    "homeassistant.config_entries",
    ConfigEntry=object,
    ConfigFlow=_Fluxo,
    ConfigFlowResult=dict,
    OptionsFlow=_Fluxo,
)
_modulo(
    "voluptuous",
    Schema=lambda *args, **kwargs: None,
    Required=lambda chave, **kwargs: chave,
    Optional=lambda chave, **kwargs: chave,
    All=lambda *args: None,
    Coerce=lambda tipo: None,
    Range=lambda **kwargs: None,
)
_modulo("homeassistant.helpers")
_modulo(
    "homeassistant.helpers.dispatcher",
    async_dispatcher_send=lambda hass, sinal, *args: sinais.append(sinal),
    async_dispatcher_connect=lambda hass, sinal, alvo: (lambda: None),
)
_modulo(
    "homeassistant.helpers.device_registry",
    CONNECTION_NETWORK_MAC="mac",
    DeviceInfo=dict,
    async_get=None,                 # cada teste poe o seu registro falso
    async_entries_for_config_entry=None,
)
_modulo("homeassistant.helpers.entity_registry")
_modulo("homeassistant.helpers.entity", Entity=_Base)
_modulo("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
_modulo(
    "homeassistant.helpers.selector",
    SelectOptionDict=dict,
    SelectSelector=lambda *args, **kwargs: None,
    SelectSelectorConfig=lambda **kwargs: None,
    SelectSelectorMode=type("SelectSelectorMode", (), {"LIST": "list"}),
)
_modulo("homeassistant.components")
_modulo(
    "homeassistant.components.light",
    ATTR_BRIGHTNESS="brightness",
    ATTR_TRANSITION="transition",
    ColorMode=ColorMode,
    LightEntity=type("LightEntity", (), {}),
    LightEntityFeature=type("LightEntityFeature", (), {"TRANSITION": 32}),
)
_modulo("homeassistant.components.sensor", SensorEntity=type("SensorEntity", (), {}))

_pacote = types.ModuleType("controlart")
_pacote.__path__ = [str(PACOTE)]
sys.modules["controlart"] = _pacote

const = importlib.import_module("controlart.const")
protocolo = importlib.import_module("controlart.protocolo")
registro = importlib.import_module("controlart.registro")
light = importlib.import_module("controlart.light")
config_flow = importlib.import_module("controlart.config_flow")


class Relogio:
    agora = 0.0

    def monotonic(self) -> float:
        return self.agora


relogio = Relogio()
protocolo.time = relogio


class EscritorFalso:
    """Faz as vezes do StreamWriter: guarda o que a integracao mandou."""

    def __init__(self) -> None:
        self.enviado: list[str] = []

    def write(self, dados: bytes) -> None:
        self.enviado.append(dados.decode("ascii"))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None
