# Protocolo dos módulos cabeados relé e dimmer

Notas levantadas observando módulos reais (firmware 3.022) e o terminal do mdConfig. Não há documentação oficial. O que está aqui foi conferido na prática, mas pode variar em outros firmwares. O dimmer tem seção própria no fim; o resto vale para os dois.

## Transporte

- TCP, porta **4998** por padrão (configurável no mdConfig). A porta 4999 também atende e recebe os mesmos quadros.
- Texto ASCII, uma mensagem por linha, terminada em `\r\n`.
- Aceita **várias conexões ao mesmo tempo**. Todas recebem os mesmos quadros, então o Home Assistant pode conviver com o mdConfig aberto.
- Responde em cerca de 2 ms.

## Endereço

Os comandos levam o endereço do módulo: os **três últimos bytes do MAC, em decimal**.

```
MAC AA-BB-CC  ->  endereço 170,187,204
```

O endereço `255,255,255` funciona como **difusão** no pedido de estado: o módulo responde com o próprio estado, e o MAC vem no quadro. É assim que a integração descobre o endereço sabendo só o IP.

## Pedir o estado

```
-> mdcmd_getmd,170,187,204
<- setcmd,AA-BB-CC,<12 entradas>,<10 saídas>
<- setbmcb0md,AA-BB-CC,0,0,0,255      (5 linhas, configuração de motores)
```

Cada entrada e cada saída é `0` ou `1`. Exemplo de um módulo com as saídas 1 e 3 acesas e a entrada 2 fechada:

```
setcmd,AA-BB-CC,0,1,0,0,0,0,0,0,0,0,0,0,1,0,1,0,0,0,0,0,0,0
```

## Mudanças espontâneas

O módulo **só fala quando algo muda**. Ele não manda o estado ao conectar e não tem batimento, então quem conecta precisa pedir o estado logo de cara e, de tempos em tempos, confirmar que a conexão está viva.

Cada mudança gera um **par** de quadros `setcmd`:

1. o real, com as entradas e saídas como ficaram;
2. até cerca de 2 s depois, um **quadro de limpeza**, com as 12 entradas zeradas e as saídas inalteradas.

O quadro de limpeza não reflete as entradas de verdade e precisa ser descartado. Se não for, um interruptor ligado parece desligar sozinho um instante depois.

**Tecla de keypad não segue essa regra.** Num módulo real, dois toques na mesma tecla, com 4 s entre eles, chegaram como dois quadros com a tecla em `1` e nenhum quadro de limpeza no meio. O quadro mostra as entradas como estão no instante do envio, com a tecla ainda apertada, e o módulo não avisa quando ela é solta. Quem espera a borda de subida perde o segundo toque. A integração pede o estado (`mdcmd_getmd`) a cada segundo depois de um toque, até 5 vezes, até a tecla aparecer solta.

## Ligar e desligar uma saída

```
-> mdcmd_sendrele,170,187,204,<canal 0-9>,<0|1>
<- setcmd,...        (confirmação, em milissegundos)
```

O comando é **absoluto e idempotente**: "liga" numa saída já acesa não faz nada. Não existe um comando de inverter.

## Outros comandos

Vistos no driver Hubitat para os mesmos módulos ([hhorigian/hubitat_Controlart_Relays](https://github.com/hhorigian/hubitat_Controlart_Relays)).

```
-> mdcmd_setallonmd,170,187,204      acende todas as saídas deste módulo
-> mdcmd_setalloffmd,170,187,204     apaga todas as saídas deste módulo
-> mdcmd_setmasteronmd               sem endereço; responde "MasterOn"
-> mdcmd_setmasteroffmd              sem endereço; responde "MasterOff"
-> get_firmware_version
<- 3027                              relé; o dimmer respondeu 1021
-> get_mac_addr
<- macaddr_RT,AA-BB-CC               relé; o dimmer respondeu macaddr,AA-BB-CC
```

Conferidos num módulo real: `get_firmware_version` e `get_mac_addr`. O firmware vem só como número (o driver Hubitat espera uma linha começando com `VERSION`, que estes módulos não mandam), e o MAC vem curto, igual ao do quadro de estado. Os `setall*` e `setmaster*` ainda **não** foram enviados a um módulo real por esta integração.

A integração só pede firmware e MAC a cada conexão, para o diagnóstico. Não usa o `setall*` nem o `setmaster*`: um módulo agrupa circuitos pela fiação, não por ambiente, então "acender o módulo inteiro" raramente corresponde a algo que se queira; e o `setmaster*`, sem endereço, pelo que descreve o driver ELAN da T4Control, vale para todos os módulos da instalação.

As linhas de motor que acompanham o estado do relé vêm assim num módulo sem motor configurado, uma por motor (0 a 4):

```
<- setbmcb0md,AA-BB-CC,0,0,0,255
```

## Tipos de entrada (mdConfig)

- **Interruptor retentivo**: a alavanca fica numa posição. O módulo inverte as saídas vinculadas a **cada transição**, então a posição da alavanca não indica se a luz está acesa.
- **Pulsador** (tecla de keypad): um pulso curto por toque. A cena vinculada roda na borda de subida.

Os vínculos entre entrada e saída ficam gravados no módulo. Cada vínculo tem um tipo: `0` inverte, `1` liga, `2` desliga.

## Armadilhas

- `Parse Error!` só aparece para **nome de comando desconhecido**. Um comando com nome válido e argumentos errados, incluindo endereço errado, é engolido em silêncio.
- Não há comando conhecido para disparar remotamente a cena de uma tecla. `mdcmd_sendcmd`, usado pelo mdConfig, grava a programação; não aciona.
- Não confie em "a entrada mudou" num quadro isolado; veja a regra do quadro de limpeza acima.
- O módulo não avisa quando uma tecla de keypad é solta. Sem pedir o estado depois do toque, o toque seguinte na mesma tecla não tem borda de subida.
- Um módulo sem energia ou com o cabo solto não fecha a conexão TCP. Só dá para perceber a queda pedindo o estado e esperando a resposta.

## Módulo dimmer

Mesmo transporte, mesmo endereço e mesmos comandos do relé. Muda o cabeçalho do quadro de estado e o significado dos valores das saídas.

```
-> mdcmd_getmd,13,149,35
<- setdmmd,0D-95-23,1,0,0,0,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0
```

- `setdmmd` no lugar de `setcmd`: o cabeçalho diz o tipo do módulo, então o cadastro reconhece o dimmer sozinho.
- Depois do MAC vêm as mesmas **12 entradas** e, em seguida, um **nível por canal**, de 0 (apagado) a 255. O módulo conhecido tem **9 canais**; a integração lê a quantidade do tamanho do quadro.
- Não vieram linhas `setbmcb0md` depois do estado.

Escrita, com o nível no lugar do 0/1:

```
-> mdcmd_sendrele,13,149,35,<canal 0-8>,<nível 0-255>
<- setdmmd,...       (confirmação, em menos de 100 ms)
```

O módulo aceita **qualquer nível** de 0 a 255 e devolve exatamente o nível pedido: 128 e 10 foram conferidos num módulo real. Instalações feitas com outras ferramentas costumam usar só 0, 51, 102, 153, 204 e 255, mas isso é escolha delas, não limite do módulo.

Ainda não conferido no módulo real: se o par de quadros (real e limpeza) se repete igual ao do relé quando uma entrada muda.
