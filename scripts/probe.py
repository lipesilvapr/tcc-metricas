#!/usr/bin/env python3
"""Sonda de rede: verifica como o site do estudo responde a partir de um runner do GitHub.

  python3 scripts/probe.py probe --out out         roda a sonda neste runner (usa curl)
  python3 scripts/probe.py summarize probes        junta as sondas de vários runners e compara

Registra, por requisição: código HTTP, tempo, tamanho, cabeçalhos principais, título e
trecho da página quando a resposta não é a esperada. Também registra o modelo da CPU e o
endereço/organização de rede de saída do runner. Apenas biblioteca padrão.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SITE = "https://automationexercise.com"
PATHS = ["/", "/login", "/api/productsList", "/api/brandsList"]
CHROME_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/130.0.0.0 Safari/537.36")
UAS = {"curl": None, "chrome": CHROME_UA}
REPEAT = 3
FIELDS = ["runner", "image_version", "cpu_modelo", "ip", "org", "ua", "url", "tentativa", "http_code", "tempo_s",
          "bytes", "content_type", "server", "cf_ray", "ok", "titulo", "trecho"]


def cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def curl(url, ua, tmp):
    body, hdr = os.path.join(tmp, "body"), os.path.join(tmp, "hdr")
    cmd = ["curl", "-s", "--max-time", "20", "-o", body, "-D", hdr,
           "-w", "%{http_code}|%{time_total}|%{size_download}|%{content_type}"]
    if ua:
        cmd += ["-A", ua]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, text=True)
    parts = (p.stdout.strip().split("|") + ["", "", "", ""])[:4]
    try:
        text = open(body, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    headers = {}
    try:
        for line in open(hdr, encoding="utf-8", errors="replace").read().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return parts, text, headers


def page_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    title = re.search(r"(?is)<title>(.*?)</title>", html)
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return (re.sub(r"\s+", " ", title.group(1)).strip() if title else ""), plain[:160]


def is_ok(path, code, text):
    if code != "200":
        return False
    if path.startswith("/api/"):
        try:
            return "responseCode" in json.loads(text)
        except Exception:
            return False
    return "automation" in text.lower()


def net_info(tmp):
    parts, text, _ = curl("https://ipinfo.io/json", None, tmp)
    try:
        d = json.loads(text)
        return d.get("ip", ""), d.get("org", "")
    except Exception:
        return "", ""


def cmd_probe(args):
    os.makedirs(args.out, exist_ok=True)
    env = os.environ
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        ip, org = net_info(tmp)
        base = {"runner": env.get("RUNNER_NAME", ""), "image_version": env.get("ImageVersion", ""),
                "cpu_modelo": cpu_model(), "ip": ip, "org": org}
        for ua_name, ua in UAS.items():
            for path in PATHS:
                for i in range(1, REPEAT + 1):
                    (code, t, size, ctype), text, h = curl(SITE + path, ua, tmp)
                    ok = is_ok(path, code, text)
                    title, snippet = ("", "") if ok else page_text(text)
                    rows.append(dict(base, ua=ua_name, url=path, tentativa=i, http_code=code, tempo_s=t, bytes=size,
                                     content_type=ctype, server=h.get("server", ""), cf_ray=h.get("cf-ray", ""),
                                     ok=int(ok), titulo=title, trecho=snippet))
                    time.sleep(1)
    with open(os.path.join(args.out, "probe.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    ok_n = sum(r["ok"] for r in rows)
    md = [f"### Sonda de rede: {base['runner']}", "",
          f"- CPU: {base['cpu_modelo']}", f"- imagem: {base['image_version']}",
          f"- rede de saída: {ip} ({org})", f"- respostas normais: {ok_n}/{len(rows)}", ""]
    print("\n".join(md))
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")
    return 0


def cmd_summarize(args):
    rows = []
    for path in sorted(glob.glob(os.path.join(args.dir, "**", "probe.csv"), recursive=True)):
        with open(path, newline="", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    if not rows:
        print("nenhum probe.csv encontrado")
        return 1
    with open(os.path.join(args.dir, "probe_all.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in FIELDS} for r in rows])
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["cpu_modelo"], r["org"])].append(r)
    md = ["## Comparação por tipo de máquina e rede de saída", "",
          "| CPU | rede de saída | runners | requisições | normais (curl) | normais (chrome) | códigos HTTP fora do normal |",
          "|---|---|---|---|---|---|---|"]
    for (cpu, org), rs in sorted(groups.items()):
        runners = len({r["runner"] for r in rs})

        def rate(ua):
            sub = [r for r in rs if r["ua"] == ua]
            return f"{sum(int(r['ok']) for r in sub)}/{len(sub)}" if sub else "-"
        codes = collections.Counter(r["http_code"] for r in rs if r["ok"] != "1")
        md.append(f"| {cpu} | {org} | {runners} | {len(rs)} | {rate('curl')} | {rate('chrome')} | "
                  f"{dict(codes) if codes else '-'} |")
    md += ["", "### Títulos e trechos das respostas fora do normal", ""]
    seen = set()
    for (cpu, org), rs in sorted(groups.items()):
        for r in rs:
            if r["ok"] != "1":
                key = (cpu, r["http_code"], r["titulo"], r["trecho"][:60])
                if key in seen:
                    continue
                seen.add(key)
                md.append(f"- **{cpu}** ({org}) {r['url']} [{r['ua']}] HTTP {r['http_code']}, "
                          f"título: `{r['titulo']}`, trecho: `{r['trecho']}`")
    out = "\n".join(md)
    print(out)
    with open(os.path.join(args.dir, "resumo.md"), "w", encoding="utf-8") as fh:
        fh.write(out)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(out + "\n")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--out", default="out")
    p.set_defaults(fn=cmd_probe)
    s = sub.add_parser("summarize")
    s.add_argument("dir")
    s.set_defaults(fn=cmd_summarize)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
