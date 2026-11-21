# tcc-metricas

Repositório de apoio ao TCC: coleta de métricas dos três projetos de automação
(Karate, REST Assured e Cypress) sempre dentro do GitHub Actions.

Fica separado dos projetos medidos para não alterar o código que está sendo avaliado.

## Como usar

1. Em `.github/workflows/static-metrics.yml`, edite os três valores `REPO_*` no bloco `env`.
2. No GitHub: **Actions → Métricas estáticas → Run workflow**.
   Os campos opcionais aceitam uma branch, tag ou SHA de cada projeto (padrão: `main`).
3. Ao terminar, o resumo do job já mostra as tabelas. Os CSVs ficam no artefato `static-metrics`.

## Saídas (artefato `static-metrics`)

| Arquivo | Conteúdo |
|---|---|
| `ambiente.csv` | commit medido de cada projeto |
| `files.csv` | cada arquivo: categoria, camada, linguagem, linhas |
| `loc_summary.csv` | linhas por projeto, categoria e camada |
| `loc_derived.csv` | visões API e UI: linhas fixas e por cenário |
| `assertions.csv` | pontos de asserção por cenário |
| `reuse.csv`, `reuse_literals.csv` | reuso de seletores e endpoints |
| `dependencies.csv` | dependências diretas e totais, tamanho |
| `workflows.csv` | tamanho dos workflows |
| `duplication.csv` | duplicação de código (jscpd) |
| `tools.txt` | versões das ferramentas e da imagem do runner |

## Metodologia

A classificação dos arquivos (teste, suporte, configuração, build/CI, docs, excluído) e o número de
cenários por projeto ficam no topo de `scripts/static_metrics.py` e devem ser citados no trabalho.
Se aparecer um arquivo sem classificação, o job falha e lista os arquivos.

## Bateria de execuções (tempo, recursos, estabilidade)

Rodada no seu computador **apenas para disparar e baixar**. As execuções medidas acontecem nos runners do GitHub.
Requer Python 3 e o GitHub CLI (`gh auth login`).

```
python scripts/battery.py check                    # confere login, repositórios, tag e workflows
python scripts/battery.py plan --reps 5 --warmup   # mostra o plano e uma estimativa
python scripts/battery.py run --reps 5 --warmup    # dispara e espera (Ctrl+C para parar; rode de novo para retomar)
python scripts/battery.py collect                  # baixa os artefatos e gera os CSVs
```

- A ferramenta executada é a da tag `estudo-v2` (`--ref` para trocar). Os nomes dos repositórios ficam no topo de `scripts/battery.py`.
- As execuções são **sequenciais** e **alternadas** entre as ferramentas (a ordem se inverte nas repetições pares).
- Repetição 0 = aquecimento (cria o cache); descarte nas análises.
- Para aumentar as repetições depois, rode de novo com um `--reps` maior: só as que faltam são executadas.
- `--limit N` executa no máximo N execuções (útil para testar). `--only karate-api,cypress` filtra ferramentas.

Saídas em `data/`:

| Arquivo | Conteúdo |
|---|---|
| `dispatch_log.csv` | cada execução disparada: ferramenta, configuração, id, resultado |
| `raw/<ferramenta>/<run_id>/` | arquivos brutos (metrics.json, tests.csv, samples.csv, jobs.json) |
| `consolidado/measurements.csv` | uma linha por execução medida (tempos, testes, CPU, memória, ambiente) |
| `consolidado/tests.csv` | uma linha por teste e execução |
| `consolidado/steps.csv` | duração de cada passo de cada job (instalação, cache, testes...) |
| `consolidado/issues.csv` | execuções sem dados (falha antes da medição etc.) |

Configurações: `A_quente_1` (cache, 1 thread), `B_frio_1` (sem cache, 1 thread), `C_quente_4` (cache, 4 threads, só API).
A UI roda sempre com 1 thread. Falhas de teste **não são descartadas**: entram nos dados como execuções com testes falhos.

## Diagnóstico de rede (site fora do normal para alguns runners)

Na primeira bateria, 16 das 17 execuções em que todos os testes falharam ocorreram em runners Intel Xeon 6975P-C.
Para confirmar a causa sem rodar os testes, use o workflow **Diagnóstico de rede**
(`.github/workflows/diagnostico-rede.yml`, script `scripts/probe.py`):

1. **Actions → Diagnóstico de rede → Run workflow.** Ele abre 12 runners (3 por vez). Cada um faz 24 requisições leves ao site
   (4 endereços x 2 identificações de cliente x 3 tentativas) e registra código HTTP, tempo, título e trecho da resposta,
   o modelo da CPU, o runner e a rede de saída.
2. Ao final, o job `resumo` compara os runners por tipo de CPU e rede de saída (resumo da execução e artefato `diagnostico-rede`).

## Histórico dos dados

- `data/` da primeira bateria (tag `estudo-v2`, 5 repetições) foi commitada como evidência, mas **não serve para comparar as ferramentas**
  (ambiente instável: respostas 403/503 do site em parte dos runners).
- Antes de iniciar uma nova bateria, **renomeie `data/` para `data-bateria1/`**. O script identifica as execuções por repetição,
  configuração e ferramenta (não pela tag) e, se a pasta antiga continuar com o nome `data`, considera tudo "já feito".

## Bateria 2 (imagem `ubuntu-22.04`)

**Por que mudou de imagem.** O diagnóstico de rede mostrou que o rótulo `ubuntu-24.04` cai em runners de duas nuvens.
Os que saem pela rede da Amazon (CPU Intel Xeon 6975P-C) receberam `403 Forbidden` ou uma página de verificação anti-robô
em parte das requisições, o que derrubou a primeira bateria. Com `ubuntu-22.04`, os 12 runners do diagnóstico saíram pela rede
da Microsoft e as 288 requisições foram normais. Os dados do diagnóstico ficam em `evidencias/`.

**Novidades da medição** (`.github/actions/measure/measure.py`):
- uma sonda ao site (API e página inicial) antes e depois dos testes e **a cada 5 segundos durante**; as requisições são leves e a duração medida não as inclui;
- a organização da rede de saída do runner (por exemplo, `AS8075 Microsoft Corporation`);
- mensagens de falha com até 600 caracteres.

O `collect` grava isso em `measurements.csv` (`rede_org`, `site_antes_ok`, `site_antes_http`, `site_depois_ok`, `site_depois_http`
e os trechos). Uma execução em que a sonda falhou antes ou depois dos testes é candidata a descarte por **ambiente** e não por
falha da ferramenta; o critério será fixado antes da análise.

**Ordem para iniciar a bateria 2**
1. Renomear `data/` para `data-bateria1/` (e commitar).
2. Trocar `ubuntu-24.04` por `ubuntu-22.04` nos três workflows (4 ocorrências: Karate tem 2, REST Assured 1, Cypress 1).
3. Criar a tag `estudo-v3` nos três repositórios e rodar a análise estática nela.
4. Rodar o diagnóstico de rede com `ubuntu-22.04` de novo, imediatamente antes de começar.
5. `python scripts/battery.py check`, depois o piloto (`run --reps 1 --warmup --limit 4`) e a bateria.

### Critério de validade da execução (fixado antes da bateria 2)

Uma execução é marcada como **afetada pelo ambiente** (`ambiente_afetado = True`, `execucao_valida = False`) se ocorrer qualquer um destes casos:

1. a sonda do site falhou antes, durante ou depois dos testes (resposta diferente de HTTP 200 com o JSON da API e a página inicial);
2. algum teste falhou com mensagem típica de ambiente: `403`, `forbidden`, `503`, `heavy load`, `queue full`, `too many people`,
   `one moment, please`, página HTML no lugar do JSON, ou `responseCode` ausente (ver `ENV_PATTERNS` em `scripts/battery.py`).

Falhas de UI do tipo "elemento não encontrado" (`cannot read properties of null`, `expected to find element`, `timed out retrying`)
**não** entram automaticamente: ficam em `falhas_indeterminadas` para revisão manual do screenshot, porque tanto podem ser a
página de erro do site (já confirmado em dois casos no piloto da bateria 2) como um problema real do teste.
A sonda a cada 5 s pode perder uma indisponibilidade curta, então essa coluna existe justamente para não atribuir tudo à ferramenta.

Execuções afetadas **não são apagadas**: ficam nos dados e a taxa delas por ferramenta é um resultado do estudo
(exposição ao ambiente). Mas ficam fora das medianas de tempo/recursos e da taxa de falhas das ferramentas.

### Repetir as execuções afetadas

```
python scripts/battery.py fill --reps 5 --max-attempts 3
```

Para cada célula (repetição, configuração, ferramenta) que ainda não tem uma execução válida, dispara uma nova tentativa (até 3 no total,
contando a primeira), uma de cada vez. Células que continuarem sem execução válida são listadas no final. As tentativas ficam no
`dispatch_log.csv` com o sufixo `|a2`, `|a3` na chave.
