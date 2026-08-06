# Copilot CLI Status Line

Status line customizada para o GitHub Copilot CLI, escrita em Python e sem dependências externas.

```text
Auto → gpt-5-mini | ctx 16k/128k 12% █░░░░░░░░░ | req 0 | 12m35s API 12s | meu-repo main*
```

A saída usa cores ANSI truecolor e caracteres Unicode comuns. Não é necessário instalar uma Nerd Font.

## Como funciona

```text
Copilot CLI → JSON em stdin → statusline.py → texto ANSI em stdout → rodapé do Copilot
```

O Copilot executa `statusline.py` sempre que o estado da sessão muda e, nesta configuração, também a cada cinco segundos. O script:

1. Lê o JSON enviado pelo Copilot.
2. Formata modelo, contexto, requests e duração.
3. Consulta o Git no diretório de trabalho.
4. Monta uma única linha colorida.
5. Omite informações ausentes em vez de interromper a interface.

Entradas inválidas, `NaN`, infinito e caracteres de controle são descartados. Comandos Git possuem timeout de 500 ms; se o diretório não for um repositório ou a consulta falhar, o segmento Git é ocultado.

## Requisitos

- GitHub Copilot CLI standalone — não confundir com a extensão antiga `gh copilot`.
- Python 3.
- Git, opcionalmente, para mostrar repositório, branch e estado do worktree.
- Terminal com cores ANSI e os caracteres Unicode `█` e `░`.

O script usa apenas recursos portáveis do Python 3, do Git e do terminal, compatíveis com macOS e Linux.

## Instalação

### 1. Instale o Copilot CLI

#### macOS

Com Homebrew:

```shell
brew install --cask copilot-cli
copilot --version
```

#### Linux

Instale primeiro Python 3 e Git pelo gerenciador de pacotes da distribuição. Por exemplo:

```shell
# Debian e Ubuntu
sudo apt update && sudo apt install python3 git

# Fedora
sudo dnf install python3 git
```

Em seguida, use o instalador oficial do Copilot CLI:

```shell
curl -fsSL https://gh.io/copilot-install | bash
copilot --version
```

Sem privilégios de root, o instalador usa `~/.local` por padrão. Se `copilot` não for encontrado, inclua `~/.local/bin` no `PATH` do shell:

```shell
export PATH="$HOME/.local/bin:$PATH"
```

Como alternativa para macOS ou Linux, a instalação via npm exige Node.js 22 ou posterior:

```shell
npm install -g @github/copilot
copilot --version
```

Consulte a [documentação oficial de instalação](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli) para opções atualizadas.

Se necessário, autentique:

```shell
copilot login
```

### 2. Torne o script executável

Mantenha o projeto em um caminho estável e execute:

```shell
chmod +x "/caminho/para/gh-status-line/statusline.py"
```

No Linux, `realpath` ajuda a obter o caminho absoluto que será usado na configuração:

```shell
realpath statusline.py
```

### 3. Configure o rodapé global

Crie ou mescle o conteúdo abaixo em `~/.copilot/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/caminho/para/gh-status-line/statusline.py",
    "padding": 1,
    "refreshInterval": 5
  },
  "footer": {
    "showCustom": true,
    "showQuota": true,
    "showAgent": true,
    "showSandbox": true,
    "showYolo": true,
    "showModelEffort": false,
    "showDirectory": false,
    "showBranch": false,
    "showContextWindow": false,
    "showCodeChanges": false,
    "showUsername": false,
    "showAiUsed": false
  }
}
```

Substitua `command` pelo caminho absoluto do script. Caminhos com espaços são aceitos pelo Copilot CLI.

No macOS e no Linux, o arquivo global fica em `~/.copilot/settings.json`. Crie o diretório com `mkdir -p ~/.copilot` caso ele ainda não exista.

> Mescle essas propriedades com as configurações existentes. Não substitua outros valores e não edite `~/.copilot/config.json`, que contém estado interno e autenticação.

### 4. Reinicie o Copilot

Abra o CLI:

```shell
copilot
```

No Linux, inicie-o dentro do repositório cujo estado Git deve aparecer:

```shell
cd /caminho/para/o-repositorio
copilot
```

Se ele já estiver aberto, execute:

```text
/restart
```

O Copilot pode solicitar confiança no diretório antes de abrir a sessão.

## Informações exibidas

| Segmento | Fonte | Comportamento |
|---|---|---|
| Modelo | `model.display_name` | Mostra o modelo e esforço fornecidos pelo Copilot. |
| Contexto | `context_window` | Mostra tokens ativos, limite, percentual e gauge. |
| Requests | `cost.total_premium_requests` | Mostra a quantidade de requests premium da sessão. |
| Tempo | `cost.total_duration_ms` e `total_api_duration_ms` | Separa duração total e espera pela API. |
| Git | `cwd` ou `workspace.current_dir` | Mostra repositório e branch; `*` indica alterações locais. |
| Diff | `cost.total_lines_added` e `total_lines_removed` | Aparece somente quando houve alterações. |
| Remoto | `remote.connected` | Mostra `remote` somente quando conectado. |
| Quota e estados | Rodapé nativo | Controlados pelas propriedades `footer` do Copilot. |

O gauge possui dez posições. As cores mudam conforme o uso do contexto:

- Verde: abaixo de 50%.
- Amarelo: de 50% a 79%.
- Vermelho: 80% ou mais.

## Personalização

Todas as propriedades visuais ficam em `statusline.py`.

### Cores

As constantes no início do arquivo usam ANSI truecolor:

```python
PURPLE = "\033[38;2;163;113;247m"
BLUE = "\033[38;2;88;166;255m"
GREEN = "\033[38;2;63;185;80m"
YELLOW = "\033[38;2;210;153;34m"
RED = "\033[38;2;248;81;73m"
MUTED = "\033[38;2;139;148;158m"
```

Altere os três valores RGB de cada constante para trocar a paleta.

### Limites do contexto

A função `context_color()` define os limites de 50% e 80%:

```python
def context_color(percent: float) -> str:
    if percent >= 80:
        return RED
    if percent >= 50:
        return YELLOW
    return GREEN
```

### Gauge

O gauge é produzido dentro de `render()`:

```python
gauge = "█" * filled + "░" * (10 - filled)
```

Alternativas compatíveis:

```python
gauge = "#" * filled + "." * (10 - filled)  # ASCII puro
gauge = "■" * filled + "□" * (10 - filled)  # Unicode
```

Os caracteres atuais pertencem ao padrão Unicode e não exigem Nerd Font. Caso fiquem desalinhados, selecione uma fonte monoespaçada ou use a versão ASCII.

### Separador

O separador é definido no retorno de `render()`:

```python
return paint(" | ", MUTED).join(segments)
```

Troque ` | ` por outro separador Unicode ou ASCII.

### Ordem, rótulos e segmentos

A ordem visual corresponde à ordem dos `segments.append(...)` dentro de `render()`. Para reorganizar a linha, mova o bloco completo do segmento. Para ocultar um campo, remova o bloco que o adiciona à lista `segments`.

Os rótulos `ctx`, `req`, `API` e `remote` também são textos comuns dentro desses blocos e podem ser renomeados diretamente.

### Frequência e espaçamento

Estas opções ficam em `~/.copilot/settings.json`:

```json
{
  "statusLine": {
    "padding": 1,
    "refreshInterval": 5
  }
}
```

- `padding`: espaços adicionados à esquerda.
- `refreshInterval`: intervalo em segundos; omita para atualizar apenas em eventos.

Após editar o script, o próximo refresh usa a nova versão. Após editar `settings.json`, execute `/restart`.

## Testes

Execute o self-test integrado:

```shell
./statusline.py --self-test
```

Ele valida:

- Formatação e cores do contexto.
- Gauge e ausência de glyphs exclusivos de Nerd Font.
- JSON inválido e campos ausentes.
- Repositório limpo, sujo, detached HEAD e diretório sem Git.
- Remoção de caracteres de controle.

Para visualizar uma amostra sem abrir o Copilot:

```shell
"/caminho/para/gh-status-line/statusline.py" <<'JSON'
{
  "cwd": "/caminho/para/um/repositorio",
  "model": {"display_name": "gpt-5-mini"},
  "context_window": {
    "current_context_tokens": 16000,
    "displayed_context_limit": 128000,
    "current_context_used_percentage": 12
  },
  "cost": {
    "total_premium_requests": 0,
    "total_duration_ms": 755000,
    "total_api_duration_ms": 12000,
    "total_lines_added": 42,
    "total_lines_removed": 8
  }
}
JSON
```

## Solução de problemas

### A linha não aparece

1. Execute `./statusline.py --self-test`.
2. Confirme a permissão com `ls -l statusline.py`.
3. Verifique se `statusLine.command` contém o caminho absoluto correto.
4. Valide `~/.copilot/settings.json` com `python3 -m json.tool ~/.copilot/settings.json`.
5. Execute `/restart` no Copilot.

### Aparecem quadrados com `?`

A versão atual não contém glyphs privados de Nerd Font. Confirme que está usando a versão mais recente de `statusline.py` e reinicie o Copilot.

Se você adicionar ícones Nerd Font, instale uma fonte compatível e também selecione essa fonte no perfil do terminal.

### O gauge fica desalinhado

Use uma fonte monoespaçada que suporte Block Elements ou substitua `█`/`░` por `#`/`.`.

### Informações aparecem duplicadas

Desative no objeto `footer` os campos que já são desenhados pelo script, como `showModelEffort`, `showDirectory`, `showBranch`, `showContextWindow` e `showCodeChanges`.

### O repositório ou a branch não aparecem

O diretório precisa estar dentro de um repositório Git. O segmento também é ocultado quando um comando Git falha ou ultrapassa 500 ms.

## Privacidade

Status lines aparecem em screenshots, gravações e transmissões. O script deliberadamente não exibe username, IDs de sessão, transcript, URLs ou prompts. Evite adicionar tokens, nomes de clientes, caminhos sensíveis ou outros segredos.

## Referências

- [Referência de configuração do Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference#configuration-file-settings)
- [Referência de comandos do Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#slash-commands-in-the-interactive-interface)
