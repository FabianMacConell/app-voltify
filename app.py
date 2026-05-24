import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import datetime
import calendar
import os
import tempfile
import altair as alt
import plotly.express as px
import html as html_lib
import uuid
from sqlalchemy import bindparam, text

st.set_page_config(page_title="ERP Voltify", page_icon="⚡", layout="wide")

conn = st.connection("postgresql", type="sql")

GSHEETS_CACHE_TTL = 600  # 10 minutos — lecturas desde memoria local

# ==========================================
# PERSISTENCIA SUPABASE (Operaciones, Bodega, Nómina)
# ==========================================
def _commit_cache_clear_rerun(mensaje=None):
    """Tras escritura SQL: commit, limpia caché de Streamlit/SQL y rerun."""
    try:
        conn.session.commit()
    except Exception:
        try:
            conn.session.rollback()
        except Exception:
            pass
    st.cache_data.clear()
    if mensaje:
        st.session_state["_flash_guardado_ok"] = mensaje
    st.rerun()

def refrescar_sql_ui(mensaje=None):
    _commit_cache_clear_rerun(mensaje)

def refrescar_widgets_nomina_tras_guardado(mensaje_flash=None):
    """Recarga nómina desde Supabase e invalida el data_editor (ed_nomina)."""
    st.cache_data.clear()
    st.session_state.nomina = cargar_nomina_sql()
    rev = int(st.session_state.get("nomina_rev", 0)) + 1
    st.session_state.nomina_rev = rev
    st.session_state.pop(f"ed_nomina_{rev - 1}", None)
    st.session_state.pop("ed_nomina", None)
    _commit_cache_clear_rerun(mensaje_flash)

_LEGACY_PASCAL_A_SNAKE = {
    "RUT": "rut",
    "Trabajador": "trabajador",
    "Cargo": "cargo",
    "Sueldo_Base": "sueldo_base",
    "Jornada_Hrs": "jornada_hrs",
    "Tipo_Contrato": "tipo_contrato",
    "Gratificacion": "gratificacion",
    "AFP": "afp",
    "Dias_Falta": "dias_falta",
    "Horas_Atraso": "horas_atraso",
    "Horas_Extras": "horas_extras",
    "Colacion": "colacion",
    "Movilizacion": "movilizacion",
    "Anticipo": "anticipo",
    "Tarea": "tarea",
    "Proyecto": "proyecto",
    "proyecto": "proyecto",
    "Empresa": "empresa",
    "Num_OC": "num_oc",
    "Cobro": "cobro",
    "Estado": "estado",
    "Prioridad": "prioridad",
    "Fecha_Inicio": "fecha_inicio",
    "Fecha_Termino": "fecha_termino",
    "Dias_Duracion": "dias_duracion",
    "Codigo": "codigo",
    "Familia": "familia",
    "Nombre_Material": "nombre_material",
    "Descripcion": "descripcion",
    "Cantidad": "cantidad",
    "Unidad": "unidad",
    "Fecha": "fecha",
    "Tipo_Movimiento": "tipo_movimiento",
    "Persona_Responsable": "persona_responsable",
    "Destino": "destino",
    "Stock_Resultante": "stock_resultante",
}

def _renombrar_legacy_a_snake(df):
    """Unifica columnas legacy (Sheets/PascalCase) → snake_case minúsculas."""
    if df is None or getattr(df, "empty", True):
        return df
    ren = {}
    for c in df.columns:
        if c in _LEGACY_PASCAL_A_SNAKE:
            ren[c] = _LEGACY_PASCAL_A_SNAKE[c]
        else:
            ren[c] = str(c).strip().lower().replace(" ", "_")
    return df.rename(columns=ren)

def _columnas_sql_lookup(df):
    return {str(c).lower(): c for c in df.columns}

def _df_desde_sql(df_raw, columnas_snake):
    """DataFrame SQL con columnas en snake_case (minúsculas), alineado a Supabase."""
    if df_raw is None or getattr(df_raw, "empty", True):
        return pd.DataFrame(columns=list(columnas_snake))
    out = df_raw.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    # Alias habituales en Supabase / migraciones legacy
    _alias_sql = {
        "nombre": "tarea",
        "responsable": "trabajador",
        "fecha_fin": "fecha_termino",
        "fecha_termino_proy": "fecha_termino",
        "nombre_proyecto": "proyecto",
    }
    for src, dst in _alias_sql.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    for col in columnas_snake:
        if col not in out.columns:
            out[col] = pd.Series(dtype=object)
    cols_extra = [c for c in out.columns if c == "id" or c in columnas_snake]
    return out[[c for c in cols_extra if c in out.columns]]

def _valor_fila(row, *claves, default=""):
    """Lee una celda probando varias claves (snake_case o PascalCase legacy)."""
    for k in claves:
        if k in row.index:
            v = row[k]
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                return v
    return default

def _es_fila_stock_bodega(row):
    tm = row.get("tipo_movimiento") if isinstance(row, dict) else row.get("tipo_movimiento", row.get("tipo_movimiento"))
    if tm is None or (isinstance(tm, float) and pd.isna(tm)):
        return True
    return str(tm).strip() == ""

def cargar_operaciones_tareas_sql(ttl=0):
    """Lectura fresca de operaciones_tareas (ttl=0 → sin caché de conn.query)."""
    try:
        sql_ops = """
            SELECT id, tarea, proyecto, trabajador, estado, prioridad,
                   fecha_inicio, fecha_termino, dias_duracion
            FROM operaciones_tareas
        """
        try:
            df_raw = conn.query(sql_ops, ttl=ttl)
        except Exception:
            df_raw = conn.query("SELECT * FROM operaciones_tareas", ttl=ttl)
        if df_raw is not None and not getattr(df_raw, "empty", True):
            if "id" in df_raw.columns:
                df_raw = df_raw.drop(columns=["id"])
            df_raw = _reparar_df_columnas_numericas(df_raw, COLUMNAS_OPERACIONES_TAREAS)
        df = _df_desde_sql(df_raw, COLUMNAS_OPERACIONES_TAREAS)
        if "id" in df.columns:
            df["id"] = pd.to_numeric(df["id"], errors="coerce")
        return sanitizar_operaciones_tareas(df)
    except Exception as e:
        st.sidebar.warning(f"SQL operaciones_tareas: {e}")
        return pd.DataFrame(columns=COLUMNAS_OPERACIONES_TAREAS)

def _params_operacion_tarea(row):
    """Mapea fila del formulario / tablero al diccionario de parámetros SQL."""
    dias = row.get("dias_duracion")
    if dias is None or (isinstance(dias, float) and pd.isna(dias)):
        dias_val = None
    else:
        dias_val = float(dias)
    return {
        "tarea": normalizar_texto_manual(row["tarea"], "oracion"),
        "proyecto": str(row["proyecto"]).strip(),
        "trabajador": str(row["trabajador"]).strip(),
        "estado": str(row["estado"]).strip(),
        "prioridad": str(row["prioridad"]).strip(),
        "fecha_inicio": _fecha_tarea_a_str(row["fecha_inicio"]),
        "fecha_termino": _fecha_tarea_a_str(row["fecha_termino"]),
        "dias_duracion": dias_val,
    }

def _dict_params_operacion_tarea_sql(p):
    return {
        "tarea": p["tarea"],
        "proyecto": p["proyecto"],
        "trabajador": p["trabajador"],
        "estado": p["estado"],
        "prioridad": p["prioridad"],
        "fecha_inicio": p["fecha_inicio"],
        "fecha_termino": p["fecha_termino"],
        "dias_duracion": p["dias_duracion"],
    }

def _insert_operacion_tarea_en_sesion(session, params_sql):
    result = session.execute(
        text("""
            INSERT INTO operaciones_tareas (
                tarea, proyecto, trabajador, estado, prioridad, fecha_inicio, fecha_termino, dias_duracion
            ) VALUES (
                :tarea, :proyecto, :trabajador, :estado, :prioridad, :fecha_inicio, :fecha_termino, :dias_duracion
            )
            RETURNING id
        """),
        params_sql,
    )
    new_id = result.scalar()
    return int(new_id) if new_id is not None else None

def _upsert_fila_operacion_en_sesion(session, row, tarea_id=None):
    p = _params_operacion_tarea(row)
    if not p["tarea"] or not p["proyecto"] or not p["trabajador"]:
        raise ValueError("tarea, proyecto y trabajador son obligatorios.")
    params_sql = _dict_params_operacion_tarea_sql(p)
    if tarea_id is not None and not (isinstance(tarea_id, float) and pd.isna(tarea_id)):
        tid = int(tarea_id)
        res = session.execute(
            text("""
                UPDATE operaciones_tareas SET
                    tarea = :tarea, proyecto = :proyecto, trabajador = :trabajador,
                    estado = :estado, prioridad = :prioridad,
                    fecha_inicio = :fecha_inicio, fecha_termino = :fecha_termino,
                    dias_duracion = :dias_duracion
                WHERE id = :id
            """),
            {**params_sql, "id": tid},
        )
        if res.rowcount > 0:
            return tid
    return _insert_operacion_tarea_en_sesion(session, params_sql)

def _finalizar_guardado_operaciones_ui(mensaje=None, refrescar=True):
    st.session_state.operaciones_tareas = cargar_operaciones_tareas_sql(ttl=0)
    st.session_state.ops_tareas_rev = int(st.session_state.get("ops_tareas_rev", 0)) + 1
    st.session_state.pop(f"ed_ops_tareas_{st.session_state.ops_tareas_rev - 1}", None)
    st.cache_data.clear()
    if refrescar:
        st.success(mensaje or "¡Tarea guardada exitosamente en Supabase!")
        st.rerun()

def guardar_fila_operacion_tarea_sql(row, tarea_id=None, refrescar_ui=False):
    """Upsert de una tarea en operaciones_tareas (transacción con commit explícito)."""
    try:
        with conn.session as session:
            new_id = _upsert_fila_operacion_en_sesion(session, row, tarea_id=tarea_id)
            session.commit()
        if refrescar_ui:
            _finalizar_guardado_operaciones_ui()
        return new_id
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al guardar tarea en SQL: {e}")
        return None

def eliminar_operacion_tarea_sql(tarea_id=None, proyecto=None, tarea=None, trabajador=None, refrescar_ui=False):
    try:
        with conn.session as session:
            if tarea_id is not None and not (isinstance(tarea_id, float) and pd.isna(tarea_id)):
                session.execute(
                    text("DELETE FROM operaciones_tareas WHERE id = :id"),
                    {"id": int(tarea_id)},
                )
            elif proyecto and tarea and trabajador:
                session.execute(
                    text("""
                        DELETE FROM operaciones_tareas
                        WHERE proyecto = :proyecto AND tarea = :tarea AND trabajador = :trabajador
                    """),
                    {
                        "proyecto": str(proyecto).strip(),
                        "tarea": str(tarea).strip(),
                        "trabajador": str(trabajador).strip(),
                    },
                )
            elif proyecto:
                session.execute(
                    text("DELETE FROM operaciones_tareas WHERE proyecto = :proyecto"),
                    {"proyecto": str(proyecto).strip()},
                )
            session.commit()
        if refrescar_ui:
            _finalizar_guardado_operaciones_ui("Tarea eliminada de Supabase.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al eliminar tarea en SQL: {e}")
        return False

def sincronizar_operaciones_tareas_sql(df, mensaje_flash=None, refrescar=True):
    """Sincroniza el tablero con operaciones_tareas en una sola transacción."""
    df = sanitizar_operaciones_tareas(df)
    df = _migrar_dias_duracion_tareas(df)
    if df.empty:
        st.warning("No hay tareas válidas para guardar en Supabase.")
        return False
    try:
        ids_vivos = []
        with conn.session as session:
            for _, row in df.iterrows():
                tid = row["id"] if "id" in row.index and pd.notna(row.get("id")) else None
                rid = _upsert_fila_operacion_en_sesion(session, row, tarea_id=tid)
                if rid is not None:
                    ids_vivos.append(int(rid))
            if ids_vivos:
                stmt = text("DELETE FROM operaciones_tareas WHERE id NOT IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                session.execute(stmt, {"ids": ids_vivos})
            session.commit()
        if refrescar:
            _finalizar_guardado_operaciones_ui(mensaje_flash)
        else:
            st.session_state.operaciones_tareas = cargar_operaciones_tareas_sql(ttl=0)
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al sincronizar operaciones_tareas: {e}")
        return False

def cargar_bodega_inventario_sql(ttl=0):
    """Lee bodega_inventario (ttl=0 = sin caché) y separa inventario maestro vs movimientos."""
    try:
        df_raw = conn.query("SELECT * FROM bodega_inventario", ttl=ttl)
        if df_raw is None or df_raw.empty:
            return (
                pd.DataFrame(columns=COLUMNAS_BODEGA_STOCK),
                pd.DataFrame(columns=COLUMNAS_BODEGA_HISTORIAL),
            )
        df_raw = df_raw.copy()
        df_raw.columns = [str(c).strip().lower().replace(" ", "_") for c in df_raw.columns]
        if "id" in df_raw.columns:
            df_raw = df_raw.drop(columns=["id"])
        df_raw = _renombrar_legacy_a_snake(df_raw)
        if "tipo_movimiento" not in df_raw.columns:
            df_raw["tipo_movimiento"] = ""
        tm = df_raw["tipo_movimiento"].astype(str).str.strip()
        mask_mov = (
            df_raw["tipo_movimiento"].notna()
            & (tm != "")
            & (~tm.str.lower().isin(["nan", "none", "null"]))
        )
        df_mov = df_raw[mask_mov].copy()
        df_stock = df_raw[~mask_mov].copy()
        stock = sanitizar_bodega_stock(_df_desde_sql(df_stock, COLUMNAS_BODEGA_STOCK))
        hist = sanitizar_bodega_historial(_df_desde_sql(df_mov, COLUMNAS_BODEGA_HISTORIAL))
        return stock, hist
    except Exception as e:
        st.warning(f"⚠️ Nota SQL bodega_inventario: {e}")
        return (
            pd.DataFrame(columns=COLUMNAS_BODEGA_STOCK),
            pd.DataFrame(columns=COLUMNAS_BODEGA_HISTORIAL),
        )

def recargar_bodega_desde_sql():
    stock, hist = cargar_bodega_inventario_sql(ttl=0)
    st.session_state.bodega_stock = stock
    st.session_state.bodega_historial = hist

def insertar_material_bodega_sql(
    codigo, familia, nombre_material, descripcion, cantidad, unidad="un", refrescar_ui=True
):
    """Alta de fila maestra en bodega_inventario (sin tipo_movimiento = inventario actual)."""
    try:
        codigo = int(codigo)
        familia = int(familia)
        nombre_material = normalizar_texto_manual(nombre_material, "titulo")
        descripcion = normalizar_texto_manual(descripcion, "oracion")
        cantidad = int(cantidad)
        unidad = str(unidad or "un")
        with conn.session as session:
            session.execute(
                text("""
                    INSERT INTO bodega_inventario (
                        codigo, familia, nombre_material, descripcion, cantidad, unidad
                    ) VALUES (
                        :codigo, :familia, :nombre_material, :descripcion, :cantidad, :unidad
                    )
                """),
                {
                    "codigo": codigo,
                    "familia": familia,
                    "nombre_material": nombre_material,
                    "descripcion": descripcion,
                    "cantidad": cantidad,
                    "unidad": unidad,
                },
            )
            if cantidad > 0:
                fecha_hoy = datetime.date.today().strftime("%Y-%m-%d")
                _insert_bodega_movimientos_en_sesion(
                    session,
                    _params_bodega_movimiento(
                        fecha_hoy,
                        "Entrada",
                        codigo,
                        nombre_material,
                        cantidad,
                        "Sistema",
                        "Alta inventario",
                        cantidad,
                        detalle_destino="Stock inicial",
                    ),
                )
            session.commit()
        recargar_bodega_desde_sql()
        st.session_state.bod_stock_rev = int(st.session_state.get("bod_stock_rev", 0)) + 1
        st.session_state.pop(f"ed_bodega_stock_{st.session_state.bod_stock_rev - 1}", None)
        st.session_state.pop("ed_bodega_stock", None)
        if refrescar_ui:
            st.cache_data.clear()
            st.success("¡Material registrado exitosamente en la bodega!")
            st.rerun()
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al dar de alta material: {e}")
        return False

def actualizar_stock_maestro_sql(codigo, cantidad):
    try:
        conn.session.execute(
            text("""
                UPDATE bodega_inventario SET cantidad = :cantidad
                WHERE codigo = :codigo
                  AND (tipo_movimiento IS NULL OR TRIM(COALESCE(tipo_movimiento::text, '')) = '')
            """),
            {"codigo": int(codigo), "cantidad": int(cantidad)},
        )
        conn.session.commit()
        return True
    except Exception as e:
        conn.session.rollback()
        st.error(f"Error al actualizar stock: {e}")
        return False

def actualizar_metadatos_stock_sql(codigo, familia, nombre, descripcion, unidad):
    try:
        conn.session.execute(
            text("""
                UPDATE bodega_inventario SET
                    familia = :familia, nombre_material = :nombre_material,
                    descripcion = :descripcion, unidad = :unidad
                WHERE codigo = :codigo
                  AND (tipo_movimiento IS NULL OR TRIM(COALESCE(tipo_movimiento::text, '')) = '')
            """),
            {
                "codigo": int(codigo),
                "familia": int(familia),
                "nombre_material": normalizar_texto_manual(nombre, "titulo"),
                "descripcion": normalizar_texto_manual(descripcion, "oracion"),
                "unidad": str(unidad or "un"),
            },
        )
        conn.session.commit()
        return True
    except Exception as e:
        conn.session.rollback()
        st.error(f"Error al actualizar inventario: {e}")
        return False

def eliminar_material_bodega_sql(codigo):
    try:
        conn.session.execute(
            text("DELETE FROM bodega_inventario WHERE codigo = :codigo"),
            {"codigo": int(codigo)},
        )
        conn.session.commit()
        recargar_bodega_desde_sql()
        return True
    except Exception as e:
        conn.session.rollback()
        st.error(f"Error al eliminar material: {e}")
        return False

def _parse_destino_bodega(destino_completo):
    destino = str(destino_completo or "").strip()
    if " — " in destino:
        principal, detalle = destino.split(" — ", 1)
        return principal.strip(), detalle.strip()
    return destino, ""


def _params_bodega_movimiento(
    fecha, tipo_mov, codigo, nombre, cantidad, persona, destino, stock_resultante, detalle_destino=""
):
    destino_prin, detalle_auto = _parse_destino_bodega(destino)
    detalle_final = str(detalle_destino or detalle_auto).strip()
    return {
        "fecha": str(fecha),
        "tipo_movimiento": str(tipo_mov),
        "codigo": int(codigo),
        "nombre_material": str(nombre),
        "cantidad": int(cantidad),
        "persona_responsable": str(persona).strip(),
        "destino": destino_prin,
        "detalle_destino": detalle_final,
        "stock_resultante": int(stock_resultante),
    }


def _dict_insert_bodega_movimientos(params):
    """Parámetros del INSERT histórico (columnas exactas de bodega_movimientos)."""
    return {
        "fecha": str(params["fecha"]),
        "tipo_movimiento": str(params["tipo_movimiento"]),
        "codigo": int(params["codigo"]),
        "nombre_material": str(params["nombre_material"]),
        "cantidad": int(params["cantidad"]),
        "persona_responsable": str(params["persona_responsable"]).strip(),
        "destino": str(params["destino"]).strip(),
        "detalle_destino": str(params.get("detalle_destino") or "").strip(),
        "stock_resultante": int(params["stock_resultante"]),
    }


def _es_entrada_bodega(tipo_movimiento):
    return str(tipo_movimiento).strip().lower() in ("entrada", "ingreso")


def _es_salida_bodega(tipo_movimiento):
    return str(tipo_movimiento).strip().lower() in ("salida", "egreso")


def obtener_stock_actual_bodega_sql(codigo, ttl=0):
    """Stock actual del material en bodega_inventario (fila maestra)."""
    cod = int(codigo)
    try:
        df_raw = conn.query(
            f"""
            SELECT nombre_material, cantidad
            FROM bodega_inventario
            WHERE codigo = {cod}
              AND (tipo_movimiento IS NULL OR TRIM(COALESCE(tipo_movimiento::text, '')) = '')
            LIMIT 1
            """,
            ttl=ttl,
        )
        if df_raw is None or df_raw.empty:
            df_raw = conn.query(
                f"""
                SELECT nombre_material, cantidad
                FROM bodega_inventario
                WHERE codigo = {cod}
                ORDER BY id DESC NULLS LAST
                LIMIT 1
                """,
                ttl=ttl,
            )
        if df_raw is None or df_raw.empty:
            return None
        out = df_raw.copy()
        out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
        return {
            "nombre_material": str(out.iloc[0].get("nombre_material", "")),
            "cantidad": int(pd.to_numeric(out.iloc[0].get("cantidad", 0), errors="coerce") or 0),
        }
    except Exception:
        return None


def _insert_bodega_movimientos_en_sesion(session, params):
    session.execute(
        text("""
            INSERT INTO bodega_movimientos (
                fecha, tipo_movimiento, codigo, nombre_material, cantidad,
                persona_responsable, destino, detalle_destino, stock_resultante
            ) VALUES (
                :fecha, :tipo_movimiento, :codigo, :nombre_material, :cantidad,
                :persona_responsable, :destino, :detalle_destino, :stock_resultante
            )
        """),
        _dict_insert_bodega_movimientos(params),
    )


def _registrar_movimiento_bodega_transaccion(
    fecha,
    tipo_movimiento,
    codigo,
    nombre_material,
    cantidad_digitada,
    persona_responsable,
    destino,
    nuevo_stock,
    detalle_destino="",
):
    destino_prin, detalle_auto = _parse_destino_bodega(destino)
    params_hist = {
        "fecha": str(fecha),
        "tipo_movimiento": str(tipo_movimiento),
        "codigo": int(codigo),
        "nombre_material": str(nombre_material),
        "cantidad": int(cantidad_digitada),
        "persona_responsable": str(persona_responsable).strip(),
        "destino": destino_prin,
        "detalle_destino": str(detalle_destino or detalle_auto).strip(),
        "stock_resultante": int(nuevo_stock),
    }
    with conn.session as session:
        session.execute(
            text("""
                UPDATE bodega_inventario
                SET cantidad = :nuevo_stock
                WHERE codigo = :codigo
            """),
            {"nuevo_stock": int(nuevo_stock), "codigo": int(codigo)},
        )
        session.execute(
            text("""
                INSERT INTO bodega_movimientos (
                    fecha, tipo_movimiento, codigo, nombre_material, cantidad,
                    persona_responsable, destino, stock_resultante
                ) VALUES (
                    :fecha, :tipo_movimiento, :codigo, :nombre_material, :cantidad,
                    :persona_responsable, :destino, :stock_resultante
                )
            """),
            params_hist,
        )
        session.commit()


def cargar_bodega_movimientos_sql(ttl=0):
    try:
        df_raw = conn.query(
            """
            SELECT id, fecha, tipo_movimiento, codigo, nombre_material, cantidad,
                   persona_responsable, destino, detalle_destino, stock_resultante
            FROM bodega_movimientos
            ORDER BY fecha DESC NULLS LAST, id DESC
            """,
            ttl=ttl,
        )
        if df_raw is None or df_raw.empty:
            return pd.DataFrame(columns=COLUMNAS_BODEGA_MOVIMIENTOS)
        out = df_raw.copy()
        out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
        for col in COLUMNAS_BODEGA_MOVIMIENTOS:
            if col not in out.columns:
                out[col] = 0 if col in ("id", "codigo", "cantidad", "stock_resultante") else ""
        out["id"] = pd.to_numeric(out["id"], errors="coerce").fillna(0).astype(int)
        out["codigo"] = pd.to_numeric(out["codigo"], errors="coerce").fillna(0).astype(int)
        out["cantidad"] = pd.to_numeric(out["cantidad"], errors="coerce").fillna(0).astype(int)
        out["stock_resultante"] = pd.to_numeric(out["stock_resultante"], errors="coerce").fillna(0).astype(int)
        return out[COLUMNAS_BODEGA_MOVIMIENTOS]
    except Exception as e:
        st.warning(f"⚠️ Nota SQL bodega_movimientos: {e}")
        return pd.DataFrame(columns=COLUMNAS_BODEGA_MOVIMIENTOS)

def sincronizar_bodega_stock_sql(df_stock):
    ok = True
    for _, row in sanitizar_bodega_stock(df_stock).iterrows():
        ok = (
            actualizar_metadatos_stock_sql(
                int(row["codigo"]),
                int(row["familia"]),
                row["nombre_material"],
                row["descripcion"],
                row["unidad"],
            )
            and ok
        )
    if ok:
        recargar_bodega_desde_sql()
    return ok

# ==========================================
# PERSISTENCIA PROYECTOS (Supabase SQL)
# ==========================================
CATEGORIAS_PROYECTO_GASTO = ["Materiales", "Comida", "Gastos Asociados", "Otros"]

COLUMNAS_PROYECTOS = ["nombre", "empresa", "ciudad", "num_oc", "cobro"]

def sanitizar_proyectos_df(df):
    """DataFrame proyectos con columnas snake_case (empresa, num_oc, cobro)."""
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=COLUMNAS_PROYECTOS)
    out = _renombrar_legacy_a_snake(df.copy())
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    for col in COLUMNAS_PROYECTOS:
        if col not in out.columns:
            out[col] = 0 if col == "cobro" else ""
    out["cobro"] = pd.to_numeric(out["cobro"], errors="coerce").fillna(0).astype(int)
    out["nombre"] = out["nombre"].astype(str).str.strip()
    out["empresa"] = out["empresa"].astype(str)
    out["ciudad"] = out["ciudad"].astype(str)
    out["num_oc"] = out["num_oc"].astype(str)
    return out[COLUMNAS_PROYECTOS]

COLUMNAS_PROYECTO_EQUIPO = [
    "proyecto", "trabajador", "cargo_proyecto", "horas_asignadas", "costo_hora_estimado",
]
COLUMNAS_PROYECTO_GASTOS_SQL = ["proyecto", "item", "categoria", "monto"]
COLUMNAS_PROYECTO_PRESUPUESTO = ["proyecto", "concepto", "cantidad", "precio_unitario", "monto"]

def _finalizar_cambio_proyectos_ui(mensaje=None):
    st.cache_data.clear()
    if mensaje:
        st.session_state["_flash_guardado_ok"] = mensaje
    st.rerun()

def cargar_proyectos_sql(ttl=0):
    try:
        df_raw = conn.query(
            "SELECT nombre, empresa, ciudad, num_oc, cobro FROM proyectos ORDER BY nombre",
            ttl=ttl,
        )
        return sanitizar_proyectos_df(df_raw)
    except Exception as e:
        st.sidebar.warning(f"SQL proyectos: {e}")
        return pd.DataFrame(columns=COLUMNAS_PROYECTOS)

def insertar_proyecto_sql(nombre, empresa, ciudad, num_oc, refrescar_ui=True):
    """Inserta proyecto (cobro = 0; se define al final en Cierre Económico)."""
    try:
        nombre_var = normalizar_texto_manual(nombre, "titulo")
        if not nombre_var:
            st.error("El nombre del proyecto es obligatorio.")
            return False
        empresa_var = normalizar_texto_manual(empresa or "", "titulo")
        ciudad_var = normalizar_texto_manual(ciudad or "", "titulo") or "No especificada"
        num_oc_var = str(num_oc or "").strip() or "Pendiente"
        with conn.session as session:
            session.execute(
                text("""
                    INSERT INTO proyectos (nombre, empresa, ciudad, num_oc, cobro)
                    VALUES (:nombre, :empresa, :ciudad, :num_oc, 0)
                """),
                {
                    "nombre": nombre_var,
                    "empresa": empresa_var,
                    "ciudad": ciudad_var,
                    "num_oc": num_oc_var,
                },
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("¡Proyecto creado exitosamente!")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al crear proyecto: {e}")
        return False

def actualizar_cobro_proyecto_sql(nombre_proyecto, cobro, refrescar_ui=True, mensaje_flash=None):
    """Actualiza cobro acordado del proyecto por nombre (p. ej. monto total cotizado)."""
    try:
        nombre_var = str(nombre_proyecto).strip()
        if not nombre_var:
            st.error("Proyecto no válido.")
            return False
        cobro_var = int(round(a_numerico_clp(cobro)))
        with conn.session as session:
            session.execute(
                text("""
                    UPDATE proyectos SET cobro = :cobro WHERE nombre = :nombre_proyecto
                """),
                {"cobro": cobro_var, "nombre_proyecto": nombre_var},
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui(
                mensaje_flash or "Cobro acordado sincronizado con el presupuesto."
            )
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al actualizar cobro: {e}")
        return False

def obtener_cobro_proyecto_sql(nombre_proyecto, ttl=0):
    """Cobro acordado del proyecto (= monto total cotizado mostrado en presupuestos)."""
    nombre_proyecto = str(nombre_proyecto).strip()
    df_p = cargar_proyectos_sql(ttl=ttl)
    if df_p.empty:
        return 0
    mask = df_p["nombre"].astype(str) == nombre_proyecto
    if not mask.any():
        return 0
    return int(df_p.loc[mask, "cobro"].iloc[0])

def cargar_proyecto_equipo_sql(ttl=0):
    try:
        df_raw = conn.query(
            """
            SELECT id, proyecto, trabajador, cargo_proyecto, horas_asignadas, costo_hora_estimado
            FROM proyecto_equipo
            ORDER BY proyecto, trabajador
            """,
            ttl=ttl,
        )
        if df_raw is None or df_raw.empty:
            return pd.DataFrame(columns=COLUMNAS_PROYECTO_EQUIPO)
        out = df_raw.copy()
        out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
        if "id" in out.columns:
            out = out.drop(columns=["id"])
        for col in COLUMNAS_PROYECTO_EQUIPO:
            if col not in out.columns:
                out[col] = 0.0 if col in ("horas_asignadas", "costo_hora_estimado") else ""
        out["horas_asignadas"] = pd.to_numeric(out["horas_asignadas"], errors="coerce").fillna(0.0)
        out["costo_hora_estimado"] = pd.to_numeric(out["costo_hora_estimado"], errors="coerce").fillna(0.0)
        return out[COLUMNAS_PROYECTO_EQUIPO]
    except Exception as e:
        st.sidebar.warning(f"SQL proyecto_equipo: {e}")
        return pd.DataFrame(columns=COLUMNAS_PROYECTO_EQUIPO)

def insertar_proyecto_equipo_sql(proyecto, trabajador, cargo_proyecto, horas_asignadas, costo_hora_estimado, refrescar_ui=True):
    try:
        params = {
            "proyecto": str(proyecto).strip(),
            "trabajador": str(trabajador).strip(),
            "cargo_proyecto": normalizar_texto_manual(cargo_proyecto, "titulo"),
            "horas_asignadas": float(horas_asignadas),
            "costo_hora_estimado": float(costo_hora_estimado),
        }
        with conn.session as session:
            session.execute(
                text("""
                    INSERT INTO proyecto_equipo (
                        proyecto, trabajador, cargo_proyecto, horas_asignadas, costo_hora_estimado
                    ) VALUES (
                        :proyecto, :trabajador, :cargo_proyecto, :horas_asignadas, :costo_hora_estimado
                    )
                """),
                params,
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Personal asignado al proyecto.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al asignar equipo: {e}")
        return False

def eliminar_proyecto_equipo_sql(proyecto, trabajador, refrescar_ui=True):
    try:
        with conn.session as session:
            session.execute(
                text("""
                    DELETE FROM proyecto_equipo
                    WHERE proyecto = :proyecto AND trabajador = :trabajador
                """),
                {"proyecto": str(proyecto).strip(), "trabajador": str(trabajador).strip()},
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Miembro eliminado del equipo.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al eliminar del equipo: {e}")
        return False

def cargar_proyecto_gastos_sql(ttl=0):
    try:
        df_raw = conn.query(
            """
            SELECT id, proyecto, item, categoria, monto
            FROM proyecto_gastos
            ORDER BY proyecto, id
            """,
            ttl=ttl,
        )
        if df_raw is None or df_raw.empty:
            return pd.DataFrame(columns=COLUMNAS_PROYECTO_GASTOS_SQL)
        out = df_raw.copy()
        out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
        if "id" in out.columns:
            out = out.drop(columns=["id"])
        for col in COLUMNAS_PROYECTO_GASTOS_SQL:
            if col not in out.columns:
                out[col] = 0 if col == "monto" else ""
        out["monto"] = pd.to_numeric(out["monto"], errors="coerce").fillna(0).astype(int)
        return out[COLUMNAS_PROYECTO_GASTOS_SQL]
    except Exception as e:
        st.sidebar.warning(f"SQL proyecto_gastos: {e}")
        return pd.DataFrame(columns=COLUMNAS_PROYECTO_GASTOS_SQL)

def insertar_proyecto_gasto_sql(proyecto, item, categoria, monto, refrescar_ui=True):
    try:
        cat = str(categoria).strip()
        if cat not in CATEGORIAS_PROYECTO_GASTO:
            cat = "Otros"
        params = {
            "proyecto": str(proyecto).strip(),
            "item": normalizar_texto_manual(item, "oracion"),
            "categoria": cat,
            "monto": int(round(a_numerico_clp(monto))),
        }
        with conn.session as session:
            session.execute(
                text("""
                    INSERT INTO proyecto_gastos (proyecto, item, categoria, monto)
                    VALUES (:proyecto, :item, :categoria, :monto)
                """),
                params,
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Gasto registrado en el proyecto.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al registrar gasto: {e}")
        return False

def eliminar_proyecto_gasto_sql(proyecto, item, refrescar_ui=True):
    try:
        with conn.session as session:
            session.execute(
                text("""
                    DELETE FROM proyecto_gastos
                    WHERE proyecto = :proyecto AND item = :item
                """),
                {"proyecto": str(proyecto).strip(), "item": str(item).strip()},
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Gasto eliminado.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al eliminar gasto: {e}")
        return False

def cargar_proyecto_presupuesto_sql(ttl=0):
    try:
        df_raw = conn.query(
            """
            SELECT id, proyecto, concepto, cantidad, precio_unitario, monto
            FROM proyecto_presupuesto
            ORDER BY proyecto, id
            """,
            ttl=ttl,
        )
        if df_raw is None or df_raw.empty:
            return pd.DataFrame(columns=["id"] + COLUMNAS_PROYECTO_PRESUPUESTO)
        out = df_raw.copy()
        out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
        for col in COLUMNAS_PROYECTO_PRESUPUESTO:
            if col not in out.columns:
                out[col] = 1.0 if col == "cantidad" else (0 if col == "monto" else "")
        out["cantidad"] = pd.to_numeric(out["cantidad"], errors="coerce").fillna(1.0)
        out["precio_unitario"] = pd.to_numeric(out["precio_unitario"], errors="coerce").fillna(0).astype(int)
        out["monto"] = pd.to_numeric(out["monto"], errors="coerce").fillna(0).astype(int)
        return out
    except Exception as e:
        st.sidebar.warning(f"SQL proyecto_presupuesto: {e}")
        return pd.DataFrame(columns=["id"] + COLUMNAS_PROYECTO_PRESUPUESTO)

def insertar_proyecto_presupuesto_linea_sql(
    proyecto, concepto, cantidad, precio_unitario, refrescar_ui=True
):
    try:
        cant = float(cantidad)
        if cant <= 0:
            st.error("La cantidad debe ser mayor a 0.")
            return False
        precio = int(round(a_numerico_clp(precio_unitario)))
        monto_linea = int(round(cant * precio))
        params = {
            "proyecto": str(proyecto).strip(),
            "concepto": normalizar_texto_manual(concepto, "oracion"),
            "cantidad": cant,
            "precio_unitario": precio,
            "monto": monto_linea,
        }
        if not params["concepto"]:
            st.error("El concepto de la partida es obligatorio.")
            return False
        with conn.session as session:
            session.execute(
                text("""
                    INSERT INTO proyecto_presupuesto (
                        proyecto, concepto, cantidad, precio_unitario, monto
                    ) VALUES (
                        :proyecto, :concepto, :cantidad, :precio_unitario, :monto
                    )
                """),
                params,
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Partida de presupuesto agregada.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al registrar partida de presupuesto: {e}")
        return False

def eliminar_proyecto_presupuesto_linea_sql(proyecto, linea_id, refrescar_ui=True):
    try:
        proyecto_var = str(proyecto).strip()
        lid = int(linea_id)
        with conn.session as session:
            session.execute(
                text("""
                    DELETE FROM proyecto_presupuesto
                    WHERE id = :id AND proyecto = :proyecto
                """),
                {"id": lid, "proyecto": proyecto_var},
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Partida de presupuesto eliminada.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al eliminar partida: {e}")
        return False

def eliminar_proyecto_completo_sql(nombre_proyecto, refrescar_ui=True):
    nombre_proyecto = str(nombre_proyecto).strip()
    try:
        with conn.session as session:
            session.execute(
                text("DELETE FROM proyecto_gastos WHERE proyecto = :proyecto"),
                {"proyecto": nombre_proyecto},
            )
            session.execute(
                text("DELETE FROM proyecto_presupuesto WHERE proyecto = :proyecto"),
                {"proyecto": nombre_proyecto},
            )
            session.execute(
                text("DELETE FROM proyecto_equipo WHERE proyecto = :proyecto"),
                {"proyecto": nombre_proyecto},
            )
            session.execute(
                text("DELETE FROM operaciones_tareas WHERE proyecto = :proyecto"),
                {"proyecto": nombre_proyecto},
            )
            session.execute(
                text("DELETE FROM proyectos WHERE nombre = :proyecto"),
                {"proyecto": nombre_proyecto},
            )
            session.commit()
        if refrescar_ui:
            _finalizar_cambio_proyectos_ui("Proyecto eliminado correctamente.")
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al eliminar proyecto: {e}")
        return False

def calcular_costo_hora_trabajador(trabajador):
    """Costo hora estimado desde nómina / liquidaciones."""
    trabajador = str(trabajador).strip()
    df_liq, _ = calcular_liquidaciones(cargar_nomina_sql(ttl=0))
    fila_liq = df_liq[df_liq["trabajador"] == trabajador]
    if fila_liq.empty:
        return 0.0
    costo_emp = float(fila_liq.iloc[0]["Costo Empresa"])
    nom = cargar_nomina_sql(ttl=0)
    fila_nom = nom[nom["trabajador"] == trabajador]
    jornada = float(fila_nom.iloc[0]["jornada_hrs"]) if not fila_nom.empty else 44.0
    if jornada <= 0:
        return 0.0
    return (costo_emp / 30) * 28 / jornada

def calcular_gastos_totales_proyecto(nombre_proyecto):
    """Mano de obra (equipo) + montos de proyecto_gastos."""
    nombre_proyecto = str(nombre_proyecto).strip()
    eq = cargar_proyecto_equipo_sql(ttl=0)
    eq = eq[eq["proyecto"] == nombre_proyecto]
    costo_mo = float((eq["horas_asignadas"] * eq["costo_hora_estimado"]).sum()) if not eq.empty else 0.0
    gast = cargar_proyecto_gastos_sql(ttl=0)
    gast = gast[gast["proyecto"] == nombre_proyecto]
    costo_gast = float(gast["monto"].sum()) if not gast.empty else 0.0
    return costo_mo + costo_gast

def mapa_cargo_proyecto_por_trabajador(nombre_proyecto):
    eq = cargar_proyecto_equipo_sql(ttl=0)
    eq = eq[eq["proyecto"] == str(nombre_proyecto).strip()]
    if eq.empty:
        return {}
    return dict(zip(eq["trabajador"].astype(str), eq["cargo_proyecto"].astype(str)))

def enriquecer_tareas_con_cargo_proyecto(df_tareas, nombre_proyecto=None):
    """Añade columna 'cargo': prioriza cargo_proyecto de proyecto_equipo por obra."""
    out = sanitizar_operaciones_tareas(df_tareas).copy()
    nom = cargar_nomina_sql(ttl=0)
    mapa_nom = (
        dict(zip(nom["trabajador"].astype(str), nom["cargo"].astype(str)))
        if not nom.empty and "cargo" in nom.columns
        else {}
    )
    mapa_cache = {}
    cargos = []
    for _, row in out.iterrows():
        trab = str(row["trabajador"])
        proy = str(row["proyecto"])
        if proy not in mapa_cache:
            mapa_cache[proy] = mapa_cargo_proyecto_por_trabajador(proy)
        cargo = mapa_cache[proy].get(trab, "") or mapa_nom.get(trab, "")
        cargos.append(str(cargo).strip())
    out["cargo"] = cargos
    return out

def _reparar_df_columnas_numericas(df, columnas_esperadas):
    """Si el DataFrame tiene columnas 0,1,2… (execute crudo), asigna nombres snake_case."""
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=list(columnas_esperadas))
    cols = list(df.columns)
    if cols and all(str(c).isdigit() for c in cols):
        # Supabase devuelve id SERIAL como primera columna → desplaza el mapeo y vacía 'cargo'
        start = 1 if len(cols) >= len(columnas_esperadas) + 1 else 0
        n = min(len(columnas_esperadas), len(cols) - start)
        out = df.iloc[:, start : start + n].copy()
        out.columns = list(columnas_esperadas[:n])
        return out
    return df

def cargar_nomina_sql(ttl=0):
    """Lectura fresca desde Supabase (ttl=0 → sin caché de conn.query)."""
    try:
        df_raw = conn.query(
            """
            SELECT rut, trabajador, cargo, sueldo_base, jornada_hrs, tipo_contrato,
                   gratificacion, afp, dias_falta, horas_atraso, horas_extras,
                   colacion, movilizacion, anticipo
            FROM asistencia_nomina
            """,
            ttl=ttl,
        )
        if "id" in df_raw.columns:
            df_raw = df_raw.drop(columns=["id"])
        df_raw = _reparar_df_columnas_numericas(df_raw, COLUMNAS_NOMINA)
        df = _df_desde_sql(df_raw, COLUMNAS_NOMINA)
        cols = [c for c in COLUMNAS_NOMINA if c in df.columns]
        if cols:
            df = df[cols]
        return sanitizar_nomina(df)
    except Exception as e:
        st.sidebar.warning(f"SQL asistencia_nomina: {e}")
        return pd.DataFrame(columns=COLUMNAS_NOMINA)

def _params_nomina_row(row):
    """Mapea una fila (formulario / data_editor) al diccionario de parámetros SQL."""
    rut_raw = str(row["rut"]).strip()
    return {
        "rut": formatear_rut(rut_raw) if rut_raw else "",
        "trabajador": normalizar_texto_manual(row["trabajador"], "titulo"),
        "cargo": normalizar_texto_manual(row.get("cargo", ""), "titulo"),
        "sueldo_base": int(round(a_numerico_clp(row.get("sueldo_base", 0)))),
        "jornada_hrs": int(round(a_numerico_clp(row.get("jornada_hrs", 44)))),
        "tipo_contrato": str(row.get("tipo_contrato", "Indefinido")),
        "gratificacion": str(row.get("gratificacion", "")),
        "afp": str(row.get("afp", "")),
        "dias_falta": float(a_numerico_clp(row.get("dias_falta", 0))),
        "horas_atraso": int(round(a_numerico_clp(row.get("horas_atraso", 0)))),
        "horas_extras": int(round(a_numerico_clp(row.get("horas_extras", 0)))),
        "colacion": int(round(a_numerico_clp(row.get("colacion", 0)))),
        "movilizacion": int(round(a_numerico_clp(row.get("movilizacion", 0)))),
        "anticipo": int(round(a_numerico_clp(row.get("anticipo", 0)))),
    }

def _dict_params_nomina_sql(p):
    """Diccionario explícito para session.execute (nombres alineados a columnas Supabase)."""
    return {
        "rut": p["rut"],
        "trabajador": p["trabajador"],
        "cargo": p["cargo"],
        "sueldo_base": p["sueldo_base"],
        "jornada_hrs": p["jornada_hrs"],
        "tipo_contrato": p["tipo_contrato"],
        "gratificacion": p["gratificacion"],
        "afp": p["afp"],
        "dias_falta": p["dias_falta"],
        "horas_atraso": p["horas_atraso"],
        "horas_extras": p["horas_extras"],
        "colacion": p["colacion"],
        "movilizacion": p["movilizacion"],
        "anticipo": p["anticipo"],
    }

def _upsert_fila_nomina_en_sesion(session, row, rut_anterior=None):
    """UPDATE por rut; si no existe fila, INSERT con text() parametrizado."""
    p = _params_nomina_row(row)
    if not p["rut"] or not p["trabajador"]:
        raise ValueError("RUT y trabajador son obligatorios para guardar en asistencia_nomina.")
    rut_prev = str(rut_anterior).strip() if rut_anterior else ""
    rut_where = formatear_rut(rut_prev) if rut_prev else p["rut"]
    params_sql = _dict_params_nomina_sql(p)
    res = session.execute(
        text("""
            UPDATE asistencia_nomina SET
                rut = :rut, trabajador = :trabajador, cargo = :cargo,
                sueldo_base = :sueldo_base, jornada_hrs = :jornada_hrs,
                tipo_contrato = :tipo_contrato, gratificacion = :gratificacion, afp = :afp,
                dias_falta = :dias_falta, horas_atraso = :horas_atraso, horas_extras = :horas_extras,
                colacion = :colacion, movilizacion = :movilizacion, anticipo = :anticipo
            WHERE rut = :rut_where
        """),
        {**params_sql, "rut_where": rut_where},
    )
    if res.rowcount == 0:
        session.execute(
            text("""
                INSERT INTO asistencia_nomina (
                    rut, trabajador, cargo, sueldo_base, jornada_hrs,
                    tipo_contrato, gratificacion, afp, dias_falta,
                    horas_atraso, horas_extras, colacion, movilizacion, anticipo
                ) VALUES (
                    :rut, :trabajador, :cargo, :sueldo_base, :jornada_hrs,
                    :tipo_contrato, :gratificacion, :afp, :dias_falta,
                    :horas_atraso, :horas_extras, :colacion, :movilizacion, :anticipo
                )
            """),
            params_sql,
        )

def _finalizar_guardado_nomina_ui(mensaje=None, refrescar=True):
    """Tras commit: limpia caché, mensaje de éxito y rerun (tabla + liquidaciones)."""
    st.session_state.nomina = cargar_nomina_sql()
    rev = int(st.session_state.get("nomina_rev", 0)) + 1
    st.session_state.nomina_rev = rev
    st.session_state.pop(f"ed_nomina_{rev - 1}", None)
    st.session_state.pop("ed_nomina", None)
    st.cache_data.clear()
    if refrescar:
        st.success(mensaje or "¡Guardado exitosamente en la nube!")
        st.rerun()

def guardar_fila_nomina_sql(row, rut_anterior=None, refrescar_ui=True):
    """Upsert de una fila en asistencia_nomina (transacción con commit explícito)."""
    try:
        with conn.session as session:
            _upsert_fila_nomina_en_sesion(session, row, rut_anterior=rut_anterior)
            session.commit()
        if refrescar_ui:
            _finalizar_guardado_nomina_ui()
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al guardar nómina en SQL: {e}")
        return False

def sincronizar_nomina_sql(df, mensaje_flash=None, refrescar=True):
    """Sincroniza todo el DataFrame con asistencia_nomina en una sola transacción."""
    df = sanitizar_nomina(df)
    df = df[df["rut"].astype(str).str.strip() != ""].copy()
    if df.empty:
        st.warning("No hay trabajadores con RUT válido para guardar en Supabase.")
        return False
    try:
        ruts_vivos = []
        with conn.session as session:
            for _, row in df.iterrows():
                _upsert_fila_nomina_en_sesion(session, row)
                ruts_vivos.append(formatear_rut(row["rut"]))
            if ruts_vivos:
                stmt = text(
                    "DELETE FROM asistencia_nomina WHERE rut NOT IN :ruts"
                ).bindparams(bindparam("ruts", expanding=True))
                session.execute(stmt, {"ruts": ruts_vivos})
            session.commit()
        if refrescar:
            _finalizar_guardado_nomina_ui(mensaje_flash)
        else:
            st.session_state.nomina = cargar_nomina_sql()
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al sincronizar asistencia_nomina: {e}")
        return False

def eliminar_trabajador_nomina_sql(rut, refrescar_ui=True):
    try:
        with conn.session as session:
            session.execute(
                text("DELETE FROM asistencia_nomina WHERE rut = :rut"),
                {"rut": formatear_rut(rut)},
            )
            session.commit()
        if refrescar_ui:
            _finalizar_guardado_nomina_ui("Trabajador eliminado de la nube.")
        else:
            st.session_state.nomina = cargar_nomina_sql()
        return True
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al eliminar trabajador: {e}")
        return False

COLOR_ESTADO_OPS = {
    "⚪ Pendiente": "#94a3b8",
    "🟡 En Proceso": "#eab308",
    "🔴 Estancado": "#ef4444",
    "🟢 Listo": "#22c55e",
}

# Intentar importar FPDF de forma segura
try:
    from fpdf import FPDF
    FPDF_DISPONIBLE = True
except ImportError:
    FPDF_DISPONIBLE = False

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD VISUAL
# ==========================================
ocultar_menu_estilo = """
            <style>
            [data-testid="stHeaderActionElements"] {display: none !important;}
            footer {display: none !important;}
            .block-container {
                padding-top: 1.5rem !important;
                padding-bottom: 2rem !important;
            }
            [data-testid="column"] img {
                max-height: 45px !important;
                width: auto !important;
                display: block;
            }
            div[role="radiogroup"] { display: none !important; }
            </style>
            """
st.markdown(ocultar_menu_estilo, unsafe_allow_html=True)

LOGO_URL = "logo.png"

# ==========================================
# 2. CONEXIÓN A GOOGLE SHEETS
# ==========================================
@st.cache_resource(ttl=GSHEETS_CACHE_TTL)
def _libro_google_sheets_cached():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    secreto = st.secrets["google_credentials"]
    if isinstance(secreto, str):
        creds_dict = json.loads(secreto.strip())
    else:
        creds_dict = dict(secreto)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("Base de Datos Voltify")

def conectar_google_sheets():
    try:
        return _libro_google_sheets_cached()
    except Exception as e:
        st.error(f"🚨 ERROR CRÍTICO DE CONEXIÓN: {e}")
        st.stop()

def obtener_o_crear_hoja(libro, nombre_hoja, columnas):
    try:
        return libro.worksheet(nombre_hoja)
    except gspread.exceptions.WorksheetNotFound:
        hoja = libro.add_worksheet(title=nombre_hoja, rows="100", cols=str(len(columnas)))
        hoja.append_row(columnas)
        return hoja

def _columnas_cache_key(columnas) -> str:
    return "\x1f".join(list(columnas))

def invalidar_cache_hoja(nombre_hoja, df_default=None, columnas=None):
    """Invalida solo la entrada en caché de una hoja (no borra toda la app)."""
    if columnas is not None:
        cols = list(columnas)
    elif df_default is not None:
        cols = df_default.columns.tolist()
    else:
        return
    try:
        _cargar_hoja_sheets_cached.clear(nombre_hoja, _columnas_cache_key(cols))
    except Exception:
        _cargar_hoja_sheets_cached.clear()

def limpiar_cache_streamlit(hojas_invalidar=None):
    """Invalida lecturas de Sheets indicadas. Sin argumentos, no vacía cache_data global."""
    if not hojas_invalidar:
        return
    for item in hojas_invalidar:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            nombre, extra = item[0], item[1]
            if isinstance(extra, pd.DataFrame):
                invalidar_cache_hoja(nombre, df_default=extra)
            else:
                invalidar_cache_hoja(nombre, columnas=extra)
        elif isinstance(item, str):
            invalidar_cache_hoja(item)

def mostrar_mensaje_guardado_flash():
    """Muestra el mensaje de éxito guardado antes del rerun automático."""
    msg = st.session_state.pop("_flash_guardado_ok", None)
    if msg:
        st.success(msg)
        if hasattr(st, "toast"):
            st.toast(msg, icon="✅")

def refrescar_app_tras_guardado(ok, mensaje=None, hojas_invalidar=None):
    """Invalida caché de hojas afectadas y rerun (sin recargar todo Sheets)."""
    if not ok:
        return False
    limpiar_cache_streamlit(hojas_invalidar)
    if mensaje:
        st.session_state["_flash_guardado_ok"] = mensaje
    st.rerun()

def guardar_datos(nombre_hoja, df, refrescar_ui=False, mensaje_flash=None, hojas_invalidar=None):
    try:
        libro = conectar_google_sheets()
        df_clean = df.fillna(0)
        
        columnas_str = [
            'rut', 'gratificacion', 'tipo_contrato', 'fecha_inicio', 'fecha_termino', 'Fecha_Emision',
            'Num_OC', 'Fecha_Inicio_Proy', 'Fecha_Termino_Proy', 'Duracion_Proy', 'Nro_Serie',
            'nombre_material', 'descripcion', 'unidad', 'tipo_movimiento', 'persona_responsable', 'destino', 'fecha',
            'prioridad', 'estado', 'tarea', 'proyecto', 'trabajador',
        ]
        for col in columnas_str:
            if col in df_clean.columns: df_clean[col] = df_clean[col].astype(str)
            
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df_clean.columns.tolist())
        hoja.clear()
        hoja.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
        if refrescar_ui:
            inv = hojas_invalidar if hojas_invalidar is not None else [(nombre_hoja, df)]
            refrescar_app_tras_guardado(True, mensaje_flash, hojas_invalidar=inv)
        return True
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")
        return False

def guardar_datos_diferido(nombre_hoja, df):
    """Encola persistencia (Supabase para Operaciones; Sheets para el resto)."""
    if nombre_hoja == "Operaciones_Tareas":
        st.session_state.operaciones_tareas = sanitizar_operaciones_tareas(df.copy())
        st.session_state._sql_pending_ops = True
        return
    if "_gs_pending" not in st.session_state:
        st.session_state._gs_pending = {}
    st.session_state._gs_pending[nombre_hoja] = df.copy()

def flush_guardados_diferidos(refrescar_ui=False, mensaje_flash=None):
    """Flush encolado: operaciones_tareas → Supabase; demás hojas → Google Sheets."""
    if st.session_state.pop("_sql_pending_ops", False):
        return sincronizar_operaciones_tareas_sql(
            st.session_state.operaciones_tareas,
            mensaje_flash=mensaje_flash,
            refrescar=refrescar_ui,
        )
    pending = st.session_state.pop("_gs_pending", None) or {}
    if not pending:
        return True
    ok = True
    for nombre_hoja, df in pending.items():
        ok = guardar_datos(nombre_hoja, df) and ok
    if ok and refrescar_ui:
        inv = [(nombre, pending[nombre]) for nombre in pending.keys()]
        refrescar_app_tras_guardado(True, mensaje_flash, hojas_invalidar=inv)
    return ok

def eliminar_fila_google_sheet(nombre_hoja, row_number_1_indexed):
    """
    Elimina una fila (1-indexed) directamente desde Google Sheets.
    Nota: la fila 1 normalmente es el header.
    """
    try:
        if not isinstance(row_number_1_indexed, int) or row_number_1_indexed < 2:
            raise ValueError("row_number_1_indexed inválido (debe ser >= 2).")
        libro = conectar_google_sheets()
        hoja = libro.worksheet(nombre_hoja)
        hoja.delete_rows(row_number_1_indexed)
        return True
    except Exception as e:
        st.error(f"Error al eliminar fila en Google Sheets: {e}")
        return False

@st.cache_data(ttl=GSHEETS_CACHE_TTL, show_spinner=False)
def _cargar_hoja_sheets_cached(nombre_hoja: str, columnas_key: str) -> pd.DataFrame:
    columnas = columnas_key.split("\x1f")
    df_default = pd.DataFrame(columns=columnas)
    try:
        libro = conectar_google_sheets()
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, columnas)
        datos = hoja.get_all_records()
        if not datos:
            return df_default
        return pd.DataFrame(datos)
    except Exception:
        return df_default

def cargar_datos(nombre_hoja, df_default):
    """Lectura con caché de 10 min; usar invalidar_cache_hoja() tras guardar."""
    key = _columnas_cache_key(df_default.columns.tolist())
    return _cargar_hoja_sheets_cached(nombre_hoja, key).copy()

# ==========================================
# 3. DATOS BASE Y CÁLCULOS
# ==========================================
TASAS_AFP = {
    "Capital (11.44%)": 0.1144, "Cuprum (11.44%)": 0.1144, "Habitat (11.27%)": 0.1127,
    "Modelo (10.58%)": 0.1058, "PlanVital (11.16%)": 0.1116, "ProVida (11.45%)": 0.1145,
    "Uno (10.69%)": 0.1069
}

def formatear_clp(valor):
    try:
        return f"${int(valor):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "$0"

formato_clp = formatear_clp

def formatear_rut(rut_sucio):
    rut = "".join(c for c in str(rut_sucio) if c.isalnum()).upper()
    if not rut:
        return ""
    cuerpo = rut[:-1]
    dv = rut[-1]
    if len(cuerpo) > 0:
        try:
            cuerpo_formateado = f"{int(cuerpo):,}".replace(",", ".")
            return f"{cuerpo_formateado}-{dv}"
        except ValueError:
            return rut
    return rut

def normalizar_texto_manual(valor, estilo="oracion"):
    """Normaliza texto ingresado a mano antes de guardar (formato oración)."""
    return cosmetic_oracion(valor)

def cosmetic_oracion(valor):
    """Maquillaje UI: primera letra mayúscula (sin tocar datos en SQL)."""
    s = str(valor or "").strip()
    if not s:
        return s
    return s.capitalize()

def etiqueta_ui(texto):
    """Label de widget Streamlit con inicial mayúscula."""
    s = str(texto or "").strip()
    if not s:
        return s
    return s[0].upper() + s[1:] if len(s) > 1 else s.upper()

_COLUMNAS_EXCLUIR_MAQUILLAJE = frozenset({
    "estado", "prioridad", "rut", "codigo", "id", "afp", "tipo_contrato",
    "gratificacion", "aprobacion", "orden_compra", "estado_comercial", "tipo",
    "num_oc", "referencia", "tipo_movimiento", "unidad", "contrato", "nombre_afp",
})

def df_maquillaje_visual(df, columnas=None, excluir=None):
    """Copia cosmética para st.dataframe / st.data_editor (no modifica el DF original)."""
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    excl = _COLUMNAS_EXCLUIR_MAQUILLAJE | frozenset(excluir or ())
    if columnas is not None:
        cols = [c for c in columnas if c in out.columns]
    else:
        cols = [
            c for c in out.columns
            if str(c).lower() not in excl
            and (out[c].dtype == object or str(out[c].dtype) == "string")
        ]
    def _cap_celda(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return v
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none"):
            return v
        return s.capitalize()

    for c in cols:
        out[c] = out[c].apply(_cap_celda)
    return out

def mostrar_tabla(df, **kwargs):
    st.dataframe(df_maquillaje_visual(df), **kwargs)

def mostrar_editor(df, **kwargs):
    return st.data_editor(df_maquillaje_visual(df), **kwargs)

def a_numerico_clp(valor, default=0.0):
    """Convierte montos desde número, texto CLP o celdas corruptas a float."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return float(default)
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if not s or s.lower() in ("nan", "none", "format"):
        return float(default)
    s = s.replace(".", "").replace(",", "").replace("$", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return float(default)

COLUMNAS_NOMINA = [
    "rut", "trabajador", "cargo", "sueldo_base", "jornada_hrs", "tipo_contrato",
    "gratificacion", "afp", "dias_falta", "horas_atraso", "horas_extras",
    "colacion", "movilizacion", "anticipo",
]

def sanitizar_nomina(df):
    """Asegura tipos numéricos en nómina (snake_case)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_NOMINA)
    out = _reparar_df_columnas_numericas(df, COLUMNAS_NOMINA)
    out = _renombrar_legacy_a_snake(out.copy())
    cols_numericas = {
        "sueldo_base", "jornada_hrs", "dias_falta", "horas_atraso", "horas_extras",
        "colacion", "movilizacion", "anticipo",
    }
    for col in COLUMNAS_NOMINA:
        if col not in out.columns:
            out[col] = 0 if col in cols_numericas else ""
    out = out[[c for c in COLUMNAS_NOMINA if c in out.columns]]
    enteros = ["sueldo_base", "colacion", "movilizacion", "anticipo", "horas_atraso", "horas_extras", "jornada_hrs"]
    decimales = ["dias_falta"]
    for col in enteros:
        out[col] = out[col].apply(lambda v, c=col: int(round(a_numerico_clp(v))))
    for col in decimales:
        out[col] = out[col].apply(lambda v, c=col: float(a_numerico_clp(v)))
    for col in ("trabajador", "cargo", "tipo_contrato", "gratificacion", "afp"):
        if col in out.columns:
            out[col] = out[col].apply(
                lambda v: str(v).strip() if pd.notna(v) else v
            )
    if "rut" in out.columns:
        out["rut"] = out["rut"].apply(
            lambda v: (
                formatear_rut(v)
                if str(v).strip() and str(v).strip().lower() not in ("sin registro", "nan")
                else str(v).strip()
            )
        )
    if "trabajador" in out.columns:
        out["trabajador"] = out["trabajador"].apply(
            lambda v: normalizar_texto_manual(v, "titulo") if pd.notna(v) and str(v).strip() else v
        )
    if "cargo" in out.columns:
        out["cargo"] = out["cargo"].apply(
            lambda v: normalizar_texto_manual(v, "titulo") if pd.notna(v) and str(v).strip() else v
        )
    return out

if 'nomina_rev' not in st.session_state:
    st.session_state.nomina_rev = 0

if 'nomina' not in st.session_state:
    st.session_state.nomina = cargar_nomina_sql()
    if st.session_state.nomina.empty:
        st.session_state.nomina = sanitizar_nomina(pd.DataFrame([{
            "rut": "11.111.111-1",
            "trabajador": "Begoñia Mac-Conell Bacho", "cargo": "Jefa de administracion y finanzas",
            "sueldo_base": 850000, "jornada_hrs": 44, "tipo_contrato": "Indefinido",
            "gratificacion": "Tope Legal Mensual", "afp": "Habitat (11.27%)",
            "dias_falta": 0, "horas_atraso": 0, "horas_extras": 0, "colacion": 0, "movilizacion": 0, "anticipo": 0,
        }]))
        sincronizar_nomina_sql(st.session_state.nomina, mensaje_flash=None, refrescar=False)

columnas_obligatorias = ["dias_falta", "horas_atraso", "horas_extras", "colacion", "movilizacion", "anticipo"]
for col in columnas_obligatorias:
    if col not in st.session_state.nomina.columns:
        st.session_state.nomina[col] = 0
st.session_state.nomina = sanitizar_nomina(st.session_state.nomina)

if 'rut' not in st.session_state.nomina.columns:
    st.session_state.nomina['rut'] = "Sin Registro"

if 'presupuestos' not in st.session_state:
    df_presupuestos_base = pd.DataFrame(columns=["Tipo", "Referencia", "Cliente", "Monto", "Aprobacion", "Orden_Compra", "Num_OC", "Estado_Comercial", "Fecha_Emision"])
    st.session_state.presupuestos = cargar_datos("Presupuestos", df_presupuestos_base)

if 'proyectos_resumen' not in st.session_state:
    df_resumen_base = pd.DataFrame(columns=["Proyecto", "Empresa", "Ciudad", "Num_OC", "Cobro", "Fecha_Inicio_Proy", "Fecha_Termino_Proy", "Duracion_Proy"])
    st.session_state.proyectos_resumen = cargar_datos("Proyectos_Resumen", df_resumen_base)

if 'proyectos_gastos' not in st.session_state:
    df_gastos_base = pd.DataFrame(columns=["Proyecto", "Detalle_Gasto", "Monto", "Dias_Asignados"])
    st.session_state.proyectos_gastos = cargar_datos("Proyectos_Gastos", df_gastos_base)

def sanitizar_proyectos_gastos(df):
    """Unifica columna de proyecto en minúsculas (Sheets usa 'Proyecto' legacy)."""
    cols = ["proyecto", "Detalle_Gasto", "Monto", "Dias_Asignados"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    out = _renombrar_legacy_a_snake(df.copy())
    if "proyecto" not in out.columns:
        out["proyecto"] = ""
    for col in cols:
        if col not in out.columns:
            out[col] = 0 if col in ("Monto", "Dias_Asignados") else ""
    out["Monto"] = pd.to_numeric(out["Monto"], errors="coerce").fillna(0)
    out["Dias_Asignados"] = pd.to_numeric(out["Dias_Asignados"], errors="coerce").fillna(0)
    out["Detalle_Gasto"] = out["Detalle_Gasto"].astype(str)
    out["proyecto"] = out["proyecto"].astype(str).str.strip()
    return out[cols]

def proyectos_gastos_para_sheets(df):
    """Exporta a Google Sheets con encabezado 'Proyecto'."""
    d = sanitizar_proyectos_gastos(df)
    return d.rename(columns={"proyecto": "Proyecto"})

if 'Dias_Asignados' not in st.session_state.proyectos_gastos.columns:
    st.session_state.proyectos_gastos['Dias_Asignados'] = 0
st.session_state.proyectos_gastos = sanitizar_proyectos_gastos(st.session_state.proyectos_gastos)

# Días hábiles de referencia para imputación proporcional de costo mensual (asignación de personal en proyectos)
DIAS_MES_REFERENCIA_ASIGNACION = 22

if 'proyectos_equipo' not in st.session_state:
    df_equipo_base = pd.DataFrame(columns=["Proyecto", "Trabajador", "Rol_Proyecto"])
    st.session_state.proyectos_equipo = cargar_datos("Proyectos_Equipo", df_equipo_base)

COLUMNAS_OPERACIONES_TAREAS = [
    "tarea", "proyecto", "trabajador", "estado", "prioridad",
    "fecha_inicio", "fecha_termino", "dias_duracion",
]
ESTADOS_TAREA_OPERACIONES = ["⚪ Pendiente", "🟡 En Proceso", "🔴 Estancado", "🟢 Listo"]
PRIORIDADES_TAREA = ["🔥 Alta", "⚡ Media", "💤 Baja"]

def normalizar_estado_tarea(valor):
    s = str(valor or "").strip()
    if s in ESTADOS_TAREA_OPERACIONES:
        return s
    sl = s.lower()
    if "listo" in sl or "terminad" in sl or "complet" in sl:
        return "🟢 Listo"
    if "estancad" in sl:
        return "🔴 Estancado"
    if "proceso" in sl or "curso" in sl:
        return "🟡 En Proceso"
    return "⚪ Pendiente"

def _fecha_tarea_a_str(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return datetime.date.today().strftime("%Y-%m-%d")
        if isinstance(val, datetime.date):
            return val.strftime("%Y-%m-%d")
        d = pd.to_datetime(str(val).strip(), errors="coerce")
        if pd.isna(d):
            return datetime.date.today().strftime("%Y-%m-%d")
        return d.date().strftime("%Y-%m-%d")
    except Exception:
        return datetime.date.today().strftime("%Y-%m-%d")

def normalizar_prioridad_tarea(valor):
    s = str(valor or "").strip()
    if s in PRIORIDADES_TAREA:
        return s
    sl = s.lower()
    if "alta" in sl or "🔥" in s:
        return "🔥 Alta"
    if "media" in sl or "⚡" in s:
        return "⚡ Media"
    return "💤 Baja"

def sanitizar_operaciones_tareas(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_OPERACIONES_TAREAS)
    out = _renombrar_legacy_a_snake(df.copy())
    ids = pd.to_numeric(out["id"], errors="coerce") if "id" in out.columns else None
    for col in COLUMNAS_OPERACIONES_TAREAS:
        if col not in out.columns:
            if col == "prioridad":
                out[col] = "💤 Baja"
            elif col == "estado":
                out[col] = "⚪ Pendiente"
            elif col == "dias_duracion":
                out[col] = float("nan")
            else:
                out[col] = ""
    out = out[COLUMNAS_OPERACIONES_TAREAS]
    out["estado"] = out["estado"].apply(normalizar_estado_tarea)
    out["prioridad"] = out["prioridad"].apply(normalizar_prioridad_tarea)
    out["fecha_inicio"] = out["fecha_inicio"].apply(_fecha_tarea_a_str)
    out["fecha_termino"] = out["fecha_termino"].apply(_fecha_tarea_a_str)
    out["dias_duracion"] = pd.to_numeric(out["dias_duracion"], errors="coerce")
    if ids is not None:
        out.insert(0, "id", ids.values)
    return out

if 'operaciones_tareas' not in st.session_state:
    st.session_state.operaciones_tareas = cargar_operaciones_tareas_sql()

if 'ops_tareas_rev' not in st.session_state:
    st.session_state.ops_tareas_rev = 0

if 'gastos_fijos' not in st.session_state:
    df_fijos_base = pd.DataFrame([{"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000}, {"Descripción": "prioridad emergencias", "Monto (CLP)": 50000}])
    st.session_state.gastos_fijos = cargar_datos("Gastos_Fijos", df_fijos_base)

COLUMNAS_BODEGA_STOCK = ["codigo", "familia", "nombre_material", "descripcion", "cantidad", "unidad"]
COLUMNAS_BODEGA_HISTORIAL = [
    "fecha", "tipo_movimiento", "codigo", "nombre_material", "cantidad",
    "persona_responsable", "destino", "stock_resultante",
]
COLUMNAS_BODEGA_MOVIMIENTOS = [
    "id", "fecha", "tipo_movimiento", "codigo", "nombre_material", "cantidad",
    "persona_responsable", "destino", "detalle_destino", "stock_resultante",
]

def sanitizar_bodega_stock(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_BODEGA_STOCK)
    out = _reparar_df_columnas_numericas(df, COLUMNAS_BODEGA_STOCK)
    out = _renombrar_legacy_a_snake(out.copy())
    for col in COLUMNAS_BODEGA_STOCK:
        if col not in out.columns:
            out[col] = "" if col in ("nombre_material", "descripcion", "unidad") else 0
    out = out[COLUMNAS_BODEGA_STOCK]
    out["codigo"] = pd.to_numeric(out["codigo"], errors="coerce").fillna(0).astype(int)
    out["familia"] = pd.to_numeric(out["familia"], errors="coerce").fillna(0).astype(int)
    out["cantidad"] = pd.to_numeric(out["cantidad"], errors="coerce").fillna(0).round(0).astype(int)
    out["nombre_material"] = out["nombre_material"].astype(str).str.strip()
    out["descripcion"] = out["descripcion"].astype(str)
    out["unidad"] = out["unidad"].astype(str).replace({"0": "un", "": "un"})
    out = out[out["codigo"] > 0].drop_duplicates(subset=["codigo"], keep="last")
    return out.reset_index(drop=True)

def sanitizar_bodega_historial(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_BODEGA_HISTORIAL)
    out = _reparar_df_columnas_numericas(df, COLUMNAS_BODEGA_HISTORIAL)
    out = _renombrar_legacy_a_snake(out.copy())
    for col in COLUMNAS_BODEGA_HISTORIAL:
        if col not in out.columns:
            out[col] = 0 if col in ("codigo", "cantidad", "stock_resultante") else ""
    out = out[COLUMNAS_BODEGA_HISTORIAL]
    out["codigo"] = pd.to_numeric(out["codigo"], errors="coerce").fillna(0).astype(int)
    out["cantidad"] = pd.to_numeric(out["cantidad"], errors="coerce").fillna(0).round(0).astype(int)
    out["stock_resultante"] = pd.to_numeric(out["stock_resultante"], errors="coerce").fillna(0).round(0).astype(int)
    out["fecha"] = out["fecha"].astype(str)
    out["tipo_movimiento"] = out["tipo_movimiento"].astype(str)
    out["nombre_material"] = out["nombre_material"].astype(str)
    out["persona_responsable"] = out["persona_responsable"].astype(str)
    out["destino"] = out["destino"].astype(str)
    return out.reset_index(drop=True)

if 'bodega_stock' not in st.session_state or 'bodega_historial' not in st.session_state:
    _bod_stock, _bod_hist = cargar_bodega_inventario_sql()
    st.session_state.bodega_stock = _bod_stock
    st.session_state.bodega_historial = _bod_hist

def sugerir_codigo_bodega(df_stock, familia):
    """Siguiente código entero en la partida (ej. familia 400 → 401, 402…)."""
    familia = int(familia)
    df = sanitizar_bodega_stock(df_stock)
    en_familia = df[(df["codigo"] > familia) & (df["codigo"] < familia + 100)]
    if en_familia.empty:
        return familia + 1
    return int(en_familia["codigo"].max()) + 1

def opciones_material_bodega(df_stock):
    df = sanitizar_bodega_stock(df_stock)
    if df.empty:
        return [], {}
    opts = []
    mapa = {}
    for _, r in df.iterrows():
        cod = int(r["codigo"])
        label = f"{cod} — {r['nombre_material']} (stock: {int(r['cantidad'])})"
        opts.append(label)
        mapa[label] = cod
    return opts, mapa

def guardar_operaciones_tareas(mensaje_flash=None):
    """Persiste el tablero en operaciones_tareas (Supabase) y refresca la UI."""
    return sincronizar_operaciones_tareas_sql(
        st.session_state.operaciones_tareas,
        mensaje_flash=mensaje_flash or "¡Tarea guardada exitosamente en Supabase!",
        refrescar=True,
    )

def recargar_bodega_stock_desde_sheets():
    """Recarga stock e historial desde bodega_inventario (Supabase)."""
    recargar_bodega_desde_sql()

def stock_actual_material(codigo):
    """Stock entero actual de un código en session_state."""
    stock = sanitizar_bodega_stock(st.session_state.bodega_stock)
    fila = stock[stock["codigo"] == int(codigo)]
    if fila.empty:
        return None
    return int(fila.iloc[0]["cantidad"])

def registrar_movimiento_bodega(codigo, cantidad, tipo_mov, fecha, persona, destino):
    """
    Consulta stock actual, calcula Entrada/Salida, UPDATE inventario + INSERT historial (una transacción).
    Retorna (ok, mensaje, stock_resultante o None).
    """
    cantidad_digitada = int(round(float(cantidad)))
    if cantidad_digitada <= 0:
        return False, "La cantidad debe ser un entero mayor a 0.", None

    codigo = int(codigo)
    tipo_movimiento = str(tipo_mov).strip()

    fila_stock = obtener_stock_actual_bodega_sql(codigo, ttl=0)
    if fila_stock is None:
        return False, f"No existe material con código {codigo}.", None

    stock_actual = int(fila_stock["cantidad"])
    nombre_material = str(fila_stock["nombre_material"])

    if _es_entrada_bodega(tipo_movimiento):
        nuevo_stock = stock_actual + cantidad_digitada
    elif _es_salida_bodega(tipo_movimiento):
        nuevo_stock = stock_actual - cantidad_digitada
    else:
        return False, "Tipo de movimiento inválido (use Entrada o Salida).", None

    if nuevo_stock < 0:
        return False, f"Cantidad insuficiente en bodega. Stock actual: {stock_actual}", stock_actual

    fecha_str = fecha.strftime("%Y-%m-%d") if hasattr(fecha, "strftime") else str(fecha)
    persona_norm = normalizar_texto_manual(persona, "titulo")
    destino_norm = str(destino).strip()

    try:
        _registrar_movimiento_bodega_transaccion(
            fecha=fecha_str,
            tipo_movimiento=tipo_movimiento,
            codigo=codigo,
            nombre_material=nombre_material,
            cantidad_digitada=cantidad_digitada,
            persona_responsable=persona_norm,
            destino=destino_norm,
            nuevo_stock=nuevo_stock,
        )
        recargar_bodega_desde_sql()
        msg_ok = f"{tipo_movimiento} registrada. Stock actualizado: {nuevo_stock} un."
        refrescar_widgets_bodega_tras_movimiento(mensaje_flash=msg_ok, rerun=True)
        return True, msg_ok, nuevo_stock
    except Exception as e:
        try:
            conn.session.rollback()
        except Exception:
            pass
        st.error(f"Error al registrar movimiento: {e}")
        return False, str(e), None

def refrescar_widgets_bodega_tras_movimiento(mensaje_flash=None, rerun=True):
    """Sincroniza UI tras cambio de stock en Supabase."""
    rev_anterior = int(st.session_state.get("bod_stock_rev", 0))
    st.session_state.bod_stock_rev = rev_anterior + 1
    st.session_state.pop(f"ed_bodega_stock_{rev_anterior}", None)
    st.session_state.pop("ed_bodega_stock", None)
    if rerun:
        refrescar_sql_ui(mensaje_flash)
    elif hasattr(st, "cache_data"):
        st.cache_data.clear()

st.session_state.bodega_stock = sanitizar_bodega_stock(st.session_state.bodega_stock)
st.session_state.bodega_historial = sanitizar_bodega_historial(st.session_state.bodega_historial)

def df_formateado_clp(df: pd.DataFrame, columnas_monto: list[str]) -> pd.DataFrame:
    """
    Devuelve una copia del DF con columnas de monto formateadas como CLP ($ con miles, sin decimales),
    sin modificar el dataframe original (útil para st.dataframe/st.table).
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    for c in columnas_monto:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).apply(formatear_clp)
    return out

# --- Capacidad mensual de trabajadores (días hábiles) ---
def dias_habiles_en_mes(year, month):
    """Cantidad de lunes a viernes en el mes."""
    last = calendar.monthrange(year, month)[1]
    n = 0
    for d in range(1, last + 1):
        if datetime.date(year, month, d).weekday() < 5:
            n += 1
    return max(n, 1)

def contar_dias_habiles_rango(f_ini, f_fin):
    """Días hábiles entre dos fechas (inclusive)."""
    if f_ini is None or f_fin is None or f_fin < f_ini:
        return 0
    n = 0
    cur = f_ini
    while cur <= f_fin:
        if cur.weekday() < 5:
            n += 1
        cur += datetime.timedelta(days=1)
    return n

def parse_fecha_celda(val):
    if val is None:
        return None
    try:
        if isinstance(val, float) and pd.isna(val):
            return None
    except Exception:
        pass
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        s = str(val).strip()
        if not s or s.lower() == "pendiente":
            return None
        return pd.to_datetime(s, errors="coerce").date()
    except Exception:
        return None

def tarea_activa_capacidad(estado):
    s = str(estado or "").lower()
    return not any(x in s for x in ("listo", "terminad", "complet"))

def filtrar_tareas_operaciones(df, proyecto, trabajador, estado):
    out = sanitizar_operaciones_tareas(df)
    if proyecto and proyecto != "Todos":
        out = out[out["proyecto"] == proyecto]
    if trabajador and trabajador != "Todos":
        out = out[out["trabajador"] == trabajador]
    if estado and estado != "Todos":
        out = out[out["estado"] == estado]
    return out

def filtrar_tareas_rango_fechas(df, fecha_desde, fecha_hasta):
    """Tareas cuyo cronograma intersecta el rango [fecha_desde, fecha_hasta]."""
    if df is None or df.empty:
        return df
    if fecha_desde is None or fecha_hasta is None:
        return df
    if fecha_hasta < fecha_desde:
        fecha_desde, fecha_hasta = fecha_hasta, fecha_desde
    filas = []
    for idx, row in df.iterrows():
        fi = parse_fecha_celda(row.get("fecha_inicio"))
        ff = parse_fecha_celda(row.get("fecha_termino"))
        if not fi or not ff:
            continue
        if ff < fi:
            fi, ff = ff, fi
        if fi <= fecha_hasta and ff >= fecha_desde:
            filas.append(idx)
    if not filas:
        return df.iloc[0:0]
    return df.loc[filas]

def tarea_solapa_mes(f_ini, f_fin, year, month):
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, calendar.monthrange(year, month)[1])
    return f_ini <= last and f_fin >= first

def df_distribucion_mes(df_tareas, year, month):
    rows = []
    for _, row in sanitizar_operaciones_tareas(df_tareas).iterrows():
        fi = parse_fecha_celda(row.get("fecha_inicio"))
        ff = parse_fecha_celda(row.get("fecha_termino"))
        if not fi or not ff:
            continue
        if ff < fi:
            fi, ff = ff, fi
        if not tarea_solapa_mes(fi, ff, year, month):
            continue
        cargo_val = ""
        if "cargo" in row.index:
            cargo_val = str(row.get("cargo", "") or "").strip()
        if not cargo_val:
            mapa_c = mapa_cargo_proyecto_por_trabajador(str(row["proyecto"]))
            cargo_val = mapa_c.get(str(row["trabajador"]), "")
        rows.append({
            "trabajador": row["trabajador"],
            "proyecto": row["proyecto"],
            "cargo": cargo_val,
            "tarea": row["tarea"],
            "estado": row["estado"],
            "prioridad": row["prioridad"],
            "Inicio": fi.strftime("%d/%m/%Y"),
            "Término": ff.strftime("%d/%m/%Y"),
        })
    if not rows:
        return pd.DataFrame(columns=[
            "trabajador", "proyecto", "cargo", "tarea", "estado", "prioridad", "Inicio", "Término",
        ])
    return pd.DataFrame(rows)

def detectar_solapes_mes(df_tareas, year, month):
    avisos = []
    df = sanitizar_operaciones_tareas(df_tareas)
    for trab in sorted(df["trabajador"].dropna().unique()):
        bloques = []
        for _, row in df[df["trabajador"] == trab].iterrows():
            fi = parse_fecha_celda(row.get("fecha_inicio"))
            ff = parse_fecha_celda(row.get("fecha_termino"))
            if not fi or not ff:
                continue
            if ff < fi:
                fi, ff = ff, fi
            if tarea_solapa_mes(fi, ff, year, month):
                bloques.append((str(row["tarea"]), str(row["proyecto"]), fi, ff))
        bloques.sort(key=lambda x: x[2])
        for i in range(len(bloques) - 1):
            t1, p1, a1, b1 = bloques[i]
            t2, p2, a2, b2 = bloques[i + 1]
            if b1 >= a2:
                avisos.append(f"**{trab}**: «{t1}» ({p1}) se superpone con «{t2}» ({p2}).")
    return avisos

def carga_trabajador_mes(df_tareas, trabajador, year, month):
    """
    Suma días hábiles asignados al trabajador en el mes, en todos los proyectos.
    Reparte la duración (Dias_Duracion o días hábiles del rango) proporcionalmente
    según los días hábiles del rango que caen en ese mes.
    """
    df = df_tareas[df_tareas["trabajador"] == trabajador]
    total = 0.0
    for _, row in df.iterrows():
        if not tarea_activa_capacidad(row.get("estado")):
            continue
        f_ini = parse_fecha_celda(row.get("fecha_inicio"))
        f_fin = parse_fecha_celda(row.get("fecha_termino"))
        if f_ini is None or f_fin is None:
            continue
        if f_fin < f_ini:
            f_ini, f_fin = f_fin, f_ini
        wd_total = contar_dias_habiles_rango(f_ini, f_fin)
        first = datetime.date(year, month, 1)
        last = datetime.date(year, month, calendar.monthrange(year, month)[1])
        d0 = max(f_ini, first)
        d1 = min(f_fin, last)
        wd_mes = contar_dias_habiles_rango(d0, d1) if d0 <= d1 else 0
        if wd_mes <= 0:
            continue
        dd = row.get("dias_duracion")
        try:
            dd = float(dd) if dd is not None and str(dd).strip() != "" and not (isinstance(dd, float) and pd.isna(dd)) else None
        except (ValueError, TypeError):
            dd = None
        if dd is not None and dd > 0:
            total += dd * (wd_mes / max(wd_total, 1e-9))
        else:
            total += wd_mes
    return total

MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

def etiqueta_mes_corto(year, month):
    return f"{MESES_CORTOS[month - 1]} {year}"

def avanzar_mes(year, month, delta=1):
    m0 = month - 1 + delta
    y = year + m0 // 12
    m = m0 % 12 + 1
    return y, m

def tabla_capacidad_personal(df_tareas, lista_trabajadores, year, month):
    """Una fila por trabajador: tope mensual, días asignados, balance y %."""
    cap = dias_habiles_en_mes(year, month)
    rows = []
    for trab in sorted(lista_trabajadores):
        asign = carga_trabajador_mes(df_tareas, trab, year, month)
        disp = cap - asign
        pct = (asign / cap) * 100 if cap else 0.0
        rows.append({
            "trabajador": trab,
            "Días hábiles (tope mes)": cap,
            "Días asignados": round(asign, 1),
            "Días disponibles": round(disp, 1),
            "% vs capacidad": round(pct, 1),
        })
    return pd.DataFrame(rows)

def tabla_proyeccion_carga_meses(df_tareas, lista_trabajadores, year, month, n_meses):
    """Columnas por mes: días asignados estimados por trabajador."""
    rows = []
    for trab in sorted(lista_trabajadores):
        row = {"trabajador": trab}
        y, m = year, month
        for _ in range(n_meses):
            lab = etiqueta_mes_corto(y, m)
            row[lab] = round(carga_trabajador_mes(df_tareas, trab, y, m), 1)
            y, m = avanzar_mes(y, m, 1)
        rows.append(row)
    return pd.DataFrame(rows)

def tabla_referencia_dias_habiles(year, month, n_meses):
    """Días hábiles de calendario por mes (referencia para la estimación)."""
    rows = []
    y, m = year, month
    for _ in range(n_meses):
        rows.append({
            "Mes": etiqueta_mes_corto(y, m),
            "Días hábiles (lun–vie)": dias_habiles_en_mes(y, m),
        })
        y, m = avanzar_mes(y, m, 1)
    return pd.DataFrame(rows)

_st_fragment = getattr(st, "fragment", lambda f: f)

@_st_fragment
def render_panel_capacidad_trabajadores(df_tareas, lista_trabajadores, key_suffix="cap"):
    """Selector de mes + tabla resumen (días asignados, disponibles, %). Sin alertas de sobrecarga."""
    hoy = datetime.date.today()
    col_a, col_b = st.columns(2)
    meses_nombres = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    with col_a:
        y = st.number_input("Año", 2020, 2035, hoy.year, key=f"cap_y_{key_suffix}")
    with col_b:
        m = st.selectbox(
            "Mes",
            list(range(1, 13)),
            format_func=lambda i: meses_nombres[i - 1],
            index=hoy.month - 1,
            key=f"cap_m_{key_suffix}",
        )
    if not lista_trabajadores:
        st.info("No hay trabajadores en nómina para mostrar capacidad.")
        return
    df_tab = tabla_capacidad_personal(df_tareas, lista_trabajadores, y, m)
    mostrar_tabla(df_tab, width="stretch", hide_index=True)

def _wos_cambiar_estado_tarea(idx, nuevo_estado, mensaje="Estado actualizado"):
    st.session_state.operaciones_tareas.at[idx, "estado"] = normalizar_estado_tarea(nuevo_estado)
    guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
    flush_guardados_diferidos(refrescar_ui=True, mensaje_flash=mensaje)

def _render_wos_tablero(proyecto_seg):
    """Tablero Kanban / lista (dentro del fragmento Work OS)."""
    df_ops_seg = enriquecer_tareas_con_cargo_proyecto(
        cargar_operaciones_tareas_sql(ttl=0), proyecto_seg
    )
    tareas_proy = df_ops_seg[df_ops_seg["proyecto"] == proyecto_seg]
    lista_trabajadores_nomina = st.session_state.nomina["trabajador"].tolist()
    if not lista_trabajadores_nomina:
        st.info("Agrega trabajadores en la pestaña de 'Finanzas' para poder asignarles tareas.")
        return

    with st.expander("➕ Añadir Nueva Tarea al Tablero", expanded=False):
        colT1, colT2 = st.columns([1, 2])
        encargado_tarea = colT1.selectbox("Asignar a (Desde Nómina):", lista_trabajadores_nomina, key=f"wos_new_asig_{proyecto_seg}")
        desc_tarea = colT2.text_input("Descripción de la Tarea:", placeholder="Ej: Instalar tablero eléctrico principal", key=f"wos_new_desc_{proyecto_seg}")
        colT3, colT4 = st.columns(2)
        f_ini_tarea = colT3.date_input("Fecha Inicio Tarea", format="DD/MM/YYYY", key=f"wos_new_ini_{proyecto_seg}")
        f_fin_tarea = colT4.date_input("Fecha Fin Tarea", format="DD/MM/YYYY", key=f"wos_new_fin_{proyecto_seg}")
        fi_ok, ff_ok = f_ini_tarea, f_fin_tarea
        if ff_ok < fi_ok:
            fi_ok, ff_ok = ff_ok, fi_ok
        wd_sugeridos = max(1, contar_dias_habiles_rango(fi_ok, ff_ok))
        dias_duracion_nueva = st.number_input(
            "Días de duración (hábiles)",
            min_value=0.5,
            step=0.5,
            value=float(wd_sugeridos),
            help="Se imputan a la capacidad mensual del trabajador (suma en todos los proyectos).",
            key=f"dur_nueva_{proyecto_seg}",
        )
        if st.button("Crear Tarea", width="stretch", key=f"wos_btn_new_{proyecto_seg}"):
            if desc_tarea:
                nueva_tarea = pd.DataFrame([{
                    "tarea": cosmetic_oracion(desc_tarea),
                    "proyecto": proyecto_seg,
                    "trabajador": encargado_tarea,
                    "estado": "⚪ Pendiente",
                    "prioridad": "💤 Baja",
                    "fecha_inicio": f_ini_tarea.strftime("%Y-%m-%d"),
                    "fecha_termino": f_fin_tarea.strftime("%Y-%m-%d"),
                    "dias_duracion": float(dias_duracion_nueva),
                }])
                st.session_state.operaciones_tareas = pd.concat(
                    [st.session_state.operaciones_tareas, nueva_tarea], ignore_index=True
                )
                guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
                flush_guardados_diferidos(
                    refrescar_ui=True,
                    mensaje_flash="¡Tarea guardada exitosamente en Supabase!",
                )
            else:
                st.error("Escribe una descripción para la tarea.")

    if tareas_proy.empty:
        st.info("No hay tareas registradas para este proyecto en el tablero.")
        return

    col_filt1, col_filt2 = st.columns([1, 2])
    trabajadores_con_tareas = tareas_proy["trabajador"].unique().tolist()
    filtro_trabajador = col_filt1.selectbox(
        "🔍 Filtrar por Asignado:", ["👥 Todos"] + trabajadores_con_tareas, key=f"wos_filtro_{proyecto_seg}"
    )
    tipo_vista = col_filt2.radio(
        "Modo de Vista:", ["📌 Kanban Interactivo", "📋 Edición en Lista"], horizontal=True, key=f"wos_vista_{proyecto_seg}"
    )
    st.divider()

    if filtro_trabajador != "👥 Todos":
        df_vista_filtrada = tareas_proy[tareas_proy["trabajador"] == filtro_trabajador].copy()
        mask_reemplazo = (
            (st.session_state.operaciones_tareas["proyecto"] == proyecto_seg)
            & (st.session_state.operaciones_tareas["trabajador"] == filtro_trabajador)
        )
    else:
        df_vista_filtrada = tareas_proy.copy()
        mask_reemplazo = st.session_state.operaciones_tareas["proyecto"] == proyecto_seg

    if tipo_vista == "📌 Kanban Interactivo":
        col_pend, col_proc, col_est, col_listo = st.columns(4)
        with col_pend:
            st.markdown("<h4 style='text-align: center; color: #94a3b8;'>⚪ Pendiente</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["estado"] == "⚪ Pendiente"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{cosmetic_oracion(row['tarea'])}**")
                    cargo_w = cosmetic_oracion(str(row.get("cargo", "") or ""))
                    cap_extra = f" · {cargo_w}" if cargo_w else ""
                    st.caption(f"👤 {cosmetic_oracion(row['trabajador'])}{cap_extra} | 📅 {row['fecha_termino']}")
                    if st.button("▶️ Iniciar", key=f"start_{proyecto_seg}_{idx}", width="stretch"):
                        _wos_cambiar_estado_tarea(idx, "🟡 En Proceso", "Tarea en proceso")

        with col_proc:
            st.markdown("<h4 style='text-align: center; color: #eab308;'>🟡 En Proceso</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["estado"] == "🟡 En Proceso"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{cosmetic_oracion(row['tarea'])}**")
                    cargo_w = cosmetic_oracion(str(row.get("cargo", "") or ""))
                    cap_extra = f" · {cargo_w}" if cargo_w else ""
                    st.caption(f"👤 {cosmetic_oracion(row['trabajador'])}{cap_extra} | 📅 {row['fecha_termino']}")
                    c1, c2 = st.columns(2)
                    if c1.button("⏸️ Estancar", key=f"pause_{proyecto_seg}_{idx}", width="stretch"):
                        _wos_cambiar_estado_tarea(idx, "🔴 Estancado", "Tarea estancada")
                    if c2.button("✅ Listo", key=f"done_{proyecto_seg}_{idx}", width="stretch"):
                        _wos_cambiar_estado_tarea(idx, "🟢 Listo", "Tarea completada")

        with col_est:
            st.markdown("<h4 style='text-align: center; color: #ef4444;'>🔴 Estancado</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["estado"] == "🔴 Estancado"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{cosmetic_oracion(row['tarea'])}**")
                    cargo_w = cosmetic_oracion(str(row.get("cargo", "") or ""))
                    cap_extra = f" · {cargo_w}" if cargo_w else ""
                    st.caption(f"👤 {cosmetic_oracion(row['trabajador'])}{cap_extra} | 📅 {row['fecha_termino']}")
                    if st.button("▶️ Reanudar", key=f"resume_{proyecto_seg}_{idx}", width="stretch"):
                        _wos_cambiar_estado_tarea(idx, "🟡 En Proceso", "Tarea reanudada")

        with col_listo:
            st.markdown("<h4 style='text-align: center; color: #22c55e;'>🟢 Listo</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["estado"] == "🟢 Listo"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{cosmetic_oracion(row['tarea'])}**")
                    cargo_w = cosmetic_oracion(str(row.get("cargo", "") or ""))
                    cap_extra = f" · {cargo_w}" if cargo_w else ""
                    st.caption(f"👤 {cosmetic_oracion(row['trabajador'])}{cap_extra} | 📅 {row['fecha_termino']}")
                    if st.button("↩️ Reabrir", key=f"revert_{proyecto_seg}_{idx}", width="stretch"):
                        _wos_cambiar_estado_tarea(idx, "🟡 En Proceso", "Tarea reabierta")
    else:
        df_vista_filtrada = df_vista_filtrada.copy()
        df_vista_filtrada["fecha_inicio"] = pd.to_datetime(df_vista_filtrada["fecha_inicio"], errors="coerce").dt.date
        df_vista_filtrada["fecha_termino"] = pd.to_datetime(df_vista_filtrada["fecha_termino"], errors="coerce").dt.date
        if "dias_duracion" not in df_vista_filtrada.columns:
            df_vista_filtrada["dias_duracion"] = 1.0
        df_vista_filtrada["dias_duracion"] = pd.to_numeric(df_vista_filtrada["dias_duracion"], errors="coerce").fillna(1.0)

        df_tareas_editadas = mostrar_editor(
            df_vista_filtrada,
            column_config={
                "tarea": st.column_config.TextColumn("Tarea"),
                "proyecto": st.column_config.TextColumn("Proyecto"),
                "trabajador": st.column_config.TextColumn("Trabajador"),
                "estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS_TAREA_OPERACIONES),
                "prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORIDADES_TAREA),
                "fecha_inicio": st.column_config.DateColumn("Inicio"),
                "fecha_termino": st.column_config.DateColumn("Fin"),
                "dias_duracion": st.column_config.NumberColumn("Días duración (háb.)", min_value=0.5, step=0.5, format="%.1f"),
            },
            disabled=["proyecto", "trabajador", "tarea"],
            hide_index=True,
            width="stretch",
            key=f"ed_tar_{proyecto_seg}",
        )

        if st.button("💾 Guardar Progreso de Tareas", type="primary", key=f"wos_save_lista_{proyecto_seg}"):
            df_tareas_editadas["fecha_inicio"] = df_tareas_editadas["fecha_inicio"].astype(str)
            df_tareas_editadas["fecha_termino"] = df_tareas_editadas["fecha_termino"].astype(str)
            df_tareas_editadas["dias_duracion"] = pd.to_numeric(df_tareas_editadas["dias_duracion"], errors="coerce").fillna(1.0)
            st.session_state.operaciones_tareas = st.session_state.operaciones_tareas[~mask_reemplazo]
            st.session_state.operaciones_tareas = pd.concat(
                [st.session_state.operaciones_tareas, df_tareas_editadas], ignore_index=True
            )
            guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
            flush_guardados_diferidos(
                refrescar_ui=True,
                mensaje_flash="¡Tarea guardada exitosamente en Supabase!",
            )

    st.write("")
    with st.expander("🗑️ Zona de Peligro: Eliminar Tareas"):
        lista_nombres_tareas = [f"{row['tarea']} ({row['trabajador']})" for _, row in df_vista_filtrada.iterrows()]
        if lista_nombres_tareas:
            tarea_a_eliminar = st.selectbox("Selecciona la tarea a eliminar:", lista_nombres_tareas, key=f"wos_del_sel_{proyecto_seg}")
            if st.button("Eliminar Tarea Seleccionada", type="primary", key=f"wos_del_btn_{proyecto_seg}"):
                nombre_tarea = tarea_a_eliminar.rsplit(" (", 1)[0]
                nombre_trab = tarea_a_eliminar.rsplit(" (", 1)[1].replace(")", "")
                mask_eliminar = (
                    (st.session_state.operaciones_tareas["proyecto"] == proyecto_seg)
                    & (st.session_state.operaciones_tareas["tarea"] == nombre_tarea)
                    & (st.session_state.operaciones_tareas["trabajador"] == nombre_trab)
                )
                st.session_state.operaciones_tareas = st.session_state.operaciones_tareas[~mask_eliminar]
                guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
                flush_guardados_diferidos(refrescar_ui=True, mensaje_flash="Tarea eliminada del proyecto.")

def _render_wos_equipo(proyecto_seg):
    """Roles del equipo (dentro del fragmento Work OS)."""
    gastos_proy_seg = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seg]
    trabajadores_financiados = []
    for detalle in gastos_proy_seg["Detalle_Gasto"]:
        detalle_str = str(detalle)
        if detalle_str.startswith("Mano de obra") and ":" in detalle_str:
            nombre = detalle_str.split(":", 1)[1].strip()
            if nombre not in trabajadores_financiados:
                trabajadores_financiados.append(nombre)

    if not trabajadores_financiados:
        st.warning("⚠️ No has asignado personal a este proyecto en la pestaña Finanzas > Proyectos.")
        return

    equipo_actual = st.session_state.proyectos_equipo[st.session_state.proyectos_equipo["Proyecto"] == proyecto_seg]
    trabajadores_en_equipo = equipo_actual["trabajador"].tolist()
    cambios_sync = False
    for trab in trabajadores_financiados:
        if trab not in trabajadores_en_equipo:
            nuevo_eq = pd.DataFrame([{"proyecto": proyecto_seg, "trabajador": trab, "Rol_Proyecto": "Por definir"}])
            st.session_state.proyectos_equipo = pd.concat([st.session_state.proyectos_equipo, nuevo_eq], ignore_index=True)
            cambios_sync = True
    mask_validos = st.session_state.proyectos_equipo["Trabajador"].isin(trabajadores_financiados) | (
        st.session_state.proyectos_equipo["Proyecto"] != proyecto_seg
    )
    if not mask_validos.all():
        st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[mask_validos]
        cambios_sync = True
    if cambios_sync:
        guardar_datos_diferido("Proyectos_Equipo", st.session_state.proyectos_equipo)

    mask_eq = st.session_state.proyectos_equipo["Proyecto"] == proyecto_seg
    df_eq_editar = st.session_state.proyectos_equipo[mask_eq]

    df_eq_mod = mostrar_editor(
        df_eq_editar,
        column_config={
            "Rol_Proyecto": st.column_config.SelectboxColumn(
                "Rol Operativo",
                options=["Por definir", "Líder de Proyecto", "Supervisor", "Técnico Especialista", "Operario", "Prevencionista"],
                required=True,
            )
        },
        disabled=["proyecto", "trabajador"],
        hide_index=True,
        width="stretch",
        key=f"ed_eq_{proyecto_seg}",
    )
    if st.button("💾 Guardar Roles del Equipo", type="primary", key=f"wos_save_eq_{proyecto_seg}"):
        st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[~mask_eq]
        st.session_state.proyectos_equipo = pd.concat([st.session_state.proyectos_equipo, df_eq_mod], ignore_index=True)
        guardar_datos_diferido("Proyectos_Equipo", st.session_state.proyectos_equipo)
        flush_guardados_diferidos(refrescar_ui=True, mensaje_flash="Roles del equipo actualizados.")

@_st_fragment
def _fragment_wos_workspace(proyecto_seg, idx_p_seg):
    """Proyecto activo: reruns aislados del resto del ERP (Finanzas, Balance, etc.)."""
    tareas_proy = st.session_state.operaciones_tareas[
        st.session_state.operaciones_tareas["proyecto"] == proyecto_seg
    ]
    total_t = len(tareas_proy)
    terminadas = len(tareas_proy[tareas_proy["estado"].str.contains("Listo|Terminada", na=False, case=False, regex=True)]) if total_t > 0 else 0
    porc = int((terminadas / total_t) * 100) if total_t > 0 else 0

    st.markdown(f"#### 🚀 Proyecto: {proyecto_seg}")
    st.progress(porc / 100.0, text=f"Progreso Global: {porc}% ({terminadas}/{total_t} Tareas Completadas)")
    st.write("")

    with st.container(border=True):
        st.markdown("##### 📊 Capacidad del equipo por mes")
        lista_nom_cap = st.session_state.nomina["trabajador"].tolist()
        render_panel_capacidad_trabajadores(st.session_state.operaciones_tareas, lista_nom_cap, key_suffix="ops_wos")
    st.write("")

    tab_tablero, tab_gantt, tab_equipo, tab_config = st.tabs(
        ["📌 Tablero de Tareas", "📅 Cronograma (Gantt)", "👥 Equipo de Trabajo", "⚙️ Ajustes de Proyecto"]
    )

    with tab_tablero:
        _render_wos_tablero(proyecto_seg)

    with tab_gantt:
        st.markdown("#### Línea de Tiempo del Proyecto")
        df_gantt = tareas_proy.copy()
        df_gantt["fecha_inicio"] = pd.to_datetime(df_gantt["fecha_inicio"], errors="coerce")
        df_gantt["fecha_termino"] = pd.to_datetime(df_gantt["fecha_termino"], errors="coerce")
        df_gantt = df_gantt.dropna(subset=["fecha_inicio", "fecha_termino"])
        if not df_gantt.empty:
            gantt = alt.Chart(df_gantt).mark_bar(cornerRadius=4, height=20).encode(
                x=alt.X("fecha_inicio:T", title="Fechas"),
                x2=alt.X2("fecha_termino:T"),
                y=alt.Y("tarea:N", sort=alt.EncodingSortField(field="fecha_inicio", order="ascending"), title=""),
                color=alt.Color(
                    "estado:N",
                    scale=alt.Scale(
                        domain=ESTADOS_TAREA_OPERACIONES,
                        range=["#94a3b8", "#eab308", "#ef4444", "#22c55e"],
                    ),
                ),
                tooltip=["tarea", "trabajador", "estado", "fecha_inicio", "fecha_termino"],
            ).properties(height=350)
            st.altair_chart(gantt, width="stretch")
        else:
            st.info("Agrega tareas con fechas válidas en el Tablero para ver la Carta Gantt.")

    with tab_equipo:
        st.markdown("#### Conformación del Equipo y Liderazgo")
        _render_wos_equipo(proyecto_seg)

    with tab_config:
        st.markdown("#### Configuración de Tiempos del Proyecto")
        val_ini = st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Inicio_Proy"]
        val_fin = st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Termino_Proy"]
        val_dur = st.session_state.proyectos_resumen.at[idx_p_seg, "Duracion_Proy"]

        def parse_fecha(f_str):
            try:
                if pd.isna(f_str) or str(f_str).strip() in ["", "Pendiente"]:
                    return None
                return pd.to_datetime(str(f_str)).date()
            except Exception:
                return None

        c_conf1, c_conf2, c_conf3 = st.columns(3)
        nuevo_ini = c_conf1.date_input(
            "Fecha de Inicio Oficial:", value=parse_fecha(val_ini), format="DD/MM/YYYY", key=f"wos_ini_{proyecto_seg}"
        )
        nuevo_fin = c_conf2.date_input(
            "Fecha de Término Oficial:", value=parse_fecha(val_fin), format="DD/MM/YYYY", key=f"wos_fin_{proyecto_seg}"
        )
        nueva_dur = c_conf3.text_input(
            "Duración Estimada:", value="" if val_dur == "Pendiente" else val_dur, placeholder="Ej: 3 meses", key=f"wos_dur_{proyecto_seg}"
        )
        if st.button("Guardar Fechas del Proyecto", type="primary", key=f"wos_cfg_fechas_{proyecto_seg}"):
            str_ini = nuevo_ini.strftime("%Y-%m-%d") if nuevo_ini else "Pendiente"
            str_fin = nuevo_fin.strftime("%Y-%m-%d") if nuevo_fin else "Pendiente"
            st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Inicio_Proy"] = str_ini
            st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Termino_Proy"] = str_fin
            st.session_state.proyectos_resumen.at[idx_p_seg, "Duracion_Proy"] = nueva_dur if nueva_dur else "Pendiente"
            guardar_datos_diferido("Proyectos_Resumen", st.session_state.proyectos_resumen)
            flush_guardados_diferidos(refrescar_ui=True, mensaje_flash="Fechas del proyecto actualizadas.")

def preparar_datos_gantt(df_tareas):
    """DataFrame listo para px.timeline (Start, Finish, etiquetas)."""
    if df_tareas is None or df_tareas.empty:
        return pd.DataFrame()
    out = sanitizar_operaciones_tareas(df_tareas).copy()
    out["Start"] = pd.to_datetime(out["fecha_inicio"], errors="coerce")
    out["Finish"] = pd.to_datetime(out["fecha_termino"], errors="coerce")
    out = out.dropna(subset=["Start", "Finish"])
    if out.empty:
        return out
    invertidas = out["Finish"] < out["Start"]
    if invertidas.any():
        tmp = out.loc[invertidas, "Start"].copy()
        out.loc[invertidas, "Start"] = out.loc[invertidas, "Finish"]
        out.loc[invertidas, "Finish"] = tmp
    mismo_dia = out["Finish"] == out["Start"]
    if mismo_dia.any():
        out.loc[mismo_dia, "Finish"] = out.loc[mismo_dia, "Start"] + pd.Timedelta(days=1)
    out["Barra"] = out["tarea"].astype(str) + " (" + out["proyecto"].astype(str) + ")"
    return out

def figura_gantt_plotly(df_gantt, color_por="estado"):
    if df_gantt is None or df_gantt.empty:
        return None
    color_por = color_por if color_por in ("estado", "proyecto") else "estado"
    fig = px.timeline(
        df_gantt,
        x_start="Start",
        x_end="Finish",
        y="Barra",
        color=color_por,
        color_discrete_map=COLOR_ESTADO_OPS if color_por == "estado" else None,
        custom_data=["trabajador", "proyecto", "estado", "prioridad", "tarea"],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[4]}</b><br>"
            "Responsable: %{customdata[0]}<br>"
            "Proyecto: %{customdata[1]}<br>"
            "Estado: %{customdata[2]}<br>"
            "Prioridad: %{customdata[3]}<br>"
            "%{x|%d/%m/%Y} → %{x2|%d/%m/%Y}<extra></extra>"
        )
    )
    fig.update_layout(
        height=max(420, min(1000, len(df_gantt) * 44)),
        autosize=True,
        xaxis_title="Línea de tiempo",
        yaxis_title="",
        legend_title=color_por,
        margin=dict(l=12, r=12, t=48, b=12),
        bargap=0.12,
    )
    fig.update_yaxes(autorange="reversed")
    return fig

def metricas_rendimiento_operaciones(df_tareas):
    df = sanitizar_operaciones_tareas(df_tareas)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    por_estado = (
        df.groupby("estado", as_index=False)
        .size()
        .rename(columns={"size": "cantidad"})
        .sort_values("cantidad", ascending=False)
    )
    avance_rows = []
    for proy, grp in df.groupby("proyecto"):
        total = len(grp)
        listas = grp["estado"].astype(str).str.contains("Listo|Terminada", case=False, na=False).sum()
        avance_rows.append({
            "proyecto": proy,
            "Avance_%": round((listas / total) * 100, 1) if total else 0.0,
            "Tareas_Listas": int(listas),
            "Tareas_Total": int(total),
        })
    por_proyecto = pd.DataFrame(avance_rows).sort_values("Avance_%", ascending=False)
    return por_estado, por_proyecto

ESTILO_BADGE_ESTADO = {
    "⚪ Pendiente": ("#475569", "#f1f5f9", "#cbd5e1"),
    "🟡 En Proceso": ("#854d0e", "#fef9c3", "#fde047"),
    "🔴 Estancado": ("#991b1b", "#fee2e2", "#fca5a5"),
    "🟢 Listo": ("#166534", "#dcfce7", "#86efac"),
}

def iniciales_responsable(nombre):
    partes = str(nombre or "").strip().split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[-1][0]).upper()
    return (partes[0][:2] if partes else "?").upper()

def html_badge_estado(estado):
    estado = normalizar_estado_tarea(estado)
    fg, bg, borde = ESTILO_BADGE_ESTADO.get(estado, ("#475569", "#f1f5f9", "#cbd5e1"))
    texto = html_lib.escape(estado)
    return (
        f'<span style="display:inline-block;margin:6px 0 10px 0;padding:5px 12px;border-radius:999px;'
        f'font-size:0.78rem;font-weight:600;letter-spacing:0.02em;color:{fg};'
        f'background:{bg};border:1px solid {borde};">{texto}</span>'
    )

def _fecha_ui_tarea(val):
    if isinstance(val, datetime.date):
        return val
    parsed = parse_fecha_celda(val)
    return parsed if parsed else datetime.date.today()

def persistir_tarea_tarjeta(mensaje_flash="Tarea actualizada.", refrescar=True):
    """Persiste operaciones_tareas en Supabase."""
    return sincronizar_operaciones_tareas_sql(
        st.session_state.operaciones_tareas,
        mensaje_flash=mensaje_flash,
        refrescar=refrescar,
    )

@_st_fragment
def _fragment_tarjeta_tarea(idx, lista_proy, lista_trab):
    """Carta individual: edición de estado/fechas con rerun aislado."""
    if idx not in st.session_state.operaciones_tareas.index:
        return
    row = st.session_state.operaciones_tareas.loc[idx]
    tarea = html_lib.escape(str(row["tarea"]))
    proyecto = html_lib.escape(str(row["proyecto"]))
    trabajador = str(row["trabajador"])
    trab_esc = html_lib.escape(trabajador)
    iniciales = iniciales_responsable(trabajador)
    estado = normalizar_estado_tarea(row["estado"])
    prioridad = normalizar_prioridad_tarea(row["prioridad"])
    f_ini = _fecha_ui_tarea(row["fecha_inicio"])
    f_fin = _fecha_ui_tarea(row["fecha_termino"])

    with st.container(border=True):
        st.markdown(
            f'<p style="margin:0 0 6px 0;font-size:1.2rem;font-weight:700;line-height:1.35;color:#0f172a;">'
            f"{tarea}</p>",
            unsafe_allow_html=True,
        )
        st.markdown(html_badge_estado(estado), unsafe_allow_html=True)
        st.markdown(f"📁 {proyecto}")
        st.markdown(
            f'<span style="display:inline-flex;align-items:center;gap:8px;">'
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:28px;height:28px;border-radius:50%;background:#e0e7ff;color:#3730a3;'
            f'font-size:0.72rem;font-weight:700;">{iniciales}</span>'
            f"<span>{trab_esc}</span></span>",
            unsafe_allow_html=True,
        )
        cargo_tarjeta = str(row.get("cargo", "") or "").strip()
        if cargo_tarjeta:
            st.markdown(f"**Cargo:** {html_lib.escape(cargo_tarjeta)}")
        st.markdown(f"**Prioridad:** {prioridad}")
        st.caption(f"📅 {f_ini.strftime('%d/%m/%Y')} → {f_fin.strftime('%d/%m/%Y')}")

        with st.expander("✏️ Editar estado y fechas", expanded=False):
            idx_est = ESTADOS_TAREA_OPERACIONES.index(estado) if estado in ESTADOS_TAREA_OPERACIONES else 0
            nuevo_est = st.selectbox(
                "estado",
                ESTADOS_TAREA_OPERACIONES,
                index=idx_est,
                key=f"ops_card_est_{idx}",
            )
            c_ini, c_fin = st.columns(2)
            nueva_ini = c_ini.date_input(
                "Inicio",
                value=f_ini,
                format="DD/MM/YYYY",
                key=f"ops_card_fini_{idx}",
            )
            nueva_fin = c_fin.date_input(
                "Término",
                value=f_fin,
                format="DD/MM/YYYY",
                key=f"ops_card_ffin_{idx}",
            )
            if st.button("💾 Guardar cambios", type="primary", key=f"ops_card_save_{idx}", width="stretch"):
                fi_ok, ff_ok = nueva_ini, nueva_fin
                if ff_ok < fi_ok:
                    fi_ok, ff_ok = ff_ok, fi_ok
                st.session_state.operaciones_tareas.loc[idx, "estado"] = normalizar_estado_tarea(nuevo_est)
                st.session_state.operaciones_tareas.loc[idx, "fecha_inicio"] = fi_ok.strftime("%Y-%m-%d")
                st.session_state.operaciones_tareas.loc[idx, "fecha_termino"] = ff_ok.strftime("%Y-%m-%d")
                st.session_state.operaciones_tareas.loc[idx, "dias_duracion"] = float(
                    max(1, contar_dias_habiles_rango(fi_ok, ff_ok))
                )
                persistir_tarea_tarjeta(mensaje_flash="Tarea actualizada.")
            if st.button("🗑️ Eliminar tarea", key=f"ops_card_del_{idx}", width="stretch"):
                st.session_state.operaciones_tareas = st.session_state.operaciones_tareas.drop(index=idx)
                guardar_operaciones_tareas(mensaje_flash="Tarea eliminada.")

@_st_fragment
def _fragment_ops_cuadricula_tarjetas(df_fil, lista_proy, lista_trab):
    """Cuadrícula 3 columnas de cartas de tarea."""
    filas = list(df_fil.iterrows())
    n_cols = 3
    for i in range(0, len(filas), n_cols):
        cols = st.columns(n_cols, gap="medium")
        for j, col in enumerate(cols):
            if i + j >= len(filas):
                continue
            idx, _ = filas[i + j]
            with col:
                _fragment_tarjeta_tarea(int(idx), lista_proy, lista_trab)

@_st_fragment
def _fragment_ops_tablero_tareas(lista_proy, lista_trab, df_base):
    """Pestaña Tablero: filtros, alta y edición (rerun aislado del Gantt)."""
    hoy = datetime.date.today()

    with st.container(border=True):
        st.markdown("#### 🔎 Filtros del tablero")
        f_proy, f_trab, f_est, f_cnt = st.columns([2, 2, 2, 1])
        filtro_proy = f_proy.selectbox("Proyecto", ["Todos"] + lista_proy, key="ops_filtro_proy")
        filtro_trab = f_trab.selectbox("Trabajador", ["Todos"] + lista_trab, key="ops_filtro_trab")
        filtro_est = f_est.selectbox("Estado", ["Todos"] + ESTADOS_TAREA_OPERACIONES, key="ops_filtro_est")
        df_fil = filtrar_tareas_operaciones(df_base, filtro_proy, filtro_trab, filtro_est)
        f_cnt.metric("Visibles", len(df_fil))

    with st.container(border=True):
        st.markdown("#### ➕ Nueva tarea")
        n1, n2, n3 = st.columns([2, 1, 1])
        nom_tarea = n1.text_input("Tarea / Actividad", placeholder="Ej: Instalación tablero principal", key="ops_new_tarea")
        proy_tarea = n2.selectbox("Proyecto", lista_proy, key="ops_new_proy")
        asig_tarea = n3.selectbox("Asignado a", lista_trab or ["— Sin personal —"], key="ops_new_trab")
        p1, p2, p3, p4 = st.columns(4)
        estado_tarea = p1.selectbox("Estado", ESTADOS_TAREA_OPERACIONES, index=0, key="ops_new_est")
        prior_tarea = p2.selectbox("Prioridad", PRIORIDADES_TAREA, index=1, key="ops_new_pri")
        f_ini_n = p3.date_input("Fecha inicio", value=hoy, format="DD/MM/YYYY", key="ops_new_ini")
        f_fin_n = p4.date_input("Fecha término", value=hoy, format="DD/MM/YYYY", key="ops_new_fin")
        if st.button("Crear tarea", type="primary", key="ops_btn_crear"):
            if not str(nom_tarea).strip():
                st.error("Indica el nombre de la tarea.")
            elif not lista_trab:
                st.error("No hay trabajadores en nómina.")
            else:
                fi_ok, ff_ok = f_ini_n, f_fin_n
                if ff_ok < fi_ok:
                    fi_ok, ff_ok = ff_ok, fi_ok
                wd = max(1, contar_dias_habiles_rango(fi_ok, ff_ok))
                nueva = pd.DataFrame([{
                    "tarea": cosmetic_oracion(nom_tarea),
                    "proyecto": proy_tarea,
                    "trabajador": asig_tarea,
                    "estado": estado_tarea,
                    "prioridad": prior_tarea,
                    "fecha_inicio": fi_ok.strftime("%Y-%m-%d"),
                    "fecha_termino": ff_ok.strftime("%Y-%m-%d"),
                    "dias_duracion": float(wd),
                }])
                st.session_state.operaciones_tareas = pd.concat(
                    [sanitizar_operaciones_tareas(st.session_state.operaciones_tareas), nueva],
                    ignore_index=True,
                )
                guardar_operaciones_tareas()

    with st.container(border=True):
        st.markdown("#### 📋 Tablero de tareas")
        if df_fil.empty:
            st.info("No hay tareas con estos filtros. Crea una tarea o amplía los filtros.")
        else:
            _fragment_ops_cuadricula_tarjetas(df_fil, lista_proy, lista_trab)

@_st_fragment
def _fragment_ops_gantt_cronograma(df_base, lista_proy, lista_trab):
    """Pestaña Gantt: filtros y timeline Plotly a ancho completo (rerun aislado del tablero)."""
    hoy = datetime.date.today()
    inicio_mes = datetime.date(hoy.year, hoy.month, 1)
    fin_mes = datetime.date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])

    with st.container(border=True):
        st.markdown("#### 🔎 Filtros del cronograma")
        g1, g2, g3 = st.columns([2, 2, 1])
        gantt_proy = g1.selectbox("Proyecto", ["Todos"] + lista_proy, key="ops_gantt_proy")
        gantt_trab = g2.selectbox("Trabajador", ["Todos"] + lista_trab, key="ops_gantt_trab")
        color_gantt = g3.selectbox(
            "Color por",
            ["estado", "proyecto"],
            format_func=lambda x: etiqueta_ui(x),
            key="ops_gantt_color",
        )
        fd1, fd2 = st.columns(2)
        fecha_desde = fd1.date_input("Fecha desde", value=inicio_mes, format="DD/MM/YYYY", key="ops_gantt_desde")
        fecha_hasta = fd2.date_input("Fecha hasta", value=fin_mes, format="DD/MM/YYYY", key="ops_gantt_hasta")

    df_gantt_fil = filtrar_tareas_operaciones(df_base, gantt_proy, gantt_trab, "Todos")
    df_gantt_fil = filtrar_tareas_rango_fechas(df_gantt_fil, fecha_desde, fecha_hasta)
    df_gantt = preparar_datos_gantt(df_gantt_fil)

    if df_gantt.empty:
        st.info("No hay tareas en este rango de fechas. Ajusta los filtros o registra cronogramas en el tablero.")
    else:
        fig = figura_gantt_plotly(df_gantt, color_por=color_gantt)
        if fig is not None:
            st.plotly_chart(fig, width="stretch", key="ops_gantt_chart")
        solapes = detectar_solapes_mes(df_gantt_fil, fecha_desde.year, fecha_desde.month)
        for aviso in solapes[:8]:
            st.warning(aviso)
        if len(solapes) > 8:
            st.caption(f"+ {len(solapes) - 8} alertas de solapamiento en el periodo visible.")

def _render_ops_rendimiento(df_base, lista_trab):
    """Pestaña analítica (métricas estratégicas)."""
    por_estado, por_proyecto = metricas_rendimiento_operaciones(df_base)

    with st.container(border=True):
        st.markdown("#### 📈 Tareas por estado")
        if por_estado.empty:
            st.info("Sin tareas registradas para analizar.")
        else:
            fig_est = px.bar(
                por_estado,
                x="estado",
                y="cantidad",
                color="estado",
                color_discrete_map=COLOR_ESTADO_OPS,
                text="cantidad",
            )
            fig_est.update_layout(showlegend=False, height=360, margin=dict(t=32, b=8))
            fig_est.update_traces(textposition="outside")
            st.plotly_chart(fig_est, width="stretch")

    with st.container(border=True):
        st.markdown("#### 🎯 % de avance por proyecto")
        if por_proyecto.empty:
            st.info("Sin proyectos con tareas asignadas.")
        else:
            fig_av = px.bar(
                por_proyecto,
                x="proyecto",
                y="Avance_%",
                text="Avance_%",
                color="Avance_%",
                color_continuous_scale=["#ef4444", "#eab308", "#22c55e"],
                range_color=[0, 100],
            )
            fig_av.update_layout(
                height=380,
                yaxis_title="Avance (%)",
                xaxis_title="",
                showlegend=False,
                margin=dict(t=32, b=8),
            )
            fig_av.update_traces(texttemplate="%{text}%", textposition="outside")
            st.plotly_chart(fig_av, width="stretch")
            mostrar_tabla(
                por_proyecto.rename(columns={
                    "Avance_%": "Avance %",
                    "Tareas_Listas": "Listas",
                    "Tareas_Total": "Total tareas",
                }),
                width="stretch",
                hide_index=True,
            )

    if lista_trab:
        with st.container(border=True):
            st.markdown("#### 👥 Capacidad mensual del equipo")
            render_panel_capacidad_trabajadores(df_base, lista_trab, key_suffix="ops_rend_cap")

def _modulo_operaciones():
    """Centro de mando: pestañas separadas; Gantt y tablero en fragmentos independientes."""
    df_proyectos_ops = sanitizar_proyectos_df(cargar_proyectos_sql(ttl=0))
    lista_proy = df_proyectos_ops["nombre"].astype(str).tolist() if not df_proyectos_ops.empty else []
    if not lista_proy and not st.session_state.proyectos_resumen.empty:
        lista_proy = st.session_state.proyectos_resumen["Proyecto"].tolist()
    lista_trab = st.session_state.nomina["trabajador"].tolist() if not st.session_state.nomina.empty else []

    if not lista_proy:
        st.warning("Crea al menos un proyecto en **Proyectos** para usar Operaciones.")
        return
    if not lista_trab:
        st.info("Registra trabajadores en **Finanzas** para asignar responsables.")

    df_base = enriquecer_tareas_con_cargo_proyecto(cargar_operaciones_tareas_sql(ttl=0))
    st.session_state.operaciones_tareas = df_base
    total_t = len(df_base)
    listas = len(df_base[df_base["estado"] == "🟢 Listo"]) if total_t else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("Tareas totales", total_t)
    m2.metric("Tareas listas", listas)
    m3.metric("Avance global", f"{int((listas / total_t) * 100) if total_t else 0}%")

    tab_tablero, tab_gantt, tab_rend = st.tabs([
        "📋 Tablero de Tareas",
        "📅 Cronograma Gantt",
        "📊 Rendimiento",
    ])

    with tab_tablero:
        _fragment_ops_tablero_tareas(lista_proy, lista_trab, df_base)

    with tab_gantt:
        _fragment_ops_gantt_cronograma(df_base, lista_proy, lista_trab)

    with tab_rend:
        _render_ops_rendimiento(df_base, lista_trab)

@_st_fragment
def _fragment_modulo_bodega():
    df_stock_sql, df_hist_sql = cargar_bodega_inventario_sql(ttl=0)
    st.session_state.bodega_stock = df_stock_sql
    st.session_state.bodega_historial = df_hist_sql

    tab_registro, tab_historial = st.tabs(["📦 Registro e Inventario", "📜 Historial y Comprobantes"])

    with tab_registro:
        tab_mov, tab_stock = st.tabs(["↔️ Entradas y Salidas", "📋 Inventario de materiales"])

        with tab_mov:
            with st.container(border=True):
                st.markdown("#### Registrar movimiento")
                if st.session_state.bodega_stock.empty:
                    st.warning("Primero registra materiales en la pestaña **Inventario de materiales**.")
                else:
                    bod_rev = st.session_state.get("bod_stock_rev", 0)
                    opciones_mat, mapa_mat = opciones_material_bodega(st.session_state.bodega_stock)
                    col_tipo, col_mat = st.columns([1, 2])
                    tipo_mov = col_tipo.selectbox("Tipo de movimiento", ["Entrada", "Salida"], key="bod_tipo_mov")
                    material_sel = col_mat.selectbox(
                        "Material (código — nombre)",
                        opciones_mat,
                        key=f"bod_material_sel_{bod_rev}",
                    )
                    codigo_mov = mapa_mat.get(material_sel)

                    if codigo_mov is not None:
                        stock_previo = stock_actual_material(codigo_mov)
                        if stock_previo is not None:
                            col_mat.caption(f"Stock actual en bodega: **{stock_previo}** un.")

                    c1, c2, c3 = st.columns(3)
                    cant_mov = c1.number_input(
                        "Cantidad",
                        min_value=1,
                        step=1,
                        value=1,
                        format="%d",
                        key="bod_cant_mov",
                    )
                    fecha_mov = c2.date_input("Fecha", value=datetime.date.today(), format="DD/MM/YYYY", key="bod_fecha_mov")
                    persona_mov = c3.text_input("Persona responsable", placeholder="Quién entrega o retira", key="bod_persona_mov")

                    proyectos_dest = ["— Seleccione destino —"]
                    if not st.session_state.proyectos_resumen.empty:
                        proyectos_dest += st.session_state.proyectos_resumen["Proyecto"].tolist()
                    proyectos_dest += ["Otro / Bodega general", "Mantenimiento", "Obra en terreno"]

                    col_d1, col_d2 = st.columns(2)
                    destino_tipo = col_d1.selectbox("Destino", proyectos_dest, key="bod_destino_sel")
                    destino_otro = col_d2.text_input(
                        "Detalle de destino (si aplica)",
                        placeholder="Ej: Bodega central, vehículo N°3…",
                        key="bod_destino_txt",
                    )
                    detalle_dest = cosmetic_oracion(destino_otro)
                    if destino_tipo == "— Seleccione destino —":
                        destino_final = detalle_dest
                    elif destino_tipo == "Otro / Bodega general":
                        destino_final = detalle_dest or "Bodega general"
                    else:
                        destino_final = destino_tipo if not detalle_dest else f"{destino_tipo} — {detalle_dest}"

                    if st.button("Registrar movimiento", type="primary", key="bod_btn_mov"):
                        persona_ui = cosmetic_oracion(persona_mov)
                        if not persona_ui:
                            st.error("Indica la persona responsable.")
                        elif not destino_final:
                            st.error("Indica el destino del material.")
                        elif codigo_mov is None:
                            st.error("Selecciona un material válido.")
                        else:
                            ok, msg, _stock_res = registrar_movimiento_bodega(
                                codigo_mov,
                                int(cant_mov),
                                tipo_mov,
                                fecha_mov,
                                persona_ui,
                                destino_final,
                            )
                            if not ok:
                                st.error(msg)

        with tab_stock:
            with st.container(border=True):
                st.markdown("#### 🔍 Buscar en inventario de materiales")
                busqueda_bod = st.text_input(
                    "Buscar por código o nombre:",
                    placeholder="Ej: 401, tornillo, cable…",
                    key="bod_busqueda",
                )
                df_stock_vista = sanitizar_bodega_stock(cargar_bodega_inventario_sql(ttl=0)[0])
                if busqueda_bod:
                    mask_b = (
                        df_stock_vista["codigo"].astype(str).str.contains(busqueda_bod, case=False, na=False)
                        | df_stock_vista["nombre_material"].astype(str).str.contains(busqueda_bod, case=False, na=False)
                        | df_stock_vista["familia"].astype(str).str.contains(busqueda_bod, case=False, na=False)
                    )
                    df_stock_vista = df_stock_vista[mask_b]
                    if df_stock_vista.empty:
                        st.warning("Sin coincidencias en el inventario de materiales.")

            with st.container(border=True):
                with st.expander("➕ Alta en inventario de materiales", expanded=False):
                    ca, cb, cc = st.columns([1, 1, 2])
                    familia_nueva = ca.number_input("Familia (partida)", min_value=1, step=1, value=400, format="%d", key="bod_fam_nueva")
                    autogen = cb.checkbox("Autogenerar código", value=True, key="bod_autogen")
                    sugerido = sugerir_codigo_bodega(st.session_state.bodega_stock, familia_nueva)
                    if autogen:
                        codigo_nuevo = int(sugerido)
                    else:
                        codigo_nuevo = cb.number_input("Código", min_value=1, step=1, value=int(sugerido), format="%d", key="bod_cod_manual")
                    nombre_nuevo = cc.text_input("Nombre del material", key="bod_nom_nuevo")
                    cd1, cd2 = st.columns(2)
                    desc_nueva = cd1.text_input("Descripción / categoría", placeholder="Ej: Tornillería", key="bod_desc_nueva")
                    stock_inicial = cd2.number_input("Stock inicial", min_value=0, step=1, value=0, format="%d", key="bod_stock_ini")
                    if st.button("Guardar material", type="primary", key="bod_btn_alta"):
                        if not str(nombre_nuevo).strip():
                            st.error("El nombre del material es obligatorio.")
                        else:
                            codigo = int(codigo_nuevo)
                            familia = int(familia_nueva)
                            nombre_material = normalizar_texto_manual(nombre_nuevo, "titulo")
                            descripcion = normalizar_texto_manual(desc_nueva, "oracion")
                            cantidad = int(stock_inicial)
                            unidad = "un"
                            stock_df = sanitizar_bodega_stock(cargar_bodega_inventario_sql(ttl=0)[0])
                            if (stock_df["codigo"] == codigo).any():
                                st.error(f"El código {codigo} ya existe. Elige otro o activa autogenerar.")
                            else:
                                insertar_material_bodega_sql(
                                    codigo=codigo,
                                    familia=familia,
                                    nombre_material=nombre_material,
                                    descripcion=descripcion,
                                    cantidad=cantidad,
                                    unidad=unidad,
                                )

            with st.container(border=True):
                st.markdown("#### Inventario actual")
                df_stock_editor = sanitizar_bodega_stock(cargar_bodega_inventario_sql(ttl=0)[0])
                cols_stock = [c for c in COLUMNAS_BODEGA_STOCK if c in df_stock_editor.columns]
                if df_stock_editor.empty:
                    st.info("El inventario de materiales está vacío. Usa el formulario de alta.")
                else:
                    df_stock_edit = mostrar_editor(
                        df_stock_editor[cols_stock],
                        column_config={
                            "codigo": st.column_config.NumberColumn("Código", min_value=1, step=1, format="%d"),
                            "familia": st.column_config.NumberColumn("Familia", min_value=1, step=1, format="%d"),
                            "nombre_material": st.column_config.TextColumn("Material"),
                            "descripcion": st.column_config.TextColumn("Descripción"),
                            "cantidad": st.column_config.NumberColumn("Stock actual", min_value=0, step=1, format="%d"),
                            "unidad": st.column_config.TextColumn("Unidad"),
                        },
                        column_order=cols_stock,
                        disabled=["codigo", "cantidad"],
                        hide_index=True,
                        width="stretch",
                        key=f"ed_bodega_stock_{st.session_state.get('bod_stock_rev', 0)}",
                    )
                    if st.button("💾 Guardar inventario de materiales", type="primary", key="bod_save_stock"):
                        if sincronizar_bodega_stock_sql(df_stock_edit):
                            refrescar_sql_ui("Inventario actualizado en bodega_inventario.")
                    with st.expander("🗑️ Eliminar material del inventario"):
                        opts_del = [f"{int(r['codigo'])} — {r['nombre_material']}" for _, r in df_stock_edit.iterrows()]
                        if opts_del:
                            sel_del = st.selectbox("Material a eliminar", opts_del, key="bod_del_mat")
                            if st.button("Eliminar del inventario", type="primary", key="bod_btn_del_mat"):
                                cod_del = int(sel_del.split("—")[0].strip())
                                if eliminar_material_bodega_sql(cod_del):
                                    refrescar_sql_ui("Material eliminado del inventario.")

    with tab_historial:
        with st.container(border=True):
            _render_bodega_historial_comprobantes()


def _migrar_dias_duracion_tareas(df):
    df = df.copy()
    if 'dias_duracion' not in df.columns:
        df['dias_duracion'] = float('nan')
    for idx in df.index:
        raw = df.at[idx, 'dias_duracion']
        try:
            if raw is not None and str(raw).strip() != "" and not (isinstance(raw, float) and pd.isna(raw)):
                float(raw)
                continue
        except (ValueError, TypeError):
            pass
        fi = parse_fecha_celda(df.at[idx, 'fecha_inicio'])
        ff = parse_fecha_celda(df.at[idx, 'fecha_termino'])
        if fi and ff:
            if ff < fi:
                fi, ff = ff, fi
            wd = contar_dias_habiles_rango(fi, ff)
            df.at[idx, 'dias_duracion'] = float(max(1, wd))
        else:
            df.at[idx, 'dias_duracion'] = 1.0
    return df

st.session_state.operaciones_tareas = _migrar_dias_duracion_tareas(st.session_state.operaciones_tareas)

def formatear_input(llave):
    val = str(st.session_state[llave]).replace(".", "").replace(",", "").replace("$", "").replace(" ", "").strip()
    try:
        val_num = int(val) if val else 0
        st.session_state[llave] = f"{val_num:,}".replace(",", ".")
    except ValueError:
        st.session_state[llave] = "0"

COLUMNAS_LIQUIDACIONES = [
    "rut", "trabajador", "cargo", "Contrato", "Sueldo Base", "Sueldo Base Diario",
    "Sueldo Proporcional", "Horas Extras Monto", "Horas Extras Qty", "gratificacion",
    "colacion", "movilizacion", "Nombre AFP", "Dcto AFP", "Dcto Fonasa", "Dcto Cesantia",
    "Imponible Calculado", "Haberes No Imponibles", "Total Haberes", "Total Prevision",
    "anticipo", "Total Descuentos", "Alcance Liquido", "Total a Pagar", "Costo Empresa",
    "dias_falta", "horas_atraso", "Dcto_Atraso_Monto",
]

def calcular_liquidaciones(df):
    df = sanitizar_nomina(_reparar_df_columnas_numericas(df, COLUMNAS_NOMINA))
    if "cargo" not in df.columns:
        df["cargo"] = pd.NA
    resultados = []
    costo_empresa_total = 0
    for index, row in df.iterrows():
        sueldo_base = a_numerico_clp(_valor_fila(row, "sueldo_base", "Sueldo_Base", default=0))
        try:
            jornada = float(_valor_fila(row, "jornada_hrs", "Jornada_Hrs", default=44))
        except (ValueError, TypeError):
            jornada = 44.0
        
        dias_falta = float(a_numerico_clp(_valor_fila(row, "dias_falta", "Dias_Falta", default=0)))
        horas_atraso = float(a_numerico_clp(_valor_fila(row, "horas_atraso", "Horas_Atraso", default=0)))
        horas_extras_qty = float(a_numerico_clp(_valor_fila(row, "horas_extras", "Horas_Extras", default=0)))
        anticipo = float(a_numerico_clp(_valor_fila(row, "anticipo", "Anticipo", default=0)))
        
        valor_dia = sueldo_base / 30 if sueldo_base > 0 else 0
        valor_hora_normal = (sueldo_base / 30) * 28 / jornada if jornada > 0 else 0
        valor_hora_extra = valor_hora_normal * 1.5
        
        tipo_grati = str(_valor_fila(row, "gratificacion", "Gratificacion", default="Sin Gratificación"))
        if tipo_grati == "Tope Legal Mensual": grati_monto = min(sueldo_base * 0.25, 197917)
        elif tipo_grati == "25% del Sueldo (Sin Tope)": grati_monto = sueldo_base * 0.25
        else: grati_monto = 0
            
        pago_extras = horas_extras_qty * valor_hora_extra
        dcto_faltas = dias_falta * valor_dia
        dcto_atrasos = horas_atraso * valor_hora_normal
        
        sueldo_imponible = sueldo_base + grati_monto + pago_extras - dcto_faltas - dcto_atrasos
        if sueldo_imponible < 0: sueldo_imponible = 0
        
        dcto_afp = sueldo_imponible * TASAS_AFP.get(
            str(_valor_fila(row, "afp", "AFP", default="Habitat (11.27%)")), 0.1144
        )
        dcto_fonasa = sueldo_imponible * 0.07
        
        tipo_contrato = str(_valor_fila(row, "tipo_contrato", "Tipo_Contrato", default="Indefinido"))
        dcto_cesantia = sueldo_imponible * 0.006 if tipo_contrato == "Indefinido" else 0.0
        
        colacion = float(a_numerico_clp(_valor_fila(row, "colacion", "Colacion", default=0)))
        movilizacion = float(a_numerico_clp(_valor_fila(row, "movilizacion", "Movilizacion", default=0)))
        no_imponibles = colacion + movilizacion
        
        total_prevision = dcto_afp + dcto_fonasa + dcto_cesantia
        total_descuentos = total_prevision + anticipo 
        
        alcance_liquido = sueldo_imponible - total_prevision + no_imponibles
        total_a_pagar = alcance_liquido - anticipo
        
        costo_real_empresa = sueldo_imponible + no_imponibles
        costo_empresa_total += costo_real_empresa

        _rut_liq = str(_valor_fila(row, "rut", "RUT", default="")).strip()
        _rut_out = (
            formatear_rut(_rut_liq)
            if _rut_liq and _rut_liq.lower() not in ("sin registro", "nan")
            else "Sin Registro"
        )

        resultados.append({
            "rut": _rut_out,
            "trabajador": str(_valor_fila(row, "trabajador", "Trabajador", default="")),
            "cargo": str(row["cargo"]).strip(),
            "Contrato": tipo_contrato,
            "Sueldo Base": sueldo_base,
            "Sueldo Base Diario": valor_dia,
            "Sueldo Proporcional": sueldo_base - dcto_faltas - dcto_atrasos,
            "Horas Extras Monto": pago_extras, "Horas Extras Qty": horas_extras_qty,
            "gratificacion": grati_monto,
            "colacion": colacion, "movilizacion": movilizacion, 
            "Nombre AFP": str(_valor_fila(row, "afp", "AFP", default="Habitat (11.27%)")),
            "Dcto AFP": dcto_afp,
            "Dcto Fonasa": dcto_fonasa, "Dcto Cesantia": dcto_cesantia,
            "Imponible Calculado": sueldo_imponible, "Haberes No Imponibles": no_imponibles, 
            "Total Haberes": sueldo_imponible + no_imponibles,
            "Total Prevision": total_prevision,
            "anticipo": anticipo,
            "Total Descuentos": total_descuentos, 
            "Alcance Liquido": alcance_liquido,
            "Total a Pagar": total_a_pagar,
            "Costo Empresa": costo_real_empresa,
            "dias_falta": dias_falta,
            "horas_atraso": horas_atraso,
            "Dcto_Atraso_Monto": dcto_atrasos
        })
    if not resultados:
        return pd.DataFrame(columns=COLUMNAS_LIQUIDACIONES), costo_empresa_total
    return pd.DataFrame(resultados, columns=COLUMNAS_LIQUIDACIONES), costo_empresa_total

def num2words(n):
    if n <= 0: return "CERO"
    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIUN", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    centenas = ["", "CIEN", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    if n < 30: return unidades[n]
    if n < 100: return decenas[n // 10] + (" Y " + unidades[n % 10] if n % 10 != 0 else "")
    if n < 1000:
        if n == 100: return "CIEN"
        return (centenas[n // 100] if n // 100 != 1 else "CIENTO") + (" " + num2words(n % 100) if n % 100 != 0 else "")
    if n < 2000: return "MIL" + (" " + num2words(n % 1000) if n % 1000 != 0 else "")
    if n < 1000000: return num2words(n // 1000) + " MIL" + (" " + num2words(n % 1000) if n % 1000 != 0 else "")
    if n == 1000000: return "UN MILLON"
    if n < 2000000: return "UN MILLON " + num2words(n % 1000000)
    return num2words(n // 1000000) + " MILLONES " + num2words(n % 1000000)

def right_text(pdf, x, y, text):
    width = pdf.get_string_width(text)
    pdf.text(x - width, y, text)

# Maquetación tabla financiera PDF (liquidación)
_PDF_FIN_X_IZQ = 10
_PDF_FIN_W_LBL_IZQ = 52
_PDF_FIN_W_VAL_IZQ = 38
_PDF_FIN_X_DER = 110
_PDF_FIN_W_LBL_DER = 52
_PDF_FIN_W_VAL_DER = 38
_PDF_FIN_ANCHO_SECCION = 90
_PDF_FIN_H_FILA = 5
_PDF_FIN_H_FILA_ALTA = 10
_PDF_COLOR_HEADER = (220, 235, 248)


def _pdf_texto_latin1(texto):
    return str(texto).encode("latin-1", "replace").decode("latin-1")


def _pdf_monto_liq(datos, clave, vacio_si_cero=False):
    val = datos.get(clave, 0)
    if vacio_si_cero and (val is None or float(val) == 0):
        return ""
    return formato_clp(val).replace("$", "").strip()


def _pdf_celda(pdf, x, y, w, h, texto, align="L", bold=False, header=False, font_size=8):
    if header:
        pdf.set_fill_color(*_PDF_COLOR_HEADER)
        pdf.set_font("Arial", "B", 9)
        fill = True
    else:
        pdf.set_fill_color(255, 255, 255)
        estilo = "B" if bold else ""
        pdf.set_font("Arial", estilo, font_size)
        fill = False
    pdf.set_xy(x, y)
    pdf.cell(w, h, _pdf_texto_latin1(texto), border=1, align=align, fill=fill)


def _pdf_fila_financiera(pdf, y, lbl_izq, val_izq, lbl_der="", val_der="", h=None, bold=False):
    h = h or _PDF_FIN_H_FILA
    _pdf_celda(pdf, _PDF_FIN_X_IZQ, y, _PDF_FIN_W_LBL_IZQ, h, lbl_izq, bold=bold)
    _pdf_celda(pdf, _PDF_FIN_X_IZQ + _PDF_FIN_W_LBL_IZQ, y, _PDF_FIN_W_VAL_IZQ, h, val_izq, align="R", bold=bold)
    _pdf_celda(pdf, _PDF_FIN_X_DER, y, _PDF_FIN_W_LBL_DER, h, lbl_der, bold=bold)
    _pdf_celda(
        pdf,
        _PDF_FIN_X_DER + _PDF_FIN_W_LBL_DER,
        y,
        _PDF_FIN_W_VAL_DER,
        h,
        val_der,
        align="R",
        bold=bold,
    )
    return y + h


def _pdf_encabezados_tabla_financiera(pdf, y):
    _pdf_celda(pdf, _PDF_FIN_X_IZQ, y, _PDF_FIN_ANCHO_SECCION, 6, "HABERES", align="C", header=True)
    _pdf_celda(pdf, _PDF_FIN_X_DER, y, _PDF_FIN_ANCHO_SECCION, 6, "DESCUENTOS", align="C", header=True)
    return y + 6


# ==========================================
# MOTOR PDF: LIQUIDACIÓN OFICIAL (FPDF)
# ==========================================
def generar_pdf_liquidacion(datos):
    pdf = FPDF(unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    # 1. ENCABEZADO
    pdf.set_font("Arial", 'B', 10)
    pdf.text(10, 15, "VOLTIFY SPA")
    pdf.set_font("Arial", '', 9)
    pdf.text(10, 20, "RUT : 77.871.702-6")
    pdf.text(10, 25, "JAVIERA CARRERA #1150 ARICA")
    pdf.text(10, 30, "Teléfono Cel 995635899")
    
    pdf.set_font("Arial", 'B', 12)
    pdf.text(70, 40, "Liquidación de Sueldo Mensual")
    
    # 2. BLOQUE DE INFORMACIÓN DEL TRABAJADOR
    y = 50
    trabajador_limpio = str(datos['trabajador']).encode('latin-1', 'replace').decode('latin-1').upper()
    cargo_limpio = str(datos['cargo']).encode('latin-1', 'replace').decode('latin-1').upper()
    rut_trabajador = formatear_rut(datos.get("rut", "Sin Registro")) or "Sin Registro"
    
    meses_str = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes_actual = meses_str[datetime.datetime.now().month - 1]
    anio_actual = datetime.datetime.now().year

    pdf.set_font("Arial", '', 9)
    pdf.text(10, y, "RUT:")
    pdf.text(25, y, rut_trabajador)
    
    pdf.text(60, y, "Nombre:")
    pdf.text(75, y, trabajador_limpio)
    
    pdf.text(145, y, "Fecha Contrato :")
    pdf.text(172, y, "16/03/2026")
    
    y += 6
    pdf.text(10, y, "Año:")
    pdf.text(20, y, str(anio_actual))
    
    pdf.text(35, y, "Mes:")
    pdf.text(45, y, mes_actual)
    
    pdf.text(65, y, "CC:")
    pdf.text(75, y, "OPERACIONES")
    
    pdf.text(110, y, "Sueldo Base:")
    pdf.text(130, y, formato_clp(datos["Sueldo Base"]).replace("$","").strip())
    
    pdf.text(155, y, "UF:")
    pdf.text(165, y, "39.841,72")
    
    y += 6
    pdf.text(10, y, "Cargo:")
    pdf.text(25, y, cargo_limpio)

    # 3. TABLA FINANCIERA (celdas con borde, fuente 8pt)
    y += 10
    y = _pdf_encabezados_tabla_financiera(pdf, y)
    pdf.set_font("Arial", "", 8)

    dias_falta_pdf = float(datos.get("dias_falta", 0) or 0)
    dias_trabajados = 30.0 - dias_falta_pdf
    dias_trabajados_str = f"{dias_trabajados:.1f}".replace(".", ",")
    imponible_str = _pdf_monto_liq(datos, "Imponible Calculado")

    afp_nombre = datos["Nombre AFP"].split("(")[0].strip().upper()
    afp_tasa = (
        datos["Nombre AFP"].split("(")[1].replace(")", "").strip()
        if "(" in str(datos["Nombre AFP"])
        else ""
    )

    y = _pdf_fila_financiera(
        pdf, y, "Días Trabajados", dias_trabajados_str, f"AFP: {afp_nombre}", afp_tasa
    )
    y = _pdf_fila_financiera(
        pdf,
        y,
        "Sueldo",
        _pdf_monto_liq(datos, "Sueldo Proporcional"),
        "Base AFP",
        imponible_str,
    )
    y = _pdf_fila_financiera(
        pdf,
        y,
        f"Horas : {datos['Horas Extras Qty']}  50.00%",
        "",
        "Cotización AFP",
        _pdf_monto_liq(datos, "Dcto AFP"),
    )
    y = _pdf_fila_financiera(
        pdf,
        y,
        "Total Horas Extras",
        _pdf_monto_liq(datos, "Horas Extras Monto"),
        "Isapre: Fonasa",
        "",
    )
    y = _pdf_fila_financiera(pdf, y, "", "", "7% Obligatorio", _pdf_monto_liq(datos, "Dcto Fonasa"))
    y = _pdf_fila_financiera(
        pdf,
        y,
        "Gratificación",
        _pdf_monto_liq(datos, "gratificacion"),
        "Cotización Pactado (0 UF)",
        _pdf_monto_liq(datos, "Dcto Fonasa"),
    )
    y = _pdf_fila_financiera(
        pdf,
        y,
        "Total Imponible",
        imponible_str,
        "Base AFC",
        imponible_str,
    )
    y = _pdf_fila_financiera(pdf, y, "Cargas", "", "Cotiz. AFC Trabajador", _pdf_monto_liq(datos, "Dcto Cesantia", vacio_si_cero=True))
    y = _pdf_fila_financiera(
        pdf,
        y,
        "Asignación Movilización",
        _pdf_monto_liq(datos, "movilizacion"),
        "Total Previsión",
        _pdf_monto_liq(datos, "Total Prevision"),
    )
    y = _pdf_fila_financiera(
        pdf,
        y,
        "Asignación Colación",
        _pdf_monto_liq(datos, "colacion"),
        "",
        "",
    )

    if datos.get("horas_atraso", 0) > 0:
        y = _pdf_fila_financiera(
            pdf,
            y,
            "",
            "",
            f"Atraso ({datos['horas_atraso']} Hrs)",
            f"(-{int(datos['Dcto_Atraso_Monto'])})",
        )

    lineas_dias = "Días no Trabajados | Vacación: | Licencia:"
    if datos.get("dias_falta", 0) > 0:
        dias_falta_str = f"{float(datos['dias_falta']):.1f}".replace(".", ",")
        lineas_dias += f" | Faltas: {dias_falta_str} día(s)"
    y = _pdf_fila_financiera(pdf, y, "", "", lineas_dias, "", h=_PDF_FIN_H_FILA_ALTA)

    base_trib = datos["Imponible Calculado"] - datos["Total Prevision"]
    if base_trib < 0:
        base_trib = 0
    y = _pdf_fila_financiera(
        pdf,
        y,
        "TOTAL HABERES",
        _pdf_monto_liq(datos, "Total Haberes"),
        "Base Tributable",
        formato_clp(base_trib).replace("$", "").strip(),
        bold=True,
    )

    if datos.get("anticipo", 0) > 0:
        y = _pdf_fila_financiera(
            pdf, y, "", "", "Anticipo", _pdf_monto_liq(datos, "anticipo")
        )

    # --- 4. TOTALES FINALES (celdas) ---
    y_tot = y + 4
    y_tot = _pdf_fila_financiera(
        pdf,
        y_tot,
        "",
        "",
        "TOTAL DESCUENTO",
        _pdf_monto_liq(datos, "Total Descuentos"),
        bold=True,
    )
    y_tot = _pdf_fila_financiera(
        pdf,
        y_tot,
        "",
        "",
        "ALCANCE LIQUIDO",
        _pdf_monto_liq(datos, "Alcance Liquido"),
        bold=True,
    )
    y_tot = _pdf_fila_financiera(
        pdf,
        y_tot,
        "",
        "",
        "TOTAL A PAGAR",
        _pdf_monto_liq(datos, "Total a Pagar"),
        bold=True,
    )
    
    # --- 5. TEXTO EN PALABRAS Y LEGAL ---
    y_words = y_tot + 10
    pdf.set_font("Arial", '', 9)
    texto_son = num2words(int(datos['Total a Pagar'])).upper()
    pdf.text(10, y_words, f"SON: {texto_son} PESOS")
    
    y_words += 10
    pdf.text(10, y_words, "Certifico que he recibido conforme y no tengo cargos ni cobro alguno posterior que hacer, por ninguno de los")
    pdf.text(10, y_words + 4, "conceptos comprometidos en ella.")
    
    y_firm = y_words + 25
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y_firm, "FIRMA TRABAJADOR")
    
    pdf.set_font("Arial", '', 8)
    pdf.text(10, y_firm + 10, "La presente liquidación se emite en 2 copias quedando una en poder del trabajador y otra en poder del empleador.")
    
    # Render final
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        temp_path = tmp.name
    pdf.output(temp_path)
    with open(temp_path, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_path)
    return pdf_bytes

def generar_etiqueta_pdf(serie):
    pdf = FPDF(format=(80, 25))
    pdf.add_page()
    pdf.set_y(5) 
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 6, "VOLTIFY SpA", ln=True, align='C')
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 8, f"{serie}", ln=True, align='C')
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        temp_path = tmp.name
    pdf.output(temp_path)
    with open(temp_path, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_path)
    return pdf_bytes

def generar_pdf_vale_bodega(mov):
    """Vale de bodega en cuadrícula (FPDF, 8pt)."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    def _val(clave, default=""):
        if hasattr(mov, "get"):
            v = mov.get(clave, default)
        else:
            v = getattr(mov, clave, default) if clave in mov.index else default
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return v

    filas_datos = [
        ("Tipo de movimiento", str(_val("tipo_movimiento"))),
        ("Código", str(int(_val("codigo", 0) or 0))),
        ("Material", str(_val("nombre_material"))),
        ("Cantidad", str(int(_val("cantidad", 0) or 0))),
        ("Fecha", str(_val("fecha"))),
        ("Persona responsable", str(_val("persona_responsable"))),
        ("Destino", str(_val("destino"))),
        ("Detalle del destino", str(_val("detalle_destino")) or "—"),
        ("Stock resultante", str(int(_val("stock_resultante", 0) or 0))),
    ]

    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, _pdf_texto_latin1("Voltify ERP - VALE DE BODEGA"), ln=True, align="C")
    pdf.ln(4)

    x0, w_lbl, w_val, h = 15, 55, 120, 7
    _pdf_celda(pdf, x0, pdf.get_y(), w_lbl + w_val, h, "Datos del movimiento", align="C", header=True)
    y = pdf.get_y() + h
    pdf.set_font("Arial", "", 8)
    for etiqueta, valor in filas_datos:
        _pdf_celda(pdf, x0, y, w_lbl, h, etiqueta, bold=False, font_size=8)
        _pdf_celda(pdf, x0 + w_lbl, y, w_val, h, valor, align="L", font_size=8)
        y += h

    y += 12
    ancho_firma = 75
    espacio = 20
    x_f1 = 15
    x_f2 = x_f1 + ancho_firma + espacio
    pdf.set_font("Arial", "", 8)
    pdf.line(x_f1, y, x_f1 + ancho_firma, y)
    pdf.line(x_f2, y, x_f2 + ancho_firma, y)
    y += 4
    pdf.set_xy(x_f1, y)
    pdf.cell(ancho_firma, 5, _pdf_texto_latin1("Firma Encargado Bodega"), align="C")
    pdf.set_xy(x_f2, y)
    pdf.cell(ancho_firma, 5, _pdf_texto_latin1("Firma Persona que Retira"), align="C")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        temp_path = tmp.name
    pdf.output(temp_path)
    with open(temp_path, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_path)
    return pdf_bytes


def _render_bodega_historial_comprobantes():
    st.markdown("#### Historial de movimientos")
    df_mov = cargar_bodega_movimientos_sql(ttl=0)

    c_f1, c_f2 = st.columns([2, 1])
    with c_f1:
        buscar_mov = st.text_input(
            "Buscar por material, código o responsable",
            placeholder="Ej: 401, tornillo, Juan Pérez…",
            key="bod_hist_buscar",
        )
    with c_f2:
        filtro_tipo = st.selectbox(
            "Tipo",
            ["Todos", "Entrada", "Salida"],
            key="bod_hist_tipo",
        )

    fecha_inicio_def = datetime.date.today() - datetime.timedelta(days=30)
    fecha_fin_def = datetime.date.today()
    rango_fechas = st.date_input(
        "📅 Filtrar por Rango de Fechas",
        value=(fecha_inicio_def, fecha_fin_def),
        key="bodega_filtro_rango_fechas",
    )

    if df_mov.empty:
        st.info("Aún no hay movimientos en el historial. Registra entradas o salidas en la pestaña **Registro e Inventario**.")
        return

    df_fil = df_mov.copy()
    if "fecha" in df_fil.columns and isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        inicio, fin = rango_fechas
        df_fil["fecha_pura"] = pd.to_datetime(df_fil["fecha"], errors="coerce").dt.date
        df_fil = df_fil[
            df_fil["fecha_pura"].notna()
            & (df_fil["fecha_pura"] >= inicio)
            & (df_fil["fecha_pura"] <= fin)
        ]

    if filtro_tipo != "Todos":
        df_fil = df_fil[df_fil["tipo_movimiento"].astype(str) == filtro_tipo]
    if buscar_mov.strip():
        q = buscar_mov.strip().lower()
        mask = (
            df_fil["nombre_material"].astype(str).str.lower().str.contains(q, na=False)
            | df_fil["codigo"].astype(str).str.contains(q, na=False)
            | df_fil["persona_responsable"].astype(str).str.lower().str.contains(q, na=False)
            | df_fil["destino"].astype(str).str.lower().str.contains(q, na=False)
        )
        df_fil = df_fil[mask]

    if df_fil.empty:
        st.warning("Sin resultados para los filtros aplicados.")
        return

    cols_vis_map = {
        "id": "ID",
        "fecha": "Fecha",
        "tipo_movimiento": "Tipo",
        "codigo": "Código",
        "nombre_material": "Material",
        "cantidad": "Cantidad",
        "persona_responsable": "Responsable",
        "destino": "Destino",
        "detalle_destino": "Detalle destino",
        "stock_resultante": "Stock resultante",
    }
    df_vis = df_fil.drop(columns=["fecha_pura"], errors="ignore").rename(
        columns={k: v for k, v in cols_vis_map.items() if k in df_fil.columns}
    )
    mostrar_tabla(df_vis, width="stretch", hide_index=True)

    opciones_mov = [
        f"{r.get('Fecha', '—')} | {r['Tipo']} | {r['Código']} — {r['Material']} ({int(r['Cantidad'])} u.)"
        for _, r in df_vis.iterrows()
    ]
    ids_mov = df_fil["id"].tolist()

    col_sel, col_pdf = st.columns([3, 1], vertical_alignment="bottom")
    with col_sel:
        idx_mov = st.selectbox(
            "Movimiento para comprobante",
            range(len(opciones_mov)),
            format_func=lambda i: opciones_mov[i],
            key="bod_hist_sel_mov",
        )
    with col_pdf:
        if FPDF_DISPONIBLE:
            fila_mov = df_fil.iloc[idx_mov]
            pdf_vale = generar_pdf_vale_bodega(fila_mov)
            cod_nom = f"{int(fila_mov['codigo'])}_{int(fila_mov['id'])}"
            col_pdf.download_button(
                label="📄 Descargar Comprobante",
                data=pdf_vale,
                file_name=f"Vale_Bodega_{cod_nom}.pdf",
                mime="application/pdf",
                type="primary",
                width="stretch",
            )
        else:
            st.error("Instala fpdf2 para generar comprobantes PDF.")


# ==========================================
# 4. CONTROL DE ACCESOS Y PANTALLA DE LOGIN
# ==========================================
if 'acceso_app' not in st.session_state: st.session_state.acceso_app = False
if 'acceso_finanzas' not in st.session_state: st.session_state.acceso_finanzas = "ninguno" 
if 'acceso_proyectos' not in st.session_state: st.session_state.acceso_proyectos = "ninguno" 

if not st.session_state.acceso_app:
    col_vacia1, col_centro, col_vacia2 = st.columns([1, 2, 1])
    with col_centro:
        with st.container(border=True):
            st.image(LOGO_URL, width="stretch")
            st.markdown("<h2 style='text-align: center;'>Portal de Gestión Empresarial</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: gray;'>Acceso exclusivo para personal autorizado</p>", unsafe_allow_html=True)
            st.divider()
            u_gen = st.text_input("👤 Usuario Corporativo")
            p_gen = st.text_input("🔑 Clave de Acceso", type="password")
            st.write("")
            if st.button("Iniciar Sesión", type="primary", width="stretch"):
                if u_gen == "voltify" and p_gen == "1234":
                    st.session_state.acceso_app = True
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")
    st.stop()

# ==========================================
# 5. NAVEGACIÓN SUPERIOR
# ==========================================
if 'menu_actual' not in st.session_state: st.session_state.menu_actual = "Inicio"

col_logo, col_espacio, col_settings = st.columns([3, 7, 2], vertical_alignment="bottom")

with col_logo:
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    st.image(LOGO_URL, width=200)

with col_settings:
    with st.popover("⚙️ Ajustes", width="stretch"):
        st.markdown("**Opciones Globales**")
        if st.button("🔄 Sincronizar", width="stretch"):
            for key in list(st.session_state.keys()):
                if key not in ['acceso_app', 'acceso_finanzas', 'acceso_proyectos']: del st.session_state[key]
            st.rerun()
        if st.button("🔒 Bloquear", width="stretch"):
            st.session_state.acceso_finanzas = "ninguno"
            st.session_state.acceso_proyectos = "ninguno"
            st.rerun()
        if st.button("🚪 Salir", width="stretch"):
            st.session_state.acceso_app = False
            st.session_state.acceso_finanzas = "ninguno"
            st.session_state.acceso_proyectos = "ninguno"
            st.rerun()

st.write("") 

b0, b1, b2, b3, b4, b5, b6 = st.columns(7)

if b0.button("🏠 Inicio", type="primary" if st.session_state.menu_actual == "Inicio" else "secondary", width="stretch"): st.session_state.menu_actual = "Inicio"; st.rerun()
if b1.button("💼 Finanzas", type="primary" if st.session_state.menu_actual == "Finanzas" else "secondary", width="stretch"): st.session_state.menu_actual = "Finanzas"; st.rerun()
if b2.button("📝 Presup.", type="primary" if st.session_state.menu_actual == "Presupuestos" else "secondary", width="stretch"): st.session_state.menu_actual = "Presupuestos"; st.rerun()
if b3.button("🏗️ Proyectos", type="primary" if st.session_state.menu_actual == "Proyectos" else "secondary", width="stretch"): st.session_state.menu_actual = "Proyectos"; st.rerun()
if b4.button("⏱️ Operaciones", type="primary" if st.session_state.menu_actual == "Operaciones" else "secondary", width="stretch"): st.session_state.menu_actual = "Operaciones"; st.rerun()
if b5.button("🏭 Bodega", type="primary" if st.session_state.menu_actual == "Bodega" else "secondary", width="stretch"): st.session_state.menu_actual = "Bodega"; st.rerun()
if b6.button("📊 Balance", type="primary" if st.session_state.menu_actual == "Balance" else "secondary", width="stretch"): st.session_state.menu_actual = "Balance"; st.rerun()

st.divider()
mostrar_mensaje_guardado_flash()

# ==========================================
# PANTALLA 0: HOME DASHBOARD
# ==========================================
if st.session_state.menu_actual == "Inicio":
    st.markdown("## 📊 Panel de Control General")

    total_trabajadores = len(st.session_state.nomina)
    presupuestos_pendientes = st.session_state.presupuestos[st.session_state.presupuestos['Aprobacion'].str.contains('Pendiente', na=False)]['Monto'].sum()
    if pd.isna(presupuestos_pendientes): presupuestos_pendientes = 0
    proyectos_activos = len(st.session_state.proyectos_resumen)
    
    colA, colB, colC = st.columns(3)
    with colA:
        with st.container(border=True):
            st.metric("👥 Trabajadores Activos", total_trabajadores)
    with colB:
        with st.container(border=True):
            st.metric("🏗️ Proyectos en Curso", proyectos_activos)
    with colC:
        with st.container(border=True):
            st.metric("⏳ Presupuestos Pendientes", formato_clp(presupuestos_pendientes))

    st.write("")
    col_izq, col_der = st.columns(2)
    
    with col_izq:
        with st.container(border=True):
            st.markdown("#### 📈 Estado General de Proyectos")
            if st.session_state.proyectos_resumen.empty:
                st.info("No hay proyectos activos para medir.")
            else:
                for idx, row in st.session_state.proyectos_resumen.iterrows():
                    nombre_proy = _valor_fila(row, "Proyecto", "proyecto")
                    if "proyecto" not in st.session_state.operaciones_tareas.columns:
                        st.session_state.operaciones_tareas = cargar_operaciones_tareas_sql()
                    tareas_proy = st.session_state.operaciones_tareas[
                        st.session_state.operaciones_tareas["proyecto"] == nombre_proy
                    ]
                    
                    if tareas_proy.empty:
                        st.write(f"**{nombre_proy}**: *Sin tareas asignadas*")
                        st.progress(0)
                    else:
                        terminadas = len(tareas_proy[tareas_proy["estado"].str.contains("Listo|Terminada", na=False, case=False, regex=True)])
                        total = len(tareas_proy)
                        porcentaje = int((terminadas / total) * 100)
                        st.write(f"**{nombre_proy}**")
                        st.progress(porcentaje / 100.0, text=f"Completado: {porcentaje}%")

    with col_der:
        with st.container(border=True):
            st.markdown("#### 🚨 Alertas y Urgencias")
            
            # Tareas Urgentes
            tareas_urgentes = st.session_state.operaciones_tareas[
                st.session_state.operaciones_tareas["estado"].isin(ESTADOS_TAREA_OPERACIONES[:3])
            ]
            if not tareas_urgentes.empty:
                st.write("**Tareas Pendientes en Terreno:**")
                mostrar_tabla(tareas_urgentes[['proyecto', 'tarea', 'estado']], hide_index=True, width="stretch")
            else:
                st.success("¡Todo al día en terreno!")
            
            st.divider()
            stock_bajo = st.session_state.bodega_stock[st.session_state.bodega_stock["cantidad"] <= 5]
            if not stock_bajo.empty:
                st.write("**Materiales con stock bajo (≤ 5 un.):**")
                mostrar_tabla(
                    stock_bajo[["codigo", "nombre_material", "cantidad"]],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.success("Bodega: niveles de stock dentro de lo normal.")

# ==========================================
# PANTALLA 1: FINANZAS Y NÓMINA
# ==========================================
def limpiar_form_nomina():
    st.session_state.form_id_nomina += 1

if 'form_id_nomina' not in st.session_state:
    st.session_state.form_id_nomina = 0

elif st.session_state.menu_actual == "Finanzas":
    st.markdown("### Área de Finanzas y Recursos Humanos")
    if st.session_state.acceso_finanzas == "ninguno":
        with st.container(border=True):
            st.info("🔒 Ingresa credenciales de administrador para desbloquear este módulo.")
            col1, col2 = st.columns([1, 2])
            with col1:
                u_fin = st.text_input("Usuario (Finanzas)")
                p_fin = st.text_input("Clave", type="password", key="p_fin")
                if st.button("Desbloquear Módulo", type="primary"):
                    if (u_fin == "master" and p_fin == "123") or (u_fin == "admin_fin" and p_fin == "admin123"): st.session_state.acceso_finanzas = "admin"; st.rerun()
                    elif (u_fin == "obs_fin" and p_fin == "obs123"): st.session_state.acceso_finanzas = "observador"; st.rerun()
                    else: st.error("Credenciales incorrectas.")
    else:
        if st.session_state.acceso_finanzas == "observador": st.warning("👁️ MODO OBSERVADOR: Visualización en modo lectura.")
            
        tab_nomina, tab_fijos, tab_facturas, tab_rendimiento = st.tabs(
            ["👥 Nómina y Liquidaciones", "🏢 Gastos Fijos Operativos", "🧾 Emisión de Facturas", "📊 Rendimiento y capacidad"]
        )
        
        with tab_nomina:
            with st.container(border=True):
                st.subheader("Control de Asistencia y Nómina")
                if st.session_state.acceso_finanzas == "admin":
                    with st.expander("➕ Ingresar Nuevo Trabajador (Datos Fijos)", expanded=False):
                        fid = st.session_state.form_id_nomina
                        
                        colRUT, colA, colB = st.columns([1, 2, 2])
                        n_rut = colRUT.text_input("RUT (Ej: 12.345.678-9)", key=f"n_rut_{fid}")
                        n_trabajador = colA.text_input("Nombre Completo", key=f"n_trab_{fid}")
                        n_cargo = colB.text_input("Cargo", key=f"n_cargo_{fid}")
                        
                        llave_sueldo = f"sueldo_{fid}"
                        if llave_sueldo not in st.session_state: st.session_state[llave_sueldo] = "0"
                        
                        colC, colD, colE = st.columns([2, 1, 2])
                        colC.text_input("Sueldo Base Mensual", key=llave_sueldo, on_change=formatear_input, kwargs={'llave': llave_sueldo})
                        n_sueldo = float(st.session_state[llave_sueldo].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        
                        n_jornada = colD.number_input("Hrs Semanales", value=44, max_value=45, key=f"n_jor_{fid}")
                        n_grati = colE.selectbox("Tipo de Gratificación", ["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"], key=f"n_gra_{fid}")
                        
                        colF, colG = st.columns(2)
                        n_contrato = colF.selectbox("Tipo de Contrato", ["Indefinido", "Plazo Fijo"], key=f"n_con_{fid}")
                        n_afp = colG.selectbox("Seleccione AFP", list(TASAS_AFP.keys()), key=f"n_afp_{fid}")
                        
                        llave_col = f"colacion_{fid}"
                        llave_mov = f"movilizacion_{fid}"
                        if llave_col not in st.session_state: st.session_state[llave_col] = "0"
                        if llave_mov not in st.session_state: st.session_state[llave_mov] = "0"
                        
                        colH, colI = st.columns(2)
                        colH.text_input("Bono Colación Fijo", key=llave_col, on_change=formatear_input, kwargs={'llave': llave_col})
                        n_cola = float(st.session_state[llave_col].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        colI.text_input("Bono Movilización Fijo", key=llave_mov, on_change=formatear_input, kwargs={'llave': llave_mov})
                        n_movi = float(st.session_state[llave_mov].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        
                        st.write("")
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("💾 Guardar Perfil Fijo", type="primary", width="stretch"):
                                if n_trabajador and n_rut:
                                    nuevo_perfil = pd.DataFrame([{
                                        "rut": formatear_rut(n_rut),
                                        "trabajador": cosmetic_oracion(n_trabajador),
                                        "cargo": cosmetic_oracion(n_cargo),
                                        "sueldo_base": n_sueldo, 
                                        "jornada_hrs": n_jornada, "tipo_contrato": n_contrato, "gratificacion": n_grati, 
                                        "afp": n_afp, "dias_falta": 0, "horas_atraso": 0, "horas_extras": 0, 
                                        "colacion": n_cola, "movilizacion": n_movi, "anticipo": 0
                                    }])
                                    st.session_state.nomina = pd.concat([st.session_state.nomina, nuevo_perfil], ignore_index=True)
                                    sincronizar_nomina_sql(st.session_state.nomina)
                                    limpiar_form_nomina()
                                else:
                                    st.error("⚠️ El RUT y el Nombre Completo son obligatorios.")
                        with col_btn2:
                            if st.button("🧹 Limpiar Campos", width="stretch"):
                                limpiar_form_nomina()
                                st.rerun()

                    df_editor = cargar_nomina_sql(ttl=0)
                    st.session_state.nomina = df_editor
                    df_nomina_edit = mostrar_editor(
                        df_editor,
                        column_config={
                            "rut": st.column_config.TextColumn("RUT"),
                            "trabajador": st.column_config.TextColumn("Trabajador"),
                            "cargo": st.column_config.TextColumn("Cargo"),
                            "sueldo_base": st.column_config.NumberColumn("Sueldo Base", min_value=0, step=1000, format="%d"),
                            "anticipo": st.column_config.NumberColumn("Anticipo ($)", min_value=0, step=1000, format="%d"),
                            "dias_falta": st.column_config.NumberColumn("Días Falta", min_value=0.0, step=0.5, format="%.1f"),
                            "horas_atraso": st.column_config.NumberColumn("Hrs Atraso", min_value=0),
                            "horas_extras": st.column_config.NumberColumn("Hrs Extras", min_value=0),
                            "colacion": st.column_config.NumberColumn("Colación", min_value=0, step=1000, format="%d"),
                            "movilizacion": st.column_config.NumberColumn("Movilización", min_value=0, step=1000, format="%d"),
                            "jornada_hrs": st.column_config.NumberColumn("Jornada (hrs)", min_value=1, step=1, format="%d"),
                            "gratificacion": st.column_config.SelectboxColumn(
                                "Gratificación",
                                options=["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"],
                            ),
                            "afp": st.column_config.SelectboxColumn("AFP", options=list(TASAS_AFP.keys())),
                            "tipo_contrato": st.column_config.SelectboxColumn("Contrato", options=["Indefinido", "Plazo Fijo"]),
                        },
                        column_order=[
                            "rut", "trabajador", "cargo", "sueldo_base", "anticipo", "dias_falta",
                            "horas_atraso", "horas_extras", "colacion", "movilizacion",
                            "jornada_hrs", "gratificacion", "afp", "tipo_contrato",
                        ],
                        num_rows="dynamic", width="stretch",
                        key=f"ed_nomina_{st.session_state.get('nomina_rev', 0)}",
                    )
                    if st.button("💾 Guardar Cambios de Nómina / Mes", type="primary"):
                        st.session_state.nomina = sanitizar_nomina(df_nomina_edit)
                        sincronizar_nomina_sql(st.session_state.nomina)
                        
                    with st.expander("🗑️ Dar de Baja / Eliminar Trabajador"):
                        lista_trabajadores = st.session_state.nomina['trabajador'].tolist()
                        if lista_trabajadores:
                            trab_a_borrar = st.selectbox("Selecciona el trabajador a eliminar:", lista_trabajadores)
                            if st.button("Eliminar Definitivamente", type="primary"):
                                fila_baja = st.session_state.nomina[
                                    st.session_state.nomina["trabajador"] == trab_a_borrar
                                ]
                                if not fila_baja.empty and eliminar_trabajador_nomina_sql(
                                    str(fila_baja.iloc[0]["rut"]), refrescar_ui=True
                                ):
                                    pass
                else:
                    df_nom_vis = sanitizar_nomina(st.session_state.nomina.copy())
                    df_nom_vis = df_formateado_clp(df_nom_vis, ["sueldo_base", "colacion", "movilizacion", "anticipo"])
                    mostrar_tabla(df_nom_vis, width="stretch")

            with st.container(border=True):
                st.subheader("Proyección de Liquidaciones")
                df_nomina_liq = sanitizar_nomina(cargar_nomina_sql())
                df_liquidaciones, total_nomina_empresa = calcular_liquidaciones(df_nomina_liq)
                
                cols_liq = [
                    "trabajador", "cargo", "Sueldo Base", "Sueldo Base Diario",
                    "Imponible Calculado", "Total Prevision", "anticipo", "Total a Pagar", "Costo Empresa",
                ]
                df_liq_visual = df_liquidaciones[[c for c in cols_liq if c in df_liquidaciones.columns]].copy()
                for col in [
                    "Sueldo Base", "Sueldo Base Diario", "Imponible Calculado",
                    "Total Prevision", "anticipo", "Total a Pagar", "Costo Empresa",
                ]:
                    if col in df_liq_visual.columns:
                        df_liq_visual[col] = df_liq_visual[col].apply(formatear_clp)
                    
                mostrar_tabla(df_liq_visual, width="stretch")
                st.info(f"**Costo Total Proyectado de Nómina:** {formato_clp(total_nomina_empresa)}")
                
                st.divider()
                st.markdown("#### 📄 Emisión de Liquidaciones Oficiales (PDF)")
                if FPDF_DISPONIBLE:
                    trab_lista = df_liquidaciones['trabajador'].tolist()
                    if trab_lista:
                        col_sel, col_btn = st.columns([3, 1], vertical_alignment="bottom")
                        trab_seleccionado = col_sel.selectbox("Seleccione un trabajador para generar documento:", trab_lista)
                        datos_trabajador_pdf = df_liquidaciones[df_liquidaciones['trabajador'] == trab_seleccionado].iloc[0]
                        pdf_generado_bytes = generar_pdf_liquidacion(datos_trabajador_pdf)
                        col_btn.download_button(
                            label="⬇️ Descargar PDF Oficial", data=pdf_generado_bytes,
                            file_name=f"Liquidacion_{trab_seleccionado.replace(' ', '_')}.pdf",
                            mime="application/pdf", type="primary", width="stretch"
                        )
                else:
                    st.error("⚠️ La librería para crear PDFs no está instalada.")

        with tab_fijos:
            with st.container(border=True):
                st.subheader("Gastos Fijos Operativos")
                if st.session_state.acceso_finanzas == "admin":
                    res_fijos = mostrar_editor(
                        st.session_state.gastos_fijos,
                        column_config={
                            "Descripción": st.column_config.TextColumn("Descripción"),
                            "Monto (CLP)": st.column_config.NumberColumn("Monto (CLP)", min_value=0, step=1000, format="%d"),
                        },
                        num_rows="dynamic",
                        width="stretch",
                    )
                    if st.button("💾 Guardar Cambios Fijos", type="primary"):
                        gf = res_fijos.copy()
                        if "Descripción" in gf.columns:
                            gf["Descripción"] = gf["Descripción"].apply(cosmetic_oracion)
                        st.session_state.gastos_fijos = gf
                        guardar_datos(
                            "Gastos_Fijos",
                            gf,
                            refrescar_ui=True,
                            mensaje_flash="Gastos fijos actualizados.",
                        )
                else:
                    mostrar_tabla(
                        df_formateado_clp(st.session_state.gastos_fijos, ["Monto (CLP)"]),
                        width="stretch",
                    )

        with tab_facturas:
            with st.container(border=True):
                st.subheader("Módulo de Emisión de Facturas (Maqueta)")
                if st.session_state.acceso_finanzas == "admin":
                    proyectos_lista_fact = st.session_state.proyectos_resumen["Proyecto"].tolist()
                    if proyectos_lista_fact:
                        proyecto_fact = st.selectbox("Selecciona un proyecto a facturar:", proyectos_lista_fact)
                        idx_fact = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_fact].index[0]
                        cobro_fact = pd.to_numeric(st.session_state.proyectos_resumen.at[idx_fact, "Cobro"], errors='coerce')
                        oc_fact = st.session_state.proyectos_resumen.at[idx_fact, "Num_OC"]
                        
                        st.divider()
                        st.markdown(f"##### Borrador contable — OC: {oc_fact}")
                        neto_calc = int(cobro_fact / 1.19) if cobro_fact > 0 else 0
                        iva_calc = int(cobro_fact - neto_calc)
                        cn, ci, ct = st.columns(3)
                        cn.metric("Monto Neto", formato_clp(neto_calc))
                        ci.metric("IVA (19%)", formato_clp(iva_calc))
                        ct.metric("Total a Facturar", formato_clp(cobro_fact))
                    else:
                        st.info("Aún no tienes proyectos creados.")

        with tab_rendimiento:
            with st.container(border=True):
                st.subheader("Rendimiento y capacidad del personal")
                lista_rend = st.session_state.nomina["trabajador"].tolist()
                if not lista_rend:
                    st.info("Registra trabajadores en la pestaña de Nómina para ver esta vista.")
                else:
                    hoy_r = datetime.date.today()
                    meses_nombres_r = [
                        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
                    ]
                    cr1, cr2 = st.columns(2)
                    with cr1:
                        yr_r = st.number_input("Año", 2020, 2035, hoy_r.year, key="fin_rend_y")
                    with cr2:
                        mes_r = st.selectbox(
                            "Mes (detalle)",
                            list(range(1, 13)),
                            format_func=lambda i: meses_nombres_r[i - 1],
                            index=hoy_r.month - 1,
                            key="fin_rend_m",
                        )
                    df_det = tabla_capacidad_personal(st.session_state.operaciones_tareas, lista_rend, yr_r, mes_r)
                    st.markdown("##### Detalle por persona (mes seleccionado)")
                    mostrar_tabla(df_det, width="stretch", hide_index=True)

                    st.divider()
                    st.markdown("##### Estimación multi-mes (proyección de carga)")
                    cp1, cp2, cp3 = st.columns(3)
                    with cp1:
                        y0 = st.number_input("Año inicio proyección", 2020, 2035, hoy_r.year, key="fin_proy_y0")
                    with cp2:
                        m0 = st.selectbox(
                            "Mes inicio",
                            list(range(1, 13)),
                            format_func=lambda i: meses_nombres_r[i - 1],
                            index=hoy_r.month - 1,
                            key="fin_proy_m0",
                        )
                    with cp3:
                        n_meses_proj = st.number_input("Cantidad de meses", min_value=1, max_value=12, value=3, step=1, key="fin_proy_n")

                    df_ref = tabla_referencia_dias_habiles(y0, m0, int(n_meses_proj))
                    mostrar_tabla(df_ref, width="stretch", hide_index=True)

                    df_proj = tabla_proyeccion_carga_meses(
                        st.session_state.operaciones_tareas, lista_rend, y0, m0, int(n_meses_proj)
                    )
                    mostrar_tabla(df_proj, width="stretch", hide_index=True)

# ==========================================
# PANTALLA 2: PRESUPUESTOS Y COTIZACIONES
# ==========================================
elif st.session_state.menu_actual == "Presupuestos":
    st.markdown("### Gestión de Presupuestos y Cotizaciones")
    with st.container(border=True):
        with st.expander("➕ Crear Nueva Cotización / Presupuesto", expanded=False):
            tipo_pres = st.radio(
                "Clasificación de la Venta:",
                ["Asociada a un Proyecto", "Venta de Productos (Independiente)"],
                horizontal=True,
            )
            colP1, colP2 = st.columns(2)
            ref_pres = None
            cliente_pres = None
            if tipo_pres == "Asociada a un Proyecto":
                df_proy_pres = cargar_proyectos_sql(ttl=0)
                proyectos_existentes = (
                    df_proy_pres["nombre"].astype(str).tolist() if not df_proy_pres.empty else []
                )
                if proyectos_existentes:
                    ref_pres = colP1.selectbox("Seleccionar Proyecto:", proyectos_existentes)
                    fila_pres = df_proy_pres[df_proy_pres["nombre"].astype(str) == ref_pres].iloc[0]
                    cliente_pres = str(fila_pres["empresa"])
                    colP2.info(f"Cliente vinculado: **{cosmetic_oracion(cliente_pres)}**")
                else:
                    st.warning("Aún no tienes proyectos creados.")
            else:
                ref_pres = colP1.text_input(
                    "Nombre del Producto o Servicio:",
                    placeholder="Ej: Venta de 50m cable eléctrico",
                )
                cliente_pres = colP2.text_input("Nombre del Cliente:")

            colP3, colP4 = st.columns(2)
            monto_pres = 0.0
            if tipo_pres == "Asociada a un Proyecto" and ref_pres:
                monto_pres = float(obtener_cobro_proyecto_sql(ref_pres, ttl=0))
                colP3.metric("Monto Total Cotizado (CLP)", formatear_clp(int(monto_pres)))
            else:
                if "input_monto_presupuesto" not in st.session_state:
                    st.session_state["input_monto_presupuesto"] = "0"
                colP3.text_input(
                    "Monto Total Cotizado (CLP):",
                    key="input_monto_presupuesto",
                    on_change=formatear_input,
                    kwargs={"llave": "input_monto_presupuesto"},
                )
                monto_pres = float(
                    st.session_state["input_monto_presupuesto"]
                    .replace(".", "")
                    .replace(",", "")
                    .replace("$", "")
                    .strip()
                    or 0
                )

            fecha_pres = colP4.date_input("Fecha de Emisión:", format="DD/MM/YYYY")

            colP5, colP6, colP7 = st.columns(3)
            aprobacion_pres = colP5.selectbox(
                "Estado de Aprobación:", ["⏳ Pendiente", "✅ Aprobada", "❌ No Aprobada"]
            )
            orden_pres = colP6.selectbox("Respaldo de Orden:", ["Sin Orden", "Con Orden"])
            num_oc_pres = colP7.text_input("N° OC (Si aplica):", placeholder="Ej: OC-1234")
            if not num_oc_pres:
                num_oc_pres = "N/A"

            if st.button("Guardar Presupuesto", type="primary"):
                if ref_pres and cliente_pres and monto_pres > 0:
                    str_fecha = fecha_pres.strftime("%Y-%m-%d") if fecha_pres else ""
                    ref_guardar = (
                        cosmetic_oracion(ref_pres)
                        if tipo_pres != "Asociada a un Proyecto"
                        else str(ref_pres).strip()
                    )
                    cliente_guardar = cosmetic_oracion(cliente_pres)
                    nuevo_presupuesto = pd.DataFrame(
                        [
                            {
                                "Tipo": tipo_pres,
                                "Referencia": ref_guardar,
                                "Cliente": cliente_guardar,
                                "Monto": monto_pres,
                                "Aprobacion": aprobacion_pres,
                                "Orden_Compra": orden_pres,
                                "Num_OC": num_oc_pres,
                                "Estado_Comercial": "📝 Presupuestada",
                                "Fecha_Emision": str_fecha,
                            }
                        ]
                    )
                    st.session_state.presupuestos = pd.concat(
                        [st.session_state.presupuestos, nuevo_presupuesto], ignore_index=True
                    )
                    guardar_datos(
                        "Presupuestos",
                        st.session_state.presupuestos,
                        refrescar_ui=True,
                        mensaje_flash="Presupuesto ingresado exitosamente.",
                    )
                    st.session_state["input_monto_presupuesto"] = "0"
                else:
                    st.error(
                        "Por favor, completa la referencia, el cliente y asegúrate de que el monto sea mayor a 0."
                    )

    with st.container(border=True):
        st.subheader("Panel de Seguimiento Comercial")
        if st.session_state.presupuestos.empty:
            st.info("Aún no hay cotizaciones emitidas en el sistema.")
        else:
            opciones_estado = [
                "📝 Presupuestada",
                "🎯 Adjudicada",
                "🚀 En progreso",
                "📦 Entregada",
                "💳 Pagada",
            ]
            opciones_aprobacion = [
                "⏳ Pendiente",
                "✅ Aprobada",
                "❌ No Aprobada",
                "Pendiente",
                "Aprobada",
                "No Aprobada",
            ]
            opciones_orden = ["Sin Orden", "Con Orden"]

            df_pres_edit = mostrar_editor(
                st.session_state.presupuestos,
                column_config={
                    "Monto": st.column_config.NumberColumn("Monto Total", min_value=0, step=1000, format="%d"),
                    "Aprobacion": st.column_config.SelectboxColumn("Aprobación", options=opciones_aprobacion),
                    "Orden_Compra": st.column_config.SelectboxColumn("Orden", options=opciones_orden),
                    "Num_OC": st.column_config.TextColumn("N° O.C."),
                    "Estado_Comercial": st.column_config.SelectboxColumn(
                        "Estado Comercial", options=opciones_estado
                    ),
                    "Fecha_Emision": st.column_config.TextColumn("Fecha Emisión"),
                },
                disabled=["Tipo", "Referencia", "Cliente"],
                hide_index=True,
                width="stretch",
                key="ed_pres",
            )

            if st.button("💾 Guardar Estados Comerciales", type="primary"):
                st.session_state.presupuestos = df_pres_edit
                guardar_datos(
                    "Presupuestos",
                    st.session_state.presupuestos,
                    refrescar_ui=True,
                    mensaje_flash="Estados de presupuestos actualizados.",
                )

            with st.expander("🗑️ Eliminar un Presupuesto"):
                lista_borrar_pres = [
                    f"[{row['Estado_Comercial']}] {row['Referencia']} - {row['Cliente']} ({formato_clp(row['Monto'])})"
                    for _, row in st.session_state.presupuestos.iterrows()
                ]
                if lista_borrar_pres:
                    pres_a_borrar = st.selectbox("Selecciona la cotización a eliminar:", lista_borrar_pres)
                    if st.button("Eliminar Presupuesto Definitivamente"):
                        idx_borrar = lista_borrar_pres.index(pres_a_borrar)
                        st.session_state.presupuestos = (
                            st.session_state.presupuestos.drop(st.session_state.presupuestos.index[idx_borrar])
                            .reset_index(drop=True)
                        )
                        guardar_datos(
                            "Presupuestos",
                            st.session_state.presupuestos,
                            refrescar_ui=True,
                            mensaje_flash="Cotización eliminada correctamente.",
                        )

# ==========================================
# PANTALLA 3: PROYECTOS
# ==========================================
elif st.session_state.menu_actual == "Proyectos":
    st.markdown("### Gestión de Proyectos")
    mostrar_mensaje_guardado_flash()

    if st.session_state.acceso_proyectos == "ninguno":
        with st.container(border=True):
            st.info("🔒 Ingresa credenciales de administrador para desbloquear este módulo.")
            col1, col2 = st.columns([1, 2])
            with col1:
                u_proy = st.text_input("Usuario (Proyectos)")
                p_proy = st.text_input("Clave", type="password", key="p_proy")
                if st.button("Desbloquear Módulo", type="primary"):
                    if (u_proy == "master" and p_proy == "123") or (u_proy == "admin_proy" and p_proy == "admin123"):
                        st.session_state.acceso_proyectos = "admin"
                        st.rerun()
                    elif (u_proy == "obs_proy" and p_proy == "obs123"):
                        st.session_state.acceso_proyectos = "observador"
                        st.rerun()
                    else:
                        st.error("Credenciales incorrectas.")
    else:
        es_admin_proy = st.session_state.acceso_proyectos == "admin"
        df_proyectos = cargar_proyectos_sql(ttl=0)

        # —— 1. CREACIÓN DE PROYECTO (2x2) ——
        if es_admin_proy:
            with st.container(border=True):
                with st.expander("➕ Crear Nueva Carpeta de Proyecto", expanded=False):
                    fila1_a, fila1_b = st.columns(2)
                    with fila1_a:
                        nombre_p = st.text_input("Nombre de la Obra o Proyecto", key="proy_new_nombre")
                    with fila1_b:
                        empresa_p = st.text_input("Nombre de la Empresa / Cliente", key="proy_new_empresa")
                    fila2_a, fila2_b = st.columns(2)
                    with fila2_a:
                        ciudad_p = st.text_input("Ciudad de ejecución", key="proy_new_ciudad")
                    with fila2_b:
                        oc_p = st.text_input(
                            "N° Orden de Compra (Si la tienes)",
                            placeholder="Ej: OC-4567",
                            key="proy_new_oc",
                        )
                    if st.button("Crear Proyecto", type="primary", key="proy_btn_crear"):
                        if not str(nombre_p).strip():
                            st.error("El nombre del proyecto es obligatorio.")
                        elif (
                            not df_proyectos.empty
                            and str(nombre_p).strip() in df_proyectos["nombre"].astype(str).values
                        ):
                            st.error("Ya existe un proyecto con ese nombre.")
                        else:
                            insertar_proyecto_sql(
                                nombre=nombre_p,
                                empresa=empresa_p,
                                ciudad=ciudad_p,
                                num_oc=oc_p,
                            )

        df_proyectos = cargar_proyectos_sql(ttl=0)
        nombres_proyectos = df_proyectos["nombre"].astype(str).tolist() if not df_proyectos.empty else []

        if not nombres_proyectos:
            st.info("Crea tu primer proyecto con el formulario superior para comenzar.")
        else:
            # —— 2. SELECCIÓN Y PANEL FINANCIERO ——
            proyecto_seleccionado = st.selectbox(
                "📂 Proyecto activo",
                nombres_proyectos,
                key="proy_sel_activo",
            )
            mask_proy = df_proyectos["nombre"] == proyecto_seleccionado
            cobro_acordado = int(df_proyectos.loc[mask_proy, "cobro"].iloc[0])
            gastos_totales = calcular_gastos_totales_proyecto(proyecto_seleccionado)
            margen = cobro_acordado - gastos_totales
            fila_proy = df_proyectos.loc[mask_proy].iloc[0]

            with st.container(border=True):
                st.markdown("#### Evaluación económica del proyecto")
                m1, m2, m3 = st.columns(3)
                m1.metric("Cobro Acordado", formato_clp(cobro_acordado))
                m2.metric("Gastos Totales", formato_clp(gastos_totales))
                m3.metric("Margen de Ganancia", formatear_clp(margen))

            # —— 3. ASIGNACIÓN DE EQUIPO ——
            with st.container(border=True):
                st.markdown("#### 👷 Asignación de equipo")
                df_equipo_proy = cargar_proyecto_equipo_sql(ttl=0)
                df_equipo_proy = df_equipo_proy[df_equipo_proy["proyecto"] == proyecto_seleccionado].copy()

                if es_admin_proy:
                    lista_trab_nom = cargar_nomina_sql(ttl=0)["trabajador"].astype(str).tolist()
                    if not lista_trab_nom:
                        st.warning("Registra trabajadores en **Finanzas → Nómina** antes de asignar equipo.")
                    else:
                        with st.form("form_asignar_equipo", clear_on_submit=True):
                            c1, c2, c3 = st.columns([2, 2, 1])
                            trab_sel = c1.selectbox("Trabajador (nómina)", lista_trab_nom)
                            cargo_proy_in = c2.text_input(
                                "Cargo en este proyecto",
                                placeholder="Ej: Jefe de obra, Electricista…",
                            )
                            horas_in = c3.number_input(
                                "Horas asignadas",
                                min_value=0.5,
                                step=0.5,
                                value=8.0,
                                format="%.1f",
                            )
                            costo_h_prev = calcular_costo_hora_trabajador(trab_sel)
                            if st.form_submit_button("➕ Añadir al equipo", type="primary"):
                                if not str(cargo_proy_in).strip():
                                    st.error("Indica el cargo en el proyecto.")
                                elif (
                                    not df_equipo_proy.empty
                                    and trab_sel in df_equipo_proy["trabajador"].astype(str).values
                                ):
                                    st.error("Ese trabajador ya está en el equipo de esta obra.")
                                else:
                                    insertar_proyecto_equipo_sql(
                                        proyecto=proyecto_seleccionado,
                                        trabajador=trab_sel,
                                        cargo_proyecto=cosmetic_oracion(cargo_proy_in),
                                        horas_asignadas=horas_in,
                                        costo_hora_estimado=costo_h_prev,
                                    )

                if df_equipo_proy.empty:
                    st.info("Sin personal asignado a esta obra.")
                else:
                    df_eq_vis = df_equipo_proy.copy()
                    df_eq_vis["costo_total"] = (
                        df_eq_vis["horas_asignadas"] * df_eq_vis["costo_hora_estimado"]
                    ).round(0).astype(int)
                    df_eq_vis["costo_hora_estimado"] = df_eq_vis["costo_hora_estimado"].apply(formato_clp)
                    df_eq_vis["costo_total"] = df_eq_vis["costo_total"].apply(formato_clp)
                    mostrar_tabla(
                        df_eq_vis[
                            ["trabajador", "cargo_proyecto", "horas_asignadas", "costo_hora_estimado", "costo_total"]
                        ],
                        width="stretch",
                        hide_index=True,
                    )
                    if es_admin_proy and not df_equipo_proy.empty:
                        trab_del = st.selectbox(
                            "Quitar del equipo",
                            df_equipo_proy["trabajador"].tolist(),
                            key="proy_del_equipo",
                        )
                        if st.button("Eliminar del equipo", key="proy_btn_del_equipo"):
                            eliminar_proyecto_equipo_sql(proyecto_seleccionado, trab_del)

            # —— 4. GASTOS DESGLOSADOS ——
            with st.container(border=True):
                st.markdown("#### 💰 Gastos desglosados")
                df_gastos_proy = cargar_proyecto_gastos_sql(ttl=0)
                df_gastos_proy = df_gastos_proy[df_gastos_proy["proyecto"] == proyecto_seleccionado].copy()

                if es_admin_proy:
                    with st.form("form_gasto_proyecto", clear_on_submit=True):
                        g1, g2, g3 = st.columns([2, 1, 1])
                        item_in = g1.text_input("Item", placeholder="Ej: Arriendo grúa, almuerzo terreno…")
                        cat_in = g2.selectbox("Categoría", CATEGORIAS_PROYECTO_GASTO)
                        monto_in = g3.number_input("Monto ($)", min_value=0, step=1000, value=0, format="%d")
                        if st.form_submit_button("Registrar gasto", type="primary"):
                            if not str(item_in).strip():
                                st.error("El ítem del gasto es obligatorio.")
                            else:
                                insertar_proyecto_gasto_sql(
                                    proyecto=proyecto_seleccionado,
                                    item=cosmetic_oracion(item_in),
                                    categoria=cat_in,
                                    monto=monto_in,
                                )

                if df_gastos_proy.empty:
                    st.info("Sin gastos registrados para este proyecto.")
                else:
                    df_gv = df_gastos_proy.copy()
                    df_gv["monto_fmt"] = df_gv["monto"].apply(formato_clp)
                    mostrar_tabla(
                        df_gv[["item", "categoria", "monto_fmt"]].rename(
                            columns={"item": "Item", "categoria": "Categoría", "monto_fmt": "Monto"}
                        ),
                        width="stretch",
                        hide_index=True,
                    )
                    if es_admin_proy:
                        item_del = st.selectbox(
                            "Eliminar gasto",
                            [f"{r['item']} — {formato_clp(r['monto'])}" for _, r in df_gastos_proy.iterrows()],
                            key="proy_del_gasto",
                        )
                        if st.button("Eliminar gasto seleccionado", key="proy_btn_del_gasto"):
                            item_nom = item_del.split(" — ")[0].strip()
                            eliminar_proyecto_gasto_sql(proyecto_seleccionado, item_nom)

            if es_admin_proy:
                st.divider()
                if st.button("🗑️ Eliminar proyecto completo", type="primary", key="proy_del_total"):
                    eliminar_proyecto_completo_sql(proyecto_seleccionado)
elif st.session_state.menu_actual == "Operaciones":
    st.markdown("### ⏱️ Operaciones — Centro de Mando")
    _modulo_operaciones()

elif st.session_state.menu_actual == "Bodega":
    st.markdown("### 🏭 Bodega — Control de Materiales")
    _fragment_modulo_bodega()

# ==========================================
# PANTALLA 6: BALANCE TOTAL
# ==========================================
elif st.session_state.menu_actual == "Balance":
    
    current_year = datetime.datetime.now().year
    meses_año_actual = [f"{current_year}-{str(i).zfill(2)}" for i in range(1, 13)]
    meses_set = set(meses_año_actual)
    
    if not st.session_state.proyectos_resumen.empty:
        for val in st.session_state.proyectos_resumen["Fecha_Termino_Proy"]:
            val_str = str(val)
            if val_str != "Pendiente" and len(val_str) >= 7:
                meses_set.add(val_str[:7])
                
    meses_totales = sorted(list(meses_set))
    
    df_liq, costo_nomina_mensual = calcular_liquidaciones(st.session_state.nomina)
    fijos_mensuales = pd.to_numeric(st.session_state.gastos_fijos["Monto (CLP)"], errors='coerce').sum()
    
    datos_grafico = []
    for mes in meses_totales:
        ingresos_mes = 0
        costos_proy_mes = 0
        
        if not st.session_state.proyectos_resumen.empty:
            for idx, row in st.session_state.proyectos_resumen.iterrows():
                fecha_term = str(row.get("Fecha_Termino_Proy", ""))
                if fecha_term.startswith(mes) or (fecha_term in ["Pendiente", ""] and mes == f"{current_year}-{str(datetime.datetime.now().month).zfill(2)}"):
                    ingresos_mes += float(row.get("Cobro", 0))
                    if not st.session_state.proyectos_gastos.empty:
                        nombre_proy_bal = _valor_fila(row, "Proyecto", "proyecto")
                        gastos_asoc = st.session_state.proyectos_gastos[
                            st.session_state.proyectos_gastos["Proyecto"] == nombre_proy_bal
                        ]["Monto"].sum()
                        costos_proy_mes += float(gastos_asoc)
        
        egresos_totales_mes = costo_nomina_mensual + fijos_mensuales + costos_proy_mes
        datos_grafico.append({"Mes": mes, "Tipo": "Ingresos (+)", "Monto": ingresos_mes})
        datos_grafico.append({"Mes": mes, "Tipo": "Egresos (-)", "Monto": egresos_totales_mes})
        
    df_full = pd.DataFrame(datos_grafico)

    with st.container(border=True):
        st.markdown("#### 💡 Balance Financiero Acumulado")
        
        col_f1, col_f2 = st.columns(2)
        vista_balance = col_f1.selectbox("📅 Temporalidad del Balance:", ["Proyección Anual (12 Meses)", "Vista Mensual Específica", "Histórico Completo"])
        
        if vista_balance == "Proyección Anual (12 Meses)":
            meses_filtrados = meses_año_actual
            titulo_metricas = "Proyección Anual (Año en Curso)"
        elif vista_balance == "Vista Mensual Específica":
            mes_actual_str = f"{current_year}-{str(datetime.datetime.now().month).zfill(2)}"
            idx_mes = meses_totales.index(mes_actual_str) if mes_actual_str in meses_totales else 0
            mes_seleccionado = col_f2.selectbox("Seleccionar Mes:", meses_totales, index=idx_mes)
            meses_filtrados = [mes_seleccionado]
            titulo_metricas = f"Balance del Mes: {mes_seleccionado}"
        else: 
            meses_filtrados = meses_totales
            titulo_metricas = "Balance Histórico Acumulado"
            
        df_filtrado = df_full[df_full["Mes"].isin(meses_filtrados)].copy()
        
        def formato_tooltip_millones(row):
            val_m = row["Monto"] / 1000000
            val_str = f"{int(val_m)}" if val_m.is_integer() else f"{val_m:.1f}"
            return f"+{val_str}M CLP" if row["Tipo"] == "Ingresos (+)" else f"-{val_str}M CLP"
            
        df_filtrado["Detalle_Tooltip"] = df_filtrado.apply(formato_tooltip_millones, axis=1)
        
        ingresos_totales = df_filtrado[df_filtrado["Tipo"] == "Ingresos (+)"]["Monto"].sum()
        egresos_totales = df_filtrado[df_filtrado["Tipo"] == "Egresos (-)"]["Monto"].sum()
        rentabilidad = ingresos_totales - egresos_totales
        
        st.divider()
        st.markdown(f"**{titulo_metricas}**")

        c1, c2, c3 = st.columns(3)
        c1.metric("Ingresos Acumulados", formato_clp(ingresos_totales))
        c2.metric("Egresos Acumulados", formato_clp(egresos_totales))
        c3.metric("Rentabilidad Neta", formato_clp(rentabilidad))
        
    st.write("") 
    
    with st.container(border=True):
        st.markdown("#### 📈 Estado de Resultado Mensualizado")

        if vista_balance == "Histórico Completo":
            x_scale = alt.Scale() 
            x_sort = meses_totales
        else:
            x_scale = alt.Scale(domain=meses_año_actual) 
            x_sort = meses_año_actual
            
        grafico_balance = alt.Chart(df_filtrado).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
            x=alt.X("Mes:O", title="Períodos", sort=x_sort, scale=x_scale, axis=alt.Axis(labelAngle=-45)),
            xOffset=alt.XOffset("Tipo:N", sort=["Ingresos (+)", "Egresos (-)"]),
            y=alt.Y("Monto:Q", 
                    title="", 
                    scale=alt.Scale(domain=[0, 100000000]), 
                    axis=alt.Axis(values=[0, 50000000, 100000000], labelExpr="datum.value == 0 ? '0' : datum.value / 1000000 + 'M'")),
            color=alt.Color("Tipo:N", 
                            scale=alt.Scale(domain=["Ingresos (+)", "Egresos (-)"], 
                                            range=["#3b82f6", "#e53e3e"]),
                            legend=alt.Legend(title="", orient="right")),
            tooltip=[
                alt.Tooltip("Mes:O", title="Período"),
                alt.Tooltip("Tipo:N", title="Concepto"),
                alt.Tooltip("Detalle_Tooltip:N", title="Impacto en Caja")
            ]
        ).properties(height=450)
        
        st.altair_chart(grafico_balance, width="stretch")
