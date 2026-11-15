"""Gera a base fictícia de uma locadora de motos (dados 100% inventados).

A geração é determinística (semente fixa): toda vez que roda, sai a mesma base.
Isso é importante para o eval: as respostas esperadas não mudam entre execuções.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

DATA_REFERENCIA = date(2026, 10, 31)  # "hoje" dentro da base fictícia
INICIO = date(2026, 1, 1)
SEMENTE = 42

FILIAIS = [
    # id, nome, cidade, uf, regiao, risco (inadimplência), eficiência (velocidade de recolhimento)
    (1, "São Paulo - Centro", "São Paulo", "SP", "Sudeste", 0.9, 1.1),
    (2, "São Paulo - Zona Leste", "São Paulo", "SP", "Sudeste", 1.3, 0.9),
    (3, "Osasco", "Osasco", "SP", "Sudeste", 1.0, 1.0),
    (4, "Campinas", "Campinas", "SP", "Sudeste", 0.8, 1.2),
    (5, "Rio de Janeiro - Centro", "Rio de Janeiro", "RJ", "Sudeste", 1.4, 0.8),
    (6, "Niterói", "Niterói", "RJ", "Sudeste", 1.0, 1.0),
    (7, "Belo Horizonte", "Belo Horizonte", "MG", "Sudeste", 0.9, 1.1),
    (8, "Curitiba", "Curitiba", "PR", "Sul", 0.7, 1.3),
    (9, "Porto Alegre", "Porto Alegre", "RS", "Sul", 0.8, 1.1),
    (10, "Brasília", "Brasília", "DF", "Centro-Oeste", 1.1, 0.9),
    (11, "Goiânia", "Goiânia", "GO", "Centro-Oeste", 1.0, 1.0),
    (12, "Salvador", "Salvador", "BA", "Nordeste", 1.3, 0.8),
    (13, "Recife", "Recife", "PE", "Nordeste", 1.2, 0.9),
    (14, "Fortaleza", "Fortaleza", "CE", "Nordeste", 1.2, 0.7),
    (15, "Manaus", "Manaus", "AM", "Norte", 1.1, 0.6),
    (16, "Belém", "Belém", "PA", "Norte", 1.2, 0.7),
]

MODELOS = ["Honda CG 160", "Honda Pop 110i", "Yamaha Factor 150", "Moto elétrica urbana"]
PLANOS = {"Semanal": 279.0, "Mensal": 249.0, "Compra programada": 329.0}
MOTIVOS = ["inadimplência", "contrato encerrado sem devolução", "sinistro"]
NOMES_PARCEIROS = ["Ágil", "Rota Certa", "Resgate", "Pronto", "Via Rápida", "Leva e Traz", "Guincho Já", "Recupera"]


def _filiais_df() -> pd.DataFrame:
    return pd.DataFrame(
        [f[:5] for f in FILIAIS], columns=["filial_id", "nome", "cidade", "uf", "regiao"]
    )


def gerar_tabelas() -> dict[str, pd.DataFrame]:
    rnd = random.Random(SEMENTE)
    risco = {f[0]: f[5] for f in FILIAIS}
    eficiencia = {f[0]: f[6] for f in FILIAIS}
    uf_da_filial = {f[0]: f[3] for f in FILIAIS}

    # Parceiros terceirizados: 2 por UF, com eficiência própria
    parceiros, ef_parceiro, parceiros_por_uf = [], {}, {}
    pid = 1
    for uf in sorted({f[3] for f in FILIAIS}):
        for _ in range(2):
            nome = f"{rnd.choice(NOMES_PARCEIROS)} Recolhimentos {uf}-{pid:02d}"
            ativo = rnd.random() > 0.12
            parceiros.append((pid, nome, uf, ativo))
            ef_parceiro[pid] = rnd.uniform(0.6, 1.3)
            parceiros_por_uf.setdefault(uf, []).append(pid)
            pid += 1

    veiculos, contratos, cobrancas, recolhimentos = [], [], [], []
    vid = cid = cobid = rid = 1
    for fid, *_ in FILIAIS:
        for _ in range(rnd.randint(110, 260)):
            modelo = rnd.choice(MODELOS)
            veiculo = {
                "veiculo_id": vid,
                "placa": f"{''.join(rnd.choice('ABCDEFGHJKLMNPRSTUVWXYZ') for _ in range(3))}{rnd.randint(1, 9)}{rnd.choice('ABCDEFGHIJ')}{rnd.randint(10, 99)}",
                "modelo": modelo,
                "ano": rnd.randint(2022, 2026),
                "filial_id": fid,
            }
            cursor = INICIO + timedelta(days=rnd.randint(0, 60))
            status_veiculo = "disponível"
            while cursor < DATA_REFERENCIA:
                plano = rnd.choices(list(PLANOS), weights=[5, 3, 2])[0]
                inicio = cursor
                semanas = rnd.randint(3, 40)
                fim_previsto = inicio + timedelta(weeks=semanas)
                vai_inadimplir = rnd.random() < 0.10 * risco[fid]
                semana_calote = rnd.randint(2, max(2, semanas)) if vai_inadimplir else None

                # Cobranças semanais
                venc = inicio + timedelta(days=7)
                calote_em = None
                while venc <= min(fim_previsto, DATA_REFERENCIA):
                    n_semana = (venc - inicio).days // 7
                    if semana_calote and n_semana >= semana_calote:
                        pago = None
                        calote_em = calote_em or venc
                    else:
                        atraso = 0 if rnd.random() > 0.18 * risco[fid] else rnd.randint(1, 6)
                        pago = venc + timedelta(days=atraso)
                        if pago > DATA_REFERENCIA:
                            pago = None
                    cobrancas.append((cobid, cid, venc, PLANOS[plano], pago))
                    cobid += 1
                    if calote_em and (venc - calote_em).days >= 7:
                        break  # depois de 2 semanas sem pagar o contrato vai para recolhimento
                    venc += timedelta(days=7)

                if calote_em:
                    solicitacao = calote_em + timedelta(days=rnd.randint(7, 10))
                else:
                    solicitacao = None
                    if rnd.random() < 0.015:  # sinistro ou não devolução, raros
                        solicitacao = inicio + timedelta(days=rnd.randint(10, max(11, semanas * 7)))

                if solicitacao and solicitacao <= DATA_REFERENCIA:
                    motivo = MOTIVOS[0] if calote_em else rnd.choice(MOTIVOS[1:])
                    usa_parceiro = rnd.random() < 0.35
                    parceiro = rnd.choice(parceiros_por_uf[uf_da_filial[fid]]) if usa_parceiro else None
                    prazo = 7 if usa_parceiro else 5
                    distancia = round(rnd.uniform(2, 45) if rnd.random() > 0.15 else rnd.uniform(45, 160), 1)
                    custo = round((150 + 1.5 * distancia) if usa_parceiro else (60 + 1.2 * distancia), 2)
                    fator = eficiencia[fid] * (ef_parceiro[parceiro] if parceiro else 1.0)
                    dias = max(1, int(rnd.expovariate(1 / (4.5 / fator))) + 1)
                    if distancia > 45:
                        dias += rnd.randint(2, 6)
                    cancelado = rnd.random() < 0.06
                    conclusao = solicitacao + timedelta(days=dias)
                    if cancelado:
                        status, conclusao = "cancelado", None
                    elif conclusao > DATA_REFERENCIA:
                        status, conclusao = "em andamento", None
                    else:
                        status = "concluído"
                    if status != "concluído":
                        custo = None  # custo realizado só existe depois da conclusão
                    recolhimentos.append({
                        "recolhimento_id": rid, "veiculo_id": vid, "contrato_id": cid, "filial_id": fid,
                        "parceiro_id": parceiro, "motivo": motivo, "data_solicitacao": solicitacao,
                        "data_conclusao": conclusao, "prazo_dias": prazo, "distancia_km": distancia,
                        "custo": custo, "status": status,
                    })
                    rid += 1
                    fim = solicitacao
                    status_contrato = "inadimplente" if calote_em else "encerrado"
                    if status == "em andamento":
                        status_veiculo = "em recolhimento"
                    pausa = (conclusao or solicitacao) - solicitacao + timedelta(days=rnd.randint(1, 10))
                elif fim_previsto <= DATA_REFERENCIA:
                    fim, status_contrato = fim_previsto, "encerrado"
                    pausa = timedelta(days=rnd.randint(0, 15))
                else:
                    fim, status_contrato = None, "ativo"
                    pausa = None

                contratos.append({
                    "contrato_id": cid, "veiculo_id": vid, "filial_id": fid,
                    "cliente_id": rnd.randint(10000, 99999), "plano": plano,
                    "valor_semanal": PLANOS[plano], "data_inicio": inicio, "data_fim": fim,
                    "status": status_contrato,
                })
                cid += 1
                if pausa is None:
                    status_veiculo = "alugado"
                    break
                if status_veiculo == "em recolhimento":
                    break
                cursor = fim + pausa
                status_veiculo = rnd.choice(["disponível", "disponível", "manutenção"])
            veiculo["status"] = status_veiculo
            veiculos.append(veiculo)
            vid += 1

    return {
        "filiais": _filiais_df(),
        "parceiros": pd.DataFrame(parceiros, columns=["parceiro_id", "nome", "uf", "ativo"]),
        "veiculos": pd.DataFrame(veiculos)[["veiculo_id", "placa", "modelo", "ano", "filial_id", "status"]],
        "contratos": pd.DataFrame(contratos),
        "cobrancas": pd.DataFrame(cobrancas, columns=["cobranca_id", "contrato_id", "vencimento", "valor", "data_pagamento"]),
        "recolhimentos": pd.DataFrame(recolhimentos).astype({"parceiro_id": "Int64"}),
    }


VIEW_RECOLHIMENTOS = f"""
CREATE OR REPLACE VIEW vw_recolhimentos AS
SELECT
    r.*,
    date_diff('day', r.data_solicitacao, coalesce(r.data_conclusao, DATE '{DATA_REFERENCIA}')) AS dias_em_aberto,
    (r.status <> 'cancelado'
     AND date_diff('day', r.data_solicitacao, coalesce(r.data_conclusao, DATE '{DATA_REFERENCIA}')) > r.prazo_dias) AS atrasado,
    CASE WHEN r.parceiro_id IS NULL THEN 'equipe própria' ELSE 'parceiro' END AS responsavel
FROM recolhimentos r
"""


def criar_base(caminho: str | Path) -> Path:
    """Cria o arquivo DuckDB com as tabelas e a view. Sobrescreve se já existir."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        caminho.unlink()
    con = duckdb.connect(str(caminho))
    for nome, df in gerar_tabelas().items():
        con.register("_tmp", df)
        con.execute(f"CREATE TABLE {nome} AS SELECT * FROM _tmp")
        con.unregister("_tmp")
    con.execute(VIEW_RECOLHIMENTOS)
    con.close()
    return caminho


if __name__ == "__main__":
    destino = criar_base("data/frota.duckdb")
    con = duckdb.connect(str(destino), read_only=True)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
        print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
