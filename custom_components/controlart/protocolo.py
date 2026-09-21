"""Camada de protocolo dos modulos cabeados ControlArt.

Protocolo (texto puro sobre TCP, porta 4998 por padrao):

  enviado    mdcmd_getmd,<a>,<b>,<c>
  recebido   setcmd,<mac>,<12 entradas>,<10 saidas>
             setbmcb0md,<mac>,...        (config de motor, ignorada)
             Parse Error!                (nome de comando desconhecido)

<a>,<b>,<c> sao os tres ultimos bytes do MAC em decimal (AA-BB-CC vira
170,187,204). O endereco 255,255,255 funciona como difusao: o modulo responde
com o proprio estado, e o MAC vem no quadro - e assim que o cadastro descobre
o endereco sem perguntar nada alem do IP.

O modulo so fala quando algo muda, e nao despeja estado ao conectar:
por isso pedimos o estado com mdcmd_getmd na conexao e periodicamente,
o que tambem serve de prova de vida.

Cada mudanca gera um PAR de quadros: o real e, ate ~2 s depois, um de
limpeza com as 12 entradas zeradas e as saidas inalteradas. O quadro de
limpeza nao reflete a realidade das entradas e e descartado.

Escrita:

  mdcmd_sendrele,<a>,<b>,<c>,<canal 0-9>,<0|1>

E absoluta e idempotente: mandar "liga" num circuito ja aceso nao faz nada.
O modulo confirma a mudanca com um setcmd em poucos milissegundos, entao as
entidades nao precisam de estado otimista - esperamos a confirmacao real.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging
import time
from typing import Any

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_TECLAS,
    INTERVALO_GETMD,
    JANELA_LIMPEZA,
    N_ENTRADAS,
    N_SAIDAS,
    RECONEXAO_MAX,
    SIGNAL_CONEXAO,
    SIGNAL_ESTADO,
    SIGNAL_TECLA,
    TIMEOUT_SONDA,
)

_LOGGER = logging.getLogger(__name__)


class SemConexao(Exception):
    """Nada respondeu no IP e porta informados."""


class SemResposta(Exception):
    """Algo respondeu, mas nao como um modulo ControlArt."""


def endereco(mac: str) -> str:
    """'AA-BB-CC' -> '170,187,204'."""
    return ",".join(str(int(parte, 16)) for parte in mac.split("-"))


async def sonda(host: str, porta: int) -> str:
    """Pergunta ao modulo quem ele e e devolve o MAC curto (AA-BB-CC)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, porta), TIMEOUT_SONDA
        )
    except (OSError, asyncio.TimeoutError) as err:
        raise SemConexao from err
    try:
        writer.write(b"mdcmd_getmd,255,255,255\r\n")
        await writer.drain()
        async with asyncio.timeout(TIMEOUT_SONDA):
            while linha := await reader.readline():
                partes = linha.decode("latin-1").strip().split(",")
                if partes[0] == "setcmd" and len(partes) == 2 + N_ENTRADAS + N_SAIDAS:
                    return partes[1].upper()
    except (OSError, asyncio.TimeoutError) as err:
        raise SemResposta from err
    finally:
        writer.close()
    raise SemResposta


class ModuloConexao:
    """Mantem uma conexao com um modulo e acompanha seu estado."""

    def __init__(self, hass: HomeAssistant, cfg: dict[str, Any]) -> None:
        self.hass = hass
        self.mac: str = cfg[CONF_MAC]
        self.host: str = cfg[CONF_HOST]
        self.porta: int = cfg[CONF_PORT]
        self.nome: str = cfg[CONF_NAME]
        self.teclas: frozenset[int] = frozenset(cfg.get(CONF_TECLAS, ()))
        self.addr = endereco(self.mac)
        self.saidas: list[int] = [0] * N_SAIDAS
        self.entradas: list[int] = [0] * N_ENTRADAS
        self.conectado = False
        self.tem_estado = False
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._parar = asyncio.Event()
        self._ultimo_quadro = 0.0

    # ------------------------------------------------------------- ciclo
    def iniciar(self) -> None:
        self._task = self.hass.async_create_background_task(
            self._laco(), f"controlart {self.mac}"
        )

    async def parar(self) -> None:
        self._parar.set()
        if self._writer is not None:
            self._writer.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _laco(self) -> None:
        espera = 1
        while not self._parar.is_set():
            try:
                await self._sessao()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - qualquer falha derruba a sessao
                _LOGGER.warning(
                    "ControlArt %s (%s): conexao perdida (%s); nova tentativa em %ds",
                    self.nome, self.host, err, espera,
                )
            self._marca_desconectado()
            try:
                await asyncio.wait_for(self._parar.wait(), timeout=espera)
                return
            except asyncio.TimeoutError:
                pass
            espera = min(espera * 2, RECONEXAO_MAX)

    async def _sessao(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.porta)
        self._writer = writer
        self.conectado = True
        _LOGGER.info("ControlArt %s conectado em %s:%d", self.nome, self.host, self.porta)
        async_dispatcher_send(self.hass, SIGNAL_CONEXAO.format(self.mac))

        await self._pede_estado()
        try:
            while not self._parar.is_set():
                try:
                    linha = await asyncio.wait_for(
                        reader.readline(), timeout=INTERVALO_GETMD
                    )
                except asyncio.TimeoutError:
                    await self._pede_estado()   # silencio longo: confirma que esta vivo
                    continue
                if not linha:
                    raise ConnectionError("fechada pelo modulo")
                texto = linha.decode("latin-1").strip()
                if texto:
                    self._trata_linha(texto)
        finally:
            writer.close()
            self._writer = None

    async def _pede_estado(self) -> None:
        if self._writer is None:
            return
        self._writer.write(f"mdcmd_getmd,{self.addr}\r\n".encode("ascii"))
        await self._writer.drain()

    async def envia_rele(self, canal: int, ligado: bool) -> None:
        """Liga ou desliga um circuito. `canal` vai de 1 a 10.

        Comando absoluto: repetir o mesmo estado nao tem efeito.
        """
        if not 1 <= canal <= N_SAIDAS:
            raise ValueError(f"canal fora da faixa 1-{N_SAIDAS}: {canal}")
        if self._writer is None or not self.conectado:
            raise HomeAssistantError(f"ControlArt {self.nome} ({self.host}) esta desconectado")
        comando = f"mdcmd_sendrele,{self.addr},{canal - 1},{1 if ligado else 0}\r\n"
        self._writer.write(comando.encode("ascii"))
        await self._writer.drain()
        _LOGGER.debug("ControlArt %s: enviado %s", self.nome, comando.strip())

    def _marca_desconectado(self) -> None:
        if self.conectado:
            self.conectado = False
            async_dispatcher_send(self.hass, SIGNAL_CONEXAO.format(self.mac))

    # --------------------------------------------------------- protocolo
    def _trata_linha(self, texto: str) -> None:
        partes = texto.split(",")
        cabeca = partes[0]
        if cabeca == "setcmd":
            if len(partes) > 1 and partes[1].upper() != self.mac:
                _LOGGER.debug("ControlArt %s: quadro de outro modulo (%s)", self.nome, partes[1])
                return
            self._trata_setcmd(partes[2:])
        elif cabeca == "setbmcb0md":
            return                       # configuracao de motor; nao usamos
        elif texto == "Parse Error!":
            _LOGGER.warning("ControlArt %s recusou a sintaxe de um comando", self.nome)
        else:
            _LOGGER.debug("ControlArt %s: quadro ignorado %r", self.nome, texto)

    def _trata_setcmd(self, campos: list[str]) -> None:
        if len(campos) != N_ENTRADAS + N_SAIDAS:
            _LOGGER.warning(
                "ControlArt %s: setcmd com %d campos (esperados %d)",
                self.nome, len(campos), N_ENTRADAS + N_SAIDAS,
            )
            return
        try:
            valores = [int(x) for x in campos]
        except ValueError:
            _LOGGER.warning("ControlArt %s: setcmd com campo nao numerico", self.nome)
            return

        entradas, saidas = valores[:N_ENTRADAS], valores[N_ENTRADAS:]
        agora = time.monotonic()
        limpeza = (
            self.tem_estado
            and not any(entradas)
            and saidas == self.saidas
            and agora - self._ultimo_quadro < JANELA_LIMPEZA
        )
        self._ultimo_quadro = agora

        if not self.tem_estado:
            self.entradas, self.saidas = entradas, saidas
            self.tem_estado = True
            async_dispatcher_send(self.hass, SIGNAL_ESTADO.format(self.mac))
            return

        if saidas != self.saidas:
            self.saidas = saidas
            async_dispatcher_send(self.hass, SIGNAL_ESTADO.format(self.mac))

        if limpeza:
            return                       # o mapa de entradas deste quadro nao e real

        anteriores = self.entradas
        if entradas == anteriores:
            return

        self.entradas = entradas
        mudou_retentivo = False
        for i in range(N_ENTRADAS):
            if entradas[i] == anteriores[i]:
                continue
            if i + 1 in self.teclas:
                if entradas[i] == 1:         # pulsador: so a borda de subida
                    async_dispatcher_send(self.hass, SIGNAL_TECLA.format(self.mac, i + 1))
            else:
                mudou_retentivo = True
        if mudou_retentivo:
            async_dispatcher_send(self.hass, SIGNAL_ESTADO.format(self.mac))


class ControlArtHub:
    """Agrupa as conexoes dos modulos cadastrados."""

    def __init__(self, hass: HomeAssistant, modulos: Iterable[dict[str, Any]]) -> None:
        self.hass = hass
        self.modulos: dict[str, ModuloConexao] = {}
        for cfg in modulos:
            modulo = ModuloConexao(hass, cfg)
            self.modulos[modulo.mac] = modulo

    def iniciar(self) -> None:
        for modulo in self.modulos.values():
            modulo.iniciar()

    async def parar(self) -> None:
        await asyncio.gather(*(m.parar() for m in self.modulos.values()))
