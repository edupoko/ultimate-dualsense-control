# DualSense Ultimate Control

Aplicativo para **Linux** que controla o **DualSense** (o controle do PlayStation 5). Ele reúne tudo o que o controle faz e o que o sistema normalmente não mostra:

- **Luzes**: cor, brilho e LEDs de jogador, com uma janela e um ícone na bandeja.
- **Teste**: confere botões, analógicos, touchpad, sensores, gatilhos, vibração, luzes, áudio e microfone.
- **Calibração**: analógicos e giroscópio.
- **Emulação**: faz o DualSense aparecer como um **Xbox 360** para jogos e programas, com perfis de botões, touchpad e giroscópio usados como mouse e vibração repassada ao controle.

Funciona por **USB** e por **Bluetooth**, com um ou vários controles ao mesmo tempo.

O nome do programa é **DualSense Ultimate Control**. O comando, o pacote e as pastas de configuração usam `dualsense-ultimate-control` (o antigo `dualsense-led` continua como alias).

## Requisitos

- Linux com o driver `hid-playstation` (kernel 5.12 ou mais novo; já vem carregado na maioria das distribuições).
- Python 3.10+ e [uv](https://docs.astral.sh/uv/).
- Para a bandeja: KDE funciona direto. No GNOME, instale a extensão *AppIndicator and KStatusNotifierItem Support*.
- Para a emulação: acesso a `/dev/uinput` (veja [Emulação](#emulação-xbox-360)).

## Instalação e uso

```bash
uv run dualsense-ultimate-control          # abre a janela
uv run dualsense-ultimate-control --tray   # só o ícone na bandeja, sem janela
```

Para ter o atalho no menu de aplicativos (sem root; rode de novo se mover a pasta do projeto):

```bash
./scripts/install-desktop.sh
```

Só uma cópia do app roda por vez: abrir de novo traz a janela já aberta para frente.

### Permissão para escrever nos LEDs

O app **não precisa de root**. Por padrão só o root altera os LEDs, então uma regra udev libera esses arquivos para o seu usuário. Quando faltar essa permissão, a janela oferece o botão **Liberar acesso…**, que pede a senha de administrador na janela do próprio sistema (polkit). A regra fica em `/etc/udev/rules.d/` e vale na hora.

Para instalar à mão:

```bash
sudo cp src/dualsense_ultimate_control/data/70-dualsense-ultimate-control.rules /etc/udev/rules.d/
sudo udevadm control --reload
```

Depois, desconecte e reconecte o controle.

## O que o app faz

### Janela e bandeja

A janela tem uma lista à esquerda com quatro páginas:

- **Controles**: barra de luz, LEDs de jogador, LED do microfone, desconexão (Bluetooth), emulação e perfil.
- **Testar controle**: entradas ao vivo, saídas, calibração, giroscópio e teste rápido.
- **Perfis de emulação**: criar, editar, importar e exportar perfis.
- **Registros**: os logs do app, com atualização automática e filtros.
- **Configurações**: idioma, tema, início com o sistema e comportamento ao fechar.

Tudo abre dentro da própria janela. Perguntas e avisos aparecem numa faixa no topo da página.

Fechar a janela só a esconde, e o app continua na bandeja (desligue **Ao fechar, manter na bandeja** em Configurações para encerrar de vez). O menu da bandeja tem sliders de cor e brilho, cores rápidas, LEDs de jogador e o botão **Sair**.

### Luzes

- **Barra de luz**: cor (todo o espectro), saturação e brilho, com cores prontas e cores personalizadas (até 16 guardadas).
- **LEDs de jogador**: de 1 a 5, no mesmo padrão do console.
- **LED do microfone**: acende o LED do botão de microfone sem mudar o microfone do sistema. O kernel não expõe esse LED, então o app o escreve direto no `hidraw`. Só o que você liga é reenviado ao reconectar.
- **Vários controles**: cada um tem a própria aba, com cor, brilho e LEDs guardados pelo endereço dele. Com dois ou mais, os LEDs de jogador podem ser automáticos (o controle 1 é o jogador 1, e assim por diante); o interruptor **Jogadores automáticos** desliga isso.
- **Desconectar**: para controles Bluetooth, desliga a ligação (para voltar, aperte o botão PS). Controles USB só saem tirando o cabo.

### Testar controle

- **Entradas**: o desenho do controle acende cada botão e o direcional, mostra os analógicos com o alcance e a circularidade, os dedos no touchpad, a pressão de L2/R2 em porcentagem e o gráfico do giroscópio.
- **Saídas**: motores de vibração, efeitos dos gatilhos adaptáveis (resistência, arma, arco, máquina e vibração), sequência de LEDs, tom de áudio no alto-falante e no fone e medidor do microfone.
- **Calibração**: centro e alcance dos analógicos, com histórico local. A calibração só vale até reiniciar o controle, a menos que você clique em **Salvar no controle**.
- **Giroscópio**: mede o desvio com o controle parado e guarda a correção no `settings.json`, para o emulador usar.
- **Teste rápido**: checklist guiado de todo o controle.

Cada teste desfaz o que ligou ao sair da aba: vibração, gatilhos e LEDs voltam ao normal.

> **Atenção:** a calibração e o salvamento gravam no controle. Só salve depois de confirmar o resultado.

### Emulação (Xbox 360)

Com a emulação ligada para um controle, o app cria um **Xbox 360 virtual** (045E:028E) para ele. Jogos e programas que aceitam XInput, SDL ou Proton o veem como um controle de Xbox.

- **Botões, eixos e gatilhos** chegam ao Xbox virtual, com a posição física (✕ ○ □ △ viram A B X Y).
- **Vibração**: o rumble do jogo é repassado ao DualSense (motores forte e fraco).
- **Perfis** (`~/.config/dualsense-ultimate-control/profiles/`): cada perfil troca botões por outros botões, teclas ou gatilhos; inverte e troca analógicos; ajusta zona morta e curva; e define o gatilho analógico ou digital e a resistência do L2/R2. O perfil padrão vale para tudo; um perfil por aplicativo vale enquanto o processo dele estiver rodando.
- **Touchpad como mouse** (`system` / `mouse` / `off`): um dedo move o cursor, dois dedos rolam, e os cliques são esquerdo e direito.
- **Giroscópio como mouse** (`off` / `always` / `button` / `touch`): vire o controle para mirar. A sensibilidade e a inversão vertical são ajustáveis.
- **Por controle**: cada DualSense tem a própria escolha de emulação, salva no `settings.json`.

Para rodar a emulação sem abrir o app, há um serviço de usuário (opcional):

```bash
scripts/install-service.sh           # instala e liga o serviço
scripts/install-service.sh --remove  # desliga e remove
```

Com o serviço ativo, o app não liga um segundo daemon. Para ele subir sem sessão aberta, use `loginctl enable-linger $USER`.

**Acesso ao `/dev/uinput`**: o usuário precisa poder escrever nele. Em geral basta estar no grupo `input`, ou ter a regra `KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess"` (a Steam e o KDE Connect costumam instalar uma). Carregue o módulo com `echo uinput | sudo tee /etc/modules-load.d/uinput.conf`. Para conferir tudo, rode `scripts/diagnose.sh`.

#### Limitações conhecidas

- **Steam Input**: com a Steam aberta e o Steam Input ligado para controles PlayStation, ela segura o DualSense e o jogo pode ver dois controles. Desative o Steam Input para PlayStation, ou feche a Steam. O app mostra o aviso quando a Steam está com o controle.
- **SDL com driver HIDAPI de PlayStation**: programas que leem o `hidraw` direto ainda veem o controle físico. Use `SDL_JOYSTICK_HIDAPI_PS5=0` no jogo.
- **Navegadores Chromium** (Chrome, Edge, Brave, apps Electron): enxergam só **um** Xbox virtual por vez. Use um controle emulado por vez para testar no navegador. Jogos não são afetados.
- **Firefox** não foi testado.

## Conflito com a Steam

Com o Steam Input ativo, a Steam abre o controle diretamente e envia as próprias cores e LEDs de jogador, passando por cima do app. As mudanças parecem "voltar sozinhas". O app detecta isso e mostra o aviso **⚠ Entrada Steam ativada…**, com um botão para as configurações de controle da Steam e outro para reaplicar as cores. Quando a Steam solta o controle, o app reaplica as suas cores sozinho.

## Temas

O visual segue o desktop e pode ser escolhido em **Configurações → Tema**: Automático, KDE (Breeze), GNOME (visual Adwaita) ou Próprio (Fusion). A escolha vale na próxima abertura do app.

| `DUALSENSE_ULTIMATE_THEME` | Visual |
|---|---|
| `auto` (padrão) | KDE → `kde`; GNOME → `gnome`; outros → `own` |
| `kde` | Breeze e fontes do Plasma, se o Qt do sistema for da mesma versão do PySide6; senão cai em `own` |
| `gnome` | Estilo do libadwaita sobre o Fusion, só com paleta e folha de estilo (sem GTK nem libadwaita) |
| `own` | Fusion com paleta clara ou escura própria |

A variável, quando definida, vence a escolha salva. A antiga `DUALSENSE_ULTIMATE_NO_KDE_THEME=1` equivale a `own`. Com `QT_STYLE_OVERRIDE` definido, o app não aplica tema próprio.

## Outras opções

- **Wayland**: o app roda pelo XWayland, porque no Wayland nativo ele não consegue posicionar o menu junto à bandeja. Para mudar, defina `QT_QPA_PLATFORM` (ex.: `QT_QPA_PLATFORM=wayland`).
- **Idioma**: português, inglês e espanhol, trocados na hora em Configurações. Os textos ficam em `src/dualsense_ultimate_control/translations.py`.

## Arquivos e pastas

| Caminho | Conteúdo |
|---|---|
| `~/.config/dualsense-ultimate-control/settings.json` | Preferências, cores, correções do giroscópio e escolhas de emulação |
| `~/.config/dualsense-ultimate-control/profiles/` | Perfis de emulação |
| `~/.config/dualsense-ultimate-control/calibration-history.json` | Histórico de calibração (últimos 50) |
| `~/.local/state/dualsense-ultimate-control/dualsense-ultimate-control.log` | Log, com rotação (512 KB por arquivo, 3 antigos) |

Ao abrir pela primeira vez, o app traz sozinho os dados da pasta antiga `dualsense-led`.

## Diagnóstico

Se o controle conecta mas não responde, ou os comandos não têm efeito, rode:

```bash
scripts/diagnose.sh
```

Ele mostra o que o Bluetooth, o kernel e o app enxergam, quem está com o controle aberto (a Steam ou o OpenRGB, por exemplo), o estado da emulação e os últimos eventos e avisos.

## Como contribuir

O fluxo de branches, commits, Pull Requests e versões está em [CONTRIBUTING.md](CONTRIBUTING.md).

## Créditos

O ícone do controle (na bandeja, na janela e no atalho) é o "Controller 1" do pacote Streamline Core (streamlinehq.com). Confira a licença do pacote antes de redistribuir o projeto.
