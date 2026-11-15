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
