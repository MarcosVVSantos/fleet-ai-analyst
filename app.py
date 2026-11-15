"""Interface Streamlit do Fleet AI Analyst. Rodar com: streamlit run app.py"""
from __future__ import annotations

import os

import altair as alt
import pandas as pd
import streamlit as st

from fleet_analyst.agente import ESQUEMA, AgenteFrota, Resposta, cliente_openai
from fleet_analyst.avaliacao import LLMDemonstracao, carregar_perguntas

MAX_PERGUNTAS = 15  # por sessão, para a demo pública não estourar o custo da API
EXEMPLOS = [p["pergunta"] for p in carregar_perguntas()[:6]]

st.set_page_config(page_title="Fleet AI Analyst", page_icon="🏍️", layout="wide")


def _segredo(nome: str, padrao: str = "") -> str:
    try:
        return st.secrets.get(nome, os.getenv(nome, padrao))
    except FileNotFoundError:  # sem .streamlit/secrets.toml
        return os.getenv(nome, padrao)


@st.cache_resource
def carregar_agente() -> tuple[AgenteFrota, bool]:
    chave = _segredo("LLM_API_KEY")
    if chave:
        llm = cliente_openai(chave, _segredo("LLM_BASE_URL", "https://api.deepseek.com"), _segredo("LLM_MODEL", "deepseek-chat"))
        return AgenteFrota(llm), False
    return AgenteFrota(LLMDemonstracao(), gerar_resumo=False), True


def desenhar_grafico(r: Resposta) -> None:
    df, g = r.dados, r.grafico or {}
    if df is None or df.empty or len(df.columns) < 2 or g.get("tipo") in (None, "nenhum"):
        return
    x = g.get("x") if g.get("x") in df.columns else df.columns[0]
    numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != x]
    y = g.get("y") if g.get("y") in numericas else (numericas[-1] if numericas else None)
    if y is None or len(df) < 2:
        return
    if g.get("tipo") == "linha" or pd.api.types.is_datetime64_any_dtype(df[x]):
        grafico = alt.Chart(df).mark_line(point=True).encode(x=alt.X(x, title=x), y=alt.Y(y, title=y))
    else:
        grafico = alt.Chart(df.head(25)).mark_bar().encode(
            y=alt.Y(f"{x}:N", sort="-x", title=x), x=alt.X(y, title=y), tooltip=list(df.columns)
        )
    st.altair_chart(grafico, width="stretch")


def mostrar(r: Resposta) -> None:
    if r.erro:
        st.error(r.erro)
    if r.conclusao:
        st.markdown(f"**{r.conclusao}**")
    if r.dados is not None:
        desenhar_grafico(r)
        st.dataframe(r.dados, width="stretch", hide_index=True)
    if r.sql:
        with st.expander("Ver o SQL gerado"):
            st.code(r.sql, language="sql")
    st.caption(f"{r.segundos:.1f} s · {r.tentativas} tentativa(s)")


agente, modo_demo = carregar_agente()
st.session_state.setdefault("historico", [])
st.session_state.setdefault("usadas", 0)

with st.sidebar:
    st.header("Sobre")
    st.markdown(
        "Agente de IA que responde perguntas sobre a operação de uma locadora de motos: "
        "gera o SQL, valida, executa e explica o resultado.\n\n"
        "**Todos os dados são fictícios.**\n\n"
        "[Código no GitHub](https://github.com/MarcosVVSantos/fleet-ai-analyst) · "
        "Feito por [Marcos Vinicio](https://www.linkedin.com/in/marcos-v-v-santos)"
    )
    with st.expander("Tabelas disponíveis"):
        st.code(ESQUEMA.strip(), language="text")
    st.caption(f"Perguntas nesta sessão: {st.session_state.usadas}/{MAX_PERGUNTAS}")

st.title("🏍️ Fleet AI Analyst")
st.write("Pergunte em português sobre recolhimentos, inadimplência, frota e parceiros.")
if modo_demo:
    st.info("Modo demonstração (sem chave de API): só as perguntas de exemplo abaixo funcionam.")

st.write("**Experimente:**")
colunas = st.columns(3)
clicada = None
for i, exemplo in enumerate(EXEMPLOS):
    if colunas[i % 3].button(exemplo, width="stretch", key=f"ex{i}"):
        clicada = exemplo

for item in st.session_state.historico:
    with st.chat_message("user"):
        st.write(item.pergunta)
    with st.chat_message("assistant"):
        mostrar(item)

pergunta = st.chat_input("Ex.: Qual filial tem o maior custo médio de recolhimento?") or clicada
if pergunta:
    with st.chat_message("user"):
        st.write(pergunta)
    with st.chat_message("assistant"):
        if st.session_state.usadas >= MAX_PERGUNTAS:
            st.warning("Limite de perguntas desta demonstração atingido. Recarregue a página mais tarde.")
        else:
            with st.spinner("Gerando e executando a consulta..."):
                resposta = agente.perguntar(pergunta)
            st.session_state.usadas += 1
            st.session_state.historico.append(resposta)
            mostrar(resposta)
