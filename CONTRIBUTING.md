# Como contribuir (fluxo de trabalho)

Este arquivo define **como o código chega à `main`**: branches, commits, Pull Requests e versões. Vale para pessoas e para agentes de IA (veja [Regras para agentes](#regras-para-agentes-de-ia)).

## Visão geral

```
main ──●──────────────●──────────────●── tag v0.2.0
        \            ↑ squash        ↑ squash
         feat/xyz ──●──●── PR       chore/release-v0.2.0 ── PR
```

1. A `main` é sempre estável e só recebe mudanças por **Pull Request**.
2. Cada tarefa tem a sua **branch curta**, criada a partir da `main` atualizada.
3. Os commits seguem o padrão **Conventional Commits**, em português.
4. O PR é juntado com **squash**: um commit por mudança na `main`.
5. Versões seguem **SemVer 0.x** e cada release recebe uma **tag**.

## Branches

Crie sempre a partir da `main` atualizada:

```bash
git switch main
git pull --ff-only
git switch -c feat/descricao-curta
```

Nome: `tipo/descricao-curta`, em minúsculas, com hífens.

| Prefixo | Quando usar | Exemplo |
|---|---|---|
| `feat/` | funcionalidade nova | `feat/f5-2-regras-de-tamanho` |
| `fix/` | correção de bug | `fix/led-nao-reaplica-no-bluetooth` |
| `docs/` | só documentação | `docs/fluxo-de-trabalho` |
| `refactor/` | reorganização sem mudar o comportamento | `refactor/separar-theme` |
| `chore/` | manutenção, dependências, releases | `chore/release-v0.2.0` |

Regras:

- **Uma tarefa por branch.** Uma etapa do plano (ex.: F5.2) cabe numa branch.
- Branches vivem poucos dias. Terminou, abre o PR; juntou, a branch é apagada.
- Nunca se commita direto na `main` e nunca se usa `git push --force` nela.

## Commits

Formato (Conventional Commits, em português):

```
tipo: resumo curto no imperativo (até ~70 caracteres)

Corpo opcional: o porquê da mudança, não o que o diff já mostra.
```

Tipos: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Para mudança incompatível (comando, pasta de configuração, formato do `settings.json`), use `feat!:` ou `fix!:` e explique a migração no corpo.

Exemplos:

```
feat: seletor de tema na página Configurações
fix: não reenviar o LED do microfone ao reconectar sem o usuário ter ligado
docs: explica o fluxo de branches e versões
```

Mantenha cada commit pequeno e coerente. Commits feitos com ajuda de um agente mantêm a linha `Co-Authored-By` que ele indicar.

## Antes de abrir o Pull Request

- [ ] Os testes passam: `uv run python -m unittest discover tests`
- [ ] O app abre: `uv run dualsense-ultimate-control`
- [ ] Textos novos têm tradução em pt, en e es (`src/dualsense_ultimate_control/translations.py`)
- [ ] O README foi atualizado se o comportamento visível mudou
- [ ] Nenhum arquivo de desenvolvimento ou segredo foi adicionado (veja o `.gitignore`)

> A pasta `tests/` não é versionada (está no `.gitignore`), então os testes rodam **na sua máquina**, não no GitHub.

## Pull Request e squash

```bash
git push -u origin feat/descricao-curta
gh pr create --fill
```

- O **título do PR** segue o padrão dos commits (`feat: …`), porque vira a mensagem do commit na `main`.
- A descrição diz o que mudou, por quê e como foi verificado.
- Junte com **squash** e apague a branch:

```bash
gh pr merge --squash --delete-branch
```

Resultado: a `main` tem um commit por mudança, em ordem linear.

## Versionamento (SemVer 0.x)

Formato `0.MINOR.PATCH`, enquanto o app é considerado instável:

| Mudança | Sobe |
|---|---|
| `fix` (correção) | PATCH → `0.1.0` → `0.1.1` |
| `feat` (funcionalidade) | MINOR → `0.1.1` → `0.2.0` |
| mudança incompatível (`!`) | MINOR, com aviso no PR e no release |

A versão `1.0.0` chega quando a emulação e a calibração estiverem estáveis. A versão fica em **dois lugares**, que mudam juntos:

- `pyproject.toml` (`version`)
- `src/dualsense_ultimate_control/__init__.py` (`__version__`)

## Release

1. Atualize a `main` e crie a branch da release:

   ```bash
   git switch main && git pull --ff-only
   git switch -c chore/release-v0.2.0
   ```

2. Troque a versão nos dois arquivos acima, commite (`chore: versão 0.2.0`) e abra o PR (squash, como qualquer outro).
3. Com o PR juntado, marque a versão na `main`:

   ```bash
   git switch main && git pull --ff-only
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   gh release create v0.2.0 --generate-notes
   ```

## Correção urgente (hotfix)

Mesmo caminho de uma correção normal, só com mais pressa: `fix/…` a partir da `main`, PR com squash, sobe o PATCH, tag e release.

## Regras para agentes de IA

Quem é um agente (Claude Code, por exemplo) **lê este arquivo ao começar uma sessão e depois de cada `/clear`**, antes de mexer no repositório.

- Nunca commitar na `main` nem usar `--force` ou `--no-verify`. Se estiver na `main`, criar a branch antes de editar.
- **Commit, push, PR, tag e release só quando o usuário pedir.** Pedido para um passo não vale para o seguinte.
- Seguir os nomes de branch, o formato de commit e o checklist deste arquivo.
- Rodar os testes antes de propor o PR e dizer o resultado de verdade, inclusive quando falharem.
- Usar o plano de trabalho local (`PLANO.md`, `FRONTEND.md`, fora do repositório) para saber a próxima etapa. Uma etapa por branch.
- Não versionar arquivos de desenvolvimento nem alterar o `.gitignore` sem pedido.
- Em dúvida entre dois caminhos, perguntar ao usuário em vez de escolher sozinho.
