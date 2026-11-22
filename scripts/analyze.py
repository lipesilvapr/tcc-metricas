#!/usr/bin/env python3
"""Análise dos dados da bateria: tabelas, comparações com intervalos e gráficos.

  python scripts/analyze.py                 usa data/ e grava em analise/

Entradas:
  data/consolidado/measurements.csv, tests.csv     (gerados por `battery.py collect`)
  data/revisao_manual.csv                          revisão manual de falhas (opcional)
  data/estaticas-v3/loc_summary.csv                métricas estáticas (opcional; artefato static-metrics)

Regras:
  - repetição 0 (aquecimento) fica de fora;
  - uma execução é válida se `execucao_valida == True` e não foi reclassificada como "ambiente" na revisão manual;
  - todas as estatísticas usam só execuções válidas; as afetadas são contadas à parte (exposição ao ambiente).
Somente biblioteca padrão (matplotlib é opcional, para os gráficos).
"""
import argparse
import csv
import itertools
import math
import os
import random
import statistics as st
from collections import Counter, defaultdict

TOOLS = ["karate-api", "restassured", "karate-ui", "cypress"]
CONFIGS = ["A_quente_1", "B_frio_1", "C_quente_4"]
SEED = 2026
BOOT = 20000


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def fnum(x):
    return float(x) if x not in ("", None) else None


# ----------------------------- estatística -------------------------------
def quartiles(v):
    v = sorted(v)
    if len(v) < 2:
        return v[0], v[0], v[0]
    q = st.quantiles(v, n=4, method="inclusive")
    return q[0], st.median(v), q[2]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    r = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def mwu_exact_p(a, b):
    """p bilateral exato do teste de Mann-Whitney (permutação da soma de postos)."""
    n, m = len(a), len(b)
    allv = a + b
    rk = ranks(allv)
    obs = sum(rk[:n])
    mean = n * (n + m + 1) / 2
    cnt = tot = 0
    for comb in itertools.combinations(range(n + m), n):
        w = sum(rk[i] for i in comb)
        tot += 1
        if abs(w - mean) >= abs(obs - mean) - 1e-9:
            cnt += 1
    return cnt / tot


def boot_ratio(a, b, rng):
    out = []
    for _ in range(BOOT):
        sa = [rng.choice(a) for _ in a]
        sb = [rng.choice(b) for _ in b]
        out.append(st.median(sa) / st.median(sb))
    out.sort()
    return out[int(0.025 * BOOT)], out[int(0.975 * BOOT)]


def fisher_p(k1, n1, k2, n2):
    """p bilateral do teste exato de Fisher para duas proporções."""
    total_k = k1 + k2
    n = n1 + n2

    def prob(x):
        return math.comb(n1, x) * math.comb(n2, total_k - x) / math.comb(n, total_k)
    p_obs = prob(k1)
    lo, hi = max(0, total_k - n2), min(n1, total_k)
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs + 1e-12))


# ------------------------------- carga -------------------------------------
def load(data_dir):
    meas = read_csv(os.path.join(data_dir, "consolidado", "measurements.csv"))
    tests = read_csv(os.path.join(data_dir, "consolidado", "tests.csv"))
    review = {}
    rpath = os.path.join(data_dir, "revisao_manual.csv")
    if os.path.exists(rpath):
        for r in read_csv(rpath):
            review[r["key"]] = r
    for r in meas:
        r["rep"] = int(r["rep"])
        r["revisao"] = review.get(r["key"], {}).get("classificacao", "")
        r["valida"] = (r["execucao_valida"] == "True") and r["revisao"] != "ambiente"
        for k in ("duracao_s", "cpu_media_pct", "mem_pico_delta_mb", "job_duracao_s", "tempo_soma_testes_s"):
            r[k] = fnum(r[k])
        for k in ("testes_total", "testes_passou", "testes_falhou", "testes_esperados"):
            r[k] = int(r[k])
    return meas, tests, review


def vals(runs, tool, cfgs, metric):
    return [r[metric] for r in runs if r["tool"] == tool and r["config"] in cfgs and r[metric] is not None]


# ------------------------------- análise -----------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="analise")
    args = ap.parse_args()
    meas, tests, review = load(args.data)
    bat = [r for r in meas if r["rep"] > 0]
    valid = [r for r in bat if r["valida"]]
    rng = random.Random(SEED)
    out = args.out

    # 1) qualidade dos dados
    q = [["execuções da bateria (sem aquecimento)", len(bat)], ["execuções válidas", len(valid)],
         ["execuções afetadas pelo ambiente", len(bat) - len(valid)],
         ["células (repetição x configuração x ferramenta) com execução válida",
          len({(r["rep"], r["config"], r["tool"]) for r in valid})],
         ["revisões manuais aplicadas", len(review)],
         ["execuções de teste (tests.csv, todas)", len(tests)]]
    for k, v in sorted(Counter(r["rede_org"] for r in meas).items()):
        q.append([f"rede de saída: {k}", v])
    for k, v in sorted(Counter(r["image_version"] for r in meas).items()):
        q.append([f"imagem do runner: {k}", v])
    for k, v in sorted(Counter(r["cpu_modelo"] for r in meas).items()):
        q.append([f"CPU: {k}", v])
    write_csv(f"{out}/00_qualidade_dos_dados.csv", ["item", "valor"], q)

    # 2) exposição ao ambiente por ferramenta
    exp = []
    for t in TOOLS:
        rs = [r for r in bat if r["tool"] == t]
        by_probe = sum(1 for r in rs if r["execucao_valida"] != "True")
        by_manual = sum(1 for r in rs if r["execucao_valida"] == "True" and r["revisao"] == "ambiente")
        exp.append([t, len(rs), by_probe, by_manual, by_probe + by_manual,
                    f"{100 * (by_probe + by_manual) / len(rs):.0f}%" if rs else ""])
    write_csv(f"{out}/01_exposicao_ao_ambiente.csv",
              ["ferramenta", "execucoes", "afetadas_por_sonda_ou_mensagem", "afetadas_por_revisao_manual",
               "afetadas_total", "percentual"], exp)

    # 3) tempo, CPU e memória por ferramenta e configuração
    for metric, fname, label in (("duracao_s", "02_tempo_comando_s.csv", "duração do comando (s)"),
                                 ("cpu_media_pct", "03_cpu_media_pct.csv", "CPU média (%)"),
                                 ("mem_pico_delta_mb", "04_memoria_pico_mb.csv", "memória: pico acima da base (MB)"),
                                 ("job_duracao_s", "05_duracao_job_s.csv", "duração do job (s)")):
        rows = []
        for t in TOOLS:
            for c in CONFIGS:
                v = vals(valid, t, [c], metric)
                if v:
                    q1, med, q3 = quartiles(v)
                    rows.append([t, c, len(v), round(med, 2), round(q1, 2), round(q3, 2), round(min(v), 2), round(max(v), 2)])
        write_csv(f"{out}/{fname}", ["ferramenta", "config", "n", "mediana", "q1", "q3", "min", "max"], rows)

    # 4) comparações entre ferramentas
    comps = [
        ("API, 1 thread (A+B)", "karate-api", ["A_quente_1", "B_frio_1"], "restassured", ["A_quente_1", "B_frio_1"], "duracao_s"),
        ("API, quente 1 thread (A)", "karate-api", ["A_quente_1"], "restassured", ["A_quente_1"], "duracao_s"),
        ("API, frio 1 thread (B)", "karate-api", ["B_frio_1"], "restassured", ["B_frio_1"], "duracao_s"),
        ("API, 4 threads (C)", "karate-api", ["C_quente_4"], "restassured", ["C_quente_4"], "duracao_s"),
        ("UI (A+B)", "karate-ui", ["A_quente_1", "B_frio_1"], "cypress", ["A_quente_1", "B_frio_1"], "duracao_s"),
        ("UI, quente (A)", "karate-ui", ["A_quente_1"], "cypress", ["A_quente_1"], "duracao_s"),
        ("UI, frio (B)", "karate-ui", ["B_frio_1"], "cypress", ["B_frio_1"], "duracao_s"),
        ("API 1 thread: CPU média (A+B)", "karate-api", ["A_quente_1", "B_frio_1"], "restassured", ["A_quente_1", "B_frio_1"], "cpu_media_pct"),
        ("UI: CPU média (A+B)", "karate-ui", ["A_quente_1", "B_frio_1"], "cypress", ["A_quente_1", "B_frio_1"], "cpu_media_pct"),
        ("UI: memória (A+B)", "karate-ui", ["A_quente_1", "B_frio_1"], "cypress", ["A_quente_1", "B_frio_1"], "mem_pico_delta_mb"),
    ]
    rows = []
    for label, ta, ca, tb, cb, metric in comps:
        a, b = vals(valid, ta, ca, metric), vals(valid, tb, cb, metric)
        lo, hi = boot_ratio(a, b, rng)
        rows.append([label, metric, ta, len(a), round(st.median(a), 2), tb, len(b), round(st.median(b), 2),
                     round(st.median(a) / st.median(b), 3), round(lo, 3), round(hi, 3), round(mwu_exact_p(a, b), 3)])
    write_csv(f"{out}/06_comparacoes.csv",
              ["comparacao", "metrica", "ferramenta_a", "n_a", "mediana_a", "ferramenta_b", "n_b", "mediana_b",
               "razao_medianas_a_b", "ic95_baixo", "ic95_alto", "p_mann_whitney_exato"], rows)

    # 5) escala de 1 para 4 threads (API)
    rows = []
    for t in ("karate-api", "restassured"):
        a, c = vals(valid, t, ["A_quente_1"], "duracao_s"), vals(valid, t, ["C_quente_4"], "duracao_s")
        lo, hi = boot_ratio(a, c, rng)
        rows.append([t, len(a), len(c), round(st.median(a), 2), round(st.median(c), 2),
                     round(st.median(a) / st.median(c), 2), round(lo, 2), round(hi, 2)])
    write_csv(f"{out}/07_ganho_com_threads.csv",
              ["ferramenta", "n_1thread", "n_4threads", "mediana_1thread_s", "mediana_4threads_s",
               "ganho_x", "ic95_baixo", "ic95_alto"], rows)

    # 6) falhas atribuíveis às ferramentas (só execuções válidas)
    vkeys = {r["key"] for r in valid}
    rows, causes = [], []
    fails_by_tool = {}
    for t in TOOLS:
        rs = [r for r in valid if r["tool"] == t]
        n_tests = sum(r["testes_total"] for r in rs)
        failed = [x for x in tests if x["key"] in vkeys and x["tool"] == t and x["status"] == "falhou"]
        runs_with_fail = sum(1 for r in rs if r["testes_falhou"] > 0)
        lo, hi = wilson(len(failed), n_tests)
        rlo, rhi = wilson(runs_with_fail, len(rs))
        fails_by_tool[t] = (len(failed), n_tests, runs_with_fail, len(rs))
        rows.append([t, len(rs), n_tests, len(failed), f"{100 * len(failed) / n_tests:.2f}%" if n_tests else "",
                     f"[{100 * lo:.1f}%; {100 * hi:.1f}%]", runs_with_fail,
                     f"{100 * runs_with_fail / len(rs):.0f}%" if rs else "", f"[{100 * rlo:.0f}%; {100 * rhi:.0f}%]"])
        for x in failed:
            rev = review.get(x["key"], {})
            causes.append([t, x["key"], x["teste"], rev.get("classificacao", "sem revisão"),
                           rev.get("justificativa", ""), x["mensagem"][:200]])
    write_csv(f"{out}/08_falhas_por_ferramenta.csv",
              ["ferramenta", "execucoes_validas", "testes_executados", "testes_com_falha", "taxa_testes",
               "ic95_testes", "execucoes_com_falha", "taxa_execucoes", "ic95_execucoes"], rows)
    write_csv(f"{out}/09_falhas_detalhe.csv", ["ferramenta", "execucao", "teste", "revisao", "justificativa", "mensagem"], causes)
    k1, n1, r1, m1 = fails_by_tool["karate-ui"]
    k2, n2, r2, m2 = fails_by_tool["cypress"]
    write_csv(f"{out}/10_falhas_karate_ui_vs_cypress.csv", ["nivel", "karate_ui", "cypress", "p_fisher_exato"],
              [["testes", f"{k1}/{n1}", f"{k2}/{n2}", round(fisher_p(k1, n1, k2, n2), 3)],
               ["execuções", f"{r1}/{m1}", f"{r2}/{m2}", round(fisher_p(r1, m1, r2, m2), 3)]])

    # 7) estática (opcional)
    spath = os.path.join(args.data, "estaticas-v3", "loc_summary.csv")
    if os.path.exists(spath):
        loc = read_csv(spath)
        L = defaultdict(int)
        for r in loc:
            if r["categoria"] in ("teste", "suporte", "configuracao", "build_ci"):
                L[(r["projeto"], r["camada"])] += int(r["linhas_codigo"])
        tl = {(r["projeto"], r["camada"]): int(r["linhas_codigo"]) for r in loc if r["categoria"] == "teste"}
        scen = {("karate", "api"): 14, ("karate", "ui"): 10, ("restassured", "api"): 14, ("cypress", "ui"): 10}
        rows = []
        for proj, layers in (("karate", ["api", "ui"]), ("restassured", ["api"]), ("cypress", ["ui"])):
            shared = L[(proj, "compartilhado")]
            tsum = sum(tl.get((proj, ly), 0) for ly in layers)
            for ly in layers:
                excl = L[(proj, ly)]
                share = tl.get((proj, ly), 0) / tsum if tsum else 1
                prop = excl + shared * share
                full = excl + shared
                n = scen[(proj, ly)]
                rows.append([proj, ly, excl, round(prop, 1), full, n, round(excl / n, 1), round(prop / n, 1), round(full / n, 1)])
        write_csv(f"{out}/11_estatica_linhas_por_camada.csv",
                  ["projeto", "camada", "loc_exclusivo", "loc_proporcional", "loc_com_compartilhado", "cenarios",
                   "loc_por_cenario_exclusivo", "loc_por_cenario_proporcional", "loc_por_cenario_compartilhado"], rows)
        tot = {p: sum(v for (pp, _), v in L.items() if pp == p) for p in ("karate", "restassured", "cypress")}
        write_csv(f"{out}/12_estatica_total_da_solucao.csv", ["solucao", "linhas_sem_docs"],
                  [["Karate (API + UI)", tot["karate"]], ["REST Assured (API)", tot["restassured"]],
                   ["Cypress (UI)", tot["cypress"]], ["REST Assured + Cypress", tot["restassured"] + tot["cypress"]]])

    # 8) gráficos (opcional)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib não instalado: gráficos não gerados (pip install matplotlib)")
        plt = None
    if plt:
        os.makedirs(f"{out}/figuras", exist_ok=True)
        jit = random.Random(1)

        def plot_group(tools, metric, ylabel, fname, title):
            fig, ax = plt.subplots(figsize=(8, 4.5))
            pos, data, labels = [], [], []
            x = 0
            for t in tools:
                for c in CONFIGS:
                    v = vals(valid, t, [c], metric)
                    if v:
                        pos.append(x)
                        data.append(v)
                        labels.append(f"{t}\n{c.split('_')[0]}·{c.split('_')[1]}·{c.split('_')[2]}t")
                        x += 1
                x += 0.6
            ax.boxplot(data, positions=pos, widths=0.5, showfliers=False)
            for p, v in zip(pos, data):
                ax.scatter([p + jit.uniform(-0.12, 0.12) for _ in v], v, s=14, alpha=0.7, zorder=3)
            ax.set_xticks(pos)
            ax.set_xticklabels(labels, fontsize=7)
            ax.set_ylabel(ylabel)
            ax.set_title(title, fontsize=10)
            ax.grid(axis="y", alpha=0.3)
            fig.tight_layout()
            fig.savefig(f"{out}/figuras/{fname}", dpi=150)
            plt.close(fig)

        plot_group(["karate-api", "restassured"], "duracao_s", "segundos", "tempo_api.png",
                   "API: duração do comando de teste (execuções válidas)")
        plot_group(["karate-ui", "cypress"], "duracao_s", "segundos", "tempo_ui.png",
                   "UI: duração do comando de teste (execuções válidas)")
        plot_group(["karate-api", "restassured", "karate-ui", "cypress"], "cpu_media_pct", "% (máquina inteira)",
                   "cpu_media.png", "CPU média durante os testes (execuções válidas)")

    # resumo no terminal
    print(f"Execuções válidas: {len(valid)} de {len(bat)} | afetadas: {len(bat) - len(valid)}")
    print(f"Arquivos gerados em {out}/")
    for f in sorted(os.listdir(out)):
        print("  ", f)


if __name__ == "__main__":
    main()
