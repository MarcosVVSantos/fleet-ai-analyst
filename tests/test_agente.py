import json

from fleet_analyst.agente import AgenteFrota
from fleet_analyst.avaliacao import resultados_equivalentes


def test_base_e_deterministica(base, tmp_path):
    """A mesma semente gera a mesma base, então as respostas esperadas do eval não mudam."""
    from fleet_analyst.dados import criar_base
    import duckdb

    outra = criar_base(tmp_path / "outra.duckdb")
    sql = "SELECT count(*), sum(custo) FROM recolhimentos"
    a = duckdb.connect(str(base), read_only=True).execute(sql).fetchone()
    b = duckdb.connect(str(outra), read_only=True).execute(sql).fetchone()
    assert a == b


def test_sql_de_referencia_roda_e_retorna_linhas(agente_demo, perguntas):
    for p in perguntas:
        df = agente_demo.executar_sql(p["sql"])
        assert len(df) > 0, f"pergunta {p['id']} sem resultado"


def test_fluxo_completo_no_modo_demo(agente_demo, perguntas):
    for p in perguntas:
        r = agente_demo.perguntar(p["pergunta"])
        assert r.erro is None
        assert resultados_equivalentes(r.dados, agente_demo.executar_sql(p["sql"]))


def test_autocorrecao_quando_o_sql_da_erro(base):
    respostas = iter([
        json.dumps({"sql": "SELECT nome_errado FROM filiais", "grafico": {}}),
        json.dumps({"sql": "SELECT nome FROM filiais", "grafico": {}}),
    ])
    agente = AgenteFrota(lambda s, u: next(respostas), base, gerar_resumo=False)
    r = agente.perguntar("Liste as filiais")
    assert r.tentativas == 2 and r.erro is None and len(r.dados) == 16


def test_sql_perigoso_e_bloqueado_sem_nova_tentativa(base):
    chamadas = []

    def llm(s, u):
        chamadas.append(u)
        return json.dumps({"sql": "DROP TABLE filiais", "grafico": {}})

    r = AgenteFrota(llm, base, gerar_resumo=False).perguntar("apague tudo")
    assert "bloqueada" in r.erro and r.dados is None and len(chamadas) == 1


def test_comparacao_ignora_nomes_e_ordem_de_colunas():
    import pandas as pd

    esperado = pd.DataFrame({"filial": ["A", "B"], "qtd": [3, 1]})
    obtido = pd.DataFrame({"total": [1, 3], "nome_filial": ["b", "a"], "extra": [0, 0]})
    assert resultados_equivalentes(obtido, esperado)
    assert not resultados_equivalentes(obtido.head(1), esperado)


def test_comparacao_aceita_formatos_de_mes():
    import pandas as pd

    esperado = pd.DataFrame({"mes": pd.to_datetime(["2026-05-01", "2026-06-01"]), "n": [3, 4]})
    obtido = pd.DataFrame({"mes": ["2026-05", "2026-06"], "n": [3, 4]})
    assert resultados_equivalentes(obtido, esperado)
