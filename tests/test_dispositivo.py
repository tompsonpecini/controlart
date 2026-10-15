"""Firmware no card "Informacoes do dispositivo" do Home Assistant.

O firmware so chega depois da conexao, entao atualiza o dispositivo ja
registrado. O MAC nao entra como MAC de rede: o modulo so informa os tres
ultimos bytes, que ficam como identificador do dispositivo.
"""

from __future__ import annotations

import sys
import unittest

from ha_falso import light, protocolo, registro, sinais

MAC = "4E-50-D2"


def rele():
    sinais.clear()
    return protocolo.ModuloConexao(
        None, {"mac": MAC, "host": "192.168.68.21", "port": 4998, "name": "Hubb M1"}
    )


class Firmware(unittest.TestCase):
    def test_numero_vira_versao_com_ponto(self):
        mod = rele()
        mod._trata_linha("3027")
        self.assertEqual(mod.versao_firmware, "3.027")

    def test_dimmer(self):
        mod = rele()
        mod._trata_linha("1021")
        self.assertEqual(mod.versao_firmware, "1.021")

    def test_formato_do_driver_hubitat(self):
        mod = rele()
        mod._trata_linha("VERSION 3.022")
        self.assertEqual(mod.versao_firmware, "3.022")

    def test_sem_resposta_fica_vazio(self):
        self.assertIsNone(rele().versao_firmware)

    def test_avisa_quando_chega(self):
        mod = rele()
        mod._trata_linha("3027")
        self.assertIn(f"controlart_identidade_{MAC}", sinais)

    def test_nao_avisa_de_novo_se_nao_mudou(self):
        mod = rele()
        mod._trata_linha("3027")
        sinais.clear()
        mod._trata_linha("3027")
        self.assertNotIn(f"controlart_identidade_{MAC}", sinais)


class Mac(unittest.TestCase):
    def test_tres_bytes_nao_viram_mac_de_rede(self):
        info = light.Saida(rele(), 1)._attr_device_info
        self.assertNotIn("connections", info)
        self.assertEqual(info["identifiers"], {("controlart", MAC)})


def dispositivo(ident, sw_version=None):
    return type("Dispositivo", (), {
        "id": ident[1], "identifiers": {ident}, "sw_version": sw_version,
    })()


class RegistroFalso:
    """So o que atualiza_dispositivo usa. Sem async_get_device: desde o HA
    2026.10 ele avisa que esta obsoleto, e o substituto nao existe nas versoes
    antigas que o hacs.json ainda aceita."""

    def __init__(self, *dispositivos):
        self.dispositivos = list(dispositivos)
        self.atualizacoes: list[dict] = []

    def async_update_device(self, device_id, **mudancas):
        self.atualizacoes.append({"id": device_id, **mudancas})


class AtualizaDispositivo(unittest.TestCase):
    def setUp(self):
        self.dr = sys.modules["homeassistant.helpers.device_registry"]
        self.pedido_entry = None

    def tearDown(self):
        self.dr.async_get = None
        self.dr.async_entries_for_config_entry = None

    def usa(self, falso):
        def entries(registro_, entry_id):
            self.pedido_entry = entry_id
            return registro_.dispositivos

        self.dr.async_get = lambda hass: falso
        self.dr.async_entries_for_config_entry = entries

    def test_grava_o_firmware_so_no_dispositivo_do_modulo(self):
        falso = RegistroFalso(dispositivo(("controlart", "74-14-6E")), dispositivo(("controlart", MAC)))
        self.usa(falso)
        mod = rele()
        mod._trata_linha("3027")
        registro.atualiza_dispositivo(None, "entrada1", mod)
        self.assertEqual(self.pedido_entry, "entrada1")
        self.assertEqual(falso.atualizacoes, [{"id": MAC, "sw_version": "3.027"}])

    def test_firmware_igual_nao_regrava(self):
        falso = RegistroFalso(dispositivo(("controlart", MAC), sw_version="3.027"))
        self.usa(falso)
        mod = rele()
        mod._trata_linha("3027")
        registro.atualiza_dispositivo(None, "entrada1", mod)
        self.assertEqual(falso.atualizacoes, [])

    def test_sem_firmware_nao_mexe(self):
        falso = RegistroFalso(dispositivo(("controlart", MAC), sw_version="3.027"))
        self.usa(falso)
        registro.atualiza_dispositivo(None, "entrada1", rele())
        self.assertEqual(falso.atualizacoes, [])


if __name__ == "__main__":
    unittest.main()
