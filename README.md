# DualSense Ultimate Control

Controle os LEDs do DualSense por uma janela e por um ícone na bandeja do sistema (Linux, Python + PySide6). Além das luzes, o app testa e calibra o controle e pode emulá-lo como um Xbox 360 (com perfis, mouse por touchpad e giroscópio). O nome do programa é **DualSense Ultimate Control**; o comando é `dualsense-ultimate-control` (o antigo `dualsense-led` segue como alias) e as pastas de configuração usam o mesmo nome. Ao abrir pela primeira vez, o app traz sozinho as configurações, perfis, histórico de calibração, log e início automático da pasta antiga `dualsense-led`.

- **Barra de luz**: sliders de cor (todo o espectro), saturação (de branco até a cor pura) e brilho (0–100%), mais cores prontas ou personalizada. Os degradês dos sliders mostram o efeito dos outros: a faixa de cor aparece na saturação atual, e a de saturação na cor atual.
- **LED do microfone**: um interruptor compacto acende o LED do botão de microfone de cada controle (não muda o microfone em si). O kernel não expõe esse LED, então o app escreve direto no `/dev/hidrawN` do controle, por USB ou Bluetooth. Só o que você liga é reenviado ao reconectar; o app não escreve "apagado" por conta própria, para não desfazer o que o botão de microfone do controle faz.
- **Jogadores automáticos**: com 2 ou mais controles conectados, cada um acende sozinho o LED de jogador da sua aba (o controle 1 é o jogador 1, o 2 é o jogador 2, e assim por diante), e a escolha manual fica travada, com os botões tracejados. Se um controle sai, os que ficam se renumeram; com um só controle, volta a valer a sua escolha. O interruptor **Jogadores automáticos** (grupo "Geral" da janela) desliga isso para você escolher à mão.
- **LEDs de jogador**: escolha o número do jogador (1 a 5) e o controle acende o mesmo padrão que o console usa: 1 = só o LED do meio, 2 = dois LEDs, 3 = três, 4 = quatro, 5 = todos. Clicar no número já escolhido apaga os LEDs.
- **Desconectar controle**: para um controle conectado por Bluetooth, o botão **Desconectar controle** (janela, grupo "LEDs do controle") e o item de mesmo nome no menu da bandeja desligam a ligação dele; para voltar, aperte o botão PS no controle. Controles por USB não têm esse botão, porque só dá para desconectá-los tirando o cabo.
- **Vários controles**: com mais de um DualSense conectado, aparecem abas ("1 · USB", "2 · Bluetooth") logo abaixo do status, no menu da bandeja e na janela. Tudo o que você muda vale só para o controle da aba selecionada. Cada controle guarda a própria cor, brilho e LEDs de jogador, identificado pelo endereço dele, e recupera esse estado quando reconecta (por USB ou Bluetooth).
- **Janela única**: a janela principal tem uma lista à esquerda com **Controles**, **Testar controle** (entradas, saídas, calibração, giroscópio e **Teste rápido**), **Perfis de emulação** e **Registros (logs)**. Tudo abre dentro dela; perguntas e avisos aparecem numa faixa no topo da página, e só o seletor de arquivo (importar/exportar perfil) é do sistema.
- **Cores rápidas**: um seletor com 7 cores prontas e um botão **+** que guarda a cor atual (a dos sliders) no seletor. Cada cor guardada fica salva no seletor (até 16, as mais antigas saem primeiro) e aparece tanto no menu da bandeja quanto na janela.
- **Ícone do app**: o mesmo desenho, num quadrado escuro (para aparecer em qualquer tema) com a barra em gradiente de cores. Vale para a janela, o atalho do menu e o início automático.
- **Ícone na bandeja**: o contorno de um controle com uma barra vertical ao lado na cor atual dos LEDs (já com o brilho aplicado; só o contorno quando o brilho é 0). O contorno usa a cor de texto do tema.
- **Menu na bandeja**: clique (esquerdo ou direito) no ícone abre um menu compacto junto à bandeja, com sliders de cor e brilho, "Cores rápidas" (expande o seletor), LEDs de jogador, "Expandir" e "Sair". O interruptor de iniciar com o sistema fica só na janela. O menu é desenhado pelo próprio app, porque o menu nativo da bandeja do Plasma só aceita itens de texto.
- **Janela**: aberta pelo menu de aplicativos, com os mesmos controles. Por padrão, fechar a janela (no X) só a esconde: o app continua na bandeja, e na primeira vez aparece uma notificação avisando. O interruptor **Ao fechar, manter na bandeja** (grupo "Geral") muda isso: desligado, fechar a janela encerra o app. Para encerrar com a opção ligada, use **Sair** no menu ou **Fechar** na janela.
- **Logs**: o app registra o que faz (controles conectados e desconectados, Steam, Bluetooth, permissões, avisos e erros) em `~/.local/state/dualsense-ultimate-control/dualsense-ultimate-control.log`, com rotação (até 512 KB por arquivo e 3 antigos). A página **Registros (logs)** da janela (lista à esquerda, ou o botão **Ver logs…** do grupo "Geral") mostra um visualizador com atualização automática, filtro "só avisos e erros", copiar, abrir a pasta e limpar. No terminal, `dualsense-ultimate-control --quit` pede ao app aberto que encerre e espera ele terminar de verdade; `dualsense-ultimate-control --logs` mostra o caminho e as últimas linhas, e `dualsense-ultimate-control --debug` registra também detalhes. Fechar o app esconde antes o ícone da bandeja, o menu e todas as janelas e registra cada etapa do encerramento; se a limpeza passar de 5 s, o processo é encerrado à força. Travamentos nativos (segfault) vão para `crash.log` na mesma pasta.
- **Idiomas**: português (padrão), inglês e espanhol. O menu **Idioma**, no grupo "Geral" da janela, troca na hora todos os textos (janela, menu da bandeja, avisos e dicas) e a escolha fica salva. Os textos ficam em `src/dualsense_ultimate_control/translations.py`: para corrigir uma tradução ou adicionar outro idioma, edite esse arquivo e inclua o código do idioma em `LANGUAGES` (`i18n.py`).
- **Iniciar com o sistema**: um interruptor na janela (grupo "Geral"). Ligado, cria `~/.config/autostart/dualsense-ultimate-control.desktop` e o app abre direto na bandeja quando você entra no computador; desligado, remove esse arquivo.
- **Tema do KDE**: o PySide6 do pip traz um Qt próprio que não carrega o Breeze do sistema. Se o Qt do sistema tiver exatamente a mesma versão, o app expõe só os plugins de tema e de estilo do Plasma e passa a usar o seu tema (Breeze, cores, fontes). Se as versões diferirem, mantém o estilo padrão do Qt. Para desligar, defina `DUALSENSE_ULTIMATE_NO_KDE_THEME=1`.
- **Wayland**: o app roda pelo XWayland, porque no Wayland nativo ele não pode posicionar o menu junto à bandeja. Para forçar outro modo, defina `QT_QPA_PLATFORM` (ex.: `QT_QPA_PLATFORM=wayland`).
- **Instância única**: só uma cópia roda por vez, mesmo se você abrir várias ao mesmo tempo. Abrir o app de novo (pelo menu, por exemplo) só traz a janela já aberta para frente.
- As configurações ficam em `~/.config/dualsense-ultimate-control/settings.json` e são reaplicadas sempre que um controle conecta (USB ou Bluetooth).

## Requisitos

- Linux com o driver `hid-playstation` (kernel 5.12+, já carregado na maioria das distros).
- Python 3.10+ e [uv](https://docs.astral.sh/uv/).
- Ambiente com bandeja do sistema: KDE funciona direto; no GNOME instale a extensão *AppIndicator and KStatusNotifierItem Support*.

## Permissão para escrever nos LEDs

O app **não precisa rodar como root**. Por padrão só o root pode alterar os LEDs; uma regra udev libera esses arquivos (e só eles) para o seu usuário.

**Pelo app:** quando falta permissão, a janela pergunta se você quer liberar o acesso, e o botão **Liberar acesso…** fica disponível. A senha de administrador é digitada na janela do próprio sistema (polkit/`pkexec`), nunca no app. A regra é instalada em `/etc/udev/rules.d/` e aplicada na hora, sem reconectar o controle. Se a permissão se perder depois, o app pergunta de novo.

**Manualmente**, se preferir:

```bash
sudo cp src/dualsense_ultimate_control/data/70-dualsense-ultimate-control.rules /etc/udev/rules.d/
```

```bash
sudo udevadm control --reload
```

Depois desconecte e reconecte o controle.

## Atalho no menu de aplicativos

```bash
./scripts/install-desktop.sh
```

Cria o atalho **DualSense Ultimate Control** no menu iniciar (em `~/.local/share/applications`), sem root. Rode de novo se mover a pasta do projeto.

## Executar pelo terminal

```bash
uv run dualsense-ultimate-control
```

Para iniciar só na bandeja, sem abrir a janela:

```bash
uv run dualsense-ultimate-control --tray
```

## Emulação de Xbox 360 (experimental)

Para jogos que só entendem controle de Xbox, o DualSense pode aparecer como um **Xbox 360 com fio** virtual (via `/dev/uinput`; o usuário precisa estar no grupo `input`):

```bash
uv run dualsense-ultimate-control --emulate
```

(ou `uv run python -m dualsense_ultimate_control.emulator`, que não carrega o Qt). A emulação vale por controle: o interruptor "Emular Xbox 360 neste controle" (janela e bandeja) marca o controle da aba selecionada, e a escolha fica salva pelo MAC. Cada DualSense marcado ganha um Xbox 360 virtual; controles que conectam ou desconectam depois são assumidos ou liberados sozinhos. Ctrl+C (ou SIGTERM) encerra e devolve os controles.

Enquanto a emulação roda, o gamepad do DualSense fica **exclusivo** do emulador (`EVIOCGRAB`), então quem lê `/dev/input/event*`/`js*` (evtest, jstest, jogos via evdev) só vê o Xbox virtual. Botões pela posição física: ✕→A, ○→B, □→X, △→Y, Create→Back, Options→Start, PS→Guide; L2/R2 viram os gatilhos analógicos. O repouso do analógico oscila entre 127 e 128 no controle; o emulador trata 127 como centro (0), então o eixo virtual fica parado sem ruído. O botão do microfone não é repassado. A vibração do jogo (`FF_RUMBLE`) chega aos motores do controle.

### Perfis

A página **Perfis de emulação** da janela principal edita os perfis, que ficam um por arquivo em `~/.config/dualsense-ultimate-control/profiles/` (também dá para importar e exportar). Um perfil pode:

- remapear cada botão para outro botão do Xbox, `lt`/`rt`, uma tecla (`key:KEY_SPACE`, por exemplo) ou nada;
- trocar os analógicos, inverter eixos e ajustar zona morta e curva de sensibilidade de cada um;
- tornar L2/R2 analógicos, digitais (com limiar) ou desligados;
- ligar a **resistência do gatilho adaptável** em L2/R2 (resistência, arma, arco, máquina ou vibração, com posição e força): o daemon a aplica ao ligar a emulação e a remove ao trocar de perfil, desmarcar o controle ou desligar a emulação;
- configurar o mouse virtual (abaixo).

Há um **perfil padrão** (vale para todos) e perfis por aplicativo: cada perfil lista executáveis ou AppIDs da Steam, e ele passa a valer **enquanto esse processo estiver rodando** (no Wayland não há forma portátil de saber a janela em foco). Vários perfis casando: vale o primeiro em ordem alfabética. O daemon relê perfis e escolhas sozinho, sem reiniciar.

### Touchpad e giroscópio como mouse

Num perfil, o grupo **Mouse** cria um mouse virtual (`DualSense Ultimate Control mouse`), só quando há movimento:

- **Touchpad** (`system` / `mouse` / `off`): em `mouse`, um dedo move o cursor, dois dedos rolam a página (subir o dedo rola para cima), tocar a metade esquerda clica e a metade direita (ou com dois dedos) faz o clique direito. `system` deixa o touchpad com o sistema, como sem emulação; `off` só o esconde. Há ajuste de velocidade.
- **Giroscópio** (`off` / `always` / `button` / `touch`): mira com o cursor. `always` sempre; `button` enquanto segura o botão escolhido (L2, por padrão); `touch` enquanto há um dedo no touchpad (o dedo vira só a embreagem e não move o cursor). Virar o controle para a direita move o cursor para a direita e apontá-lo para cima move o cursor para cima; há opção para inverter o eixo vertical e ajuste de sensibilidade (pixels por grau). A mira usa a correção do giroscópio feita na aba **Giroscópio** da página Testar controle.

### Rodar no login, sem abrir o app (serviço systemd)

```bash
scripts/install-service.sh           # instala e liga ~/.config/systemd/user/dualsense-ultimate-control-emulator.service
scripts/install-service.sh --remove  # desliga e remove
```

É uma opção manual (a janela não tem interruptor para isso). O serviço roda o mesmo daemon no login, sem o app. Quais controles são emulados continua sendo a escolha salva no `settings.json` (o daemon a relê sozinho), então marque-os uma vez pelo app. Com o serviço ativo o app **não liga um segundo daemon** (o interruptor só muda a escolha salva). Logs: `journalctl --user -u dualsense-ultimate-control-emulator`. Para o serviço subir mesmo sem sessão aberta use `loginctl enable-linger $USER`, mas o `/dev/uinput` precisa estar acessível: o módulo `uinput` carregado (`echo uinput | sudo tee /etc/modules-load.d/uinput.conf`) e o usuário no grupo `input` (ou uma regra udev `KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess"`, que a Steam e o KDE Connect já instalam em muitas distribuições). `scripts/diagnose.sh` confere uinput, grupo, serviço e Xbox virtuais.

**Steam Input:** com a Steam aberta e o Steam Input ligado para controles PlayStation, ela segura o hidraw do DualSense e o jogo pode ver dois controles (o físico e o Xbox virtual). O app mostra o aviso da Steam também para quem tem a emulação ligada, com a instrução de desativar o Steam Input para PlayStation. Sem a Steam rodando não há conflito.

**Limitação:** o grab não esconde o `/dev/hidrawN`. Programas que leem o hidraw direto (a Steam, e o SDL quando o driver HIDAPI de PlayStation está ligado) ainda veem o DualSense e podem mostrar dois controles. Para esses casos, desligue o driver HIDAPI do SDL para o jogo (`SDL_JOYSTICK_HIDAPI_PS5=0`) ou, no Proton/Steam, desative o Steam Input para controles PlayStation. Uma regra udev que esconda o controle físico (`ENV{ID_INPUT_JOYSTICK}=""` no nó do gamepad) também funciona para programas que filtram por udev, mas afeta o sistema inteiro.

**Limitação dos navegadores Chromium** (Chrome, Chromium, Edge, Brave, apps Electron): eles enxergam **só um** Xbox virtual de cada vez. Com dois controles emulados, testers como o hardwaretester.com/gamepad mostram um só, e desligar a emulação de um controle (ou desconectá-lo) faz o outro sumir também. O Chromium agrupa os gamepads pelo caminho no sysfs, e todo dispositivo criado por uinput fica em `/sys/devices/virtual/input/`, então ele trata todos como o mesmo aparelho. Isso não é bug do emulador: **jogos não são afetados**. No SDL (jogos nativos, Proton, Steam) cada Xbox virtual aparece separado, e desligar um não mexe nos outros. Para testar no navegador, use um controle emulado por vez; se o Xbox sumir, desligue e ligue de novo a emulação desse controle (isso recria o Xbox virtual, e o navegador volta a enxergá-lo). Firefox não foi testado.

## Testes

```bash
uv run python -m unittest discover tests
```

## Diagnóstico

Se o controle "conectar mas não aparecer" ou os comandos não fizerem efeito, rode `scripts/diagnose.sh`: ele mostra o que o Bluetooth, o kernel e o app enxergam, quem está com o controle aberto (a Steam ou o OpenRGB, por exemplo) e os últimos eventos e avisos.

## Conflito com a Steam

Com o Steam Input ativo, a Steam abre o controle diretamente (`/dev/hidrawN`) e envia as próprias cores e LEDs de jogador, passando por cima do que o app define. As mudanças parecem "voltar sozinhas".

O app detecta quando a Steam está com o controle selecionado aberto e mostra o aviso **⚠ Entrada Steam ativada…** no menu e na janela. O aviso explica como resolver, tem um botão que abre direto as configurações de controle da Steam e outro para reaplicar as cores do app. Para evitar a disputa, feche a Steam ou desative, nas configurações de controle da Steam, o Steam Input para controles PlayStation (ou as opções dela que controlam a barra de luz e o LED de jogador). Quando a Steam solta o controle, o app reaplica as suas cores sozinho.

## Créditos

O ícone do controle (na bandeja, na janela e no atalho) é o "Controller 1" do pacote Streamline Core (streamlinehq.com). Confira a licença do pacote antes de redistribuir o projeto.
