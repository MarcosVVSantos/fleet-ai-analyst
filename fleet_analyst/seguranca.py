"""Travas de segurança: só deixa rodar UMA consulta de leitura, nas tabelas conhecidas.

O LLM pode errar (ou alguém pode tentar enganá-lo com a pergunta). Por isso o SQL
gerado nunca é executado direto: antes ele passa por esta validação, que lê o SQL
como uma árvore (com o sqlglot) em vez de procurar palavras com regex.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

TABELAS_PERMITIDAS = {"filiais", "parceiros", "veiculos", "contratos", "cobrancas", "recolhimentos", "vw_recolhimentos"}
LIMITE_LINHAS = 500

# Comandos que alteram dados ou acessam o sistema
_PROIBIDOS = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Command, exp.Merge, exp.Copy, exp.Attach, exp.Detach, exp.Pragma, exp.Set,
)


class SQLRecusado(ValueError):
    """O SQL gerado não passou nas travas."""


def validar_sql(sql: str) -> str:
    """Retorna o SQL normalizado (com LIMIT) ou levanta SQLRecusado."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise SQLRecusado("SQL vazio.")
    try:
        comandos = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as e:
        raise SQLRecusado(f"SQL inválido: {e}") from e
    if len(comandos) != 1 or comandos[0] is None:
        raise SQLRecusado("Só é permitido um comando por vez.")
    arvore = comandos[0]

    if not isinstance(arvore, exp.Query):
        raise SQLRecusado("Só consultas de leitura (SELECT) são permitidas.")
    for no in arvore.walk():
        if isinstance(no, _PROIBIDOS):
            raise SQLRecusado(f"Comando não permitido: {type(no).__name__}.")

    ctes = {c.alias_or_name.lower() for c in arvore.find_all(exp.CTE)}
    for tabela in arvore.find_all(exp.Table):
        # Funções no lugar de tabela (ex.: read_csv('/etc/passwd')) são bloqueadas
        if not isinstance(tabela.this, exp.Identifier):
            raise SQLRecusado("Funções no lugar de tabelas (como read_csv) não são permitidas.")
        nome = tabela.name.lower()
        if tabela.db or tabela.catalog:
            raise SQLRecusado(f"Tabela fora da base: {tabela.sql()}.")
        if nome not in TABELAS_PERMITIDAS and nome not in ctes:
            raise SQLRecusado(f"Tabela desconhecida: {nome}.")

    if isinstance(arvore, exp.Select) and arvore.args.get("limit") is None:
        arvore = arvore.limit(LIMITE_LINHAS)
    return arvore.sql(dialect="duckdb")
