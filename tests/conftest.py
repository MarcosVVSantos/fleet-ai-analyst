import pytest

from fleet_analyst.agente import AgenteFrota
from fleet_analyst.avaliacao import LLMDemonstracao, carregar_perguntas
from fleet_analyst.dados import criar_base


@pytest.fixture(scope="session")
def base(tmp_path_factory):
    return criar_base(tmp_path_factory.mktemp("dados") / "frota.duckdb")


@pytest.fixture(scope="session")
def perguntas():
    return carregar_perguntas()


@pytest.fixture()
def agente_demo(base):
    return AgenteFrota(LLMDemonstracao(), base, gerar_resumo=False)
