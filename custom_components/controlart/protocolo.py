"""Camada de protocolo dos modulos cabeados ControlArt.

Protocolo (texto puro sobre TCP, porta 4998 por padrao):

  enviado    mdcmd_getmd,<a>,<b>,<c>
  recebido   setcmd,<mac>,<12 entradas>,<10 saidas>      (rele, 0 ou 1)
             setdmmd,<mac>,<12 entradas>,<N canais>      (dimmer, 0 a 255)
             setbmcb0md,<mac>,...        (config de motor, ignorada)
             Parse Error!                (nome de comando desconhecido)

O cabecalho do quadro diz o tipo do modulo, e o dimmer informa quantos
canais tem pelo tamanho do quadro (9 no modulo conhecido).

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
  mdcmd_sendrele,<a>,<b>,<c>,<canal>,<nivel 0-255>      (dimmer)

E absoluta e idempotente: mandar "liga" num circuito ja aceso nao faz nada.
O modulo confirma a mudanca com um setcmd em poucos milissegundos, entao as
entidades nao precisam de estado otimista - esperamos a confirmacao real.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable
from datetime import datetime
import logging
import time
from typing import Any, NamedTuple

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CABECALHOS,
    CONF_SAIDAS,
    CONF_TECLAS,
    CONF_TIPO,
    INTERVALO_GETMD,
    JANELA_LIMPEZA,
    N_ENTRADAS,
    N_SAIDAS,
    RECONEXAO_MAX,
    SIGNAL_CONEXAO,
    SIGNAL_ESTADO,
    SIGNAL_IDENTIDADE,
    SIGNAL_TECLA,
    TIMEOUT_CONFIRMACAO,
    TIMEOUT_RESPOSTA,
    TIMEOUT_SONDA,
    TIPO_RELE,
)

NIVEL_MAX = 255
LINHAS_GUARDADAS = 50           # para o diagnostico: o bastante para alguns minutos de uso
PASSO_RAMPA = 0.2               # s · intervalo minimo entre os degraus de uma transicao

# Identificacao pedida na conexao. Nao vem do proprio repositorio: e o que o
# driver Hubitat da ControlArt (hhorigian/hubitat_Controlart_Relays) manda.
PEDIDOS_IDENTIFICACAO = ("get_firmware_version", "get_mac_addr")

_LOGGER = logging.getLogger(__name__)


class SemConexao(Exception):
    """Nada respondeu no IP e porta informados."""


class SemResposta(Exception):
    """Algo respondeu, mas nao como um modulo ControlArt."""


def endereco(mac: str) -> str:
    """'AA-BB-CC' -> '170,187,204'."""
    return ",".join(str(int(parte, 16)) for parte in mac.split("-"))


class Identidade(NamedTuple):
    """O que o cadastro descobre perguntando ao modulo."""

    mac: str        # curto, AA-BB-CC
    tipo: str       # TIPO_RELE ou TIPO_DIMMER
    saidas: int     # saidas do rele ou canais do dimmer


async def sonda(host: str, porta: int) -> Identidade:
    """Pergunta ao modulo quem ele e: MAC, tipo e quantas saidas tem."""
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
                tipo = CABECALHOS.get(partes[0])
                saidas = len(partes) - 2 - N_ENTRADAS
                if tipo == TIPO_RELE and saidas != N_SAIDAS:
                    continue
                if tipo and saidas > 0:
                    return Identidade(partes[1].upper(), tipo, saidas)
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
        self.tipo: str = cfg.get(CONF_TIPO, TIPO_RELE)
        self.n_saidas: int = cfg.get(CONF_SAIDAS, N_SAIDAS)
        self.addr = endereco(self.mac)
        self.saidas: list[int] = [0] * self.n_saidas
        self.entradas: list[int] = [0] * N_ENTRADAS
        self._acesos: list[int] = [NIVEL_MAX] * self.n_saidas   # ultimo nivel > 0 visto
        self.conectado = False
        self.tem_estado = False
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._parar = asyncio.Event()
        self._mudanca = asyncio.Event()     # renovado a cada mudanca das saidas
        self._ultimo_quadro = 0.0
        self._rampas: dict[int, asyncio.Task] = {}   # transicao em andamento, por canal
        # so para o diagnostico
        self.linhas: deque[tuple[str, str, str]] = deque(maxlen=LINHAS_GUARDADAS)
        self.firmware: str | None = None        # rele 3027, dimmer 1021 (15/10/2026)
        self.mac_informado: str | None = None   # "macaddr_RT,<mac>" no rele, "macaddr,<mac>" no dimmer
        self._motores: deque[str] = deque(maxlen=5)
        self.conexoes = 0
        self.ultima_queda: str | None = None

    @property
    def motores(self) -> list[str]:
        """Linhas setbmcb0md como vieram: o significado dos campos nao e conhecido."""
        return list(self._motores)

    @property
    def versao_firmware(self) -> str | None:
        """Firmware como o mdConfig mostra: 3027 vira 3.027 (o docs/protocolo.md cita 3.022)."""
        if self.firmware is None:
            return None
        if self.firmware.isdigit() and len(self.firmware) > 1:
            return f"{self.firmware[0]}.{self.firmware[1:]}"
        return self.firmware.removeprefix("VERSION").strip()

    def diagnostico(self) -> dict[str, Any]:
        return {
            "nome": self.nome,
            "host": self.host,
            "porta": self.porta,
            "mac": self.mac,
            "tipo": self.tipo,
            "saidas_ou_canais": self.n_saidas,
            "teclas": sorted(self.teclas),
            "conectado": self.conectado,
            "tem_estado": self.tem_estado,
            "entradas": self.entradas,
            "saidas": self.saidas,
            "firmware": self.firmware,
            "mac_informado": self.mac_informado,
            "motores": self.motores,
            "conexoes": self.conexoes,
            "ultima_queda": self.ultima_queda,
            "linhas": [f"{hora} {sentido} {texto}" for hora, sentido, texto in self.linhas],
        }

    def _registra(self, sentido: str, texto: str) -> None:
        self.linhas.append((datetime.now().isoformat(timespec="milliseconds"), sentido, texto))

    # ------------------------------------------------------------- ciclo
    def iniciar(self) -> None:
        self._task = self.hass.async_create_background_task(
            self._laco(), f"controlart {self.mac}"
        )

    async def parar(self) -> None:
        self._parar.set()
        for canal in list(self._rampas):
            self._cancela_rampa(canal)
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
                self.ultima_queda = f"{datetime.now().isoformat(timespec='seconds')} {err!r}"
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
        self.conexoes += 1
        _LOGGER.info("ControlArt %s conectado em %s:%d", self.nome, self.host, self.porta)
        async_dispatcher_send(self.hass, SIGNAL_CONEXAO.format(self.mac))

        await self._pede_estado()
        for pedido in PEDIDOS_IDENTIFICACAO:
            await self._escreve(pedido)
        aguardando = True                       # o getmd precisa de resposta
        try:
            while not self._parar.is_set():
                try:
                    linha = await asyncio.wait_for(
                        reader.readline(),
                        timeout=TIMEOUT_RESPOSTA if aguardando else INTERVALO_GETMD,
                    )
                except asyncio.TimeoutError:
                    if aguardando:
                        # modulo sem energia ou cabo solto nao manda RST: sem isso a
                        # conexao parece viva e as entidades mostram estado velho
                        raise ConnectionError("sem resposta ao pedido de estado") from None
                    await self._pede_estado()   # silencio longo: confirma que esta vivo
                    aguardando = True
                    continue
                if not linha:
                    raise ConnectionError("fechada pelo modulo")
                aguardando = False              # qualquer quadro prova que esta vivo
                texto = linha.decode("latin-1").strip()
                if texto:
                    self._trata_linha(texto)
        finally:
            writer.close()
            self._writer = None

    async def _pede_estado(self) -> None:
        if self._writer is None:
            return
        await self._escreve(f"mdcmd_getmd,{self.addr}")

    async def _escreve(self, comando: str) -> None:
        """Manda uma linha ao modulo. Quem chama garante que ha conexao."""
        assert self._writer is not None
        self._writer.write(f"{comando}\r\n".encode("ascii"))
        await self._writer.drain()
        self._registra("->", comando)

    async def envia_rele(self, canal: int, ligado: bool) -> None:
        """Liga ou desliga um circuito. `canal` vai de 1 a 10.

        Comando absoluto: repetir o mesmo estado nao tem efeito.
        """
        await self._envia(canal, 1 if ligado else 0)

    async def envia_nivel(self, canal: int, nivel: int) -> None:
        """Poe um canal do dimmer no nivel de 0 (apagado) a 255.

        Mesmo comando do rele, com o nivel no lugar do 0/1. Se o modulo
        arredondar o nivel, vale o que vier no quadro de confirmacao.
        """
        if not 0 <= nivel <= NIVEL_MAX:
            raise ValueError(f"nivel fora da faixa 0-{NIVEL_MAX}: {nivel}")
        self._cancela_rampa(canal)
        await self._envia(canal, nivel)

    def rampa(self, canal: int, alvo: int, segundos: float) -> None:
        """Leva o canal do dimmer ate `alvo` aos poucos, em segundo plano.

        O modulo nao tem rampa propria conhecida, mas aceita qualquer nivel e
        confirma em milissegundos: a transicao e uma sequencia de comandos com
        no minimo PASSO_RAMPA entre eles, nunca mais de um degrau por nivel.
        Um comando novo no mesmo canal cancela a rampa em andamento.
        """
        if not 1 <= canal <= self.n_saidas:
            raise ValueError(f"canal fora da faixa 1-{self.n_saidas}: {canal}")
        if not 0 <= alvo <= NIVEL_MAX:
            raise ValueError(f"nivel fora da faixa 0-{NIVEL_MAX}: {alvo}")
        if self._writer is None or not self.conectado:
            raise HomeAssistantError(f"ControlArt {self.nome} ({self.host}) esta desconectado")
        self._cancela_rampa(canal)
        self._rampas[canal] = asyncio.get_running_loop().create_task(
            self._rampa(canal, alvo, segundos), name=f"controlart {self.mac} rampa {canal}"
        )

    async def _rampa(self, canal: int, alvo: int, segundos: float) -> None:
        relogio = asyncio.get_running_loop()
        inicio = self.saidas[canal - 1]
        passos = min(abs(alvo - inicio), max(1, round(segundos / PASSO_RAMPA)))
        try:
            for n in range(1, passos + 1):
                comeco = relogio.time()
                await self._envia(canal, round(inicio + (alvo - inicio) * n / passos))
                if n < passos:
                    await asyncio.sleep(max(0.0, segundos / passos - (relogio.time() - comeco)))
        except HomeAssistantError as err:
            _LOGGER.warning("ControlArt %s: transicao do canal %d interrompida: %s",
                            self.nome, canal, err)
        finally:
            if self._rampas.get(canal) is asyncio.current_task():
                del self._rampas[canal]

    def _cancela_rampa(self, canal: int) -> None:
        tarefa = self._rampas.pop(canal, None)
        if tarefa is not None and tarefa is not asyncio.current_task():
            tarefa.cancel()

    def nivel_ao_ligar(self, canal: int) -> int:
        """Nivel para acender sem brilho pedido: o ultimo aceso, ou o maximo."""
        return self._acesos[canal - 1]

    async def _envia(self, canal: int, valor: int) -> None:
        """Manda o comando e espera o quadro em que a saida muda.

        O modulo engole em silencio um comando com endereco ou argumento
        errado, entao sem esperar a mudanca o erro passaria despercebido.
        Se a saida ja esta no valor pedido, nao ha quadro a esperar.
        """
        if not 1 <= canal <= self.n_saidas:
            raise ValueError(f"canal fora da faixa 1-{self.n_saidas}: {canal}")
        if self._writer is None or not self.conectado:
            raise HomeAssistantError(f"ControlArt {self.nome} ({self.host}) esta desconectado")
        anterior = self.saidas[canal - 1]
        mudanca = self._mudanca
        comando = f"mdcmd_sendrele,{self.addr},{canal - 1},{valor}"
        await self._escreve(comando)
        _LOGGER.debug("ControlArt %s: enviado %s", self.nome, comando)
        if valor != anterior:
            await self._confirma(
                lambda: self.saidas[canal - 1] != anterior, mudanca, f"saida {canal} em {valor}"
            )

    async def _confirma(self, mudou, mudanca: asyncio.Event, descricao: str) -> None:
        """Espera um quadro em que `mudou()` fica verdadeiro, ou levanta erro."""
        try:
            async with asyncio.timeout(TIMEOUT_CONFIRMACAO):
                while not mudou():
                    await mudanca.wait()
                    mudanca = self._mudanca
        except TimeoutError as err:
            raise HomeAssistantError(
                f"ControlArt {self.nome} ({self.host}) nao confirmou o comando: {descricao}"
            ) from err

    def _avisa_mudanca(self) -> None:
        """Acorda quem espera confirmacao e arma o aviso da proxima mudanca."""
        self._mudanca.set()
        self._mudanca = asyncio.Event()

    def _marca_desconectado(self) -> None:
        self.tem_estado = False             # ao reconectar, so vale o quadro novo
        if self.conectado:
            self.conectado = False
            async_dispatcher_send(self.hass, SIGNAL_CONEXAO.format(self.mac))

    # --------------------------------------------------------- protocolo
    def _trata_linha(self, texto: str) -> None:
        self._registra("<-", texto)
        partes = texto.split(",")
        cabeca = partes[0]
        if cabeca in CABECALHOS:
            if len(partes) > 1 and partes[1].upper() != self.mac:
                _LOGGER.debug("ControlArt %s: quadro de outro modulo (%s)", self.nome, partes[1])
                return
            if CABECALHOS[cabeca] != self.tipo:
                _LOGGER.warning(
                    "ControlArt %s: quadro %s, mas o modulo foi cadastrado como %s; "
                    "cadastre de novo", self.nome, cabeca, self.tipo,
                )
                return
            self._trata_setcmd(partes[2:])
        elif cabeca == "setbmcb0md":
            self._motores.append(texto)  # configuracao de motor: so para o diagnostico
        elif texto.isdigit() or texto.startswith("VERSION"):
            # o modulo responde so o numero; o driver Hubitat espera VERSION
            if texto != self.firmware:
                self.firmware = texto
                async_dispatcher_send(self.hass, SIGNAL_IDENTIDADE.format(self.mac))
        elif texto.lower().startswith("macaddr"):
            self.mac_informado = texto
        elif texto == "Parse Error!":
            _LOGGER.warning("ControlArt %s recusou a sintaxe de um comando", self.nome)
        else:
            _LOGGER.debug("ControlArt %s: quadro ignorado %r", self.nome, texto)

    def _trata_setcmd(self, campos: list[str]) -> None:
        """Quadro de estado, do rele (setcmd) ou do dimmer (setdmmd)."""
        if len(campos) != N_ENTRADAS + self.n_saidas:
            _LOGGER.warning(
                "ControlArt %s: quadro de estado com %d campos (esperados %d)",
                self.nome, len(campos), N_ENTRADAS + self.n_saidas,
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
        self._acesos = [nivel or anterior for nivel, anterior in zip(saidas, self._acesos)]

        if not self.tem_estado:
            self.entradas, self.saidas = entradas, saidas
            self.tem_estado = True
            self._avisa_mudanca()
            async_dispatcher_send(self.hass, SIGNAL_ESTADO.format(self.mac))
            return

        if saidas != self.saidas:
            self.saidas = saidas
            self._avisa_mudanca()
            async_dispatcher_send(self.hass, SIGNAL_ESTADO.format(self.mac))

        if limpeza:
            # O mapa de entradas deste quadro nao e real para interruptores, mas
            # pulsador volta sozinho a 0: sem zerar aqui, o proximo toque na
            # mesma tecla chega igual ao anterior e nao tem borda de subida.
            self.entradas = [
                0 if i + 1 in self.teclas else valor for i, valor in enumerate(self.entradas)
            ]
            return

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
