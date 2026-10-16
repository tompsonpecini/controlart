# ControlArt para Home Assistant

Integração local para os **módulos cabeados da ControlArt**, configurados pelo mdConfig: o **relé** (10 saídas a relé, 12 entradas digitais) e o **dimmer** (canais com nível de 0 a 255, 12 entradas digitais). Fala direto com cada módulo por TCP na rede local: sem nuvem, sem Node-RED, sem outro Home Assistant no meio.

_English summary below._

## O que aparece no Home Assistant

Cada módulo vira um dispositivo com:

| Entidade        | Quantas                             | Para quê                                                                           |
| --------------- | ----------------------------------- | ---------------------------------------------------------------------------------- |
| `light`         | 10 no relé, uma por canal no dimmer | As saídas. Liga e desliga (com brilho, no dimmer), e o estado vem sempre do módulo |
| `event`         | uma por tecla de keypad             | Dispara um evento a cada toque, para usar em automações                            |
| `binary_sensor` | uma por entrada de interruptor      | A posição da alavanca (diagnóstico, desligada por padrão)                          |
| `binary_sensor` | 1                                   | Se o módulo está respondendo                                                       |
| `sensor`        | 1                                   | O endereço IP do módulo (diagnóstico), visível mesmo com ele fora do ar            |

O card do dispositivo mostra o **firmware**, como o mdConfig (por exemplo 3.027).

A página da integração também oferece **Baixar diagnóstico**: as últimas linhas trocadas com cada módulo, o firmware e o MAC que ele informa, e quantas vezes a conexão caiu. Serve para suporte a distância, sem terminal na rede da instalação.

Os interruptores e keypads da parede continuam funcionando como sempre: quem aciona as saídas é o módulo. O Home Assistant enxerga tudo o que acontece e manda comandos junto, sem um cancelar o outro.

## Instalação

### HACS (recomendado)

[![Abrir este repositório no HACS do seu Home Assistant.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tompsonpecini&repository=controlart&category=integration)

O botão abre este repositório direto no seu HACS. Clique em **Baixar** e reinicie o Home Assistant.

Ele funciona pelo [my.home-assistant.io](https://my.home-assistant.io/), que só sabe chegar na sua instância depois que você informa o endereço dela uma vez, em **Configurações → Sistema → Rede → URL do Home Assistant**. Até lá, ele pergunta.

<details>
<summary>Fazendo à mão</summary>

1. HACS → menu ⋮ → **Repositórios personalizados**.
2. URL `https://github.com/tompsonpecini/controlart`, categoria **Integração** → **Adicionar**.
3. Abra o repositório e clique em **Baixar**.
4. Reinicie o Home Assistant.

</details>

### À mão

Copie a pasta `custom_components/controlart` para dentro de `config/custom_components/` e reinicie.

## Configuração

[![Começar o cadastro da integração ControlArt no seu Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=controlart)

O botão abre o cadastro direto. Sem ele: _Configurações → Dispositivos e serviços → Adicionar integração → ControlArt._

1. Informe o **IP** do módulo. A porta é 4998, salvo se você mudou no mdConfig. O MAC e o tipo não precisam: o módulo informa os dois quando é consultado.
2. Marque quais **entradas são teclas de keypad** (pulsadores). As demais são tratadas como interruptores comuns.
3. Para os outros módulos: na integração, **Configurar → Adicionar um módulo**.

O nome das saídas começa como "Saída 1", "Saída 2"… Renomeie no próprio Home Assistant e ponha cada uma na sua área; a integração não mexe no que você ajustou.

O módulo precisa de **IP fixo** (reserva no roteador ou IP estático no mdConfig).

## Dicas

- **Tecla de keypad numa automação**: use o gatilho de _estado_ na entidade `event`. Cada toque muda o estado para o horário do toque. Filtre `not_to: [unknown, unavailable]` para não disparar quando o Home Assistant reinicia. Dois toques seguidos na mesma tecla precisam de pouco mais de 1 s entre eles para virar dois eventos.
- **Interruptor comum numa automação**: a posição da alavanca **não** diz se a luz está acesa. O módulo inverte a saída a cada movimento, então as duas coisas se desencontram. Dispare em _qualquer_ mudança do sensor da entrada e use `toggle`.
- **Cenas do keypad**: o módulo executa a cena programada no mdConfig quando a tecla é apertada na parede. Não existe comando para disparar essa cena remotamente. Para acioná-la pelo Home Assistant, reproduza-a num script.
- **Dimmer aceso sem brilho escolhido** (botão, voz, "acender a sala"): o canal volta ao último nível em que ficou aceso desde que o Home Assistant iniciou; se nunca acendeu, vai ao máximo. Os degraus de uma transição não contam: apagar devagar e acender de novo volta ao nível de antes.
- **Transição no dimmer** (`transition` em `light.turn_on` e `light.turn_off`): a integração faz a rampa, um nível de cada vez, com pelo menos 0,2 s entre os degraus. O serviço volta na hora; um comando novo no mesmo canal cancela a rampa.
- **Comando que o módulo não confirma** vira erro no Home Assistant em vez de passar em silêncio. Um módulo que para de responder derruba a conexão e as entidades ficam indisponíveis até ele voltar.
- **Script que acende várias luzes em sequência**: ponha `continue_on_error: true` nas ações de luz. Sem isso, um comando não confirmado interrompe o resto do script.

## Limitações

- Motores e cortinas configurados no módulo são ignorados: o comando de motor não é conhecido. As linhas de configuração de motor que o módulo manda aparecem no diagnóstico.
- A integração não altera a programação do módulo; isso continua sendo feito no mdConfig.

O protocolo, com as armadilhas que apareceram pelo caminho, está descrito em [docs/protocolo.md](docs/protocolo.md).

Os testes rodam sem o Home Assistant instalado, só com a biblioteca padrão: `python -m unittest discover -s tests`.

---

## English summary

Local-push Home Assistant integration for **ControlArt wired modules**: the relay module (10 relay outputs, 12 digital inputs) and the dimmer module (channels with a 0 to 255 level, 12 digital inputs). Each module becomes a device with one `light` entity per output (with brightness on the dimmer), one `event` entity per keypad push button, one diagnostic `binary_sensor` per switch input, a connectivity sensor and a diagnostic IP sensor. The device card shows the module firmware, and **Download diagnostics** returns the last lines exchanged with each module. Setup only asks for the module's IP; the module reports its own MAC and type. Wall switches and keypads keep working through the module itself; Home Assistant follows every change and can switch outputs alongside them.

Install with the HACS button above (or add `https://github.com/tompsonpecini/controlart` as a custom repository, type Integration), restart, then use the setup button to add the first module.

Not affiliated with ControlArt. Use at your own risk.
