#!/usr/bin/env python3
"""Métricas estáticas dos três projetos do estudo (Karate, REST Assured, Cypress).

Usa apenas a biblioteca padrão do Python. Requer `cloc` e `git` instalados.
As regras de classificação de arquivos e as contagens de cenários ficam no topo
deste arquivo: elas fazem parte da metodologia e devem ser citadas no trabalho.

Uso:
    python3 scripts/static_metrics.py --targets targets --out out
Espera os projetos em <targets>/karate, <targets>/restassured e <targets>/cypress.
"""
import argparse
import csv
import fnmatch
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

# --------------------------------------------------------------------------
# METODOLOGIA: classificação dos arquivos (a primeira regra que casar vence).
# padrão (fnmatch; '*' casa também '/'), categoria, camada
#   categoria: teste | suporte | configuracao | build_ci | docs | excluido
#   camada:    api | ui | compartilhado
# --------------------------------------------------------------------------
RULES = {
    "karate": [
        ("src/test/resources/features/api/*", "teste", "api"),
        ("src/test/resources/features/ui/*", "teste", "ui"),
        ("src/test/resources/helpers/*", "suporte", "compartilhado"),
        ("src/test/resources/pages/*", "suporte", "ui"),
        ("src/test/resources/data/*", "suporte", "compartilhado"),
        ("src/test/java/com/automationexercise/runners/ApiTest.java", "suporte", "api"),
        ("src/test/java/com/automationexercise/runners/UiTest.java", "suporte", "ui"),
        ("src/test/java/*", "suporte", "compartilhado"),
        ("src/test/resources/karate-config.js", "configuracao", "compartilhado"),
        ("src/test/resources/logback-test.xml", "configuracao", "compartilhado"),
        ("pom.xml", "build_ci", "compartilhado"),
        (".github/*", "build_ci", "compartilhado"),
        ("README.md", "docs", "compartilhado"),
        (".gitignore", "docs", "compartilhado"),
    ],
    "restassured": [
        (".allure/*", "excluido", "api"),  # distribuição do Allure CLI commitada por engano
        ("src/test/java/com/automationexercise/api/tests/*", "teste", "api"),
        ("src/test/java/*", "suporte", "api"),
        ("src/test/resources/*", "configuracao", "api"),
        ("pom.xml", "build_ci", "api"),
        (".github/*", "build_ci", "api"),
        ("README.md", "docs", "api"),
        (".gitignore", "docs", "api"),
    ],
    "cypress": [
        ("package-lock.json", "excluido", "ui"),  # arquivo gerado
        ("cypress/e2e/*", "teste", "ui"),
        ("cypress/pages/*", "suporte", "ui"),
        ("cypress/support/*", "suporte", "ui"),
        ("cypress/fixtures/*", "suporte", "ui"),
        ("cypress.config.js", "configuracao", "ui"),
        ("jsconfig.json", "configuracao", "ui"),
        ("package.json", "build_ci", "ui"),
        (".github/*", "build_ci", "ui"),
        ("README.md", "docs", "ui"),
        (".gitignore", "docs", "ui"),
    ],
}

# Número de cenários (testes) por projeto e camada. Conferir com os relatórios de execução.
SCENARIOS = {
    "karate": {"api": 14, "ui": 10},
    "restassured": {"api": 14},
    "cypress": {"ui": 10},
}

# Visões comparáveis por projeto: (nome da visão, camada)
VIEWS = {
    "karate": [("API", "api"), ("UI", "ui")],
    "restassured": [("API", "api")],
    "cypress": [("UI", "ui")],
}

# "Pontos de asserção" (chamadas/passos de asserção nos arquivos de teste, aproximado)
ASSERT_RE = {
    "karate": re.compile(r"^\s*(?:\*|Given|When|Then|And|But)\s+(?:match|status|assert)\b", re.M),
    "restassured": re.compile(r"\bassert[A-Z]\w*\("),
    "cypress": re.compile(r"\.should\(|\bexpect\("),
}

# Literais de seletores de UI e de endpoints de API
SELECTOR_RE = {
    "karate": re.compile(
        r"\b(?:input|click|waitFor|text|locate|locateAll|select|optional|exists|clear|focus)\(\s*(['\"])(.+?)\1"),
    "cypress": re.compile(r"cy\.get\(\s*(['\"`])(.+?)\1"),
}
ENDPOINT_RE = {
    "karate": re.compile(r"\bpath\s+'([^']+)'"),
    "restassured": re.compile(r"\.(?:get|post|put|delete)\(\s*\"(/[^\"]+)\""),
    "cypress": re.compile(r"url:\s*['\"](/api/[^'\"]+)['\"]"),
}

LOC_CATEGORIES = ["teste", "suporte", "configuracao", "build_ci"]


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def list_files(project_dir):
    out = subprocess.run(["git", "-C", project_dir, "ls-files", "-z"],
                         check=True, capture_output=True).stdout.decode("utf-8", "replace")
    return [p for p in out.split("\0") if p]


def cloc_by_file(project_dir):
    raw = run(["cloc", "--vcs=git", "--by-file", "--json", "--quiet", "."], cwd=project_dir)
    data = json.loads(raw) if raw.strip() else {}
    result = {}
    for key, val in data.items():
        if key in ("header", "SUM"):
            continue
        path = os.path.normpath(key).replace(os.sep, "/")
        result[path] = (val.get("language", ""), val.get("blank", 0), val.get("comment", 0), val.get("code", 0))
    return result


def classify(project, path):
    for pattern, cat, layer in RULES[project]:
        if fnmatch.fnmatch(path, pattern):
            return cat, layer
    return None


def read_text(project_dir, path):
    with open(os.path.join(project_dir, path), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def normalize_endpoint(lit):
    lit = lit.lstrip("/")
    return lit[4:] if lit.startswith("api/") else lit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="targets")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    files_rows, unclassified = [], []
    classified = {p: [] for p in RULES}  # project -> [(path, cat, layer, code)]
    amb_rows = []

    for project in RULES:
        pdir = os.path.join(args.targets, project)
        tracked = list_files(pdir)
        cloc = cloc_by_file(pdir)
        sha = run(["git", "-C", pdir, "rev-parse", "HEAD"]).strip()
        date = run(["git", "-C", pdir, "log", "-1", "--format=%cI"]).strip()
        amb_rows.append([project, sha, date, len(tracked)])
        for path in sorted(tracked):
            cl = classify(project, path)
            if cl is None:
                unclassified.append(f"{project}: {path}")
                continue
            cat, layer = cl
            lang, blank, comment, code = cloc.get(path, ("", 0, 0, 0))
            size = os.path.getsize(os.path.join(pdir, path)) if os.path.exists(os.path.join(pdir, path)) else 0
            files_rows.append([project, path, cat, layer, lang, blank, comment, code, size])
            classified[project].append((path, cat, layer, code))

    write_csv(os.path.join(args.out, "ambiente.csv"),
              ["projeto", "commit_sha", "data_commit", "arquivos_versionados"], amb_rows)
    write_csv(os.path.join(args.out, "files.csv"),
              ["projeto", "arquivo", "categoria", "camada", "linguagem", "brancos", "comentarios", "codigo", "bytes"],
              files_rows)

    # ---- resumo de linhas por categoria/camada ----
    agg = defaultdict(lambda: [0, 0, 0, 0])
    for project, _p, cat, layer, _lang, blank, comment, code, _b in files_rows:
        a = agg[(project, cat, layer)]
        a[0] += 1
        a[1] += code
        a[2] += comment
        a[3] += blank
    loc_rows = [[k[0], k[1], k[2], *v] for k, v in sorted(agg.items())]
    write_csv(os.path.join(args.out, "loc_summary.csv"),
              ["projeto", "categoria", "camada", "arquivos", "linhas_codigo", "comentarios", "brancos"], loc_rows)

    # ---- visões comparáveis (API e UI) com custo fixo e variável ----
    derived = []
    for project, views in VIEWS.items():
        for view, layer in views:
            for crit, layers in (("exclusivo", {layer}), ("com_compartilhado", {layer, "compartilhado"})):
                sums = {c: sum(a[1] for (pr, ct, ly), a in agg.items()
                               if pr == project and ct == c and ly in layers) for c in LOC_CATEGORIES}
                total = sum(sums.values())
                fixo = sums["suporte"] + sums["configuracao"] + sums["build_ci"]
                n = SCENARIOS[project][layer]
                derived.append([project, view, crit, sums["teste"], sums["suporte"], sums["configuracao"],
                                sums["build_ci"], total, fixo, n,
                                round(sums["teste"] / n, 2), round(total / n, 2)])
    write_csv(os.path.join(args.out, "loc_derived.csv"),
              ["projeto", "visao", "criterio", "loc_teste", "loc_suporte", "loc_configuracao", "loc_build_ci",
               "loc_total_sem_docs", "loc_fixo", "cenarios", "loc_teste_por_cenario", "loc_total_por_cenario"],
              derived)

    # ---- pontos de asserção ----
    assert_rows = []
    for project in RULES:
        pdir = os.path.join(args.targets, project)
        per_layer = defaultdict(int)
        for path, cat, layer, _code in classified[project]:
            if cat == "teste":
                per_layer[layer] += len(ASSERT_RE[project].findall(read_text(pdir, path)))
        for layer, count in sorted(per_layer.items()):
            n = SCENARIOS[project][layer]
            assert_rows.append([project, layer, count, n, round(count / n, 2)])
    write_csv(os.path.join(args.out, "assertions.csv"),
              ["projeto", "camada", "pontos_de_assercao", "cenarios", "pontos_por_cenario"], assert_rows)

    # ---- reuso: literais de seletores e endpoints ----
    reuse_rows, literal_rows = [], []
    for project in RULES:
        pdir = os.path.join(args.targets, project)
        kinds = []
        if project in SELECTOR_RE:
            kinds.append(("seletor", lambda t, p=project: [m.group(2) for m in SELECTOR_RE[p].finditer(t)]))
        if project in ENDPOINT_RE:
            kinds.append(("endpoint", lambda t, p=project: [normalize_endpoint(m.group(1))
                                                           for m in ENDPOINT_RE[p].finditer(t)]))
        for kind, extract in kinds:
            counts = defaultdict(lambda: {"teste": 0, "suporte": 0})
            for path, cat, _layer, _code in classified[project]:
                if cat in ("teste", "suporte"):
                    for lit in extract(read_text(pdir, path)):
                        counts[lit][cat] += 1
            total_teste = sum(c["teste"] for c in counts.values())
            total = total_teste + sum(c["suporte"] for c in counts.values())
            uniq = len(counts)
            reuse_rows.append([project, kind, uniq, total, total_teste,
                               round(100 * total_teste / total, 1) if total else 0,
                               round(total / uniq, 2) if uniq else 0])
            for lit, c in sorted(counts.items()):
                literal_rows.append([project, kind, lit, c["teste"], c["suporte"]])
    write_csv(os.path.join(args.out, "reuse.csv"),
              ["projeto", "tipo", "literais_unicos", "ocorrencias_total", "ocorrencias_em_teste",
               "pct_em_teste", "ocorrencias_por_literal"], reuse_rows)
    write_csv(os.path.join(args.out, "reuse_literals.csv"),
              ["projeto", "tipo", "literal", "ocorrencias_em_teste", "ocorrencias_em_suporte"], literal_rows)

    # ---- dependências ----
    dep_rows = []
    kdir, rdir, cdir = (os.path.join(args.targets, p) for p in ("karate", "restassured", "cypress"))
    for project, pdir in (("karate", kdir), ("restassured", rdir)):
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        root = ET.parse(os.path.join(pdir, "pom.xml")).getroot()
        direct = len(root.findall("m:dependencies/m:dependency", ns))
        cp_file = os.path.join(args.out, f"{project}_classpath.txt")
        total, size = "", ""
        if os.path.exists(cp_file):
            jars = [j for j in open(cp_file, encoding="utf-8").read().strip().split(os.pathsep) if j]
            total = len(jars)
            size = round(sum(os.path.getsize(j) for j in jars if os.path.exists(j)) / 1e6, 2)
        dep_rows.append([project, direct, total, size, "classpath de teste (jars), sem plugins do Maven"])
    pkg = json.load(open(os.path.join(cdir, "package.json"), encoding="utf-8"))
    direct = len(pkg.get("dependencies", {})) + len(pkg.get("devDependencies", {}))
    lock_path = os.path.join(cdir, "package-lock.json")
    total = ""
    if os.path.exists(lock_path):
        lock = json.load(open(lock_path, encoding="utf-8"))
        total = len([k for k in lock.get("packages", {}) if k])
    nm = os.path.join(cdir, "node_modules")
    size = ""
    if os.path.isdir(nm):
        size = round(sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fs in os.walk(nm) for f in fs
                         if os.path.isfile(os.path.join(dp, f))) / 1e6, 2)
    dep_rows.append(["cypress", direct, total, size, "pacotes npm instalados, sem o binário do Cypress"])
    write_csv(os.path.join(args.out, "dependencies.csv"),
              ["projeto", "dependencias_diretas", "dependencias_totais", "tamanho_mb", "observacao"], dep_rows)

    # ---- tamanho dos workflows ----
    wf_rows = []
    for project in RULES:
        pdir = os.path.join(args.targets, project)
        for path in sorted(list_files(pdir)):
            if fnmatch.fnmatch(path, ".github/workflows/*.yml") or fnmatch.fnmatch(path, ".github/workflows/*.yaml"):
                lines = read_text(pdir, path).splitlines()
                non_empty = len([ln for ln in lines if ln.strip()])
                jobs, in_jobs = 0, False
                for ln in lines:
                    if re.match(r"^jobs:\s*$", ln):
                        in_jobs = True
                        continue
                    if in_jobs and re.match(r"^\S", ln):
                        in_jobs = False
                    if in_jobs and re.match(r"^  [\w-]+:\s*$", ln):
                        jobs += 1
                steps = len([ln for ln in lines if re.match(r"^ {6}- ", ln)])
                wf_rows.append([project, path, non_empty, jobs, steps])
    write_csv(os.path.join(args.out, "workflows.csv"),
              ["projeto", "arquivo", "linhas_nao_vazias", "jobs", "passos"], wf_rows)

    # ---- duplicação (resultado do jscpd, se existir) ----
    dup_rows = []
    for project in RULES:
        rep = os.path.join(args.out, "jscpd", project, "jscpd-report.json")
        if os.path.exists(rep):
            stats = json.load(open(rep, encoding="utf-8")).get("statistics", {})
            tot = stats.get("total", {})
            fmts = ",".join(sorted(stats.get("formats", {}).keys()))
            dup_rows.append([project, fmts, tot.get("lines", ""), tot.get("duplicatedLines", ""),
                             tot.get("percentage", ""), tot.get("clones", "")])
        else:
            dup_rows.append([project, "indisponivel", "", "", "", ""])
    write_csv(os.path.join(args.out, "duplication.csv"),
              ["projeto", "formatos_analisados", "linhas", "linhas_duplicadas", "percentual", "clones"], dup_rows)

    # ---- resumo em Markdown ----
    def md_table(header, rows):
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
        return "\n".join(lines)

    parts = ["# Métricas estáticas\n",
             "## Commits medidos\n", md_table(["projeto", "commit", "data", "arquivos"], amb_rows), "",
             "## Linhas de código (cloc) por categoria\n",
             md_table(["projeto", "categoria", "camada", "arquivos", "código", "comentários", "brancos"], loc_rows), "",
             "## Visões comparáveis\n",
             md_table(["projeto", "visão", "critério", "teste", "suporte", "config", "build/ci", "total",
                       "fixo", "cenários", "teste/cenário", "total/cenário"], derived), "",
             "## Pontos de asserção\n",
             md_table(["projeto", "camada", "pontos", "cenários", "pontos/cenário"], assert_rows), "",
             "## Reuso (seletores e endpoints)\n",
             md_table(["projeto", "tipo", "únicos", "ocorrências", "em teste", "% em teste", "ocorr./literal"],
                      reuse_rows), "",
             "## Dependências\n",
             md_table(["projeto", "diretas", "totais", "MB", "obs."], dep_rows), "",
             "## Workflows\n", md_table(["projeto", "arquivo", "linhas", "jobs", "passos"], wf_rows), "",
             "## Duplicação (jscpd)\n",
             md_table(["projeto", "formatos", "linhas", "duplicadas", "%", "clones"], dup_rows), ""]
    if unclassified:
        parts += ["## ATENÇÃO: arquivos sem classificação\n"] + [f"- {u}" for u in unclassified] + [""]
    summary = "\n".join(parts)
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(summary)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")

    if unclassified:
        with open(os.path.join(args.out, "unclassified.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(unclassified))
        print("ERRO: há arquivos sem classificação. Ajuste RULES em scripts/static_metrics.py:", file=sys.stderr)
        for u in unclassified:
            print("  " + u, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
