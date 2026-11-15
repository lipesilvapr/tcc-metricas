# Métricas estáticas

## Commits medidos

| projeto | commit | data | arquivos |
|---|---|---|---|
| karate | b0fba21bd6611a4d0e6f0d0ef76db0c777b4a6a9 | 2026-11-14T18:08:54-03:00 | 24 |
| restassured | ac02d419cf0976432b3b503e4f5abc02126c1bbd | 2026-11-15T11:39:53-03:00 | 32 |
| cypress | 62bf89748670bcd6896ae700de6dde24104e4474 | 2026-11-14T18:07:39-03:00 | 21 |

## Linhas de código (cloc) por categoria

| projeto | categoria | camada | arquivos | código | comentários | brancos |
|---|---|---|---|---|---|---|
| cypress | build_ci | ui | 2 | 65 | 2 | 8 |
| cypress | configuracao | ui | 2 | 36 | 5 | 8 |
| cypress | docs | ui | 2 | 68 | 0 | 19 |
| cypress | excluido | ui | 1 | 3288 | 0 | 0 |
| cypress | suporte | ui | 10 | 190 | 20 | 37 |
| cypress | teste | ui | 4 | 102 | 3 | 26 |
| karate | build_ci | compartilhado | 2 | 115 | 2 | 11 |
| karate | configuracao | compartilhado | 2 | 65 | 10 | 10 |
| karate | docs | compartilhado | 2 | 51 | 0 | 15 |
| karate | suporte | api | 1 | 14 | 0 | 4 |
| karate | suporte | compartilhado | 5 | 76 | 16 | 16 |
| karate | suporte | ui | 3 | 46 | 0 | 10 |
| karate | teste | api | 5 | 179 | 7 | 25 |
| karate | teste | ui | 4 | 91 | 1 | 20 |
| restassured | build_ci | api | 2 | 145 | 4 | 12 |
| restassured | configuracao | api | 3 | 10 | 2 | 0 |
| restassured | docs | api | 2 | 62 | 0 | 15 |
| restassured | suporte | api | 18 | 378 | 39 | 82 |
| restassured | teste | api | 7 | 233 | 10 | 48 |

## Visões comparáveis

| projeto | visão | critério | teste | suporte | config | build/ci | total | fixo | cenários | teste/cenário | total/cenário |
|---|---|---|---|---|---|---|---|---|---|---|---|
| karate | API | exclusivo | 179 | 14 | 0 | 0 | 193 | 14 | 14 | 12.79 | 13.79 |
| karate | API | com_compartilhado | 179 | 90 | 65 | 115 | 449 | 270 | 14 | 12.79 | 32.07 |
| karate | UI | exclusivo | 91 | 46 | 0 | 0 | 137 | 46 | 10 | 9.1 | 13.7 |
| karate | UI | com_compartilhado | 91 | 122 | 65 | 115 | 393 | 302 | 10 | 9.1 | 39.3 |
| restassured | API | exclusivo | 233 | 378 | 10 | 145 | 766 | 533 | 14 | 16.64 | 54.71 |
| restassured | API | com_compartilhado | 233 | 378 | 10 | 145 | 766 | 533 | 14 | 16.64 | 54.71 |
| cypress | UI | exclusivo | 102 | 190 | 36 | 65 | 393 | 291 | 10 | 10.2 | 39.3 |
| cypress | UI | com_compartilhado | 102 | 190 | 36 | 65 | 393 | 291 | 10 | 10.2 | 39.3 |

## Pontos de asserção

| projeto | camada | pontos | cenários | pontos/cenário |
|---|---|---|---|---|
| karate | api | 48 | 14 | 3.43 |
| karate | ui | 12 | 10 | 1.2 |
| restassured | api | 34 | 14 | 2.43 |
| cypress | ui | 12 | 10 | 1.2 |

## Reuso (seletores e endpoints)

| projeto | tipo | únicos | ocorrências | em teste | % em teste | ocorr./literal |
|---|---|---|---|---|---|---|
| karate | seletor | 34 | 45 | 36 | 80.0 | 1.32 |
| karate | endpoint | 8 | 13 | 11 | 84.6 | 1.62 |
| restassured | endpoint | 8 | 12 | 0 | 0.0 | 1.5 |
| cypress | seletor | 32 | 34 | 0 | 0.0 | 1.06 |
| cypress | endpoint | 2 | 2 | 0 | 0.0 | 1.0 |

## Dependências

| projeto | diretas | totais | MB | obs. |
|---|---|---|---|---|
| karate | 1 | 89 | 126.0 | classpath de teste (jars), sem plugins do Maven |
| restassured | 7 | 58 | 31.67 | classpath de teste (jars), sem plugins do Maven |
| cypress | 5 | 254 | 75.67 | pacotes npm instalados, sem o binário do Cypress |

## Workflows

| projeto | arquivo | linhas | jobs | passos |
|---|---|---|---|---|
| karate | .github/workflows/tests.yml | 55 | 2 | 10 |
| restassured | .github/workflows/api-tests.yml | 40 | 1 | 7 |
| cypress | .github/workflows/ui-tests.yml | 43 | 1 | 6 |

## Duplicação (jscpd)

| projeto | formatos | linhas | duplicadas | % | clones |
|---|---|---|---|---|---|
| karate | gherkin,java,javascript,json,markup | 579 | 0 | 0.0 | 0 |
| restassured | java,properties | 777 | 48 | 6.177606177606178 | 4 |
| cypress | javascript,json | 378 | 0 | 0.0 | 0 |
