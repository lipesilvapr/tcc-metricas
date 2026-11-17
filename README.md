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
