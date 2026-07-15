from __future__ import annotations

import os
import json
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine import URL

APP_TITLE = "Auditorias de Seguranca do Trabalho e Meio Ambiente"
CLASSIFICACOES = ["S", "N", "NA"]
BASE_DIR = Path(__file__).parent
TEMPLATE_PATH = BASE_DIR / "auditoria_templates.json"
LOGO_URL = "https://blueskies.com/global/wp-content/uploads/sites/22/2017/06/retina-01-300x300.png"
AREAS_ANALISADAS = [
    "SELECAO",
    "RECEBIMENTO",
    "LOW RISK",
    "HIGH CARE",
    "RESIDUO",
    "ETIQUETA",
    "EXPEDICAO",
    "ALMOXARIFADO",
    "LAVANDERIA",
    "MANUTENCAO",
    "ETE / ETA",
    "ADMINISTRATIVOS",
]


@dataclass
class SheetTemplate:
    name: str
    departamento_cols: list[tuple[int, str]]
    itens: list[dict[str, Any]]


def get_db_url() -> str:
    # Prioriza chaves dedicadas AUDITORIA_DB_* para nao herdar configs globais de outros apps.
    secret_user = None
    secret_pass = None
    secret_host = None
    secret_port = None
    secret_db = None
    secret_url = None

    try:
        secret_user = st.secrets.get("AUDITORIA_DB_USER")
        secret_pass = st.secrets.get("AUDITORIA_DB_PASS")
        secret_host = st.secrets.get("AUDITORIA_DB_HOST")
        secret_port = st.secrets.get("AUDITORIA_DB_PORT")
        secret_db = st.secrets.get("AUDITORIA_DB_NAME")
        secret_url = st.secrets.get("AUDITORIA_DB_URL")
    except Exception:
        pass

    user = str(secret_user or os.getenv("AUDITORIA_DB_USER", "postgres"))
    password = str(secret_pass or os.getenv("AUDITORIA_DB_PASS", "AApgKSLEDBJzbYaMiNCGVaXcisiIXrII"))
    host = str(secret_host or os.getenv("AUDITORIA_DB_HOST", "tokaido.proxy.rlwy.net"))
    port = int(secret_port or os.getenv("AUDITORIA_DB_PORT", "27106"))
    database = str(secret_db or os.getenv("AUDITORIA_DB_NAME", "railway"))

    has_explicit_components = any(
        [
            secret_user,
            secret_pass,
            secret_host,
            secret_port,
            secret_db,
            os.getenv("AUDITORIA_DB_USER"),
            os.getenv("AUDITORIA_DB_PASS"),
            os.getenv("AUDITORIA_DB_HOST"),
            os.getenv("AUDITORIA_DB_PORT"),
            os.getenv("AUDITORIA_DB_NAME"),
        ]
    )

    # Se AUDITORIA_DB_URL estiver definido e nao houver componentes separados, usa fallback.
    db_url_env = os.getenv("AUDITORIA_DB_URL")
    db_url = str(secret_url or db_url_env or "").strip()
    if db_url and not has_explicit_components:
        return db_url.replace("postgres://", "postgresql://", 1)

    url = URL.create(
        drivername="postgresql+pg8000",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    return url.render_as_string(hide_password=False)


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    return create_engine(get_db_url(), pool_pre_ping=True)


def ensure_db_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS trusted"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trusted.tb_auditoria_form_tipo (
                    id BIGSERIAL PRIMARY KEY,
                    nome TEXT NOT NULL UNIQUE,
                    ativo BOOLEAN NOT NULL DEFAULT TRUE,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trusted.tb_auditoria_form_area (
                    id BIGSERIAL PRIMARY KEY,
                    nome TEXT NOT NULL UNIQUE,
                    ordem INTEGER NOT NULL,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trusted.tb_auditoria_form_tipo_area (
                    id BIGSERIAL PRIMARY KEY,
                    tipo_id BIGINT NOT NULL REFERENCES trusted.tb_auditoria_form_tipo(id) ON DELETE CASCADE,
                    area_id BIGINT NOT NULL REFERENCES trusted.tb_auditoria_form_area(id) ON DELETE CASCADE,
                    ordem INTEGER NOT NULL,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_tb_auditoria_form_tipo_area UNIQUE (tipo_id, area_id)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trusted.tb_auditoria_form_item_template (
                    id BIGSERIAL PRIMARY KEY,
                    tipo_id BIGINT NOT NULL REFERENCES trusted.tb_auditoria_form_tipo(id) ON DELETE CASCADE,
                    item_codigo TEXT NOT NULL,
                    referencia TEXT,
                    requisito TEXT,
                    ordem INTEGER NOT NULL,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_tb_auditoria_form_tipo_area_tipo
                ON trusted.tb_auditoria_form_tipo_area (tipo_id, ordem)
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_tb_auditoria_form_item_template_tipo
                ON trusted.tb_auditoria_form_item_template (tipo_id, ordem)
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trusted.tb_auditoria_form_analise (
                    id BIGSERIAL PRIMARY KEY,
                    tipo_auditoria TEXT NOT NULL,
                    numero_analise TEXT NOT NULL,
                    data_auditoria DATE NOT NULL,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_tb_auditoria_form_analise UNIQUE (tipo_auditoria, numero_analise, data_auditoria)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trusted.tb_auditoria_form_item (
                    id BIGSERIAL PRIMARY KEY,
                    analise_id BIGINT NOT NULL REFERENCES trusted.tb_auditoria_form_analise(id) ON DELETE CASCADE,
                    item TEXT NOT NULL,
                    referencia TEXT,
                    requisito TEXT,
                    departamento TEXT NOT NULL,
                    classificacao TEXT NOT NULL,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_tb_auditoria_form_item_classificacao CHECK (classificacao IN ('S', 'N', 'NA'))
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_tb_auditoria_form_item_analise_id
                ON trusted.tb_auditoria_form_item (analise_id)
                """
            )
        )


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def area_token(value: str) -> str:
    txt = normalize_text(value).upper()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return " ".join(txt.split())


AREA_TOKEN_MAP = {area_token(nome): nome for nome in AREAS_ANALISADAS}


def seed_templates_if_empty(engine: Engine) -> None:
    with engine.begin() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM trusted.tb_auditoria_form_item_template")
        ).scalar_one()
        if total > 0:
            return

        for idx, area in enumerate(AREAS_ANALISADAS, start=1):
            conn.execute(
                text(
                    """
                    INSERT INTO trusted.tb_auditoria_form_area (nome, ordem, atualizado_em)
                    VALUES (:nome, :ordem, NOW())
                    ON CONFLICT (nome)
                    DO UPDATE SET ordem = EXCLUDED.ordem, atualizado_em = NOW()
                    """
                ),
                {"nome": area, "ordem": idx},
            )

        if not TEMPLATE_PATH.exists():
            return

        raw = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        tipos = raw.get("tipos", [])

        for tipo in tipos:
            tipo_nome = normalize_text(tipo.get("name"))
            if not tipo_nome:
                continue

            tipo_id = conn.execute(
                text(
                    """
                    INSERT INTO trusted.tb_auditoria_form_tipo (nome, ativo, atualizado_em)
                    VALUES (:nome, TRUE, NOW())
                    ON CONFLICT (nome)
                    DO UPDATE SET ativo = TRUE, atualizado_em = NOW()
                    RETURNING id
                    """
                ),
                {"nome": tipo_nome},
            ).scalar_one()

            departamentos_raw = tipo.get("departamentos", [])
            deps: list[str] = []
            seen_dep: set[str] = set()
            for dep in departamentos_raw:
                canonical = AREA_TOKEN_MAP.get(area_token(dep))
                if canonical and canonical not in seen_dep:
                    deps.append(canonical)
                    seen_dep.add(canonical)

            if not deps:
                deps = AREAS_ANALISADAS.copy()

            for ordem, dep in enumerate(deps, start=1):
                area_id = conn.execute(
                    text("SELECT id FROM trusted.tb_auditoria_form_area WHERE nome = :nome"),
                    {"nome": dep},
                ).scalar_one()
                conn.execute(
                    text(
                        """
                        INSERT INTO trusted.tb_auditoria_form_tipo_area (tipo_id, area_id, ordem, atualizado_em)
                        VALUES (:tipo_id, :area_id, :ordem, NOW())
                        ON CONFLICT (tipo_id, area_id)
                        DO UPDATE SET ordem = EXCLUDED.ordem, atualizado_em = NOW()
                        """
                    ),
                    {"tipo_id": tipo_id, "area_id": area_id, "ordem": ordem},
                )

            conn.execute(
                text("DELETE FROM trusted.tb_auditoria_form_item_template WHERE tipo_id = :tipo_id"),
                {"tipo_id": tipo_id},
            )

            itens = tipo.get("itens", [])
            ordem_item = 1
            for item in itens:
                item_codigo = normalize_text(item.get("item"))
                requisito = normalize_text(item.get("requisito"))
                if not item_codigo and not requisito:
                    continue
                if not item_codigo:
                    continue

                conn.execute(
                    text(
                        """
                        INSERT INTO trusted.tb_auditoria_form_item_template
                        (tipo_id, item_codigo, referencia, requisito, ordem, atualizado_em)
                        VALUES (:tipo_id, :item_codigo, :referencia, :requisito, :ordem, NOW())
                        """
                    ),
                    {
                        "tipo_id": tipo_id,
                        "item_codigo": item_codigo,
                        "referencia": normalize_text(item.get("referencia")),
                        "requisito": requisito,
                        "ordem": ordem_item,
                    },
                )
                ordem_item += 1


def load_templates(engine: Engine) -> list[SheetTemplate]:
    tipos_df = pd.read_sql_query(
        text(
            """
            SELECT id, nome
            FROM trusted.tb_auditoria_form_tipo
            WHERE ativo = TRUE
            ORDER BY nome
            """
        ),
        engine,
    )

    templates: list[SheetTemplate] = []

    for _, tipo_row in tipos_df.iterrows():
        tipo_id = int(tipo_row["id"])
        tipo_nome = str(tipo_row["nome"])

        areas_df = pd.read_sql_query(
            text(
                """
                SELECT a.nome
                FROM trusted.tb_auditoria_form_tipo_area ta
                JOIN trusted.tb_auditoria_form_area a ON a.id = ta.area_id
                WHERE ta.tipo_id = :tipo_id
                ORDER BY ta.ordem, a.nome
                """
            ),
            engine,
            params={"tipo_id": tipo_id},
        )

        itens_df = pd.read_sql_query(
            text(
                """
                SELECT item_codigo, referencia, requisito
                FROM trusted.tb_auditoria_form_item_template
                WHERE tipo_id = :tipo_id
                ORDER BY ordem, id
                """
            ),
            engine,
            params={"tipo_id": tipo_id},
        )

        if itens_df.empty:
            continue

        departamentos: list[tuple[int, str]] = []
        idx = 1
        for _, area_row in areas_df.iterrows():
            canonical = AREA_TOKEN_MAP.get(area_token(area_row["nome"]))
            if canonical:
                departamentos.append((idx, canonical))
                idx += 1

        if not departamentos:
            for dep in AREAS_ANALISADAS:
                departamentos.append((idx, dep))
                idx += 1

        itens: list[dict[str, Any]] = []
        for _, item_row in itens_df.iterrows():
            item_codigo = normalize_text(item_row["item_codigo"])
            requisito = normalize_text(item_row["requisito"])
            if not item_codigo and not requisito:
                continue
            if not item_codigo:
                continue

            itens.append(
                {
                    "item": item_codigo,
                    "referencia": normalize_text(item_row["referencia"]),
                    "requisito": requisito,
                }
            )

        if itens:
            templates.append(
                SheetTemplate(
                    name=tipo_nome,
                    departamento_cols=departamentos,
                    itens=itens,
                )
            )

    return templates


def get_sheet_dataframe(template: SheetTemplate) -> pd.DataFrame:
    df = pd.DataFrame(template.itens)
    for _, dep_name in template.departamento_cols:
        if dep_name not in df.columns:
            df[dep_name] = ""
    for dep_name in AREAS_ANALISADAS:
        if dep_name not in df.columns:
            df[dep_name] = ""
    return df


def get_area_columns_from_df(df: pd.DataFrame) -> list[str]:
    cols = []
    for area in AREAS_ANALISADAS:
        if area in df.columns:
            cols.append(area)
    return cols


def list_analyses_by_type(engine: Engine, tipo_auditoria: str) -> pd.DataFrame:
    query = text(
        """
        SELECT
            a.id,
            a.numero_analise,
            a.data_auditoria,
            a.atualizado_em,
            COUNT(i.id) AS total_registros,
            SUM(CASE WHEN i.classificacao = 'S' THEN 1 ELSE 0 END) AS conformes,
            SUM(CASE WHEN i.classificacao = 'N' THEN 1 ELSE 0 END) AS nao_conformes,
            SUM(CASE WHEN i.classificacao = 'NA' THEN 1 ELSE 0 END) AS nao_aplicaveis
        FROM trusted.tb_auditoria_form_analise a
        LEFT JOIN trusted.tb_auditoria_form_item i ON i.analise_id = a.id
        WHERE a.tipo_auditoria = :tipo_auditoria
        GROUP BY a.id
        ORDER BY a.data_auditoria DESC, a.numero_analise DESC
        """
    )
    with engine.connect() as conn:
        return pd.read_sql_query(query, conn, params={"tipo_auditoria": tipo_auditoria})


def get_dashboard_data(engine: Engine, tipo_auditoria: str) -> dict[str, pd.DataFrame]:
    kpi_query = text(
        """
        SELECT
            COUNT(DISTINCT a.id) AS total_analises,
            COUNT(i.id) AS total_registros,
            SUM(CASE WHEN i.classificacao = 'S' THEN 1 ELSE 0 END) AS total_s,
            SUM(CASE WHEN i.classificacao = 'N' THEN 1 ELSE 0 END) AS total_n,
            SUM(CASE WHEN i.classificacao = 'NA' THEN 1 ELSE 0 END) AS total_na
        FROM trusted.tb_auditoria_form_analise a
        LEFT JOIN trusted.tb_auditoria_form_item i ON i.analise_id = a.id
        WHERE a.tipo_auditoria = :tipo_auditoria
        """
    )

    serie_query = text(
        """
        SELECT
            a.data_auditoria,
            COUNT(DISTINCT a.id) AS analises,
            SUM(CASE WHEN i.classificacao = 'S' THEN 1 ELSE 0 END) AS s,
            SUM(CASE WHEN i.classificacao = 'N' THEN 1 ELSE 0 END) AS n,
            SUM(CASE WHEN i.classificacao = 'NA' THEN 1 ELSE 0 END) AS na
        FROM trusted.tb_auditoria_form_analise a
        LEFT JOIN trusted.tb_auditoria_form_item i ON i.analise_id = a.id
        WHERE a.tipo_auditoria = :tipo_auditoria
        GROUP BY a.data_auditoria
        ORDER BY a.data_auditoria
        """
    )

    area_query = text(
        """
        SELECT
            i.departamento,
            SUM(CASE WHEN i.classificacao = 'S' THEN 1 ELSE 0 END) AS s,
            SUM(CASE WHEN i.classificacao = 'N' THEN 1 ELSE 0 END) AS n,
            SUM(CASE WHEN i.classificacao = 'NA' THEN 1 ELSE 0 END) AS na,
            COUNT(*) AS total
        FROM trusted.tb_auditoria_form_item i
        JOIN trusted.tb_auditoria_form_analise a ON a.id = i.analise_id
        WHERE a.tipo_auditoria = :tipo_auditoria
        GROUP BY i.departamento
        ORDER BY i.departamento
        """
    )

    top_nao_conformes_query = text(
        """
        SELECT
            i.departamento,
            SUM(CASE WHEN i.classificacao = 'N' THEN 1 ELSE 0 END) AS nao_conformes
        FROM trusted.tb_auditoria_form_item i
        JOIN trusted.tb_auditoria_form_analise a ON a.id = i.analise_id
        WHERE a.tipo_auditoria = :tipo_auditoria
        GROUP BY i.departamento
        ORDER BY nao_conformes DESC, i.departamento
        """
    )

    with engine.connect() as conn:
        kpi_df = pd.read_sql_query(kpi_query, conn, params={"tipo_auditoria": tipo_auditoria})
        serie_df = pd.read_sql_query(serie_query, conn, params={"tipo_auditoria": tipo_auditoria})
        area_df = pd.read_sql_query(area_query, conn, params={"tipo_auditoria": tipo_auditoria})
        top_n_df = pd.read_sql_query(top_nao_conformes_query, conn, params={"tipo_auditoria": tipo_auditoria})

    return {
        "kpi": kpi_df,
        "serie": serie_df,
        "area": area_df,
        "top_n": top_n_df,
    }


def load_analysis_items(engine: Engine, analise_id: int, template: SheetTemplate) -> tuple[dict[str, Any], pd.DataFrame]:
    analise_query = text(
        """
        SELECT id, tipo_auditoria, numero_analise, data_auditoria
        FROM trusted.tb_auditoria_form_analise
        WHERE id = :analise_id
        """
    )

    itens_query = text(
        """
        SELECT item, referencia, requisito, departamento, classificacao
        FROM trusted.tb_auditoria_form_item
        WHERE analise_id = :analise_id
        """
    )

    with engine.connect() as conn:
        analise = conn.execute(analise_query, {"analise_id": analise_id}).mappings().first()
        if analise is None:
            raise ValueError("Analise nao encontrada.")

        itens_db = pd.read_sql_query(itens_query, conn, params={"analise_id": analise_id})

    df = get_sheet_dataframe(template)

    if not itens_db.empty:
        itens_db["departamento"] = itens_db["departamento"].astype(str).apply(
            lambda x: AREA_TOKEN_MAP.get(area_token(x), x)
        )
        pivot = itens_db.pivot_table(
            index=["item", "referencia", "requisito"],
            columns="departamento",
            values="classificacao",
            aggfunc="first",
        ).reset_index()

        merge_keys = ["item", "referencia", "requisito"]
        merged = df.merge(pivot, on=merge_keys, how="left", suffixes=("", "_db"))

        for dep_name in get_area_columns_from_df(merged):
            if f"{dep_name}_db" in merged.columns:
                merged[dep_name] = merged[f"{dep_name}_db"].fillna(merged[dep_name])
                merged.drop(columns=[f"{dep_name}_db"], inplace=True)

        df = merged

    for dep_name in get_area_columns_from_df(df):
        df[dep_name] = (
            df[dep_name]
            .fillna("")
            .astype(str)
            .str.upper()
            .apply(lambda x: x if x in CLASSIFICACOES else "")
        )

    analise_meta = {
        "id": analise["id"],
        "tipo_auditoria": analise["tipo_auditoria"],
        "numero_analise": analise["numero_analise"],
        "data_auditoria": analise["data_auditoria"],
    }
    return analise_meta, df


def save_analysis(
    engine: Engine,
    analise_id: int | None,
    tipo_auditoria: str,
    numero_analise: str,
    data_auditoria: date,
    df: pd.DataFrame,
) -> int:
    with engine.begin() as conn:
        if analise_id is None:
            row = conn.execute(
                text(
                    """
                    INSERT INTO trusted.tb_auditoria_form_analise
                    (tipo_auditoria, numero_analise, data_auditoria, atualizado_em)
                    VALUES (:tipo, :numero, :data, NOW())
                    ON CONFLICT (tipo_auditoria, numero_analise, data_auditoria)
                    DO UPDATE SET atualizado_em = NOW()
                    RETURNING id
                    """
                ),
                {"tipo": tipo_auditoria, "numero": numero_analise, "data": data_auditoria},
            ).first()
            analise_id = int(row[0])
        else:
            conn.execute(
                text(
                    """
                    UPDATE trusted.tb_auditoria_form_analise
                    SET numero_analise = :numero,
                        data_auditoria = :data,
                        atualizado_em = NOW()
                    WHERE id = :id
                    """
                ),
                {"numero": numero_analise, "data": data_auditoria, "id": analise_id},
            )

        conn.execute(
            text("DELETE FROM trusted.tb_auditoria_form_item WHERE analise_id = :id"),
            {"id": analise_id},
        )

        departamentos = get_area_columns_from_df(df)

        insert_sql = text(
            """
            INSERT INTO trusted.tb_auditoria_form_item
            (analise_id, item, referencia, requisito, departamento, classificacao, atualizado_em)
            VALUES
            (:analise_id, :item, :referencia, :requisito, :departamento, :classificacao, NOW())
            """
        )

        payload: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            for departamento in departamentos:
                classificacao = str(row[departamento]).upper().strip()
                if classificacao not in CLASSIFICACOES:
                    classificacao = "NA"
                payload.append(
                    {
                        "analise_id": analise_id,
                        "item": str(row["item"]),
                        "referencia": str(row.get("referencia", "")),
                        "requisito": str(row.get("requisito", "")),
                        "departamento": departamento,
                        "classificacao": classificacao,
                    }
                )

        conn.execute(insert_sql, payload)

    return analise_id


def render_header() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background: #e6e6e6;
        }
        [data-testid="stHeader"] {
            background: transparent;
        }
        .pdf-title {
            font-family: "Times New Roman", serif;
            font-size: 2rem;
            font-weight: 700;
            color: #111;
            margin: 0.25rem 0 1rem 0;
        }
        .pdf-subtitle {
            font-family: "Times New Roman", serif;
            font-size: 1.1rem;
            font-weight: 700;
            color: #111;
            margin: 0;
        }
        .ux-chip {
            background: #ffffff;
            border: 1px solid #d0d0d0;
            border-radius: 10px;
            padding: 0.5rem 0.75rem;
            font-weight: 600;
            color: #0a3d62;
            display: inline-block;
            margin-bottom: 0.5rem;
        }
        .ux-card {
            background: #ffffff;
            border: 1px solid #d8d8d8;
            border-left: 6px solid #1177cc;
            border-radius: 12px;
            padding: 0.9rem 1rem;
            margin: 0.4rem 0;
        }
        .ux-label {
            color: #3a3a3a;
            font-size: 0.85rem;
            margin-bottom: 0.1rem;
        }
        .ux-value {
            color: #111;
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 0.35rem;
        }
        .ux-req {
            color: #111;
            font-size: 1.08rem;
            font-weight: 700;
            margin-top: 0.35rem;
        }
        .ux-title {
            color: #111;
            font-size: 1rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }
        .ux-desc {
            color: #222;
            font-size: 0.98rem;
            font-weight: 400;
            margin-top: 0.1rem;
            margin-bottom: 0.35rem;
        }
        div[data-testid="stRadio"] [role="radiogroup"] {
            display: flex;
            gap: 0.35rem;
            align-items: center;
            flex-wrap: nowrap;
        }
        div[data-testid="stRadio"] [role="radiogroup"] > label {
            border-radius: 8px;
            padding: 0.2rem 0.45rem;
            border: 1px solid rgba(0,0,0,0.15);
            opacity: 0.45;
            min-width: 44px;
            justify-content: center;
            transition: all 0.15s ease;
        }
        div[data-testid="stRadio"] [role="radiogroup"] > label:nth-child(1) {
            background: #23a559;
            color: #fff;
        }
        div[data-testid="stRadio"] [role="radiogroup"] > label:nth-child(2) {
            background: #d64545;
            color: #fff;
        }
        div[data-testid="stRadio"] [role="radiogroup"] > label:nth-child(3) {
            background: #f3c845;
            color: #111;
        }
        div[data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) {
            opacity: 1;
            border: 2px solid #111;
            box-shadow: 0 0 0 2px rgba(17, 17, 17, 0.12);
            transform: translateY(-1px);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='pdf-title'>{APP_TITLE}</div>", unsafe_allow_html=True)


def get_tipo_badge(tipo: str) -> str:
    if "MA" in tipo.upper():
        return "Meio Ambiente"
    if "ST" in tipo.upper():
        return "Seguranca do Trabalho"
    return tipo


def render_analyses_kpis(analyses: pd.DataFrame) -> None:
    total = int(len(analyses))
    ultima_data = "-"
    total_nao_conformes = 0

    if total > 0:
        try:
            ultima_data = str(analyses.iloc[0]["data_auditoria"])
        except Exception:
            ultima_data = "-"
        try:
            total_nao_conformes = int(analyses["nao_conformes"].fillna(0).sum())
        except Exception:
            total_nao_conformes = 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Analises registradas", total)
    c2.metric("Ultima auditoria", ultima_data)
    c3.metric("Nao conformidades", total_nao_conformes)


def save_current_analysis(engine: Engine, template: SheetTemplate, numero: str, data_auditoria: date, df: pd.DataFrame) -> tuple[bool, str]:
    valid, msg = validate_before_save(numero, df)
    if not valid:
        return False, msg

    try:
        analise_id = save_analysis(
            engine=engine,
            analise_id=st.session_state.get(f"active_analise_id_{template.name}"),
            tipo_auditoria=template.name,
            numero_analise=numero,
            data_auditoria=data_auditoria,
            df=df,
        )
        st.session_state[f"active_analise_id_{template.name}"] = analise_id
        return True, "Analise salva no banco blue_raw.trusted com sucesso."
    except Exception as exc:
        return False, f"Erro ao salvar no banco: {exc}"


def reset_editor_state(tipo: str) -> None:
    st.session_state[f"active_tipo"] = tipo
    st.session_state[f"active_analise_id_{tipo}"] = None
    st.session_state[f"active_df_{tipo}"] = None


def open_existing_analysis(engine: Engine, template: SheetTemplate, analise_id: int) -> None:
    meta, df = load_analysis_items(engine, analise_id, template)
    tipo = template.name
    st.session_state[f"active_tipo"] = tipo
    st.session_state[f"active_analise_id_{tipo}"] = int(meta["id"])
    st.session_state[f"active_numero_{tipo}"] = str(meta["numero_analise"])
    st.session_state[f"active_data_{tipo}"] = meta["data_auditoria"]
    st.session_state[f"active_df_{tipo}"] = df
    st.session_state[f"screen_{tipo}"] = "editor"


def ensure_editor_df(template: SheetTemplate) -> pd.DataFrame:
    tipo = template.name
    df_key = f"active_df_{tipo}"
    if st.session_state.get(df_key) is None:
        st.session_state[df_key] = get_sheet_dataframe(template)
    return st.session_state[df_key]


def render_sheet_editor(template: SheetTemplate, area_selecionada: str) -> pd.DataFrame:
    tipo = template.name
    df = ensure_editor_df(template)

    base_cols = ["item", "referencia", "requisito"]
    dep_cols = get_area_columns_from_df(df)

    if not dep_cols:
        st.warning("Nenhuma area encontrada para esta auditoria.")
        return df

    if area_selecionada not in dep_cols:
        area_selecionada = dep_cols[0]

    st.caption(f"Area selecionada: {area_selecionada} | Itens: {len(df)}")

    preenchidos = int(df[area_selecionada].astype(str).str.upper().isin(CLASSIFICACOES).sum())
    total_itens = max(len(df), 1)
    percentual = int(round((preenchidos / total_itens) * 100, 0))
    st.progress(
        preenchidos / total_itens,
        text=f"Nivel de preenchimento do check: {percentual}% ({preenchidos}/{len(df)})",
    )

    form_key = f"form_area_{tipo}_{area_selecionada}"
    with st.form(form_key, clear_on_submit=False):
        st.caption("Marque os itens e clique em Aplicar classificacoes para atualizar sem refresh a cada clique.")

        for idx, row in df.iterrows():
            item = str(row.get("item", ""))
            referencia = str(row.get("referencia", ""))
            requisito = str(row.get("requisito", ""))
            atual = str(row.get(area_selecionada, "")).upper().strip()
            if atual not in CLASSIFICACOES:
                atual = ""
            atual_label = atual if atual else "Nao selecionado"

            info_col, sel_col = st.columns([8, 3])
            with info_col:
                st.markdown(
                    f"""
                    <div class="ux-card">
                        <div class="ux-title">Item {item} | Lei/Norma: {referencia}</div>
                        <div class="ux-desc">{requisito}</div>
                        <div class="ux-label">Atual em {area_selecionada}: {atual_label}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            widget_key = f"choice_{tipo}_{area_selecionada}_{idx}"
            if widget_key not in st.session_state:
                st.session_state[widget_key] = atual

            with sel_col:
                st.markdown("**Selecao**")
                current_val = st.session_state.get(widget_key, "")
                if current_val not in CLASSIFICACOES:
                    current_val = None
                st.radio(
                    label=f"classificacao_{idx}",
                    options=CLASSIFICACOES,
                    horizontal=True,
                    index=CLASSIFICACOES.index(current_val) if current_val in CLASSIFICACOES else None,
                    key=widget_key,
                    label_visibility="collapsed",
                )

        aplicar = st.form_submit_button("Aplicar classificacoes da area", type="primary", use_container_width=True)

    if aplicar:
        for idx, _row in df.iterrows():
            widget_key = f"choice_{tipo}_{area_selecionada}_{idx}"
            raw_value = st.session_state.get(widget_key, "")
            value = str(raw_value).upper().strip() if raw_value is not None else ""
            df.at[idx, area_selecionada] = value if value in CLASSIFICACOES else ""

        st.session_state[f"active_df_{tipo}"] = df
        st.success("Classificacoes aplicadas para a area selecionada.")
        st.rerun()

    st.session_state[f"active_df_{tipo}"] = df

    dep_cols_full = get_area_columns_from_df(df)
    summary = df[dep_cols_full].stack().value_counts().reindex(CLASSIFICACOES, fill_value=0)
    s1, s2, s3 = st.columns(3)
    s1.metric("Total S", int(summary.get("S", 0)))
    s2.metric("Total N", int(summary.get("N", 0)))
    s3.metric("Total NA", int(summary.get("NA", 0)))
    return df


def get_tipo_title(tipo: str) -> str:
    if "MA" in tipo.upper():
        return "Inspecoes Rotineiras de Meio Ambiente - Lista de verificacao"
    if "ST" in tipo.upper():
        return "Inspecoes Rotineiras de Seguranca do Trabalho - Lista de verificacao"
    return f"Inspecoes Rotineiras - {tipo}"


def validate_before_save(numero: str, df: pd.DataFrame) -> tuple[bool, str]:
    if not numero:
        return False, "Informe o numero da analise antes de salvar."

    dep_cols = get_area_columns_from_df(df)
    invalid = (~df[dep_cols].isin(CLASSIFICACOES)).any().any()
    if invalid:
        return False, "Ha classificacoes invalidas. Use apenas S, N ou NA."

    return True, ""


def render_tipo_menu(engine: Engine, template: SheetTemplate) -> None:
    tipo = template.name
    st.markdown(f"<span class='ux-chip'>Tipo: {get_tipo_badge(tipo)}</span>", unsafe_allow_html=True)
    st.subheader(f"Painel de auditorias: {tipo}")

    analyses = list_analyses_by_type(engine, tipo)
    render_analyses_kpis(analyses)

    top_l, top_r = st.columns([2, 1])
    with top_l:
        filtro_numero = st.text_input(
            "Buscar por numero",
            value="",
            placeholder="Ex.: 2026-07-001",
            key=f"filtro_numero_{tipo}",
        ).strip()
    with top_r:
        por_pagina = int(
            st.number_input(
                "Cards por pagina",
                min_value=3,
                max_value=20,
                value=6,
                step=1,
                key=f"limite_lista_{tipo}",
            )
        )

    if filtro_numero:
        analyses = analyses[
            analyses["numero_analise"].astype(str).str.contains(filtro_numero, case=False, na=False)
        ]

    if analyses.empty:
        st.info("Nenhuma analise encontrada para este filtro.")
    else:
        total = len(analyses)
        total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
        page_key = f"analyses_page_{tipo}"
        if page_key not in st.session_state:
            st.session_state[page_key] = 1
        st.session_state[page_key] = min(max(int(st.session_state[page_key]), 1), total_paginas)

        p1, p2, p3 = st.columns([1, 2, 1])
        with p1:
            if st.button("Pagina anterior", key=f"analyses_prev_{tipo}", disabled=st.session_state[page_key] <= 1, use_container_width=True):
                st.session_state[page_key] -= 1
                st.rerun()
        with p2:
            pag = int(
                st.number_input(
                    "Pagina",
                    min_value=1,
                    max_value=total_paginas,
                    value=st.session_state[page_key],
                    step=1,
                    key=f"analyses_page_input_{tipo}",
                )
            )
            if pag != st.session_state[page_key]:
                st.session_state[page_key] = pag
                st.rerun()
        with p3:
            if st.button("Proxima pagina", key=f"analyses_next_{tipo}", disabled=st.session_state[page_key] >= total_paginas, use_container_width=True):
                st.session_state[page_key] += 1
                st.rerun()

        start = (st.session_state[page_key] - 1) * por_pagina
        end = min(start + por_pagina, total)
        page_df = analyses.iloc[start:end]

        st.caption(f"Exibindo analises {start + 1} a {end} de {total}")

        for _, row in page_df.iterrows():
            analise_id = int(row["id"])
            numero = row["numero_analise"]
            data = row["data_auditoria"]
            registros = int(row.get("total_registros", 0) or 0)
            s = int(row.get("conformes", 0) or 0)
            n = int(row.get("nao_conformes", 0) or 0)
            na = int(row.get("nao_aplicaveis", 0) or 0)

            st.markdown(
                f"""
                <div class="ux-card">
                    <div class="ux-label">Numero</div>
                    <div class="ux-value">{numero}</div>
                    <div class="ux-label">Data</div>
                    <div class="ux-value">{data}</div>
                    <div class="ux-label">Resumo</div>
                    <div class="ux-value">Registros: {registros} | S: {s} | N: {n} | NA: {na}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button(f"Abrir analise {numero}", key=f"open_card_{tipo}_{analise_id}", use_container_width=True):
                open_existing_analysis(engine, template, analise_id)
                st.rerun()

    if st.button("Iniciar nova analise", key=f"new_{tipo}", type="primary", use_container_width=True):
        reset_editor_state(tipo)
        st.session_state[f"active_numero_{tipo}"] = ""
        st.session_state[f"active_data_{tipo}"] = date.today()
        st.session_state[f"area_{tipo}"] = AREAS_ANALISADAS[0]
        st.session_state[f"screen_{tipo}"] = "editor"
        st.rerun()

    if st.button("Abrir dashboard de analises", key=f"dashboard_{tipo}", use_container_width=True):
        st.session_state[f"screen_{tipo}"] = "dashboard"
        st.rerun()


def render_dashboard_screen(engine: Engine, template: SheetTemplate) -> None:
    tipo = template.name
    st.markdown(f"<span class='ux-chip'>Dashboard de analises: {get_tipo_badge(tipo)}</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='pdf-subtitle'>{get_tipo_title(tipo)}</div>", unsafe_allow_html=True)

    if st.button("Voltar ao menu", key=f"back_dashboard_{tipo}"):
        st.session_state[f"screen_{tipo}"] = "menu"
        st.rerun()

    data = get_dashboard_data(engine, tipo)
    kpi_df = data["kpi"]
    serie_df = data["serie"]
    area_df = data["area"]
    top_n_df = data["top_n"]

    if kpi_df.empty:
        st.info("Ainda nao existem dados para montar o dashboard deste tipo de auditoria.")
        return

    kpi = kpi_df.iloc[0].fillna(0)
    total_analises = int(kpi.get("total_analises", 0) or 0)
    total_registros = int(kpi.get("total_registros", 0) or 0)
    total_s = int(kpi.get("total_s", 0) or 0)
    total_n = int(kpi.get("total_n", 0) or 0)
    total_na = int(kpi.get("total_na", 0) or 0)

    base_conformidade = max(total_s + total_n, 1)
    taxa_conformidade = round((total_s / base_conformidade) * 100, 1)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Analises", total_analises)
    c2.metric("Registros", total_registros)
    c3.metric("Conformes (S)", total_s)
    c4.metric("Nao conformes (N)", total_n)
    c5.metric("Taxa de conformidade", f"{taxa_conformidade}%")

    st.markdown("### Evolucao por data")
    if not serie_df.empty:
        serie_df = serie_df.fillna(0)
        serie_df["data_auditoria"] = pd.to_datetime(serie_df["data_auditoria"])
        serie_df = serie_df.sort_values("data_auditoria")

        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.caption("Analises por data")
            st.line_chart(serie_df.set_index("data_auditoria")[["analises"]])
        with chart_cols[1]:
            st.caption("Classificacoes por data (S/N/NA)")
            st.line_chart(serie_df.set_index("data_auditoria")[["s", "n", "na"]])
    else:
        st.info("Sem historico temporal suficiente para exibicao.")

    st.markdown("### Desempenho por area")
    if not area_df.empty:
        area_df = area_df.fillna(0)
        area_df["taxa_conformidade"] = area_df.apply(
            lambda r: round((float(r["s"]) / max(float(r["s"]) + float(r["n"]), 1)) * 100, 1),
            axis=1,
        )

        chart_cols2 = st.columns(2)
        with chart_cols2[0]:
            st.caption("Nao conformidades por area")
            st.bar_chart(area_df.set_index("departamento")[["n"]])
        with chart_cols2[1]:
            st.caption("Taxa de conformidade por area (%)")
            st.bar_chart(area_df.set_index("departamento")[["taxa_conformidade"]])

        top_show = top_n_df.fillna(0).head(5)
        if not top_show.empty:
            st.markdown("### Top 5 areas com mais nao conformidades")
            for _, row in top_show.iterrows():
                st.markdown(
                    f"- **{row['departamento']}**: {int(row['nao_conformes'])} nao conformidades"
                )
    else:
        st.info("Sem dados por area para exibicao.")


def render_editor_screen(engine: Engine, template: SheetTemplate) -> None:
    tipo = template.name
    st.markdown(f"<span class='ux-chip'>Fluxo guiado: 1) Dados  2) Area  3) Classificacao  4) Salvar</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='pdf-subtitle'>{get_tipo_title(tipo)}</div>", unsafe_allow_html=True)

    if st.button("Voltar ao menu", key=f"back_{tipo}"):
        st.session_state[f"screen_{tipo}"] = "menu"
        st.rerun()

    meta_col_1, meta_col_2 = st.columns([2, 2])
    with meta_col_1:
        numero = st.text_input(
            "Numero da analise",
            value=st.session_state.get(f"active_numero_{tipo}", ""),
            key=f"numero_input_{tipo}",
            placeholder="Ex.: 2026-07-001",
        ).strip()
    with meta_col_2:
        data_auditoria = st.date_input(
            "Data da auditoria",
            value=st.session_state.get(f"active_data_{tipo}", date.today()),
            key=f"data_input_{tipo}",
        )

    st.session_state[f"active_numero_{tipo}"] = numero
    st.session_state[f"active_data_{tipo}"] = data_auditoria

    logo_col, filtro_col = st.columns([1, 5])
    with logo_col:
        st.image(LOGO_URL, width=120)

    dep_cols = get_area_columns_from_df(ensure_editor_df(template))
    if not dep_cols:
        st.warning("Nao foram encontradas areas para esta auditoria.")
        return

    area_default = st.session_state.get(f"area_{tipo}", dep_cols[0] if dep_cols else "")

    nav1, nav2, nav3 = st.columns([1, 3, 1])
    with nav1:
        current_idx = dep_cols.index(area_default) if area_default in dep_cols else 0
        if st.button("Area anterior", key=f"prev_area_{tipo}", disabled=current_idx <= 0):
            st.session_state[f"area_{tipo}"] = dep_cols[max(current_idx - 1, 0)]
            st.rerun()
    with nav2:
        st.caption(f"Area {((dep_cols.index(st.session_state.get(f'area_{tipo}', dep_cols[0])) + 1) if st.session_state.get(f'area_{tipo}', dep_cols[0]) in dep_cols else 1)} de {len(dep_cols)}")
    with nav3:
        current_idx = dep_cols.index(st.session_state.get(f"area_{tipo}", dep_cols[0])) if st.session_state.get(f"area_{tipo}", dep_cols[0]) in dep_cols else 0
        if st.button("Proxima area", key=f"next_area_{tipo}", disabled=current_idx >= len(dep_cols) - 1):
            st.session_state[f"area_{tipo}"] = dep_cols[min(current_idx + 1, len(dep_cols) - 1)]
            st.rerun()

    area_default = st.session_state.get(f"area_{tipo}", dep_cols[0])
    with filtro_col:
        area_selecionada = st.selectbox(
            "Area",
            options=dep_cols,
            index=dep_cols.index(area_default) if area_default in dep_cols else 0,
            key=f"area_select_{tipo}",
        )

    st.session_state[f"area_{tipo}"] = area_selecionada

    df = render_sheet_editor(template, area_selecionada)

    area_n = int((df[area_selecionada] == "N").sum()) if area_selecionada in df.columns else 0
    area_s = int((df[area_selecionada] == "S").sum()) if area_selecionada in df.columns else 0
    area_na = int((df[area_selecionada] == "NA").sum()) if area_selecionada in df.columns else 0
    k1, k2, k3 = st.columns(3)
    k1.metric(f"{area_selecionada} - S", area_s)
    k2.metric(f"{area_selecionada} - N", area_n)
    k3.metric(f"{area_selecionada} - NA", area_na)

    action_l, action_r = st.columns([3, 2])
    with action_l:
        if st.button("Salvar analise", type="primary", use_container_width=True, key=f"save_{tipo}"):
            ok, msg = save_current_analysis(engine, template, numero, data_auditoria, df)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
    with action_r:
        if st.button("Salvar e voltar ao menu", use_container_width=True, key=f"save_back_{tipo}"):
            ok, msg = save_current_analysis(engine, template, numero, data_auditoria, df)
            if ok:
                st.success(msg)
                st.session_state[f"screen_{tipo}"] = "menu"
                st.rerun()
            else:
                st.error(msg)


def main() -> None:
    render_header()

    engine = get_engine()
    try:
        ensure_db_schema(engine)
        seed_templates_if_empty(engine)
        templates = load_templates(engine)
    except Exception as exc:
        st.error(f"Falha ao carregar templates no banco blue_raw: {exc}")
        st.stop()

    if not templates:
        st.warning("Nenhum template de auditoria foi encontrado no banco de dados.")
        st.stop()

    template_map = {t.name: t for t in templates}
    tipos = list(template_map.keys())

    st.markdown("### Menu inicial")
    tipo_selecionado = st.selectbox("Selecione o tipo de auditoria", options=tipos)

    screen_key = f"screen_{tipo_selecionado}"
    if screen_key not in st.session_state:
        st.session_state[screen_key] = "menu"

    template = template_map[tipo_selecionado]
    if st.session_state[screen_key] == "menu":
        render_tipo_menu(engine, template)
    elif st.session_state[screen_key] == "dashboard":
        render_dashboard_screen(engine, template)
    else:
        render_editor_screen(engine, template)


if __name__ == "__main__":
    main()
