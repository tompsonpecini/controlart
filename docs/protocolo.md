# Protocolo do módulo cabeado relé

Notas levantadas observando módulos reais (firmware 3.022) e o terminal do mdConfig. Não há documentação oficial. O que está aqui foi conferido na prática, mas pode variar em outros firmwares.

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

## Ligar e desligar uma saída

```
-> mdcmd_sendrele,170,187,204,<canal 0-9>,<0|1>
<- setcmd,...        (confirmação, em milissegundos)
```

O comando é **absoluto e idempotente**: "liga" numa saída já acesa não faz nada. Não existe um comando de inverter.

## Tipos de entrada (mdConfig)

- **Interruptor retentivo**: a alavanca fica numa posição. O módulo inverte as saídas vinculadas a **cada transição**, então a posição da alavanca não indica se a luz está acesa.
- **Pulsador** (tecla de keypad): um pulso curto por toque. A cena vinculada roda na borda de subida.

Os vínculos entre entrada e saída ficam gravados no módulo. Cada vínculo tem um tipo: `0` inverte, `1` liga, `2` desliga.

## Armadilhas

- `Parse Error!` só aparece para **nome de comando desconhecido**. Um comando com nome válido e argumentos errados, incluindo endereço errado, é engolido em silêncio.
- Não há comando conhecido para disparar remotamente a cena de uma tecla. `mdcmd_sendcmd`, usado pelo mdConfig, grava a programação; não aciona.
- Não confie em "a entrada mudou" num quadro isolado; veja a regra do quadro de limpeza acima.
