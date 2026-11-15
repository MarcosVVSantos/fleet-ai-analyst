"""Roda o eval: as 20 perguntas em um ou mais modelos, e gera evals/resultados.md.

Uso (com as variáveis no .env ou no terminal):
    python -m evals.rodar_eval                 # modelo definido em LLM_MODEL
    python -m evals.rodar_eval deepseek-chat llama-3.3-70b-versatile   # compara modelos

Para comparar modelos de provedores diferentes, defina por modelo:
    LLM_BASE_URL__<MODELO> e LLM_API_KEY__<MODELO>   (nome do modelo em maiúsculas, com _ no lugar de - . /)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from fleet_analyst.agente import AgenteFrota, cliente_openai
from fleet_analyst.avaliacao import carregar_perguntas, resultados_equivalentes

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "data" / "frota.duckdb"


def _carregar_env() -> None:
    env = RAIZ / ".env"
    if env.exists():
        for linha in env.read_text().splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _config(modelo: str) -> tuple[str, str]:
    sufixo = "".join(c if c.isalnum() else "_" for c in modelo).upper()
    base_url = os.getenv(f"LLM_BASE_URL__{sufixo}", os.getenv("LLM_BASE_URL", "https://api.deepseek.com"))
    api_key = os.getenv(f"LLM_API_KEY__{sufixo}", os.getenv("LLM_API_KEY", ""))
    if not api_key:
        sys.exit(f"Sem chave de API para {modelo}. Defina LLM_API_KEY (veja .env.example).")
    return base_url, api_key


def avaliar(modelo: str, perguntas: list[dict]) -> list[dict]:
    base_url, api_key = _config(modelo)
    agente = AgenteFrota(cliente_openai(api_key, base_url, modelo), BASE, gerar_resumo=False)
    linhas = []
    for p in perguntas:
        esperado = agente.executar_sql(p["sql"])
        r = agente.perguntar(p["pergunta"])
        acertou = r.dados is not None and resultados_equivalentes(r.dados, esperado)
        linhas.append({"id": p["id"], "pergunta": p["pergunta"], "acertou": acertou,
                       "segundos": r.segundos, "tentativas": r.tentativas, "erro": r.erro or "",
                       "sql_gerado": r.sql or "", "sql_referencia": p["sql"].strip(),
                       "obtido": r.dados.head(5).to_markdown(index=False) if r.dados is not None else "",
                       "obtido_linhas": 0 if r.dados is None else len(r.dados),
                       "esperado": esperado.head(5).to_markdown(index=False), "esperado_linhas": len(esperado)})
        print(f"[{modelo}] {p['id']:>2} {'✅' if acertou else '❌'} {r.segundos:>5.1f}s  {p['pergunta']}")
    return linhas


def main() -> None:
    _carregar_env()
    modelos = sys.argv[1:] or [os.getenv("LLM_MODEL", "deepseek-chat")]
    perguntas = carregar_perguntas()
    resultados = {m: avaliar(m, perguntas) for m in modelos}

    md = [f"# Resultados do eval ({datetime.now():%d/%m/%Y})", "",
          f"{len(perguntas)} perguntas em português sobre a base fictícia de frota. "
          "Acerto = o resultado da consulta gerada é igual ao da consulta de referência.", "",
          "| Modelo | Acertos | Tempo médio por pergunta | Perguntas que precisaram de autocorreção |",
          "|---|---|---|---|"]
    for m, linhas in resultados.items():
        acertos = sum(l["acertou"] for l in linhas)
        tempo = sum(l["segundos"] for l in linhas) / len(linhas)
        retries = sum(l["tentativas"] > 1 for l in linhas)
        md.append(f"| {m} | {acertos}/{len(linhas)} ({100 * acertos / len(linhas):.0f}%) | {tempo:.1f} s | {retries} |")
    md += ["", "## Detalhe por pergunta", "", "| # | Pergunta | " + " | ".join(modelos) + " |",
           "|---|---|" + "---|" * len(modelos)]
    for i, p in enumerate(perguntas):
        marcas = " | ".join("✅" if resultados[m][i]["acertou"] else "❌" for m in modelos)
        md.append(f"| {p['id']} | {p['pergunta']} | {marcas} |")
    # Detalhe dos erros: é o que mostra se o problema está no agente, na pergunta ou no eval
    for m, linhas in resultados.items():
        erros = [l for l in linhas if not l["acertou"]]
        det = [f"# Erros do eval: {m}", ""]
        for l in erros:
            det += [f"## {l['id']}. {l['pergunta']}", "",
                    f"Erro: {l['erro'] or '-'} · Tentativas: {l['tentativas']}", "",
                    "**SQL gerado**", "```sql", l["sql_gerado"], "```",
                    f"**Resultado obtido** ({l['obtido_linhas']} linhas, 5 primeiras)", "", l["obtido"], "",
                    "**SQL de referência**", "```sql", l["sql_referencia"], "```",
                    f"**Resultado esperado** ({l['esperado_linhas']} linhas, 5 primeiras)", "", l["esperado"], ""]
        nome = "".join(c if c.isalnum() else "_" for c in m)
        (RAIZ / "evals" / f"erros_{nome}.md").write_text("\n".join(det), encoding="utf-8")

    destino = RAIZ / "evals" / "resultados.md"
    destino.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nRelatório salvo em {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
