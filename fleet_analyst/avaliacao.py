"""Ferramentas do eval: carregar perguntas, comparar resultados e um LLM de demonstração."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_PERGUNTAS = RAIZ / "evals" / "perguntas.yaml"


def carregar_perguntas(caminho: Path = ARQUIVO_PERGUNTAS) -> list[dict]:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def _normalizar(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "∅"
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, (int, float)):
        return f"{round(float(valor), 1):.1f}"
    return str(valor).strip().lower()


def _contem_todos(linha: list[str], valores: list[str]) -> bool:
    """True se a linha tem todos os valores (respeitando repetições)."""
    restante = list(linha)
    for v in valores:
        if v not in restante:
            return False
        restante.remove(v)
    return True


def resultados_equivalentes(obtido: pd.DataFrame, esperado: pd.DataFrame) -> bool:
    """Compara o conteúdo, não o texto do SQL.

    Critério: mesmo número de linhas e, para cada linha esperada, existe uma linha obtida que contém
    todos os seus valores (números arredondados a 1 casa). Nomes de coluna, ordem das colunas e
    colunas extras não importam, porque há mais de um jeito certo de escrever a mesma resposta.
    """
    if len(obtido) != len(esperado):
        return False
    linhas_obtidas = [sorted(map(_normalizar, linha)) for linha in obtido.itertuples(index=False)]
    usadas: set[int] = set()
    for linha in esperado.itertuples(index=False):
        valores = list(map(_normalizar, linha))
        achou = False
        for i, cand in enumerate(linhas_obtidas):
            if i in usadas:
                continue
            if _contem_todos(cand, valores):
                usadas.add(i)
                achou = True
                break
        if not achou:
            return False
    return True


class LLMDemonstracao:
    """'LLM' falso que responde só as perguntas do eval com o SQL de referência.

    Serve para o app funcionar sem chave de API (modo demonstração) e para testar o
    fluxo inteiro do agente nos testes automatizados.
    """

    def __init__(self, perguntas: list[dict] | None = None):
        self.mapa = {p["pergunta"].strip().lower(): p["sql"] for p in (perguntas or carregar_perguntas())}

    def __call__(self, sistema: str, usuario: str) -> str:
        pergunta = usuario.split("\n", 1)[0].removeprefix("Pergunta:").strip().lower()
        sql = self.mapa.get(pergunta)
        if sql is None:
            return json.dumps({"sql": None, "grafico": {}, "erro": "No modo demonstração só as perguntas de exemplo funcionam."})
        return json.dumps({"sql": sql, "grafico": _grafico_padrao(sql), "erro": None})


def _grafico_padrao(sql: str) -> dict:
    return {"tipo": "linha" if "date_trunc" in sql else "barra"}
