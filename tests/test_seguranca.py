import pytest

from fleet_analyst.seguranca import SQLRecusado, validar_sql

PERMITIDOS = [
    "SELECT * FROM filiais",
    "WITH t AS (SELECT filial_id FROM veiculos) SELECT count(*) FROM t",
    "SELECT f.nome, count(*) FROM vw_recolhimentos r JOIN filiais f USING (filial_id) GROUP BY 1",
]

BLOQUEADOS = [
    "DROP TABLE filiais",
    "DELETE FROM contratos",
    "UPDATE veiculos SET status = 'x'",
    "INSERT INTO filiais VALUES (99, 'x', 'x', 'x', 'x')",
    "SELECT 1; DROP TABLE filiais",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM information_schema.tables",
    "COPY filiais TO 'vazamento.csv'",
    "ATTACH 'outra.db'",
    "PRAGMA version",
    "SELECT * FROM tabela_que_nao_existe",
]


@pytest.mark.parametrize("sql", PERMITIDOS)
def test_permite_leitura(sql):
    assert validar_sql(sql).upper().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize("sql", BLOQUEADOS)
def test_bloqueia_o_resto(sql):
    with pytest.raises(SQLRecusado):
        validar_sql(sql)


def test_adiciona_limit():
    assert "LIMIT 500" in validar_sql("SELECT * FROM cobrancas")
