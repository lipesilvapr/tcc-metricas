#!/usr/bin/env python3
"""Executa um comando de teste e registra tempo, CPU, memória e resultados por teste.

Configurado por variáveis de ambiente (preenchidas pela action `measure`):
  M_PROJETO, M_CAMADA, M_COMMAND, M_JUNIT_GLOB (padrões separados por quebra de linha ou vírgula),
  M_EXPECTED (nº de testes esperado, opcional), M_CACHE (cache ligado/desligado, só registro),
  M_THREADS (nº de threads, só registro), M_PROBE_URL (sonda do site, opcional), M_OUT (pasta de saída)

Saídas em M_OUT:
  <projeto>-<camada>-metrics.json   resumo da execução
  <projeto>-<camada>-tests.csv      um registro por teste
  <projeto>-<camada>-samples.csv    amostras de CPU e memória (1 por segundo)
  <projeto>-<camada>-site.csv       sondas do site durante os testes (1 a cada 5 s)

O código de saída é o do comando, então o job fica vermelho quando algum teste falha.
Apenas biblioteca padrão do Python; roda em Linux (usa /proc).
"""
import csv
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

INTERVAL = 1.0
MONITOR_INTERVAL = 5.0
PROBE_URL = os.environ.get("M_PROBE_URL", "https://automationexercise.com/api/productsList")


def read_cpu():
    with open("/proc/stat", encoding="utf-8") as fh:
        vals = [int(x) for x in fh.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
    total = sum(vals[:8]) if len(vals) >= 8 else sum(vals)
    return total, idle


def read_mem_mb():
    info = {}
    with open("/proc/meminfo", encoding="utf-8") as fh:
        for line in fh:
            key, val = line.split(":")
            info[key] = int(val.split()[0])  # kB
    return (info["MemTotal"] - info["MemAvailable"]) / 1024.0, info["MemTotal"] / 1024.0


def cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _get(url, tmp):
    body = os.path.join(tmp, "body")
    t0 = time.perf_counter()
    p = subprocess.run(["curl", "-s", "--max-time", "15", "-o", body, "-w", "%{http_code}", url],
                       capture_output=True, text=True, timeout=30)
    text = open(body, encoding="utf-8", errors="replace").read() if os.path.exists(body) else ""
    return p.stdout.strip(), text, round(time.perf_counter() - t0, 3)


def _plain(text):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:160]


def site_probe(url):
    """Duas requisições ao site, fora do tempo medido: a API (JSON com responseCode) e a página inicial.
    ok = as duas responderam normalmente."""
    parsed = urlparse(url)
    page_url = f"{parsed.scheme}://{parsed.netloc}/"
    res = {"http_code": "", "tempo_s": None, "ok": False, "trecho": "", "pagina_http": "", "pagina_ok": False}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            code, text, t = _get(url, tmp)
            res["http_code"], res["tempo_s"] = code, t
            try:
                api_ok = code == "200" and "responseCode" in json.loads(text)
            except Exception:
                api_ok = False
            trecho = "" if api_ok else _plain(text)
            pcode, ptext, _ = _get(page_url, tmp)
            res["pagina_http"] = pcode
            res["pagina_ok"] = pcode == "200" and "automation exercise" in ptext.lower()
            if not res["pagina_ok"] and not trecho:
                trecho = _plain(ptext)
            res["ok"] = bool(api_ok and res["pagina_ok"])
            res["trecho"] = trecho
    except Exception as exc:  # a sonda nunca pode derrubar a medição
        res["trecho"] = f"erro na sonda: {exc}"[:160]
    return res


def egress_org():
    """Organização da rede de saída do runner (ex.: AS8075 Microsoft Corporation)."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            body = os.path.join(tmp, "body")
            subprocess.run(["curl", "-s", "--max-time", "10", "-o", body, "https://ipinfo.io/json"],
                           capture_output=True, timeout=20)
            return json.load(open(body, encoding="utf-8")).get("org", "")
    except Exception:
        return ""


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.samples = []  # (t, cpu_pct, mem_used_mb)
        self.t0 = time.perf_counter()

    def run(self):
        prev_total, prev_idle = read_cpu()
        while not self.stop_event.wait(INTERVAL):
            total, idle = read_cpu()
            d_total, d_idle = total - prev_total, idle - prev_idle
            cpu = 100.0 * (1 - d_idle / d_total) if d_total > 0 else 0.0
            mem, _ = read_mem_mb()
            self.samples.append((round(time.perf_counter() - self.t0, 1), round(cpu, 1), round(mem, 1)))
            prev_total, prev_idle = total, idle


class SiteMonitor(threading.Thread):
    """Sonda o site a cada MONITOR_INTERVAL segundos enquanto os testes rodam."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.results = []  # (t_s, ok, api_http, pagina_http, trecho)
        self.t0 = time.perf_counter()

    def run(self):
        while not self.stop_event.wait(MONITOR_INTERVAL):
            r = site_probe(PROBE_URL)
            self.results.append((round(time.perf_counter() - self.t0, 1), int(r["ok"]), r["http_code"],
                                 r["pagina_http"], r["trecho"]))


def parse_junit(patterns):
    files = []
    for pat in patterns:
        files += sorted(glob.glob(pat, recursive=True))
    tests = []
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            print(f"[measure] AVISO: não foi possível ler {path}: {exc}")
            continue
        for tc in root.iter("testcase"):
            status, msg = "passou", ""
            fail = tc.find("failure")
            err = tc.find("error")
            if fail is not None or err is not None:
                node = fail if fail is not None else err
                status = "falhou"
                msg = (node.get("message") or (node.text or "")).strip().replace("\n", " ")[:600]
            elif tc.find("skipped") is not None:
                status = "ignorado"
            tests.append({
                "classname": tc.get("classname", ""),
                "name": tc.get("name", ""),
                "status": status,
                "time_s": float(tc.get("time") or 0),
                "mensagem": msg,
            })
    return files, tests


def main():
    env = os.environ
    projeto, camada = env["M_PROJETO"], env["M_CAMADA"]
    command = env["M_COMMAND"]
    patterns = [p.strip() for p in env.get("M_JUNIT_GLOB", "").replace(",", "\n").splitlines() if p.strip()]
    out = env.get("M_OUT", "run-metrics")
    os.makedirs(out, exist_ok=True)
    prefix = os.path.join(out, f"{projeto}-{camada}")

    site_antes = site_probe(PROBE_URL)
    rede_org = egress_org()
    baseline_mem, mem_total = read_mem_mb()
    sampler = Sampler()
    sampler.start()
    monitor = SiteMonitor()
    monitor.start()
    started = datetime.datetime.now(datetime.timezone.utc)
    t0 = time.perf_counter()
    proc = subprocess.run(["bash", "-c", command])
    duration = time.perf_counter() - t0
    sampler.stop_event.set()
    monitor.stop_event.set()
    sampler.join(timeout=3)
    monitor.join(timeout=20)
    site_depois = site_probe(PROBE_URL)
    durante = monitor.results
    falhas_durante = [r for r in durante if not r[1]]

    files, tests = parse_junit(patterns)
    samples = sampler.samples
    cpu_vals = [s[1] for s in samples]
    mem_vals = [s[2] for s in samples]
    mem_peak = max(mem_vals) if mem_vals else baseline_mem

    counts = {"total": len(tests),
              "passou": sum(t["status"] == "passou" for t in tests),
              "falhou": sum(t["status"] == "falhou" for t in tests),
              "ignorado": sum(t["status"] == "ignorado" for t in tests),
              "tempo_soma_s": round(sum(t["time_s"] for t in tests), 3)}
    expected = int(env["M_EXPECTED"]) if env.get("M_EXPECTED", "").strip().isdigit() else None

    result = {
        "schema": 1,
        "projeto": projeto,
        "camada": camada,
        "comando": command,
        "codigo_saida": proc.returncode,
        "inicio_utc": started.isoformat(),
        "duracao_s": round(duration, 3),
        "cache": env.get("M_CACHE", ""),
        "threads": env.get("M_THREADS", ""),
        "recursos": {
            "intervalo_s": INTERVAL,
            "amostras": len(samples),
            "mem_baseline_mb": round(baseline_mem, 1),
            "mem_pico_mb": round(mem_peak, 1),
            "mem_pico_delta_mb": round(max(mem_peak - baseline_mem, 0), 1),
            "cpu_media_pct": round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else None,
            "cpu_pico_pct": max(cpu_vals) if cpu_vals else None,
        },
        "testes": counts,
        "site": {"url": PROBE_URL, "antes": site_antes, "depois": site_depois,
                 "durante": {"n": len(durante), "falhas": len(falhas_durante),
                             "primeira_falha_s": falhas_durante[0][0] if falhas_durante else None}},
        "rede": {"org": rede_org},
        "testes_esperados": expected,
        "contagem_confere": (counts["total"] == expected) if expected is not None else None,
        "arquivos_junit": len(files),
        "ambiente": {
            "image_os": env.get("ImageOS", ""),
            "image_version": env.get("ImageVersion", ""),
            "runner_os": env.get("RUNNER_OS", ""),
            "runner_arch": env.get("RUNNER_ARCH", ""),
            "runner_name": env.get("RUNNER_NAME", ""),
            "cpu_modelo": cpu_model(),
            "cpu_n": os.cpu_count(),
            "mem_total_mb": round(mem_total, 1),
        },
        "github": {
            "repositorio": env.get("GITHUB_REPOSITORY", ""),
            "run_id": env.get("GITHUB_RUN_ID", ""),
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
            "run_number": env.get("GITHUB_RUN_NUMBER", ""),
            "evento": env.get("GITHUB_EVENT_NAME", ""),
            "workflow": env.get("GITHUB_WORKFLOW", ""),
            "job": env.get("GITHUB_JOB", ""),
            "commit": env.get("GITHUB_SHA", ""),
            "ref": env.get("GITHUB_REF_NAME", ""),
        },
    }

    with open(prefix + "-metrics.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    with open(prefix + "-tests.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["projeto", "camada", "run_id", "run_attempt", "classname", "teste", "status", "tempo_s", "mensagem"])
        for t in tests:
            w.writerow([projeto, camada, result["github"]["run_id"], result["github"]["run_attempt"],
                        t["classname"], t["name"], t["status"], t["time_s"], t["mensagem"]])
    with open(prefix + "-site.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["t_s", "ok", "api_http", "pagina_http", "trecho"])
        w.writerows(durante)
    with open(prefix + "-samples.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["t_s", "cpu_pct", "mem_usada_mb"])
        w.writerows(samples)

    # avisos e resumo na página da execução
    if not files:
        print(f"[measure] AVISO: nenhum arquivo JUnit encontrado para: {patterns}")
    if expected is not None and counts["total"] != expected:
        print(f"[measure] AVISO: {counts['total']} testes encontrados, esperado {expected}")
    r = result["recursos"]
    md = [f"### Execução medida: {projeto} / {camada}", "",
          "| métrica | valor |", "|---|---|",
          f"| duração do comando | {result['duracao_s']} s |",
          f"| testes (total / passou / falhou / ignorado) | {counts['total']} / {counts['passou']} / {counts['falhou']} / {counts['ignorado']} |",
          f"| esperado | {expected} (confere: {result['contagem_confere']}) |",
          f"| CPU média / pico | {r['cpu_media_pct']} % / {r['cpu_pico_pct']} % |",
          f"| memória pico (acima da linha de base) | {r['mem_pico_delta_mb']} MB |",
          f"| cache / threads | {result['cache']} / {result['threads']} |",
          f"| site antes / depois (HTTP) | {site_antes['ok']} ({site_antes['http_code']}) / {site_depois['ok']} ({site_depois['http_code']}) |",
          f"| site durante (sondas / falhas) | {len(durante)} / {len(falhas_durante)} |",
          f"| rede de saída | {rede_org} |",
          f"| código de saída | {proc.returncode} |", ""]
    print("\n".join(md))
    gh = env.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")

    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
