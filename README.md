# ControlArt para Home Assistant

Integração local para os **módulos cabeados a relé da ControlArt** (10 saídas a relé, 12 entradas digitais), configurados pelo mdConfig. Fala direto com cada módulo por TCP na rede local: sem nuvem, sem Node-RED, sem outro Home Assistant no meio.

*English summary below.*

## O que aparece no Home Assistant

Cada módulo vira um dispositivo com:

| Entidade | Quantas | Para quê |
|---|---|---|
| `light` | 10 | As saídas. Liga e desliga, e o estado vem sempre do módulo |
| `event` | uma por tecla de keypad | Dispara um evento a cada toque, para usar em automações |
| `binary_sensor` | uma por entrada de interruptor | A posição da alavanca (diagnóstico, desligada por padrão) |
| `binary_sensor` | 1 | Se o módulo está respondendo |

Os interruptores e keypads da parede continuam funcionando como sempre: quem aciona as saídas é o módulo. O Home Assistant enxerga tudo o que acontece e manda comandos junto, sem um cancelar o outro.

## Instalação

**Pelo HACS**: HACS → menu ⋮ → *Repositórios personalizados* → `https://github.com/tompsonpecini/controlart`, categoria *Integração*. Instale e reinicie o Home Assistant.

**À mão**: copie a pasta `custom_components/controlart` para dentro de `config/custom_components/` e reinicie.

## Configuração

*Configurações → Dispositivos e serviços → Adicionar integração → ControlArt.*

1. Informe o **IP** do módulo. A porta é 4998, salvo se você mudou no mdConfig. O MAC não precisa: o módulo informa o próprio MAC quando é consultado.
2. Marque quais **entradas são teclas de keypad** (pulsadores). As demais são tratadas como interruptores comuns.
3. Para os outros módulos: na integração, **Configurar → Adicionar um módulo**.

O nome das saídas começa como "Saída 1", "Saída 2"… Renomeie no próprio Home Assistant e ponha cada uma na sua área; a integração não mexe no que você ajustou.

O módulo precisa de **IP fixo** (reserva no roteador ou IP estático no mdConfig).

## Dicas

- **Tecla de keypad numa automação**: use o gatilho de *estado* na entidade `event`. Cada toque muda o estado para o horário do toque. Filtre `not_to: [unknown, unavailable]` para não disparar quando o Home Assistant reinicia.
- **Interruptor comum numa automação**: a posição da alavanca **não** diz se a luz está acesa. O módulo inverte a saída a cada movimento, então as duas coisas se desencontram. Dispare em *qualquer* mudança do sensor da entrada e use `toggle`.
- **Cenas do keypad**: o módulo executa a cena programada no mdConfig quando a tecla é apertada na parede. Não existe comando para disparar essa cena remotamente. Para acioná-la pelo Home Assistant, reproduza-a num script.

## Limitações

- Só o módulo **relé** (10 saídas). O dimmer ControlArt é outro produto, com outro protocolo.
- Motores e cortinas configurados no módulo são ignorados.
- A integração não altera a programação do módulo; isso continua sendo feito no mdConfig.

O protocolo, com as armadilhas que apareceram pelo caminho, está descrito em [docs/protocolo.md](docs/protocolo.md).

---

## English summary

Local-push Home Assistant integration for **ControlArt wired relay modules** (10 relay outputs, 12 digital inputs). Each module becomes a device with 10 `light` entities, one `event` entity per keypad push button, one diagnostic `binary_sensor` per switch input, and a connectivity sensor. Setup only asks for the module's IP; the module reports its own MAC. Wall switches and keypads keep working through the module itself; Home Assistant follows every change and can switch outputs alongside them.

Not affiliated with ControlArt. Use at your own risk.
