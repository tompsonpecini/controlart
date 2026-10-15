"""Transicao suave no dimmer: a integracao faz a rampa, nivel a nivel.

O modulo nao tem rampa propria conhecida, mas aceita qualquer nivel e
confirma em menos de 100 ms (conferido num modulo real), entao a rampa e
uma sequencia de comandos espacados. Roda em segundo plano: o servico do
Home Assistant volta na hora, e um comando novo no mesmo canal cancela a
rampa em andamento.
"""

from __future__ import annotations

import asyncio
import unittest

from ha_falso import EscritorFalso, const, light, protocolo, relogio, sinais

MAC = "0D-95-23"


class ModuloQueConfirma(EscritorFalso):
    """Responde a cada sendrele com o quadro do novo nivel, como o modulo real."""

    def __init__(self, mod) -> None:
        super().__init__()
        self.mod = mod
        self.estado = list(mod.saidas)       # o modulo guarda o proprio estado

    def write(self, dados: bytes) -> None:
        super().write(dados)
        partes = dados.decode("ascii").strip().split(",")
        if partes[0] == "mdcmd_sendrele":
            self.estado[int(partes[4])] = int(partes[5])
            asyncio.get_running_loop().call_soon(self._quadro, list(self.estado))

    def _quadro(self, niveis) -> None:
        self.estado = list(niveis)
        relogio.agora += 5
        self.mod._trata_linha(",".join(["setdmmd", MAC, *["0"] * 12, *map(str, niveis)]))

    def niveis(self, canal: int) -> list[int]:
        return [
            int(c.strip().split(",")[5])
            for c in self.enviado
            if c.startswith("mdcmd_sendrele") and int(c.split(",")[4]) == canal - 1
        ]


def dimmer():
    sinais.clear()
    relogio.agora = 0.0
    mod = protocolo.ModuloConexao(
        None,
        {"mac": MAC, "host": "x", "port": 4998, "name": "Dimmer",
         const.CONF_TIPO: const.TIPO_DIMMER, const.CONF_SAIDAS: 9},
    )
    mod._trata_linha(",".join(["setdmmd", MAC, *["0"] * 21]))
    mod.conectado = True
    mod._writer = ModuloQueConfirma(mod)
    return mod


async def ate_parar(mod, canal, limite=2.0):
    tarefa = mod._rampas.get(canal)
    if tarefa is not None:
        await asyncio.wait_for(tarefa, limite)


class Rampa(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._passo = protocolo.PASSO_RAMPA
        protocolo.PASSO_RAMPA = 0.01

    def tearDown(self):
        protocolo.PASSO_RAMPA = self._passo

    async def test_sobe_em_degraus_iguais_ate_o_alvo(self):
        mod = dimmer()
        mod.rampa(1, 255, 0.05)
        await ate_parar(mod, 1)
        self.assertEqual(mod._writer.niveis(1), [51, 102, 153, 204, 255])
        self.assertEqual(mod.saidas[0], 255)

    async def test_desce_ate_apagar(self):
        mod = dimmer()
        mod._writer._quadro([200] + [0] * 8)
        mod.rampa(1, 0, 0.04)
        await ate_parar(mod, 1)
        self.assertEqual(mod._writer.niveis(1), [150, 100, 50, 0])

    async def test_nao_passa_de_um_degrau_por_nivel(self):
        mod = dimmer()
        mod.rampa(1, 3, 1.0)                                # 100 passos possiveis, so 3 niveis
        await ate_parar(mod, 1)
        self.assertEqual(mod._writer.niveis(1), [1, 2, 3])

    async def test_comando_novo_cancela_a_rampa(self):
        mod = dimmer()
        mod.rampa(1, 255, 1.0)
        await asyncio.sleep(0.05)
        await mod.envia_nivel(1, 0)
        await asyncio.sleep(0.05)
        self.assertEqual(mod.saidas[0], 0)
        self.assertEqual(mod._writer.niveis(1)[-1], 0)
        self.assertNotIn(1, mod._rampas)

    async def test_descarregar_a_integracao_para_a_rampa(self):
        mod = dimmer()
        mod.rampa(1, 255, 1.0)
        tarefa = mod._rampas[1]
        await asyncio.sleep(0.03)
        await mod.parar()
        await asyncio.sleep(0)
        self.assertTrue(tarefa.done())
        self.assertEqual(mod._rampas, {})

    async def test_apagar_com_transicao_lembra_o_nivel_de_antes(self):
        # antes, os degraus da descida contavam: acender depois ia ao ultimo (50)
        mod = dimmer()
        mod._writer._quadro([200] + [0] * 8)
        mod.rampa(1, 0, 0.04)
        await ate_parar(mod, 1)
        self.assertEqual(mod.saidas[0], 0)
        self.assertEqual(mod.nivel_ao_ligar(1), 200)

    async def test_acender_no_meio_da_descida_volta_ao_nivel_de_antes(self):
        mod = dimmer()
        mod._writer._quadro([255] + [0] * 8)
        mod.rampa(1, 0, 1.0)
        await asyncio.sleep(0.05)
        self.assertLess(mod.saidas[0], 255)                 # ja desceu alguns degraus
        self.assertEqual(mod.nivel_ao_ligar(1), 255)

    async def test_subir_com_transicao_lembra_o_alvo(self):
        mod = dimmer()
        mod.rampa(1, 180, 0.04)
        await ate_parar(mod, 1)
        await mod.envia_nivel(1, 0)
        self.assertEqual(mod.nivel_ao_ligar(1), 180)

    async def test_canais_independentes(self):
        mod = dimmer()
        mod.rampa(1, 255, 0.05)
        mod.rampa(2, 102, 0.05)
        await ate_parar(mod, 1)
        await ate_parar(mod, 2)
        self.assertEqual((mod.saidas[0], mod.saidas[1]), (255, 102))


class Luz(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._passo = protocolo.PASSO_RAMPA
        protocolo.PASSO_RAMPA = 0.01

    def tearDown(self):
        protocolo.PASSO_RAMPA = self._passo

    def test_anuncia_transicao(self):
        canal = light.CanalDimmer(dimmer(), 1)
        self.assertTrue(canal._attr_supported_features & light.LightEntityFeature.TRANSITION)

    async def test_ligar_com_transicao_volta_na_hora(self):
        mod = dimmer()
        await asyncio.wait_for(
            light.CanalDimmer(mod, 1).async_turn_on(brightness=200, transition=0.05), 0.02
        )
        await ate_parar(mod, 1)
        self.assertEqual(mod.saidas[0], 200)

    async def test_desligar_com_transicao(self):
        mod = dimmer()
        mod._writer._quadro([255] + [0] * 8)
        await light.CanalDimmer(mod, 1).async_turn_off(transition=0.03)
        await ate_parar(mod, 1)
        self.assertEqual(mod.saidas[0], 0)
        self.assertGreater(len(mod._writer.niveis(1)), 1)


if __name__ == "__main__":
    unittest.main()
