"""Constantes da integracao ControlArt."""

DOMAIN = "controlart"

PORTA_PADRAO = 4998
INTERVALO_GETMD = 120          # s · pedido periodico de estado, serve de keepalive
JANELA_LIMPEZA = 2.0           # s · quadro com entradas zeradas logo apos outro
RECONEXAO_MAX = 30             # s · teto da espera progressiva
TIMEOUT_SONDA = 5.0            # s · para o modulo responder ao ser cadastrado

N_SAIDAS = 10
N_ENTRADAS = 12

# chaves da configuracao guardada na entrada
CONF_MODULOS = "modules"
CONF_TECLAS = "keypad_inputs"   # entradas ligadas a teclas de keypad (pulsadores)

SIGNAL_ESTADO = "controlart_estado_{}"      # por mac
SIGNAL_TECLA = "controlart_tecla_{}_{}"     # por mac, entrada
SIGNAL_CONEXAO = "controlart_conexao_{}"    # por mac
