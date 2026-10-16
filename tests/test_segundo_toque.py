"""Segundo toque na mesma tecla, quando o modulo nao manda quadro de limpeza.

Conferido num modulo real: dois toques numa tecla de keypad, com 4 s entre
eles, chegaram como dois quadros com a tecla em 1 e nada entre eles. O quadro
mostra as entradas como estao no instante do envio, e o modulo nao avisa
quando a tecla e solta. Sem pedir o estado depois do toque, a tecla ficava
guardada em 1 e o segundo toque nao tinha borda de subida.
"""

from __future__ import annotations

import asyncio
import unittest

from ha_falso import EscritorFalso, protocolo, relogio, sinais

MAC = "AA-BB-CC"
TECLA = 6
ALAVANCAS = (2, 5, 9)              # interruptores comuns com a alavanca para cima


def campos(entradas=(), saidas=()) -> list[str]:
    return (["1" if n in entradas else "0" for n in range(1, 13)]
            + ["1" if n in saidas else "0" for n in range(1, 11)])


class ModuloReal(EscritorFalso):
    """Responde ao getmd com as entradas ao vivo, como o modulo real."""

    def __init__(self, mod, segurada_por: int = 0) -> None:
        super().__init__()
        self.mod = mod
        self.segurada_por = segurada_por   # quantos getmd ainda veem a tecla apertada
        self.saidas: tuple[int, ...] = ()

    def write(self, dados: bytes) -> None:
        super().write(dados)
        if dados.startswith(b"mdcmd_getmd"):
            asyncio.get_running_loop().call_soon(self._responde)

    def _responde(self) -> None:
        relogio.agora += 1.0
        entradas = ALAVANCAS
        if self.segurada_por > 0:
            self.segurada_por -= 1
            entradas = (*ALAVANCAS, TECLA)
        self.mod._trata_setcmd(campos(entradas, self.saidas))

    def pedidos(self) -> int:
        return sum(1 for linha in self.enviado if linha.startswith("mdcmd_getmd"))


def modulo(segurada_por: int = 0):
    sinais.clear()
    relogio.agora = 0.0
    mod = protocolo.ModuloConexao(
        None, {"mac": MAC, "host": "x", "port": 4998, "name": "Teste", "keypad_inputs": [TECLA]}
    )
    mod._trata_setcmd(campos(ALAVANCAS))      # getmd da conexao
    mod.conectado = True
    mod._writer = ModuloReal(mod, segurada_por)
    return mod


def toque(mod, em: float, saidas=()) -> None:
    """O quadro que o modulo manda ao executar a cena da tecla."""
    relogio.agora = em
    mod._writer.saidas = tuple(saidas)
    mod._trata_setcmd(campos((*ALAVANCAS, TECLA), saidas))


def toques() -> int:
    return sinais.count(f"controlart_tecla_{MAC}_{TECLA}")


async def ate_a_vigia_parar(mod, limite: float = 1.0) -> None:
    if mod._vigia is not None:
        await asyncio.wait_for(mod._vigia, limite)


class SegundoToque(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._espera = protocolo.ESPERA_TECLA
        protocolo.ESPERA_TECLA = 0.01

    def tearDown(self):
        protocolo.ESPERA_TECLA = self._espera

    async def test_dois_toques_sem_quadro_entre_eles(self):
        # o caso real: a cena inverte uma saida, e os dois quadros vem com a tecla em 1
        mod = modulo()
        toque(mod, 10.0, saidas=[7])
        await ate_a_vigia_parar(mod)
        toque(mod, 14.3, saidas=[])
        self.assertEqual(toques(), 2)

    async def test_pede_o_estado_uma_vez_quando_a_tecla_ja_foi_solta(self):
        mod = modulo()
        toque(mod, 10.0, saidas=[7])
        await ate_a_vigia_parar(mod)
        self.assertEqual(mod._writer.pedidos(), 1)
        self.assertEqual(mod.entradas[TECLA - 1], 0)
        self.assertEqual([mod.entradas[n - 1] for n in ALAVANCAS], [1, 1, 1])

    async def test_tecla_segurada_pede_de_novo_ate_aparecer_solta(self):
        mod = modulo(segurada_por=2)
        toque(mod, 10.0, saidas=[7])
        await ate_a_vigia_parar(mod)
        self.assertEqual(mod._writer.pedidos(), 3)
        self.assertEqual(mod.entradas[TECLA - 1], 0)
        self.assertEqual(toques(), 1)                     # segurar nao vira outro toque

    async def test_desiste_depois_de_algumas_tentativas(self):
        mod = modulo(segurada_por=100)
        toque(mod, 10.0, saidas=[7])
        await ate_a_vigia_parar(mod)
        self.assertEqual(mod._writer.pedidos(), protocolo.TENTATIVAS_TECLA)

    async def test_toques_seguidos_usam_uma_vigia_so(self):
        mod = modulo()
        toque(mod, 10.0, saidas=[7])
        primeira = mod._vigia
        mod._trata_setcmd(campos(ALAVANCAS, [7]))          # tecla solta antes da vigia
        toque(mod, 10.5, saidas=[])
        self.assertIs(mod._vigia, primeira)
        await ate_a_vigia_parar(mod)
        self.assertEqual(toques(), 2)

    async def test_interruptor_nao_gera_pedido(self):
        mod = modulo()
        relogio.agora = 10.0
        mod._trata_setcmd(campos((2, 5), [1]))             # alavanca 9 desce
        await asyncio.sleep(0.05)
        self.assertIsNone(mod._vigia)
        self.assertEqual(mod._writer.pedidos(), 0)

    async def test_desconectado_nao_pede(self):
        mod = modulo()
        mod.conectado = False
        toque(mod, 10.0, saidas=[7])
        self.assertIsNone(mod._vigia)
        self.assertEqual(toques(), 1)

    async def test_parar_cancela_a_vigia(self):
        protocolo.ESPERA_TECLA = 1.0
        mod = modulo()
        toque(mod, 10.0, saidas=[7])
        vigia = mod._vigia
        await mod.parar()
        await asyncio.sleep(0)
        self.assertTrue(vigia.cancelled())
        self.assertEqual(mod._writer.pedidos(), 0)


if __name__ == "__main__":
    unittest.main()
