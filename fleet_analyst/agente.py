"""Agente text-to-SQL: pergunta em português -> SQL -> resultado -> resposta.

Fluxo de cada pergunta:
1. O LLM recebe o esquema da base e a pergunta, e devolve um JSON com o SQL e a sugestão de gráfico.
2. O SQL passa pelas travas (seguranca.validar_sql) e roda no DuckDB em modo somente leitura.
3. Se der erro, o erro volta para o LLM UMA vez, para ele corrigir (autocorreção).
4. Com o resultado em mãos, o LLM escreve uma conclusão curta em português.

Qualquer provedor com API compatível com a da OpenAI funciona (DeepSeek, Groq, Gemini, OpenAI...).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import duckdb
import pandas as pd

from .dados import DATA_REFERENCIA, criar_base
from .seguranca import SQLRecusado, validar_sql

ESQUEMA = f"""
Base fictícia de uma locadora de motos para entregadores. "Hoje" na base é {DATA_REFERENCIA} (use essa data, nunca current_date).

filiais(filial_id INT, nome TEXT, cidade TEXT, uf TEXT, regiao TEXT)
parceiros(parceiro_id INT, nome TEXT, uf TEXT, ativo BOOL)  -- empresas terceirizadas que fazem recolhimentos
veiculos(veiculo_id INT, placa TEXT, modelo TEXT, ano INT, filial_id INT, status TEXT)
    -- status: 'alugado', 'disponível', 'manutenção', 'em recolhimento'
contratos(contrato_id INT, veiculo_id INT, filial_id INT, cliente_id INT, plano TEXT, valor_semanal DOUBLE,
          data_inicio DATE, data_fim DATE, status TEXT)
    -- plano: 'Semanal', 'Mensal', 'Compra programada'; status: 'ativo', 'encerrado', 'inadimplente'; data_fim NULL se ativo
cobrancas(cobranca_id INT, contrato_id INT, vencimento DATE, valor DOUBLE, data_pagamento DATE)
    -- uma cobrança por semana; data_pagamento NULL = não paga; pago em atraso se data_pagamento > vencimento
recolhimentos(recolhimento_id INT, veiculo_id INT, contrato_id INT, filial_id INT, parceiro_id INT,
              motivo TEXT, data_solicitacao DATE, data_conclusao DATE, prazo_dias INT,
              distancia_km DOUBLE, custo DOUBLE, status TEXT)
    -- motivo: 'inadimplência', 'contrato encerrado sem devolução', 'sinistro'
    -- status: 'concluído', 'em andamento', 'cancelado'; parceiro_id NULL = feito pela equipe própria
vw_recolhimentos = recolhimentos + colunas calculadas:
    dias_em_aberto INT  -- dias entre a solicitação e a conclusão (ou até hoje, se não concluído)
    atrasado BOOL       -- passou do prazo_dias (cancelados nunca contam como atrasados)
    responsavel TEXT    -- 'equipe própria' ou 'parceiro'
"""

PROMPT_SQL = f"""Você é um analista de dados de operações de frota. Converta a pergunta em UMA consulta SQL (dialeto DuckDB).

{ESQUEMA}
Regras:
- Use somente as tabelas acima. Para perguntas sobre atraso ou tempo de recolhimento, prefira vw_recolhimentos.
- Só SELECT (ou WITH ... SELECT). Nunca altere dados.
- Dê nomes de coluna claros em português com aliases (ex.: AS filial, AS recolhimentos_atrasados).
- Percentuais de 0 a 100 com 1 casa decimal (round(..., 1)). Valores em R$ com 2 casas.
- Ordene o resultado de forma útil para quem lê e limite a 50 linhas, salvo se pedirem tudo.
- Se a pergunta não puder ser respondida com esses dados, devolva "sql": null e explique em "erro".

Responda SOMENTE com um JSON, sem texto fora dele:
{{"sql": "...", "grafico": {{"tipo": "barra" | "linha" | "nenhum", "x": "<coluna>", "y": "<coluna>"}}, "erro": null}}
"""

PROMPT_RESUMO = """Você é um analista de operações. Em no máximo 2 frases em português, responda à pergunta
com base no resultado abaixo, citando os números principais. Não invente nada que não esteja no resultado."""


class ClienteLLM(Protocol):
    def __call__(self, sistema: str, usuario: str) -> str: ...


def cliente_openai(api_key: str, base_url: str, modelo: str) -> ClienteLLM:
    """Cria a função que chama o LLM. Funciona com qualquer API compatível com a da OpenAI."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)

    def chamar(sistema: str, usuario: str) -> str:
        r = client.chat.completions.create(
            model=modelo,
            temperature=0,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        )
        return r.choices[0].message.content or ""

    return chamar


@dataclass
class Resposta:
    pergunta: str
    sql: str | None = None
    dados: pd.DataFrame | None = None
    grafico: dict = field(default_factory=dict)
    conclusao: str = ""
    erro: str | None = None
    tentativas: int = 0
    segundos: float = 0.0


def _extrair_json(texto: str) -> dict:
    """O LLM às vezes embrulha o JSON em ```json ... ```; isso tira o embrulho."""
    texto = texto.strip()
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        raise ValueError("O modelo não devolveu JSON.")
    return json.loads(m.group(0))


class AgenteFrota:
    def __init__(self, llm: ClienteLLM, caminho_base: str | Path = "data/frota.duckdb", gerar_resumo: bool = True):
        caminho_base = Path(caminho_base)
        if not caminho_base.exists():
            criar_base(caminho_base)
        self.llm = llm
        self.gerar_resumo = gerar_resumo
        # Somente leitura e sem acesso a arquivos/internet: segunda camada de proteção
        self.con = duckdb.connect(str(caminho_base), read_only=True, config={"enable_external_access": False})

    def executar_sql(self, sql: str) -> pd.DataFrame:
        # Um cursor por consulta: o app atende várias pessoas ao mesmo tempo
        return self.con.cursor().execute(validar_sql(sql)).df()

    def perguntar(self, pergunta: str) -> Resposta:
        inicio = time.perf_counter()
        resp = Resposta(pergunta=pergunta)
        mensagem = f"Pergunta: {pergunta}"
        for tentativa in (1, 2):
            resp.tentativas = tentativa
            try:
                saida = _extrair_json(self.llm(PROMPT_SQL, mensagem))
            except (ValueError, json.JSONDecodeError) as e:
                resp.erro = f"Resposta do modelo em formato inesperado: {e}"
                continue
            if not saida.get("sql"):
                resp.erro = saida.get("erro") or "O modelo não conseguiu gerar uma consulta para essa pergunta."
                break
            resp.sql = saida["sql"]
            resp.grafico = saida.get("grafico") or {}
            try:
                resp.dados = self.executar_sql(resp.sql)
                resp.erro = None
                break
            except SQLRecusado as e:
                resp.erro = f"Consulta bloqueada pelas travas de segurança: {e}"
                break  # não tenta de novo: travas não são negociáveis
            except duckdb.Error as e:
                resp.erro = f"Erro ao executar o SQL: {e}"
                mensagem = (
                    f"Pergunta: {pergunta}\n\nSua consulta anterior:\n{resp.sql}\n\n"
                    f"deu este erro no DuckDB:\n{e}\n\nCorrija e devolva o JSON no mesmo formato."
                )

        if resp.dados is not None and self.gerar_resumo:
            amostra = resp.dados.head(20).to_csv(index=False)
            try:
                resp.conclusao = self.llm(PROMPT_RESUMO, f"Pergunta: {pergunta}\n\nResultado (CSV):\n{amostra}").strip()
            except Exception:  # o resumo é opcional; a tabela já responde
                resp.conclusao = ""
        resp.segundos = round(time.perf_counter() - inicio, 2)
        return resp
