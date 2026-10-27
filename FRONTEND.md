# Plano: melhorias do front-end

## Protocolo de trabalho (1 etapa por sessão)
1. Ao iniciar a sessão, o usuário aponta para este arquivo; execute **apenas a primeira etapa não marcada**.
2. Ao concluir: marcar `[x]` aqui, anotar desvios em "Notas das etapas", avisar **qual é a próxima etapa + modelo/esforço sugerido** e liberar o usuário para limpar a sessão.
3. Cada etapa termina com os testes (`uv run python -m unittest discover tests`) passando e o app abrindo.
4. Novas melhorias entram no fim da lista como F2, F3… cada uma com `· modelo · esforço`.

## Contexto
O app (PySide6, tudo em código, textos via `tr()`/`i18n.bind`) abre hoje várias janelas soltas a partir da janela principal (`src/dualsense_ultimate_control/window.py`). Estado compartilhado: um único `LedService` injetado nas janelas; os widgets reagem aos sinais dele.

## Etapas

- [ ] **F1 — Evitar abrir novas janelas** · *Opus 5.5 · médio/alto* (dividida em F1.1–F1.5; cada uma pode ser uma sessão)
  Hoje abrem janelas próprias: `LogWindow` (`logview.py:45`, QDialog), `ProfilesDialog` (`profiles_dialog.py:400`, QDialog sem pai), `TestWindow` (`testpanel/window.py:22`, QWidget de topo), `QuickTestDialog` (`testpanel/quicktest.py:135`), além de caixas modais (`QMessageBox`, `QColorDialog` em `widgets.py:43`, `QFileDialog` em `profiles_dialog.py:596,619`). O menu da bandeja (`popup.py`) fica como está: não é janela de aplicativo.
  Pronto quando: abrir Logs, Perfis, Teste e Teste rápido não cria nenhuma janela de topo nova; tudo vive dentro da janela principal. Sobram só o seletor de arquivo do sistema e o erro fatal de inicialização.

  - [x] **F1.1 — Navegação interna na janela principal** · *Sonnet 5.5 · médio.* `window.py` ganha um `QStackedWidget` com barra/lista lateral (Controles, Perfis, Teste, Logs). `show_logs/show_profiles/show_test` viram `set_page(...)`; tray e instância única chamam as mesmas funções. Atenção ao `closeEvent`/`close_to_tray`.
  - [ ] **F1.2 — Logs e Perfis como páginas** · *Sonnet 5.5 · médio.* `LogWindow` e `ProfilesDialog` deixam de herdar `QDialog` e viram `QWidget`; botões "Fechar"/`reject` voltam à página anterior. A pergunta "descartar alterações?" vira `can_leave()` consultado pela navegação.
  - [ ] **F1.3 — Painel de teste e Teste rápido embutidos** · *Opus 5.5 · alto.* `TestWindow` vira página; `QuickTestDialog` vira sub-aba/painel dentro dela. O ciclo de vida do dispositivo hoje preso a `showEvent/hideEvent` (`_reopen`, `_close_device`, cancelar alcance da calibração, timers) passa a ser guiado por "página ativada/desativada" **e** pela ocultação da janela inteira. Maior risco da F1 (hidraw aberto/solto).
  - [ ] **F1.4 — Confirmações e seletor de cor sem janela** · *Sonnet 5.5 · médio.* `QMessageBox.question/warning` viram faixa de aviso inline (Sim/Não no topo da página): descartar/excluir/substituir perfil, confirmação da calibração (`testpanel/calibration.py:235`), permissão (`window.py:280`), ajuda Steam/Bluetooth (`widgets.py:58-92`). `QColorDialog` vira seletor embutido (as `ColorSliders`/`ColorPalette` já existem). Mantém modal: `QFileDialog` e o erro fatal de `__main__.py`.
  - [ ] **F1.5 — Testes e docs** · *Sonnet 5.5 · baixo.* Testes da lógica pura (`can_leave`, mapa página↔ação do tray) com `QT_QPA_PLATFORM=offscreen`; README atualizado; abrir o app com os controles reais e conferir que nada abre fora da janela.

  Riscos: perder o ciclo de vida de abrir/fechar dispositivo (F1.3); janela principal mais densa (largura mínima atual 400, usar scroll nas páginas de Perfis/Teste); páginas vivas enquanto a janela está escondida na bandeja (parar timers/hidraw ao ocultar a janela inteira).

## Notas das etapas

**F1.1 (concluída)**: `MainWindow` virou lista lateral (`QListWidget`, 160 px) + `QStackedWidget`, com páginas Controles, Testar controle, Perfis de emulação (só com emulação) e Registros. Títulos reutilizam `test.title`/`profiles.title`/`log.title` e a chave nova `nav.controls` (pt/en/es). As páginas são criadas na primeira visita (`set_page`), perdem o tipo janela (`setWindowFlags(Widget)`) e ficam dentro de um `QScrollArea` (o mínimo de 780×560 do editor vira rolagem). Janela com mínimo de 560 de largura e tamanho inicial de 900×680. `show_logs/show_test/show_profiles` trocam a página e mostram a janela. 370 testes verdes (5 novos em `tests/test_window_pages.py`).
- **Desvio (adiantou parte da F1.2)**: Logs e Perfis já abrem como páginas sem mudar as classes. O "Fechar"/Esc deles emite `finished` e volta para Controles (`set_page(..., force=True)`, para não perguntar duas vezes). Sair de Perfis com edição pendente pergunta (usa `_confirm_discard()`) e, se o usuário recusar, a lista volta para Perfis. Sobra para a F1.2: virar `QWidget`, tirar título e `resize` de janela, `can_leave()` público e trocar o "Fechar" das páginas por "Voltar" (hoje a página de Logs mostra dois "Fechar": o dela volta, o do rodapé sai do app).
- O `TestWindow` não mudou: o stack esconde as páginas inativas e o Qt repassa `showEvent`/`hideEvent`, então a leitura do hidraw para ao trocar de página ou ir para a bandeja. Não houve teste com o controle. O Teste rápido ainda abre janela própria (F1.3).
- **Não conferido**: o app aberto com os controles reais. A janela foi só renderizada fora da tela. Reiniciar o app para pegar a mudança.
