#!/usr/bin/env python3
"""Bateria de execuções medidas no GitHub Actions: dispara, espera e consolida.

O script só dispara os workflows e baixa os resultados. Toda a execução medida
acontece nos runners do GitHub. Requer o GitHub CLI (`gh`) autenticado.

Comandos:
  python scripts/battery.py check                    confere login, repositórios, tag e workflows
  python scripts/battery.py plan --reps 10           mostra o plano e uma estimativa de tempo
  python scripts/battery.py run --reps 10 --warmup   dispara e espera (pode ser interrompido e retomado)
  python scripts/battery.py fill --reps 10           repete as execuções afetadas pelo site (até 3 tentativas)
  python scripts/battery.py collect                  baixa os resultados e gera os CSVs consolidados

Os dados ficam em data/ (dispatch_log.csv, raw/ e consolidado/).
"""
import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# CONFIGURAÇÃO DO ESTUDO (confira os nomes dos repositórios)
# --------------------------------------------------------------------------
OWNER = "lipesilvapr"
DEFAULT_REF = "estudo-v3"  # tag (ou branch) que será executada

TOOLS = {
    "karate-api": {"repo": f"{OWNER}/Karate-Automation-Exercise", "workflow": "tests.yml", "camada": "api"},
    "karate-ui": {"repo": f"{OWNER}/Karate-Automation-Exercise", "workflow": "tests.yml", "camada": "ui"},
    "restassured": {"repo": f"{OWNER}/restassured-automation-exercise", "workflow": "api-tests.yml", "camada": "api"},
    "cypress": {"repo": f"{OWNER}/cypress-automation-exercise", "workflow": "ui-tests.yml", "camada": "ui"},
}

CONFIGS = {
    "A_quente_1": {"cache": "true", "threads": "1"},
    "B_frio_1": {"cache": "false", "threads": "1"},
    "C_quente_4": {"cache": "true", "threads": "4"},
}

# configurações executadas por ferramenta (a UI roda sempre com 1 thread)
PLAN = {
    "karate-api": ["A_quente_1", "B_frio_1", "C_quente_4"],
    "restassured": ["A_quente_1", "B_frio_1", "C_quente_4"],
    "karate-ui": ["A_quente_1", "B_frio_1"],
    "cypress": ["A_quente_1", "B_frio_1"],
}
ORDER = ["karate-api", "restassured", "karate-ui", "cypress"]

# estimativa grosseira (min por execução, incluindo preparação) só para o comando `plan`
EST_MIN = {"karate-api": 3, "restassured": 4, "karate-ui": 6, "cypress": 4}

# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
OUT = DATA / "consolidado"
LOG = DATA / "dispatch_log.csv"
POLL = float(os.environ.get("BATTERY_POLL_S", "15"))
RUN_TIMEOUT_MIN = 60

# Mensagens de falha que indicam problema do ambiente (site) e não do teste. Fixado antes da bateria.
ENV_PATTERNS = ["403", "forbidden", "503", "heavy load", "queue full", "too many people", "one moment, please",
                "<!doctype html", "<html", "não foi possível converter o corpo", "(null:number)"]

# Falhas de UI "elemento não encontrado": podem ser a página de erro do site OU um problema real do teste.
# Ficam como INDETERMINADAS para revisão manual (screenshot no relatório do Karate / Cypress).
UNCERTAIN_PATTERNS = ["cannot read properties of null", "expected to find element", "timed out retrying", "js failed"]

LOG_FIELDS = ["key", "rep", "config", "tool", "camada", "repo", "workflow", "ref", "cache", "threads",
              "dispatched_at", "run_id", "status", "conclusion", "url"]


def say(msg=""):
    print(msg, flush=True)


# ------------------------------- gh ---------------------------------------
def gh(*args, check=True, retries=3):
    last = None
    for attempt in range(retries if check else 1):
        p = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
        if p.returncode == 0 or not check:
            return p
        last = p
        time.sleep(min(3 * (attempt + 1), 10) if POLL > 1 else 0.01)
    raise RuntimeError(f"gh {' '.join(args)} falhou: {last.stderr.strip() or last.stdout.strip()}")


def gh_json(*args):
    return json.loads(gh(*args).stdout)


def inputs_for(tool, cfg_id):
    cfg = CONFIGS[cfg_id]
    if tool.startswith("karate"):
        return {"use_cache": cfg["cache"], "threads": cfg["threads"], "camada": TOOLS[tool]["camada"]}
    if tool == "restassured":
        return {"use_cache": cfg["cache"], "threads": cfg["threads"]}
    return {"use_cache": cfg["cache"]}  # cypress: sem entrada de threads


# ------------------------------- plano ------------------------------------
def build_plan(reps, warmup, only):
    tasks = []
    tools = [t for t in ORDER if not only or t in only]
    if warmup:
        tasks += [(0, "A_quente_1", t) for t in tools]
    for rep in range(1, reps + 1):
        for cfg in CONFIGS:
            order = [t for t in tools if cfg in PLAN[t]]
            if rep % 2 == 0:
                order.reverse()  # alterna a ordem entre repetições para não favorecer ninguém
            tasks += [(rep, cfg, t) for t in order]
    return tasks


# ------------------------------- log --------------------------------------
def read_log():
    log = {}
    if LOG.exists():
        with open(LOG, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                log[row["key"]] = row
    return log


def write_log(log):
    DATA.mkdir(parents=True, exist_ok=True)
    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS, lineterminator="\n")
        w.writeheader()
        for row in log.values():
            w.writerow({k: row.get(k, "") for k in LOG_FIELDS})


# ------------------------------- check ------------------------------------
def cmd_check(args):
    ok = True
    p = gh("auth", "status", check=False)
    say("login no GitHub: " + ("OK" if p.returncode == 0 else "FALHOU (rode: gh auth login)"))
    ok &= p.returncode == 0
    seen = set()
    for tool, t in TOOLS.items():
        repo, wf = t["repo"], t["workflow"]
        if (repo, wf) in seen:
            continue
        seen.add((repo, wf))
        checks = [
            ("repositório existe", [["repo", "view", repo, "--json", "name"]]),
            (f"tag ou branch '{args.ref}' existe", [["api", f"repos/{repo}/git/ref/tags/{args.ref}"],
                                                     ["api", f"repos/{repo}/git/ref/heads/{args.ref}"]]),
            (f"workflow {wf} existe nessa ref", [["api", f"repos/{repo}/contents/.github/workflows/{wf}?ref={args.ref}"]]),
        ]
        for label, alternatives in checks:
            passed = any(gh(*cmd, check=False).returncode == 0 for cmd in alternatives)
            say(f"{repo}: {label}: " + ("OK" if passed else "FALHOU"))
            ok &= passed
    say("\nTudo certo." if ok else "\nHá itens com FALHOU. Corrija antes de rodar a bateria.")
    return 0 if ok else 1


# ------------------------------- plan -------------------------------------
def cmd_plan(args):
    only = set(args.only.split(",")) if args.only else None
    tasks = build_plan(args.reps, args.warmup, only)
    per_tool = {}
    for rep, cfg, tool in tasks:
        per_tool[tool] = per_tool.get(tool, 0) + 1
    say(f"Execuções planejadas: {len(tasks)} (repetições: {args.reps}, aquecimento: {'sim' if args.warmup else 'não'})")
    for tool, n in per_tool.items():
        say(f"  {tool:12s} {n:3d} execuções  ({TOOLS[tool]['repo']}, {TOOLS[tool]['workflow']})")
    est = sum(EST_MIN[t] for _, _, t in tasks)
    say(f"Estimativa grosseira (sequencial): {est // 60} h {est % 60} min")
    say("Primeiras execuções:")
    for rep, cfg, tool in tasks[:8]:
        say(f"  rep {rep:2d}  {cfg:11s} {tool}")
    return 0


# ------------------------------- run --------------------------------------
def list_runs(t):
    return gh_json("run", "list", "-R", t["repo"], "--workflow", t["workflow"], "--event", "workflow_dispatch",
                   "--limit", "20", "--json", "databaseId,createdAt,status")


def dispatch(tool, cfg_id, ref):
    t = TOOLS[tool]
    before = {r["databaseId"] for r in list_runs(t)}
    args = ["workflow", "run", t["workflow"], "-R", t["repo"], "--ref", ref]
    for k, v in inputs_for(tool, cfg_id).items():
        args += ["-f", f"{k}={v}"]
    gh(*args)
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(POLL)
        new = [r for r in list_runs(t) if r["databaseId"] not in before]
        if new:
            return max(new, key=lambda r: r["databaseId"])["databaseId"]
    raise RuntimeError(f"não encontrei a execução disparada em {t['repo']}")


def wait_done(tool, run_id):
    t = TOOLS[tool]
    deadline = time.time() + RUN_TIMEOUT_MIN * 60
    while True:
        d = gh_json("run", "view", str(run_id), "-R", t["repo"], "--json", "status,conclusion,url")
        if d.get("status") == "completed":
            return d
        if time.time() > deadline:
            return {"status": "timeout", "conclusion": "timeout", "url": d.get("url", "")}
        time.sleep(POLL)


def execute_task(log, key, rep, cfg, tool, ref):
    """Dispara (ou retoma) uma execução, espera terminar e grava no log."""
    t = TOOLS[tool]
    row = log.get(key)
    if row and row.get("run_id"):
        run_id = row["run_id"]
        say(f"  retomando a execução {run_id}")
    else:
        run_id = dispatch(tool, cfg, ref)
        cfgv = CONFIGS[cfg]
        row = {"key": key, "rep": rep, "config": cfg, "tool": tool, "camada": t["camada"], "repo": t["repo"],
               "workflow": t["workflow"], "ref": ref, "cache": cfgv["cache"], "threads": cfgv["threads"],
               "dispatched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "run_id": run_id,
               "status": "dispatched", "conclusion": "", "url": ""}
        log[key] = row
        write_log(log)
    res = wait_done(tool, run_id)
    row.update({"status": res["status"], "conclusion": res.get("conclusion") or "", "url": res.get("url", "")})
    write_log(log)
    say(f"  execução {run_id}: {row['conclusion']}  {row['url']}")


def cmd_run(args):
    if cmd_check(argparse.Namespace(ref=args.ref)) != 0:
        return 1
    only = set(args.only.split(",")) if args.only else None
    tasks = build_plan(args.reps, args.warmup, only)
    log = read_log()
    started = 0
    for i, (rep, cfg, tool) in enumerate(tasks, 1):
        key = f"{rep}|{cfg}|{tool}"
        row = log.get(key)
        if row and row["status"] == "completed":
            continue
        if args.limit and started >= args.limit:
            say(f"Limite de {args.limit} execuções atingido.")
            break
        started += 1
        say(f"[{i}/{len(tasks)}] rep {rep} {cfg} {tool} ...")
        execute_task(log, key, rep, cfg, tool, args.ref)
    say("Fim. Rode `collect` para baixar e consolidar os resultados (e `fill` para repetir as execuções afetadas pelo site).")
    return 0


def valid_cells():
    """Células (rep, config, ferramenta) que já têm uma execução válida (não afetada pelo ambiente)."""
    path = OUT / "measurements.csv"
    cells = set()
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["execucao_valida"] == "True":
                    cells.add((int(r["rep"]), r["config"], r["tool"]))
    return cells


def cmd_fill(args):
    """Repete as células da bateria que só têm execuções afetadas pelo site, até `--max-attempts` tentativas."""
    if cmd_check(argparse.Namespace(ref=args.ref)) != 0:
        return 1
    only = set(args.only.split(",")) if args.only else None
    cells = [(rep, cfg, tool) for rep, cfg, tool in build_plan(args.reps, False, only)]
    for attempt in range(2, args.max_attempts + 1):
        cmd_collect(argparse.Namespace())
        valid = valid_cells()
        log = read_log()
        missing = []
        for rep, cfg, tool in cells:
            base = f"{rep}|{cfg}|{tool}"
            done = [k for k in log if k == base or k.startswith(base + "|a")]
            finished = all(log[k]["status"] == "completed" for k in done) if done else False
            if (rep, cfg, tool) not in valid and finished and len(done) == attempt - 1:
                missing.append((rep, cfg, tool))
        if not missing:
            say(f"Nenhuma célula para repetir na tentativa {attempt}.")
            break
        say(f"Tentativa {attempt}: {len(missing)} célula(s) sem execução válida.")
        for i, (rep, cfg, tool) in enumerate(missing, 1):
            if args.limit and i > args.limit:
                say(f"Limite de {args.limit} execuções atingido.")
                return 0
            say(f"[{i}/{len(missing)}] repetindo rep {rep} {cfg} {tool} (tentativa {attempt}) ...")
            execute_task(log, f"{rep}|{cfg}|{tool}|a{attempt}", rep, cfg, tool, args.ref)
    cmd_collect(argparse.Namespace())
    valid = valid_cells()
    still = [c for c in cells if c not in valid]
    say(f"Células sem nenhuma execução válida: {len(still)} de {len(cells)}")
    for rep, cfg, tool in still:
        say(f"  rep {rep} {cfg} {tool}")
    return 0


# ------------------------------- collect ----------------------------------
def iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def secs(a, b):
    try:
        return round((iso(b) - iso(a)).total_seconds(), 1)
    except Exception:
        return ""


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def cmd_collect(args):
    log = read_log()
    meas, tests, steps, issues = [], [], [], []
    for key, row in log.items():
        run_id = row["run_id"]
        if row["status"] != "completed":
            issues.append({"key": key, "run_id": run_id, "problema": f"execução não concluída ({row['status']})"})
            continue
        run_dir = RAW / row["tool"] / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        jobs_file = run_dir / "jobs.json"
        if not jobs_file.exists():
            out = gh("api", f"repos/{row['repo']}/actions/runs/{run_id}/jobs?per_page=100").stdout
            jobs_file.write_text(out, encoding="utf-8")
        jobs = json.loads(jobs_file.read_text(encoding="utf-8")).get("jobs", [])
        if not list(run_dir.rglob("*-metrics.json")):
            gh("run", "download", str(run_id), "-R", row["repo"], "-D", str(run_dir),
               "--pattern", "run-metrics-*", check=False)
        found = sorted(run_dir.rglob("*-metrics.json"))
        if not found:
            issues.append({"key": key, "run_id": run_id,
                           "problema": "artefato run-metrics não encontrado (a execução falhou antes da medição?)"})
        for mpath in found:
            m = json.loads(mpath.read_text(encoding="utf-8"))
            g, r, t, a = m["github"], m["recursos"], m["testes"], m["ambiente"]
            job = next((j for j in jobs if j.get("name") == g.get("job")), {})
            site = m.get("site", {})
            tpath = mpath.with_name(mpath.name.replace("-metrics.json", "-tests.csv"))
            run_tests = []
            if tpath.exists():
                with open(tpath, newline="", encoding="utf-8") as fh:
                    run_tests = list(csv.DictReader(fh))
            falhas_amb = sum(1 for tr in run_tests if tr["status"] == "falhou"
                             and any(p in tr["mensagem"].lower() for p in ENV_PATTERNS))
            falhas_indet = sum(1 for tr in run_tests if tr["status"] == "falhou"
                               and not any(p in tr["mensagem"].lower() for p in ENV_PATTERNS)
                               and any(p in tr["mensagem"].lower() for p in UNCERTAIN_PATTERNS))
            sondas_falhas = (site.get("antes", {}).get("ok") is False or site.get("depois", {}).get("ok") is False
                             or (site.get("durante", {}).get("falhas") or 0) > 0)
            ambiente_afetado = bool(sondas_falhas or falhas_amb > 0)
            meas.append({
                "key": key, "rep": row["rep"], "config": row["config"], "tool": row["tool"],
                "projeto": m["projeto"], "camada": m["camada"], "repo": g["repositorio"], "run_id": run_id,
                "run_attempt": g["run_attempt"], "cache": m["cache"], "threads": m.get("threads", ""),
                "ref": row["ref"], "commit": g["commit"], "inicio_utc": m["inicio_utc"],
                "duracao_s": m["duracao_s"], "codigo_saida": m["codigo_saida"],
                "testes_total": t["total"], "testes_passou": t["passou"], "testes_falhou": t["falhou"],
                "testes_ignorado": t["ignorado"], "testes_esperados": m.get("testes_esperados", ""),
                "contagem_confere": m.get("contagem_confere", ""), "tempo_soma_testes_s": t["tempo_soma_s"],
                "cpu_media_pct": r["cpu_media_pct"], "cpu_pico_pct": r["cpu_pico_pct"],
                "mem_baseline_mb": r["mem_baseline_mb"], "mem_pico_mb": r["mem_pico_mb"],
                "mem_pico_delta_mb": r["mem_pico_delta_mb"], "amostras": r["amostras"],
                "cpu_modelo": a["cpu_modelo"], "cpu_n": a["cpu_n"], "mem_total_mb": a["mem_total_mb"],
                "image_version": a["image_version"], "runner_name": a["runner_name"],
                "job": g.get("job", ""), "job_conclusao": job.get("conclusion", ""),
                "job_duracao_s": secs(job.get("started_at", ""), job.get("completed_at", "")) if job else "",
                "rede_org": m.get("rede", {}).get("org", ""),
                "site_antes_ok": m.get("site", {}).get("antes", {}).get("ok", ""),
                "site_antes_http": m.get("site", {}).get("antes", {}).get("http_code", ""),
                "site_antes_trecho": m.get("site", {}).get("antes", {}).get("trecho", ""),
                "site_depois_ok": m.get("site", {}).get("depois", {}).get("ok", ""),
                "site_depois_http": m.get("site", {}).get("depois", {}).get("http_code", ""),
                "site_depois_trecho": m.get("site", {}).get("depois", {}).get("trecho", ""),
                "site_durante_n": site.get("durante", {}).get("n", ""),
                "site_durante_falhas": site.get("durante", {}).get("falhas", ""),
                "falhas_ambiente": falhas_amb,
                "falhas_indeterminadas": falhas_indet,
                "ambiente_afetado": ambiente_afetado,
                "execucao_valida": not ambiente_afetado,
            })
            for trow in run_tests:
                trow.update({"key": key, "rep": row["rep"], "config": row["config"], "tool": row["tool"],
                             "cache": m["cache"], "threads": m.get("threads", "")})
                trow["causa_ambiente"] = (trow["status"] == "falhou"
                                          and any(p in trow["mensagem"].lower() for p in ENV_PATTERNS))
                tests.append(trow)
        for j in jobs:
            for s in j.get("steps", []):
                steps.append({"key": key, "rep": row["rep"], "config": row["config"], "tool": row["tool"],
                              "run_id": run_id, "job": j.get("name", ""), "passo_n": s.get("number", ""),
                              "passo": s.get("name", ""), "conclusao": s.get("conclusion", ""),
                              "inicio": s.get("started_at", ""), "fim": s.get("completed_at", ""),
                              "duracao_s": secs(s.get("started_at", ""), s.get("completed_at", ""))})

    mf = ["key", "rep", "config", "tool", "projeto", "camada", "repo", "run_id", "run_attempt", "cache", "threads",
          "ref", "commit", "inicio_utc", "duracao_s", "codigo_saida", "testes_total", "testes_passou",
          "testes_falhou", "testes_ignorado", "testes_esperados", "contagem_confere", "tempo_soma_testes_s",
          "cpu_media_pct", "cpu_pico_pct", "mem_baseline_mb", "mem_pico_mb", "mem_pico_delta_mb", "amostras",
          "cpu_modelo", "cpu_n", "mem_total_mb", "image_version", "runner_name", "job", "job_conclusao",
          "job_duracao_s", "rede_org", "site_antes_ok", "site_antes_http", "site_antes_trecho",
          "site_depois_ok", "site_depois_http", "site_depois_trecho", "site_durante_n", "site_durante_falhas",
          "falhas_ambiente", "falhas_indeterminadas", "ambiente_afetado", "execucao_valida"]
    write_csv(OUT / "measurements.csv", mf, meas)
    tf = ["key", "rep", "config", "tool", "cache", "threads", "projeto", "camada", "run_id", "run_attempt",
          "classname", "teste", "status", "tempo_s", "mensagem", "causa_ambiente"]
    write_csv(OUT / "tests.csv", tf, tests)
    write_csv(OUT / "steps.csv", ["key", "rep", "config", "tool", "run_id", "job", "passo_n", "passo", "conclusao",
                                  "inicio", "fim", "duracao_s"], steps)
    write_csv(OUT / "issues.csv", ["key", "run_id", "problema"], issues)
    say(f"measurements.csv: {len(meas)} linhas | tests.csv: {len(tests)} | steps.csv: {len(steps)} | problemas: {len(issues)}")
    for i in issues:
        say(f"  PROBLEMA {i['key']} (run {i['run_id']}): {i['problema']}")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("check", cmd_check), ("plan", cmd_plan), ("run", cmd_run), ("fill", cmd_fill), ("collect", cmd_collect)):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        if name in ("check", "run", "fill"):
            sp.add_argument("--ref", default=DEFAULT_REF, help="tag ou branch a executar (padrão: %(default)s)")
        if name in ("plan", "run", "fill"):
            sp.add_argument("--reps", type=int, default=10)
        if name in ("plan", "run"):
            sp.add_argument("--warmup", action="store_true", help="uma execução de aquecimento (repetição 0) por ferramenta")
            sp.add_argument("--only", default="", help="lista separada por vírgula: karate-api,restassured,karate-ui,cypress")
        if name == "fill":
            sp.add_argument("--max-attempts", type=int, default=3, help="tentativas por célula, contando a primeira")
            sp.add_argument("--only", default="")
        if name in ("run", "fill"):
            sp.add_argument("--limit", type=int, default=0, help="executa no máximo N execuções (para testes)")
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
