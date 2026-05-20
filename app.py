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
import uuid

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
st.set_page_config(page_title="ERP Voltify", page_icon="⚡", layout="wide")

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
def conectar_google_sheets():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        secreto = st.secrets["google_credentials"]
        if isinstance(secreto, str): creds_dict = json.loads(secreto.strip())
        else: creds_dict = dict(secreto)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        return client.open("Base de Datos Voltify")
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

def guardar_datos(nombre_hoja, df):
    try:
        libro = conectar_google_sheets()
        df_clean = df.fillna(0)
        
        columnas_str = [
            'RUT', 'Gratificacion', 'Tipo_Contrato', 'Fecha_Inicio', 'Fecha_Termino', 'Fecha_Emision',
            'Num_OC', 'Fecha_Inicio_Proy', 'Fecha_Termino_Proy', 'Duracion_Proy', 'Nro_Serie',
            'Nombre_Material', 'Descripcion', 'Unidad', 'Tipo_Movimiento', 'Persona_Responsable', 'Destino', 'Fecha',
            'Prioridad', 'Estado', 'Tarea', 'Proyecto', 'Trabajador',
        ]
        for col in columnas_str:
            if col in df_clean.columns: df_clean[col] = df_clean[col].astype(str)
            
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df_clean.columns.tolist())
        hoja.clear()
        hoja.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
        return True
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")
        return False

def guardar_datos_diferido(nombre_hoja, df):
    """Encola persistencia a Google Sheets (un flush por ejecución / fragmento)."""
    if "_gs_pending" not in st.session_state:
        st.session_state._gs_pending = {}
    st.session_state._gs_pending[nombre_hoja] = df.copy()

def flush_guardados_diferidos():
    """Escribe en Sheets todo lo encolado en esta ejecución."""
    pending = st.session_state.pop("_gs_pending", None) or {}
    for nombre_hoja, df in pending.items():
        guardar_datos(nombre_hoja, df)

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

def cargar_datos(nombre_hoja, df_default):
    try:
        libro = conectar_google_sheets()
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df_default.columns.tolist())
        datos = hoja.get_all_records()
        if not datos: return df_default
        return pd.DataFrame(datos)
    except Exception:
        return df_default

# ==========================================
# 3. DATOS BASE Y CÁLCULOS
# ==========================================
TASAS_AFP = {
    "Capital (11.44%)": 0.1144, "Cuprum (11.44%)": 0.1144, "Habitat (11.27%)": 0.1127,
    "Modelo (10.58%)": 0.1058, "PlanVital (11.16%)": 0.1116, "ProVida (11.45%)": 0.1145,
    "Uno (10.69%)": 0.1069
}

def formato_clp(valor):
    try: return f"${int(valor):,.0f}".replace(",", ".")
    except (ValueError, TypeError): return "$0"

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
    "RUT", "Trabajador", "Cargo", "Sueldo_Base", "Jornada_Hrs", "Tipo_Contrato",
    "Gratificacion", "AFP", "Dias_Falta", "Horas_Atraso", "Horas_Extras",
    "Colacion", "Movilizacion", "Anticipo",
]

def sanitizar_nomina(df):
    """Asegura tipos numéricos en nómina (evita strings de formato en Sueldo_Base, etc.)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    cols_numericas = {
        "Sueldo_Base", "Jornada_Hrs", "Dias_Falta", "Horas_Atraso", "Horas_Extras",
        "Colacion", "Movilizacion", "Anticipo",
    }
    for col in COLUMNAS_NOMINA:
        if col not in out.columns:
            out[col] = 0 if col in cols_numericas else ""
    out = out[[c for c in COLUMNAS_NOMINA if c in out.columns]]
    enteros = ["Sueldo_Base", "Colacion", "Movilizacion", "Anticipo", "Horas_Atraso", "Horas_Extras", "Jornada_Hrs"]
    decimales = ["Dias_Falta"]
    for col in enteros:
        out[col] = out[col].apply(lambda v, c=col: int(round(a_numerico_clp(v))))
    for col in decimales:
        out[col] = out[col].apply(lambda v, c=col: float(a_numerico_clp(v)))
    return out

if 'nomina' not in st.session_state:
    df_nomina_base = pd.DataFrame([{
        "RUT": "11.111.111-1",
        "Trabajador": "Begoñia Mac-Conell Bacho", "Cargo": "Jefa de administracion y finanzas",
        "Sueldo_Base": 850000, "Jornada_Hrs": 44, "Tipo_Contrato": "Indefinido", "Gratificacion": "Tope Legal Mensual", "AFP": "Habitat (11.27%)",
        "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, "Colacion": 0, "Movilizacion": 0, "Anticipo": 0
    }])
    st.session_state.nomina = sanitizar_nomina(cargar_datos("Nomina_Personal", df_nomina_base))

columnas_obligatorias = ["Dias_Falta", "Horas_Atraso", "Horas_Extras", "Colacion", "Movilizacion", "Anticipo"]
for col in columnas_obligatorias:
    if col not in st.session_state.nomina.columns:
        st.session_state.nomina[col] = 0
st.session_state.nomina = sanitizar_nomina(st.session_state.nomina)

if 'RUT' not in st.session_state.nomina.columns:
    st.session_state.nomina['RUT'] = "Sin Registro"

if 'presupuestos' not in st.session_state:
    df_presupuestos_base = pd.DataFrame(columns=["Tipo", "Referencia", "Cliente", "Monto", "Aprobacion", "Orden_Compra", "Num_OC", "Estado_Comercial", "Fecha_Emision"])
    st.session_state.presupuestos = cargar_datos("Presupuestos", df_presupuestos_base)

if 'proyectos_resumen' not in st.session_state:
    df_resumen_base = pd.DataFrame(columns=["Proyecto", "Empresa", "Ciudad", "Num_OC", "Cobro", "Fecha_Inicio_Proy", "Fecha_Termino_Proy", "Duracion_Proy"])
    st.session_state.proyectos_resumen = cargar_datos("Proyectos_Resumen", df_resumen_base)

if 'proyectos_gastos' not in st.session_state:
    df_gastos_base = pd.DataFrame(columns=["Proyecto", "Detalle_Gasto", "Monto", "Dias_Asignados"])
    st.session_state.proyectos_gastos = cargar_datos("Proyectos_Gastos", df_gastos_base)

if 'Dias_Asignados' not in st.session_state.proyectos_gastos.columns:
    st.session_state.proyectos_gastos['Dias_Asignados'] = 0

# Días hábiles de referencia para imputación proporcional de costo mensual (asignación de personal en proyectos)
DIAS_MES_REFERENCIA_ASIGNACION = 22

if 'proyectos_equipo' not in st.session_state:
    df_equipo_base = pd.DataFrame(columns=["Proyecto", "Trabajador", "Rol_Proyecto"])
    st.session_state.proyectos_equipo = cargar_datos("Proyectos_Equipo", df_equipo_base)

COLUMNAS_OPERACIONES_TAREAS = [
    "Tarea", "Proyecto", "Trabajador", "Estado", "Prioridad",
    "Fecha_Inicio", "Fecha_Termino", "Dias_Duracion",
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
    out = df.copy()
    for col in COLUMNAS_OPERACIONES_TAREAS:
        if col not in out.columns:
            if col == "Prioridad":
                out[col] = "💤 Baja"
            elif col == "Estado":
                out[col] = "⚪ Pendiente"
            elif col == "Dias_Duracion":
                out[col] = float("nan")
            else:
                out[col] = ""
    out = out[COLUMNAS_OPERACIONES_TAREAS]
    out["Estado"] = out["Estado"].apply(normalizar_estado_tarea)
    out["Prioridad"] = out["Prioridad"].apply(normalizar_prioridad_tarea)
    out["Fecha_Inicio"] = out["Fecha_Inicio"].apply(_fecha_tarea_a_str)
    out["Fecha_Termino"] = out["Fecha_Termino"].apply(_fecha_tarea_a_str)
    out["Dias_Duracion"] = pd.to_numeric(out["Dias_Duracion"], errors="coerce")
    return out

if 'operaciones_tareas' not in st.session_state:
    df_tareas_base = pd.DataFrame(columns=COLUMNAS_OPERACIONES_TAREAS)
    ops_cargadas = cargar_datos("Operaciones_Tareas", df_tareas_base)
    if ops_cargadas.empty:
        legacy_base = pd.DataFrame(columns=["Proyecto", "Trabajador", "Tarea", "Estado", "Fecha_Inicio", "Fecha_Termino", "Dias_Duracion"])
        legacy = cargar_datos("Proyectos_Tareas", legacy_base)
        if not legacy.empty:
            if "Prioridad" not in legacy.columns:
                legacy["Prioridad"] = "💤 Baja"
            cols = [c for c in COLUMNAS_OPERACIONES_TAREAS if c in legacy.columns]
            ops_cargadas = legacy[cols].copy()
            ops_cargadas = sanitizar_operaciones_tareas(ops_cargadas)
            guardar_datos("Operaciones_Tareas", ops_cargadas)
    st.session_state.operaciones_tareas = sanitizar_operaciones_tareas(ops_cargadas)

if 'ops_tareas_rev' not in st.session_state:
    st.session_state.ops_tareas_rev = 0

if 'gastos_fijos' not in st.session_state:
    df_fijos_base = pd.DataFrame([{"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000}, {"Descripción": "prioridad emergencias", "Monto (CLP)": 50000}])
    st.session_state.gastos_fijos = cargar_datos("Gastos_Fijos", df_fijos_base)

COLUMNAS_BODEGA_STOCK = ["Codigo", "Familia", "Nombre_Material", "Descripcion", "Cantidad", "Unidad"]
COLUMNAS_BODEGA_HISTORIAL = [
    "Fecha", "Tipo_Movimiento", "Codigo", "Nombre_Material", "Cantidad",
    "Persona_Responsable", "Destino", "Stock_Resultante",
]

if 'bodega_stock' not in st.session_state:
    df_bodega_stock_base = pd.DataFrame([
        {"Codigo": 401, "Familia": 400, "Nombre_Material": 'Tornillo Cabeza Ancha 1"', "Descripcion": "Tornillería", "Cantidad": 0, "Unidad": "un"},
        {"Codigo": 402, "Familia": 400, "Nombre_Material": 'Tornillo Cabeza Ancha 2"', "Descripcion": "Tornillería", "Cantidad": 0, "Unidad": "un"},
    ])
    st.session_state.bodega_stock = cargar_datos("Bodega_Stock", df_bodega_stock_base)

if 'bodega_historial' not in st.session_state:
    df_bodega_hist_base = pd.DataFrame(columns=COLUMNAS_BODEGA_HISTORIAL)
    st.session_state.bodega_historial = cargar_datos("Bodega_Historial", df_bodega_hist_base)

def sanitizar_bodega_stock(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_BODEGA_STOCK)
    out = df.copy()
    for col in COLUMNAS_BODEGA_STOCK:
        if col not in out.columns:
            out[col] = "" if col in ("Nombre_Material", "Descripcion", "Unidad") else 0
    out = out[COLUMNAS_BODEGA_STOCK]
    out["Codigo"] = pd.to_numeric(out["Codigo"], errors="coerce").fillna(0).astype(int)
    out["Familia"] = pd.to_numeric(out["Familia"], errors="coerce").fillna(0).astype(int)
    out["Cantidad"] = pd.to_numeric(out["Cantidad"], errors="coerce").fillna(0).round(0).astype(int)
    out["Nombre_Material"] = out["Nombre_Material"].astype(str).str.strip()
    out["Descripcion"] = out["Descripcion"].astype(str)
    out["Unidad"] = out["Unidad"].astype(str).replace({"0": "un", "": "un"})
    out = out[out["Codigo"] > 0].drop_duplicates(subset=["Codigo"], keep="last")
    return out.reset_index(drop=True)

def sanitizar_bodega_historial(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_BODEGA_HISTORIAL)
    out = df.copy()
    for col in COLUMNAS_BODEGA_HISTORIAL:
        if col not in out.columns:
            out[col] = 0 if col in ("Codigo", "Cantidad", "Stock_Resultante") else ""
    out = out[COLUMNAS_BODEGA_HISTORIAL]
    out["Codigo"] = pd.to_numeric(out["Codigo"], errors="coerce").fillna(0).astype(int)
    out["Cantidad"] = pd.to_numeric(out["Cantidad"], errors="coerce").fillna(0).round(0).astype(int)
    out["Stock_Resultante"] = pd.to_numeric(out["Stock_Resultante"], errors="coerce").fillna(0).round(0).astype(int)
    out["Fecha"] = out["Fecha"].astype(str)
    out["Tipo_Movimiento"] = out["Tipo_Movimiento"].astype(str)
    out["Nombre_Material"] = out["Nombre_Material"].astype(str)
    out["Persona_Responsable"] = out["Persona_Responsable"].astype(str)
    out["Destino"] = out["Destino"].astype(str)
    return out.reset_index(drop=True)

def sugerir_codigo_bodega(df_stock, familia):
    """Siguiente código entero en la partida (ej. familia 400 → 401, 402…)."""
    familia = int(familia)
    df = sanitizar_bodega_stock(df_stock)
    en_familia = df[(df["Codigo"] > familia) & (df["Codigo"] < familia + 100)]
    if en_familia.empty:
        return familia + 1
    return int(en_familia["Codigo"].max()) + 1

def opciones_material_bodega(df_stock):
    df = sanitizar_bodega_stock(df_stock)
    if df.empty:
        return [], {}
    opts = []
    mapa = {}
    for _, r in df.iterrows():
        cod = int(r["Codigo"])
        label = f"{cod} — {r['Nombre_Material']} (stock: {int(r['Cantidad'])})"
        opts.append(label)
        mapa[label] = cod
    return opts, mapa

def limpiar_cache_streamlit():
    if hasattr(st, "cache_data"):
        st.cache_data.clear()

def guardar_operaciones_tareas():
    """Persiste el tablero en Operaciones_Tareas y refresca caché de Streamlit."""
    st.session_state.operaciones_tareas = sanitizar_operaciones_tareas(st.session_state.operaciones_tareas)
    st.session_state.operaciones_tareas = _migrar_dias_duracion_tareas(st.session_state.operaciones_tareas)
    ok = guardar_datos("Operaciones_Tareas", st.session_state.operaciones_tareas)
    limpiar_cache_streamlit()
    st.session_state.ops_tareas_rev = int(st.session_state.get("ops_tareas_rev", 0)) + 1
    st.session_state.pop(f"ed_ops_tareas_{st.session_state.ops_tareas_rev - 1}", None)
    return ok

def recargar_bodega_stock_desde_sheets():
    """Lee el stock vigente desde la hoja Bodega_Stock (fuente de verdad)."""
    base = pd.DataFrame(columns=COLUMNAS_BODEGA_STOCK)
    st.session_state.bodega_stock = sanitizar_bodega_stock(cargar_datos("Bodega_Stock", base))

def stock_actual_material(codigo):
    """Stock entero actual de un código en session_state."""
    stock = sanitizar_bodega_stock(st.session_state.bodega_stock)
    fila = stock[stock["Codigo"] == int(codigo)]
    if fila.empty:
        return None
    return int(fila.iloc[0]["Cantidad"])

def registrar_movimiento_bodega(codigo, cantidad, tipo_mov, fecha, persona, destino):
    """
    Lee Bodega_Stock, aplica entrada/salida (enteros), persiste stock + historial en Sheets.
    Retorna (ok, mensaje, stock_resultante o None).
    """
    recargar_bodega_stock_desde_sheets()

    cantidad = int(round(float(cantidad)))
    if cantidad <= 0:
        return False, "La cantidad debe ser un entero mayor a 0.", None

    codigo = int(codigo)
    tipo_mov = str(tipo_mov).strip()
    if tipo_mov not in ("Entrada", "Salida"):
        return False, "Tipo de movimiento inválido.", None

    stock = sanitizar_bodega_stock(st.session_state.bodega_stock)
    fila = stock[stock["Codigo"] == codigo]
    if fila.empty:
        return False, f"No existe material con código {codigo}.", None

    idx = fila.index[0]
    nombre = str(stock.at[idx, "Nombre_Material"])
    stock_actual = int(stock.at[idx, "Cantidad"])

    if tipo_mov == "Salida" and cantidad > stock_actual:
        return False, f"Cantidad insuficiente en bodega. Stock actual: {stock_actual}", stock_actual

    if tipo_mov == "Entrada":
        nuevo_stock = int(stock_actual + cantidad)
    else:
        nuevo_stock = int(stock_actual - cantidad)

    if nuevo_stock < 0:
        return False, f"Cantidad insuficiente en bodega. Stock actual: {stock_actual}", stock_actual

    stock.at[idx, "Cantidad"] = nuevo_stock
    st.session_state.bodega_stock = sanitizar_bodega_stock(stock)

    fecha_str = fecha.strftime("%Y-%m-%d") if hasattr(fecha, "strftime") else str(fecha)
    nueva_fila = pd.DataFrame([{
        "Fecha": fecha_str,
        "Tipo_Movimiento": tipo_mov,
        "Codigo": codigo,
        "Nombre_Material": nombre,
        "Cantidad": int(cantidad),
        "Persona_Responsable": str(persona).strip(),
        "Destino": str(destino).strip(),
        "Stock_Resultante": int(nuevo_stock),
    }])
    hist = sanitizar_bodega_historial(st.session_state.bodega_historial)
    st.session_state.bodega_historial = sanitizar_bodega_historial(
        pd.concat([hist, nueva_fila], ignore_index=True)
    )

    if not guardar_datos("Bodega_Stock", st.session_state.bodega_stock):
        return False, "No se pudo actualizar Bodega_Stock en Google Sheets.", stock_actual
    if not guardar_datos("Bodega_Historial", st.session_state.bodega_historial):
        return False, "Stock actualizado, pero falló el guardado del historial.", nuevo_stock

    refrescar_widgets_bodega_tras_movimiento()

    return True, f"{tipo_mov} registrada. Stock actualizado: {nuevo_stock} un.", nuevo_stock

def refrescar_widgets_bodega_tras_movimiento():
    """Sincroniza UI tras cambio de stock: caché, revisión de widgets y data_editor."""
    limpiar_cache_streamlit()
    rev_anterior = int(st.session_state.get("bod_stock_rev", 0))
    st.session_state.bod_stock_rev = rev_anterior + 1
    st.session_state.pop(f"ed_bodega_stock_{rev_anterior}", None)
    st.session_state.pop("ed_bodega_stock", None)

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
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).apply(formato_clp)
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
        out = out[out["Proyecto"] == proyecto]
    if trabajador and trabajador != "Todos":
        out = out[out["Trabajador"] == trabajador]
    if estado and estado != "Todos":
        out = out[out["Estado"] == estado]
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
        fi = parse_fecha_celda(row.get("Fecha_Inicio"))
        ff = parse_fecha_celda(row.get("Fecha_Termino"))
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
        fi = parse_fecha_celda(row.get("Fecha_Inicio"))
        ff = parse_fecha_celda(row.get("Fecha_Termino"))
        if not fi or not ff:
            continue
        if ff < fi:
            fi, ff = ff, fi
        if not tarea_solapa_mes(fi, ff, year, month):
            continue
        rows.append({
            "Trabajador": row["Trabajador"],
            "Proyecto": row["Proyecto"],
            "Tarea": row["Tarea"],
            "Estado": row["Estado"],
            "Prioridad": row["Prioridad"],
            "Inicio": fi.strftime("%d/%m/%Y"),
            "Término": ff.strftime("%d/%m/%Y"),
        })
    if not rows:
        return pd.DataFrame(columns=["Trabajador", "Proyecto", "Tarea", "Estado", "Prioridad", "Inicio", "Término"])
    return pd.DataFrame(rows)

def detectar_solapes_mes(df_tareas, year, month):
    avisos = []
    df = sanitizar_operaciones_tareas(df_tareas)
    for trab in sorted(df["Trabajador"].dropna().unique()):
        bloques = []
        for _, row in df[df["Trabajador"] == trab].iterrows():
            fi = parse_fecha_celda(row.get("Fecha_Inicio"))
            ff = parse_fecha_celda(row.get("Fecha_Termino"))
            if not fi or not ff:
                continue
            if ff < fi:
                fi, ff = ff, fi
            if tarea_solapa_mes(fi, ff, year, month):
                bloques.append((str(row["Tarea"]), str(row["Proyecto"]), fi, ff))
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
    df = df_tareas[df_tareas["Trabajador"] == trabajador]
    total = 0.0
    for _, row in df.iterrows():
        if not tarea_activa_capacidad(row.get("Estado")):
            continue
        f_ini = parse_fecha_celda(row.get("Fecha_Inicio"))
        f_fin = parse_fecha_celda(row.get("Fecha_Termino"))
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
        dd = row.get("Dias_Duracion")
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
            "Trabajador": trab,
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
        row = {"Trabajador": trab}
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
    cap_mes = dias_habiles_en_mes(y, m)
    st.caption(
        f"Mes de referencia: **{meses_nombres[m - 1]} {y}** — tope **{cap_mes}** días hábiles. "
        "Los **días asignados** suman tareas **pendientes y en proceso** en todos los proyectos (reparto por fechas)."
    )
    if not lista_trabajadores:
        st.info("No hay trabajadores en nómina para mostrar capacidad.")
        return
    df_tab = tabla_capacidad_personal(df_tareas, lista_trabajadores, y, m)
    st.dataframe(df_tab, use_container_width=True, hide_index=True)

def _wos_cambiar_estado_tarea(idx, nuevo_estado, mensaje="Estado actualizado"):
    st.session_state.operaciones_tareas.at[idx, "Estado"] = normalizar_estado_tarea(nuevo_estado)
    guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
    if hasattr(st, "toast"):
        st.toast(mensaje, icon="✅")

def _render_wos_tablero(proyecto_seg):
    """Tablero Kanban / lista (dentro del fragmento Work OS)."""
    tareas_proy = st.session_state.operaciones_tareas[
        st.session_state.operaciones_tareas["Proyecto"] == proyecto_seg
    ]
    lista_trabajadores_nomina = st.session_state.nomina["Trabajador"].tolist()
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
        if st.button("Crear Tarea", use_container_width=True, key=f"wos_btn_new_{proyecto_seg}"):
            if desc_tarea:
                nueva_tarea = pd.DataFrame([{
                    "Tarea": desc_tarea,
                    "Proyecto": proyecto_seg,
                    "Trabajador": encargado_tarea,
                    "Estado": "⚪ Pendiente",
                    "Prioridad": "💤 Baja",
                    "Fecha_Inicio": f_ini_tarea.strftime("%Y-%m-%d"),
                    "Fecha_Termino": f_fin_tarea.strftime("%Y-%m-%d"),
                    "Dias_Duracion": float(dias_duracion_nueva),
                }])
                st.session_state.operaciones_tareas = pd.concat(
                    [st.session_state.operaciones_tareas, nueva_tarea], ignore_index=True
                )
                guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
                if hasattr(st, "toast"):
                    st.toast("Tarea asignada.", icon="✅")
            else:
                st.error("Escribe una descripción para la tarea.")

    if tareas_proy.empty:
        st.info("No hay tareas registradas para este proyecto en el tablero.")
        flush_guardados_diferidos()
        return

    col_filt1, col_filt2 = st.columns([1, 2])
    trabajadores_con_tareas = tareas_proy["Trabajador"].unique().tolist()
    filtro_trabajador = col_filt1.selectbox(
        "🔍 Filtrar por Asignado:", ["👥 Todos"] + trabajadores_con_tareas, key=f"wos_filtro_{proyecto_seg}"
    )
    tipo_vista = col_filt2.radio(
        "Modo de Vista:", ["📌 Kanban Interactivo", "📋 Edición en Lista"], horizontal=True, key=f"wos_vista_{proyecto_seg}"
    )
    st.divider()

    if filtro_trabajador != "👥 Todos":
        df_vista_filtrada = tareas_proy[tareas_proy["Trabajador"] == filtro_trabajador].copy()
        mask_reemplazo = (
            (st.session_state.operaciones_tareas["Proyecto"] == proyecto_seg)
            & (st.session_state.operaciones_tareas["Trabajador"] == filtro_trabajador)
        )
    else:
        df_vista_filtrada = tareas_proy.copy()
        mask_reemplazo = st.session_state.operaciones_tareas["Proyecto"] == proyecto_seg

    if tipo_vista == "📌 Kanban Interactivo":
        col_pend, col_proc, col_est, col_listo = st.columns(4)
        with col_pend:
            st.markdown("<h4 style='text-align: center; color: #94a3b8;'>⚪ Pendiente</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["Estado"] == "⚪ Pendiente"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['Tarea']}**")
                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                    if st.button("▶️ Iniciar", key=f"start_{proyecto_seg}_{idx}", use_container_width=True):
                        _wos_cambiar_estado_tarea(idx, "🟡 En Proceso", "Tarea en proceso")

        with col_proc:
            st.markdown("<h4 style='text-align: center; color: #eab308;'>🟡 En Proceso</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["Estado"] == "🟡 En Proceso"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['Tarea']}**")
                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                    c1, c2 = st.columns(2)
                    if c1.button("⏸️ Estancar", key=f"pause_{proyecto_seg}_{idx}", use_container_width=True):
                        _wos_cambiar_estado_tarea(idx, "🔴 Estancado", "Tarea estancada")
                    if c2.button("✅ Listo", key=f"done_{proyecto_seg}_{idx}", use_container_width=True):
                        _wos_cambiar_estado_tarea(idx, "🟢 Listo", "Tarea completada")

        with col_est:
            st.markdown("<h4 style='text-align: center; color: #ef4444;'>🔴 Estancado</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["Estado"] == "🔴 Estancado"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['Tarea']}**")
                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                    if st.button("▶️ Reanudar", key=f"resume_{proyecto_seg}_{idx}", use_container_width=True):
                        _wos_cambiar_estado_tarea(idx, "🟡 En Proceso", "Tarea reanudada")

        with col_listo:
            st.markdown("<h4 style='text-align: center; color: #22c55e;'>🟢 Listo</h4>", unsafe_allow_html=True)
            for idx, row in df_vista_filtrada[df_vista_filtrada["Estado"] == "🟢 Listo"].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['Tarea']}**")
                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                    if st.button("↩️ Reabrir", key=f"revert_{proyecto_seg}_{idx}", use_container_width=True):
                        _wos_cambiar_estado_tarea(idx, "🟡 En Proceso", "Tarea reabierta")
    else:
        df_vista_filtrada = df_vista_filtrada.copy()
        df_vista_filtrada["Fecha_Inicio"] = pd.to_datetime(df_vista_filtrada["Fecha_Inicio"], errors="coerce").dt.date
        df_vista_filtrada["Fecha_Termino"] = pd.to_datetime(df_vista_filtrada["Fecha_Termino"], errors="coerce").dt.date
        if "Dias_Duracion" not in df_vista_filtrada.columns:
            df_vista_filtrada["Dias_Duracion"] = 1.0
        df_vista_filtrada["Dias_Duracion"] = pd.to_numeric(df_vista_filtrada["Dias_Duracion"], errors="coerce").fillna(1.0)

        df_tareas_editadas = st.data_editor(
            df_vista_filtrada,
            column_config={
                "Estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS_TAREA_OPERACIONES),
                "Prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORIDADES_TAREA),
                "Fecha_Inicio": st.column_config.DateColumn("Inicio"),
                "Fecha_Termino": st.column_config.DateColumn("Fin"),
                "Dias_Duracion": st.column_config.NumberColumn("Días duración (háb.)", min_value=0.5, step=0.5, format="%.1f"),
            },
            disabled=["Proyecto", "Trabajador", "Tarea"],
            hide_index=True,
            use_container_width=True,
            key=f"ed_tar_{proyecto_seg}",
        )

        if st.button("💾 Guardar Progreso de Tareas", type="primary", key=f"wos_save_lista_{proyecto_seg}"):
            df_tareas_editadas["Fecha_Inicio"] = df_tareas_editadas["Fecha_Inicio"].astype(str)
            df_tareas_editadas["Fecha_Termino"] = df_tareas_editadas["Fecha_Termino"].astype(str)
            df_tareas_editadas["Dias_Duracion"] = pd.to_numeric(df_tareas_editadas["Dias_Duracion"], errors="coerce").fillna(1.0)
            st.session_state.operaciones_tareas = st.session_state.operaciones_tareas[~mask_reemplazo]
            st.session_state.operaciones_tareas = pd.concat(
                [st.session_state.operaciones_tareas, df_tareas_editadas], ignore_index=True
            )
            guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
            if hasattr(st, "toast"):
                st.toast("Estados actualizados.", icon="✅")

    st.write("")
    with st.expander("🗑️ Zona de Peligro: Eliminar Tareas"):
        lista_nombres_tareas = [f"{row['Tarea']} ({row['Trabajador']})" for _, row in df_vista_filtrada.iterrows()]
        if lista_nombres_tareas:
            tarea_a_eliminar = st.selectbox("Selecciona la tarea a eliminar:", lista_nombres_tareas, key=f"wos_del_sel_{proyecto_seg}")
            if st.button("Eliminar Tarea Seleccionada", type="primary", key=f"wos_del_btn_{proyecto_seg}"):
                nombre_tarea = tarea_a_eliminar.rsplit(" (", 1)[0]
                nombre_trab = tarea_a_eliminar.rsplit(" (", 1)[1].replace(")", "")
                mask_eliminar = (
                    (st.session_state.operaciones_tareas["Proyecto"] == proyecto_seg)
                    & (st.session_state.operaciones_tareas["Tarea"] == nombre_tarea)
                    & (st.session_state.operaciones_tareas["Trabajador"] == nombre_trab)
                )
                st.session_state.operaciones_tareas = st.session_state.operaciones_tareas[~mask_eliminar]
                guardar_datos_diferido("Operaciones_Tareas", st.session_state.operaciones_tareas)
                if hasattr(st, "toast"):
                    st.toast("Tarea eliminada.", icon="🗑️")

    flush_guardados_diferidos()

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
    trabajadores_en_equipo = equipo_actual["Trabajador"].tolist()
    cambios_sync = False
    for trab in trabajadores_financiados:
        if trab not in trabajadores_en_equipo:
            nuevo_eq = pd.DataFrame([{"Proyecto": proyecto_seg, "Trabajador": trab, "Rol_Proyecto": "Por definir"}])
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

    st.caption("Asigna los roles del equipo en terreno:")
    df_eq_mod = st.data_editor(
        df_eq_editar,
        column_config={
            "Rol_Proyecto": st.column_config.SelectboxColumn(
                "Rol Operativo",
                options=["Por definir", "Líder de Proyecto", "Supervisor", "Técnico Especialista", "Operario", "Prevencionista"],
                required=True,
            )
        },
        disabled=["Proyecto", "Trabajador"],
        hide_index=True,
        use_container_width=True,
        key=f"ed_eq_{proyecto_seg}",
    )
    if st.button("💾 Guardar Roles del Equipo", type="primary", key=f"wos_save_eq_{proyecto_seg}"):
        st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[~mask_eq]
        st.session_state.proyectos_equipo = pd.concat([st.session_state.proyectos_equipo, df_eq_mod], ignore_index=True)
        guardar_datos_diferido("Proyectos_Equipo", st.session_state.proyectos_equipo)
        if hasattr(st, "toast"):
            st.toast("Roles del equipo actualizados.", icon="✅")

    flush_guardados_diferidos()

@_st_fragment
def _fragment_wos_workspace(proyecto_seg, idx_p_seg):
    """Proyecto activo: reruns aislados del resto del ERP (Finanzas, Balance, etc.)."""
    tareas_proy = st.session_state.operaciones_tareas[
        st.session_state.operaciones_tareas["Proyecto"] == proyecto_seg
    ]
    total_t = len(tareas_proy)
    terminadas = len(tareas_proy[tareas_proy["Estado"].str.contains("Listo|Terminada", na=False, case=False, regex=True)]) if total_t > 0 else 0
    porc = int((terminadas / total_t) * 100) if total_t > 0 else 0

    st.markdown(f"#### 🚀 Proyecto: {proyecto_seg}")
    st.progress(porc / 100.0, text=f"Progreso Global: {porc}% ({terminadas}/{total_t} Tareas Completadas)")
    st.write("")

    with st.container(border=True):
        st.markdown("##### 📊 Capacidad del equipo por mes")
        lista_nom_cap = st.session_state.nomina["Trabajador"].tolist()
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
        df_gantt["Fecha_Inicio"] = pd.to_datetime(df_gantt["Fecha_Inicio"], errors="coerce")
        df_gantt["Fecha_Termino"] = pd.to_datetime(df_gantt["Fecha_Termino"], errors="coerce")
        df_gantt = df_gantt.dropna(subset=["Fecha_Inicio", "Fecha_Termino"])
        if not df_gantt.empty:
            gantt = alt.Chart(df_gantt).mark_bar(cornerRadius=4, height=20).encode(
                x=alt.X("Fecha_Inicio:T", title="Fechas"),
                x2=alt.X2("Fecha_Termino:T"),
                y=alt.Y("Tarea:N", sort=alt.EncodingSortField(field="Fecha_Inicio", order="ascending"), title=""),
                color=alt.Color(
                    "Estado:N",
                    scale=alt.Scale(
                        domain=ESTADOS_TAREA_OPERACIONES,
                        range=["#94a3b8", "#eab308", "#ef4444", "#22c55e"],
                    ),
                ),
                tooltip=["Tarea", "Trabajador", "Estado", "Fecha_Inicio", "Fecha_Termino"],
            ).properties(height=350)
            st.altair_chart(gantt, use_container_width=True)
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
            if hasattr(st, "toast"):
                st.toast("Configuración actualizada.", icon="✅")

    flush_guardados_diferidos()

def preparar_datos_gantt(df_tareas):
    """DataFrame listo para px.timeline (Start, Finish, etiquetas)."""
    if df_tareas is None or df_tareas.empty:
        return pd.DataFrame()
    out = sanitizar_operaciones_tareas(df_tareas).copy()
    out["Start"] = pd.to_datetime(out["Fecha_Inicio"], errors="coerce")
    out["Finish"] = pd.to_datetime(out["Fecha_Termino"], errors="coerce")
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
    out["Barra"] = out["Tarea"].astype(str) + " (" + out["Proyecto"].astype(str) + ")"
    return out

def figura_gantt_plotly(df_gantt, color_por="Estado"):
    if df_gantt is None or df_gantt.empty:
        return None
    color_por = color_por if color_por in ("Estado", "Proyecto") else "Estado"
    fig = px.timeline(
        df_gantt,
        x_start="Start",
        x_end="Finish",
        y="Barra",
        color=color_por,
        color_discrete_map=COLOR_ESTADO_OPS if color_por == "Estado" else None,
        custom_data=["Trabajador", "Proyecto", "Estado", "Prioridad", "Tarea"],
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
        df.groupby("Estado", as_index=False)
        .size()
        .rename(columns={"size": "Cantidad"})
        .sort_values("Cantidad", ascending=False)
    )
    avance_rows = []
    for proy, grp in df.groupby("Proyecto"):
        total = len(grp)
        listas = grp["Estado"].astype(str).str.contains("Listo|Terminada", case=False, na=False).sum()
        avance_rows.append({
            "Proyecto": proy,
            "Avance_%": round((listas / total) * 100, 1) if total else 0.0,
            "Tareas_Listas": int(listas),
            "Tareas_Total": int(total),
        })
    por_proyecto = pd.DataFrame(avance_rows).sort_values("Avance_%", ascending=False)
    return por_estado, por_proyecto

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
                    "Tarea": str(nom_tarea).strip(),
                    "Proyecto": proy_tarea,
                    "Trabajador": asig_tarea,
                    "Estado": estado_tarea,
                    "Prioridad": prior_tarea,
                    "Fecha_Inicio": fi_ok.strftime("%Y-%m-%d"),
                    "Fecha_Termino": ff_ok.strftime("%Y-%m-%d"),
                    "Dias_Duracion": float(wd),
                }])
                st.session_state.operaciones_tareas = pd.concat(
                    [sanitizar_operaciones_tareas(st.session_state.operaciones_tareas), nueva],
                    ignore_index=True,
                )
                if guardar_operaciones_tareas():
                    if hasattr(st, "toast"):
                        st.toast("Tarea creada y guardada.", icon="✅")
                    st.success("Tarea registrada en Operaciones_Tareas.")

    with st.container(border=True):
        st.markdown("#### 📋 Tablero de tareas")
        if df_fil.empty:
            st.info("No hay tareas con estos filtros. Crea una tarea o amplía los filtros.")
        else:
            df_edit = df_fil.copy()
            indices_filas = list(df_fil.index)
            df_edit["Fecha_Inicio"] = pd.to_datetime(df_edit["Fecha_Inicio"], errors="coerce").dt.date
            df_edit["Fecha_Termino"] = pd.to_datetime(df_edit["Fecha_Termino"], errors="coerce").dt.date
            df_edit["Dias_Duracion"] = pd.to_numeric(df_edit["Dias_Duracion"], errors="coerce").fillna(1.0)

            df_tablero = st.data_editor(
                df_edit,
                column_config={
                    "Tarea": st.column_config.TextColumn("Tarea / Actividad", required=True),
                    "Proyecto": st.column_config.SelectboxColumn("Proyecto", options=lista_proy, required=True),
                    "Trabajador": st.column_config.SelectboxColumn("Responsable", options=lista_trab, required=True),
                    "Prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORIDADES_TAREA, required=True),
                    "Estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS_TAREA_OPERACIONES, required=True),
                    "Fecha_Inicio": st.column_config.DateColumn("Inicio", format="DD/MM/YYYY"),
                    "Fecha_Termino": st.column_config.DateColumn("Término", format="DD/MM/YYYY"),
                    "Dias_Duracion": st.column_config.NumberColumn("Días hábiles", min_value=0.5, step=0.5, format="%.1f"),
                },
                hide_index=True,
                use_container_width=True,
                key=f"ed_ops_tareas_{st.session_state.get('ops_tareas_rev', 0)}",
            )

            if st.button("💾 Guardar tablero", type="primary", key="ops_btn_guardar_tablero"):
                for pos, idx in enumerate(indices_filas):
                    if pos >= len(df_tablero):
                        break
                    actualizada = df_tablero.iloc[pos].copy()
                    actualizada["Fecha_Inicio"] = _fecha_tarea_a_str(actualizada["Fecha_Inicio"])
                    actualizada["Fecha_Termino"] = _fecha_tarea_a_str(actualizada["Fecha_Termino"])
                    actualizada["Estado"] = normalizar_estado_tarea(actualizada["Estado"])
                    actualizada["Prioridad"] = normalizar_prioridad_tarea(actualizada["Prioridad"])
                    st.session_state.operaciones_tareas.loc[idx] = actualizada
                if guardar_operaciones_tareas():
                    if hasattr(st, "toast"):
                        st.toast("Tablero sincronizado con Google Sheets.", icon="✅")
                    st.success("Cambios guardados en Operaciones_Tareas.")

            with st.expander("🗑️ Eliminar tarea"):
                opciones_del = [
                    f"{row['Tarea']} — {row['Proyecto']} ({row['Trabajador']})"
                    for _, row in df_fil.iterrows()
                ]
                if opciones_del:
                    sel_del = st.selectbox("Tarea a eliminar", opciones_del, key="ops_sel_del")
                    if st.button("Eliminar tarea seleccionada", type="primary", key="ops_btn_del"):
                        idx_real = df_fil.index[opciones_del.index(sel_del)]
                        st.session_state.operaciones_tareas = st.session_state.operaciones_tareas.drop(index=idx_real)
                        if guardar_operaciones_tareas():
                            st.success("Tarea eliminada.")

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
        color_gantt = g3.selectbox("Color por", ["Estado", "Proyecto"], key="ops_gantt_color")
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
            st.plotly_chart(fig, use_container_width=True, key="ops_gantt_chart")
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
                x="Estado",
                y="Cantidad",
                color="Estado",
                color_discrete_map=COLOR_ESTADO_OPS,
                text="Cantidad",
            )
            fig_est.update_layout(showlegend=False, height=360, margin=dict(t=32, b=8))
            fig_est.update_traces(textposition="outside")
            st.plotly_chart(fig_est, use_container_width=True)

    with st.container(border=True):
        st.markdown("#### 🎯 % de avance por proyecto")
        if por_proyecto.empty:
            st.info("Sin proyectos con tareas asignadas.")
        else:
            fig_av = px.bar(
                por_proyecto,
                x="Proyecto",
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
            st.plotly_chart(fig_av, use_container_width=True)
            st.dataframe(
                por_proyecto.rename(columns={
                    "Avance_%": "Avance %",
                    "Tareas_Listas": "Listas",
                    "Tareas_Total": "Total tareas",
                }),
                use_container_width=True,
                hide_index=True,
            )

    if lista_trab:
        with st.container(border=True):
            st.markdown("#### 👥 Capacidad mensual del equipo")
            render_panel_capacidad_trabajadores(df_base, lista_trab, key_suffix="ops_rend_cap")

def _modulo_operaciones():
    """Centro de mando: pestañas separadas; Gantt y tablero en fragmentos independientes."""
    st.caption("Centro de mando operativo — sincronizado con **Operaciones_Tareas** en Google Sheets.")

    lista_proy = (
        st.session_state.proyectos_resumen["Proyecto"].tolist()
        if not st.session_state.proyectos_resumen.empty else []
    )
    lista_trab = st.session_state.nomina["Trabajador"].tolist() if not st.session_state.nomina.empty else []

    if not lista_proy:
        st.warning("Crea al menos un proyecto en **Proyectos** para usar Operaciones.")
        return
    if not lista_trab:
        st.info("Registra trabajadores en **Finanzas** para asignar responsables.")

    df_base = sanitizar_operaciones_tareas(st.session_state.operaciones_tareas)
    total_t = len(df_base)
    listas = len(df_base[df_base["Estado"] == "🟢 Listo"]) if total_t else 0
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
    st.caption(
        "Códigos por familia/partida (ej. familia **400** tornillería: **401**, **402**…). "
        "Cantidades siempre en números enteros. El stock se calcula al registrar entradas o salidas."
    )

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
                if destino_tipo == "— Seleccione destino —":
                    destino_final = destino_otro.strip()
                elif destino_tipo == "Otro / Bodega general":
                    destino_final = destino_otro.strip() or "Bodega general"
                else:
                    destino_final = destino_tipo if not destino_otro.strip() else f"{destino_tipo} — {destino_otro.strip()}"

                if st.button("Registrar movimiento", type="primary", key="bod_btn_mov"):
                    if not persona_mov.strip():
                        st.error("Indica la persona responsable.")
                    elif not destino_final:
                        st.error("Indica el destino del material.")
                    elif codigo_mov is None:
                        st.error("Selecciona un material válido.")
                    else:
                        cant_int = int(cant_mov)
                        if tipo_mov == "Salida" and codigo_mov is not None:
                            stock_chk = stock_actual_material(codigo_mov)
                            if stock_chk is not None and cant_int > stock_chk:
                                st.error(f"Cantidad insuficiente en bodega. Stock actual: {stock_chk}")
                            else:
                                ok, msg, stock_res = registrar_movimiento_bodega(
                                    codigo_mov, cant_int, tipo_mov, fecha_mov, persona_mov, destino_final
                                )
                                if ok:
                                    if hasattr(st, "toast"):
                                        st.toast(msg, icon="✅")
                                    st.success(f"{msg} (código {codigo_mov})")
                                    if stock_res is not None:
                                        st.metric("Stock actualizado", f"{int(stock_res)} un.")
                                else:
                                    st.error(msg)
                        else:
                            ok, msg, stock_res = registrar_movimiento_bodega(
                                codigo_mov, cant_int, tipo_mov, fecha_mov, persona_mov, destino_final
                            )
                            if ok:
                                if hasattr(st, "toast"):
                                    st.toast(msg, icon="✅")
                                st.success(f"{msg} (código {codigo_mov})")
                                if stock_res is not None:
                                    st.metric("Stock actualizado", f"{int(stock_res)} un.")
                            else:
                                st.error(msg)

        with st.container(border=True):
            st.markdown("#### Histórico de movimientos")
            hist = sanitizar_bodega_historial(st.session_state.bodega_historial)
            if hist.empty:
                st.info("Aún no hay entradas ni salidas registradas.")
            else:
                hist = hist.copy()
                hist["_orden"] = pd.to_datetime(hist["Fecha"], errors="coerce")
                hist = hist.sort_values("_orden", ascending=False).drop(columns=["_orden"])
                st.dataframe(hist, use_container_width=True, hide_index=True)

    with tab_stock:
        with st.container(border=True):
            st.markdown("#### 🔍 Buscar en inventario de materiales")
            busqueda_bod = st.text_input(
                "Buscar por código o nombre:",
                placeholder="Ej: 401, tornillo, cable…",
                key="bod_busqueda",
            )
            df_stock_vista = sanitizar_bodega_stock(st.session_state.bodega_stock)
            if busqueda_bod:
                mask_b = (
                    df_stock_vista["Codigo"].astype(str).str.contains(busqueda_bod, case=False, na=False)
                    | df_stock_vista["Nombre_Material"].astype(str).str.contains(busqueda_bod, case=False, na=False)
                    | df_stock_vista["Familia"].astype(str).str.contains(busqueda_bod, case=False, na=False)
                )
                df_stock_vista = df_stock_vista[mask_b]
                if df_stock_vista.empty:
                    st.warning("Sin coincidencias en el inventario de materiales.")

        with st.container(border=True):
            with st.expander("➕ Alta en inventario de materiales", expanded=False):
                st.caption("Familia = partida (400 tornillería). Códigos típicos: 401, 402, 403…")
                ca, cb, cc = st.columns([1, 1, 2])
                familia_nueva = ca.number_input("Familia (partida)", min_value=1, step=1, value=400, format="%d", key="bod_fam_nueva")
                autogen = cb.checkbox("Autogenerar código", value=True, key="bod_autogen")
                sugerido = sugerir_codigo_bodega(st.session_state.bodega_stock, familia_nueva)
                if autogen:
                    codigo_nuevo = int(sugerido)
                    st.caption(f"Código sugerido para familia {int(familia_nueva)}: **{codigo_nuevo}**")
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
                        codigo_nuevo = int(codigo_nuevo)
                        stock_df = sanitizar_bodega_stock(st.session_state.bodega_stock)
                        if (stock_df["Codigo"] == codigo_nuevo).any():
                            st.error(f"El código {codigo_nuevo} ya existe. Elige otro o activa autogenerar.")
                        else:
                            fila_nueva = pd.DataFrame([{
                                "Codigo": codigo_nuevo,
                                "Familia": int(familia_nueva),
                                "Nombre_Material": str(nombre_nuevo).strip(),
                                "Descripcion": str(desc_nueva).strip(),
                                "Cantidad": int(stock_inicial),
                                "Unidad": "un",
                            }])
                            st.session_state.bodega_stock = pd.concat([stock_df, fila_nueva], ignore_index=True)
                            guardar_datos("Bodega_Stock", st.session_state.bodega_stock)
                            refrescar_widgets_bodega_tras_movimiento()
                            st.success(f"Material **{codigo_nuevo}** añadido al inventario de materiales.")
                            st.rerun()

        with st.container(border=True):
            st.markdown("#### Inventario de materiales")
            st.caption("Datos sincronizados con la hoja **Bodega_Stock** en Google Sheets.")
            if st.session_state.bodega_stock.empty:
                st.info("El inventario de materiales está vacío. Usa el formulario de alta.")
            else:
                df_stock_edit = st.data_editor(
                    sanitizar_bodega_stock(st.session_state.bodega_stock),
                    column_config={
                        "Codigo": st.column_config.NumberColumn("Código", min_value=1, step=1, format="%d"),
                        "Familia": st.column_config.NumberColumn("Familia", min_value=1, step=1, format="%d"),
                        "Nombre_Material": st.column_config.TextColumn("Material"),
                        "Descripcion": st.column_config.TextColumn("Descripción"),
                        "Cantidad": st.column_config.NumberColumn("Stock actual", min_value=0, step=1, format="%d"),
                        "Unidad": st.column_config.TextColumn("Unidad"),
                    },
                    disabled=["Codigo", "Cantidad"],
                    hide_index=True,
                    use_container_width=True,
                    key=f"ed_bodega_stock_{st.session_state.get('bod_stock_rev', 0)}",
                )
                st.caption("El **stock actual** se actualiza automáticamente al registrar entradas o salidas.")
                if st.button("💾 Guardar inventario de materiales", type="primary", key="bod_save_stock"):
                    st.session_state.bodega_stock = sanitizar_bodega_stock(df_stock_edit)
                    guardar_datos("Bodega_Stock", st.session_state.bodega_stock)
                    limpiar_cache_streamlit()
                    st.success("Inventario de materiales actualizado en Google Sheets (Bodega_Stock).")
                with st.expander("🗑️ Eliminar material del inventario"):
                    opts_del = [f"{int(r['Codigo'])} — {r['Nombre_Material']}" for _, r in df_stock_edit.iterrows()]
                    if opts_del:
                        sel_del = st.selectbox("Material a eliminar", opts_del, key="bod_del_mat")
                        if st.button("Eliminar del inventario", type="primary", key="bod_btn_del_mat"):
                            cod_del = int(sel_del.split("—")[0].strip())
                            st.session_state.bodega_stock = sanitizar_bodega_stock(
                                st.session_state.bodega_stock[st.session_state.bodega_stock["Codigo"] != cod_del]
                            )
                            guardar_datos("Bodega_Stock", st.session_state.bodega_stock)
                            refrescar_widgets_bodega_tras_movimiento()
                            st.success("Material eliminado del inventario de materiales.")
                            st.rerun()


def _migrar_dias_duracion_tareas(df):
    df = df.copy()
    if 'Dias_Duracion' not in df.columns:
        df['Dias_Duracion'] = float('nan')
    for idx in df.index:
        raw = df.at[idx, 'Dias_Duracion']
        try:
            if raw is not None and str(raw).strip() != "" and not (isinstance(raw, float) and pd.isna(raw)):
                float(raw)
                continue
        except (ValueError, TypeError):
            pass
        fi = parse_fecha_celda(df.at[idx, 'Fecha_Inicio'])
        ff = parse_fecha_celda(df.at[idx, 'Fecha_Termino'])
        if fi and ff:
            if ff < fi:
                fi, ff = ff, fi
            wd = contar_dias_habiles_rango(fi, ff)
            df.at[idx, 'Dias_Duracion'] = float(max(1, wd))
        else:
            df.at[idx, 'Dias_Duracion'] = 1.0
    return df

st.session_state.operaciones_tareas = _migrar_dias_duracion_tareas(st.session_state.operaciones_tareas)

def formatear_input(llave):
    val = str(st.session_state[llave]).replace(".", "").replace(",", "").replace("$", "").replace(" ", "").strip()
    try:
        val_num = int(val) if val else 0
        st.session_state[llave] = f"{val_num:,}".replace(",", ".")
    except ValueError:
        st.session_state[llave] = "0"

def calcular_liquidaciones(df):
    resultados = []
    costo_empresa_total = 0
    for index, row in df.iterrows():
        sueldo_base = a_numerico_clp(row.get('Sueldo_Base', 0))
        try: jornada = float(row.get('Jornada_Hrs', 44))
        except: jornada = 44.0
        
        dias_falta = float(a_numerico_clp(row.get('Dias_Falta', 0)))
        horas_atraso = float(a_numerico_clp(row.get('Horas_Atraso', 0)))
        horas_extras_qty = float(a_numerico_clp(row.get('Horas_Extras', 0)))
        anticipo = float(a_numerico_clp(row.get('Anticipo', 0)))
        
        valor_dia = sueldo_base / 30 if sueldo_base > 0 else 0
        valor_hora_normal = (sueldo_base / 30) * 28 / jornada if jornada > 0 else 0
        valor_hora_extra = valor_hora_normal * 1.5
        
        tipo_grati = str(row.get('Gratificacion', 'Sin Gratificación'))
        if tipo_grati == "Tope Legal Mensual": grati_monto = min(sueldo_base * 0.25, 197917)
        elif tipo_grati == "25% del Sueldo (Sin Tope)": grati_monto = sueldo_base * 0.25
        else: grati_monto = 0
            
        pago_extras = horas_extras_qty * valor_hora_extra
        dcto_faltas = dias_falta * valor_dia
        dcto_atrasos = horas_atraso * valor_hora_normal
        
        sueldo_imponible = sueldo_base + grati_monto + pago_extras - dcto_faltas - dcto_atrasos
        if sueldo_imponible < 0: sueldo_imponible = 0
        
        dcto_afp = sueldo_imponible * TASAS_AFP.get(row.get('AFP', 'Habitat (11.27%)'), 0.1144)
        dcto_fonasa = sueldo_imponible * 0.07
        
        tipo_contrato = str(row.get('Tipo_Contrato', 'Indefinido'))
        dcto_cesantia = sueldo_imponible * 0.006 if tipo_contrato == "Indefinido" else 0.0
        
        colacion = float(a_numerico_clp(row.get('Colacion', 0)))
        movilizacion = float(a_numerico_clp(row.get('Movilizacion', 0)))
        no_imponibles = colacion + movilizacion
        
        total_prevision = dcto_afp + dcto_fonasa + dcto_cesantia
        total_descuentos = total_prevision + anticipo 
        
        alcance_liquido = sueldo_imponible - total_prevision + no_imponibles
        total_a_pagar = alcance_liquido - anticipo
        
        costo_real_empresa = sueldo_imponible + no_imponibles
        costo_empresa_total += costo_real_empresa
        
        resultados.append({
            "RUT": str(row.get('RUT', 'Sin Registro')),
            "Trabajador": row['Trabajador'], "Cargo": row['Cargo'], "Contrato": tipo_contrato,
            "Sueldo Base": sueldo_base,
            "Sueldo Base Diario": valor_dia,
            "Sueldo Proporcional": sueldo_base - dcto_faltas - dcto_atrasos,
            "Horas Extras Monto": pago_extras, "Horas Extras Qty": horas_extras_qty,
            "Gratificacion": grati_monto,
            "Colacion": colacion, "Movilizacion": movilizacion, 
            "Nombre AFP": row.get('AFP', 'Habitat (11.27%)'), "Dcto AFP": dcto_afp,
            "Dcto Fonasa": dcto_fonasa, "Dcto Cesantia": dcto_cesantia,
            "Imponible Calculado": sueldo_imponible, "Haberes No Imponibles": no_imponibles, 
            "Total Haberes": sueldo_imponible + no_imponibles,
            "Total Prevision": total_prevision,
            "Anticipo": anticipo,
            "Total Descuentos": total_descuentos, 
            "Alcance Liquido": alcance_liquido,
            "Total a Pagar": total_a_pagar,
            "Costo Empresa": costo_real_empresa,
            "Dias_Falta": dias_falta,
            "Horas_Atraso": horas_atraso,
            "Dcto_Atraso_Monto": dcto_atrasos
        })
    return pd.DataFrame(resultados), costo_empresa_total

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


# ==========================================
# MOTOR PDF: LITERAR DEL DOCUMENTO WORD (¡BLOQUEADO - NO MODIFICAR!)
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
    trabajador_limpio = str(datos['Trabajador']).encode('latin-1', 'replace').decode('latin-1').upper()
    cargo_limpio = str(datos['Cargo']).encode('latin-1', 'replace').decode('latin-1').upper()
    rut_trabajador = datos.get("RUT", "Sin Registro")
    
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

    # 3. TÍTULOS DE COLUMNAS
    y += 10
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y, "HABERES")
    pdf.text(110, y, "DESCUENTOS")

    y += 6
    pdf.set_font("Arial", '', 9)
    y_start_cols = y

    # --- COLUMNA IZQUIERDA ---
    y_l = y_start_cols
    dias_falta_pdf = float(datos.get("Dias_Falta", 0) or 0)
    dias_trabajados = 30.0 - dias_falta_pdf
    dias_trabajados_str = f"{dias_trabajados:.1f}".replace(".", ",")
    pdf.text(10, y_l, f"Días Trabajados: {dias_trabajados_str}")
    
    y_l += 6
    pdf.text(10, y_l, "Sueldo:")
    right_text(pdf, 95, y_l, formato_clp(datos["Sueldo Proporcional"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(10, y_l, f"Horas : {datos['Horas Extras Qty']}     50.00%")
    y_l += 6
    pdf.text(10, y_l, "Total Horas Extras:")
    right_text(pdf, 95, y_l, formato_clp(datos["Horas Extras Monto"]).replace("$","").strip())
    
    y_l += 24 
    pdf.text(10, y_l, "Gratificación")
    right_text(pdf, 95, y_l, formato_clp(datos["Gratificacion"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(10, y_l, "Total Imponible:")
    right_text(pdf, 95, y_l, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(10, y_l, "Cargas:")
    
    y_l += 6
    pdf.text(35, y_l, "Asignación Movilización:")
    right_text(pdf, 95, y_l, formato_clp(datos["Movilizacion"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(35, y_l, "Asignación Colación:")
    right_text(pdf, 95, y_l, formato_clp(datos["Colacion"]).replace("$","").strip())
    
    y_l += 10
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y_l, "TOTAL HABERES:")
    right_text(pdf, 95, y_l, formato_clp(datos["Total Haberes"]).replace("$","").strip())
    pdf.set_font("Arial", '', 9)

    # --- COLUMNA DERECHA ---
    y_r = y_start_cols
    afp_nombre = datos["Nombre AFP"].split('(')[0].strip().upper()
    afp_tasa = datos["Nombre AFP"].split('(')[1].replace(')', '').strip() if '(' in datos["Nombre AFP"] else ""
    
    pdf.text(110, y_r, f"AFP:   {afp_nombre}")
    pdf.text(160, y_r, f"{afp_tasa}")
    
    y_r += 6
    pdf.text(130, y_r, "Base AFP:")
    right_text(pdf, 195, y_r, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(130, y_r, "Cotización AFP:")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto AFP"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(110, y_r, "Isapre:   Fonasa")
    
    y_r += 6
    pdf.text(110, y_r, "7% Obligatorio:")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto Fonasa"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(110, y_r, "Cotización Pactado:")
    pdf.text(145, y_r, "0 UF")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto Fonasa"]).replace("$","").strip()) 
    
    y_r += 6
    pdf.text(130, y_r, "Base AFC:")
    right_text(pdf, 195, y_r, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(130, y_r, "Cotización AFC Trabajador:")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto Cesantia"]).replace("$","").strip() if datos["Dcto Cesantia"] > 0 else "")
    
    y_r += 6
    pdf.text(130, y_r, "Total Previsión:")
    right_text(pdf, 195, y_r, formato_clp(datos["Total Prevision"]).replace("$","").strip())
    
    y_r += 6
    if datos["Horas_Atraso"] > 0:
        pdf.text(110, y_r, f"Atraso ( {datos['Horas_Atraso']} Horas )")
        right_text(pdf, 160, y_r, f"(-{int(datos['Dcto_Atraso_Monto'])})")
        
    pdf.text(165, y_r, "Días no Trabajados")
    y_r += 4
    pdf.text(165, y_r, "Vacación:")
    y_r += 4
    pdf.text(165, y_r, "Licencia:")
    y_r += 4
    pdf.text(165, y_r, "Faltas:")
    if datos["Dias_Falta"] > 0:
        dias_falta_str = f"{float(datos['Dias_Falta']):.1f}".replace(".", ",")
        pdf.text(180, y_r, f"{dias_falta_str} día(s)")
        
    y_r += 8
    pdf.text(130, y_r, "Base Tributable:")
    base_trib = datos["Imponible Calculado"] - datos["Total Prevision"]
    if base_trib < 0: base_trib = 0
    right_text(pdf, 195, y_r, formato_clp(base_trib).replace("$","").strip())
    
    if datos["Anticipo"] > 0:
        y_r += 6
        pdf.text(130, y_r, "Anticipo:")
        right_text(pdf, 195, y_r, formato_clp(datos["Anticipo"]).replace("$","").strip())

    # --- 4. TOTALES FINALES ---
    y_tot = max(y_l, y_r) + 15
    pdf.set_font("Arial", 'B', 9)
    
    pdf.text(110, y_tot, "TOTAL DESCUENTO")
    right_text(pdf, 195, y_tot, formato_clp(datos["Total Descuentos"]).replace("$","").strip())
    
    y_tot += 6
    pdf.text(110, y_tot, "ALCANCE LIQUIDO")
    right_text(pdf, 195, y_tot, formato_clp(datos["Alcance Liquido"]).replace("$","").strip())
    
    y_tot += 6
    pdf.text(110, y_tot, "TOTAL A PAGAR")
    right_text(pdf, 195, y_tot, formato_clp(datos["Total a Pagar"]).replace("$","").strip())
    
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
    temp_path = tempfile.mktemp(suffix=".pdf")
    pdf.output(temp_path)
    with open(temp_path, "rb") as f: pdf_bytes = f.read()
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
    temp_path = tempfile.mktemp(suffix=".pdf")
    pdf.output(temp_path)
    with open(temp_path, "rb") as f: pdf_bytes = f.read()
    os.remove(temp_path)
    return pdf_bytes

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
            st.image(LOGO_URL, use_container_width=True)
            st.markdown("<h2 style='text-align: center;'>Portal de Gestión Empresarial</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: gray;'>Acceso exclusivo para personal autorizado</p>", unsafe_allow_html=True)
            st.divider()
            u_gen = st.text_input("👤 Usuario Corporativo")
            p_gen = st.text_input("🔑 Clave de Acceso", type="password")
            st.write("")
            if st.button("Iniciar Sesión", type="primary", use_container_width=True):
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
    with st.popover("⚙️ Ajustes", use_container_width=True):
        st.markdown("**Opciones Globales**")
        if st.button("🔄 Sincronizar", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key not in ['acceso_app', 'acceso_finanzas', 'acceso_proyectos']: del st.session_state[key]
            st.rerun()
        if st.button("🔒 Bloquear", use_container_width=True):
            st.session_state.acceso_finanzas = "ninguno"
            st.session_state.acceso_proyectos = "ninguno"
            st.rerun()
        if st.button("🚪 Salir", use_container_width=True):
            st.session_state.acceso_app = False
            st.session_state.acceso_finanzas = "ninguno"
            st.session_state.acceso_proyectos = "ninguno"
            st.rerun()

st.write("") 

b0, b1, b2, b3, b4, b5, b6 = st.columns(7)

if b0.button("🏠 Inicio", type="primary" if st.session_state.menu_actual == "Inicio" else "secondary", use_container_width=True): st.session_state.menu_actual = "Inicio"; st.rerun()
if b1.button("💼 Finanzas", type="primary" if st.session_state.menu_actual == "Finanzas" else "secondary", use_container_width=True): st.session_state.menu_actual = "Finanzas"; st.rerun()
if b2.button("📝 Presup.", type="primary" if st.session_state.menu_actual == "Presupuestos" else "secondary", use_container_width=True): st.session_state.menu_actual = "Presupuestos"; st.rerun()
if b3.button("🏗️ Proyectos", type="primary" if st.session_state.menu_actual == "Proyectos" else "secondary", use_container_width=True): st.session_state.menu_actual = "Proyectos"; st.rerun()
if b4.button("⏱️ Operaciones", type="primary" if st.session_state.menu_actual == "Operaciones" else "secondary", use_container_width=True): st.session_state.menu_actual = "Operaciones"; st.rerun()
if b5.button("🏭 Bodega", type="primary" if st.session_state.menu_actual == "Bodega" else "secondary", use_container_width=True): st.session_state.menu_actual = "Bodega"; st.rerun()
if b6.button("📊 Balance", type="primary" if st.session_state.menu_actual == "Balance" else "secondary", use_container_width=True): st.session_state.menu_actual = "Balance"; st.rerun()

st.divider()

# ==========================================
# PANTALLA 0: HOME DASHBOARD
# ==========================================
if st.session_state.menu_actual == "Inicio":
    st.markdown("## 📊 Panel de Control General")
    st.caption("Visión global del estado de Voltify SpA.")
    
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
                    nombre_proy = row["Proyecto"]
                    tareas_proy = st.session_state.operaciones_tareas[st.session_state.operaciones_tareas["Proyecto"] == nombre_proy]
                    
                    if tareas_proy.empty:
                        st.write(f"**{nombre_proy}**: *Sin tareas asignadas*")
                        st.progress(0)
                    else:
                        terminadas = len(tareas_proy[tareas_proy["Estado"].str.contains("Listo|Terminada", na=False, case=False, regex=True)])
                        total = len(tareas_proy)
                        porcentaje = int((terminadas / total) * 100)
                        st.write(f"**{nombre_proy}**")
                        st.progress(porcentaje / 100.0, text=f"Completado: {porcentaje}%")

    with col_der:
        with st.container(border=True):
            st.markdown("#### 🚨 Alertas y Urgencias")
            
            # Tareas Urgentes
            tareas_urgentes = st.session_state.operaciones_tareas[
                st.session_state.operaciones_tareas["Estado"].isin(ESTADOS_TAREA_OPERACIONES[:3])
            ]
            if not tareas_urgentes.empty:
                st.write("**Tareas Pendientes en Terreno:**")
                st.dataframe(tareas_urgentes[['Proyecto', 'Tarea', 'Estado']], hide_index=True, use_container_width=True)
            else:
                st.success("¡Todo al día en terreno!")
            
            st.divider()
            stock_bajo = st.session_state.bodega_stock[st.session_state.bodega_stock["Cantidad"] <= 5]
            if not stock_bajo.empty:
                st.write("**Materiales con stock bajo (≤ 5 un.):**")
                st.dataframe(
                    stock_bajo[["Codigo", "Nombre_Material", "Cantidad"]],
                    hide_index=True,
                    use_container_width=True,
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
                            if st.button("💾 Guardar Perfil Fijo", type="primary", use_container_width=True):
                                if n_trabajador and n_rut:
                                    nuevo_perfil = pd.DataFrame([{
                                        "RUT": n_rut, "Trabajador": n_trabajador, "Cargo": n_cargo, "Sueldo_Base": n_sueldo, 
                                        "Jornada_Hrs": n_jornada, "Tipo_Contrato": n_contrato, "Gratificacion": n_grati, 
                                        "AFP": n_afp, "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, 
                                        "Colacion": n_cola, "Movilizacion": n_movi, "Anticipo": 0
                                    }])
                                    st.session_state.nomina = pd.concat([st.session_state.nomina, nuevo_perfil], ignore_index=True)
                                    guardar_datos("Nomina_Personal", st.session_state.nomina)
                                    limpiar_form_nomina()
                                    st.success("Trabajador registrado exitosamente.")
                                    st.rerun()
                                else:
                                    st.error("⚠️ El RUT y el Nombre Completo son obligatorios.")
                        with col_btn2:
                            if st.button("🧹 Limpiar Campos", use_container_width=True):
                                limpiar_form_nomina()
                                st.rerun()

                    st.caption("Modifique las variables del mes directamente en la tabla (Anticipo y Faltas están junto al Sueldo):")
                    df_nomina_edit = st.data_editor(
                        sanitizar_nomina(st.session_state.nomina),
                        column_config={
                            "RUT": None, 
                            "Sueldo_Base": st.column_config.NumberColumn("Sueldo Base", min_value=0, step=1000, format="%d"),
                            "Colacion": st.column_config.NumberColumn("Colación", min_value=0, step=1000, format="%d"),
                            "Movilizacion": st.column_config.NumberColumn("Movilización", min_value=0, step=1000, format="%d"),
                            "Tipo_Contrato": st.column_config.SelectboxColumn("Contrato", options=["Indefinido", "Plazo Fijo"]),
                            "Gratificacion": st.column_config.SelectboxColumn("Gratificación", options=["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"]),
                            "AFP": st.column_config.SelectboxColumn("AFP", options=list(TASAS_AFP.keys())),
                            "Dias_Falta": st.column_config.NumberColumn("Días Falta", min_value=0.0, step=0.5, format="%.1f"),
                            "Horas_Atraso": st.column_config.NumberColumn("Hrs Atraso", min_value=0),
                            "Horas_Extras": st.column_config.NumberColumn("Hrs Extras", min_value=0),
                            "Anticipo": st.column_config.NumberColumn("Anticipo ($)", min_value=0, step=1000, format="%d"),
                        },
                        column_order=["Trabajador", "Cargo", "Sueldo_Base", "Anticipo", "Dias_Falta", "Horas_Atraso", "Horas_Extras", "Colacion", "Movilizacion", "Jornada_Hrs", "Gratificacion", "AFP", "Tipo_Contrato"],
                        num_rows="dynamic", use_container_width=True, key="ed_nomina"
                    )
                    if st.button("💾 Guardar Cambios de Nómina / Mes", type="primary"):
                        st.session_state.nomina = sanitizar_nomina(df_nomina_edit)
                        guardar_datos("Nomina_Personal", st.session_state.nomina)
                        st.success("Nómina actualizada.")
                        
                    with st.expander("🗑️ Dar de Baja / Eliminar Trabajador"):
                        lista_trabajadores = st.session_state.nomina['Trabajador'].tolist()
                        if lista_trabajadores:
                            trab_a_borrar = st.selectbox("Selecciona el trabajador a eliminar:", lista_trabajadores)
                            if st.button("Eliminar Definitivamente", type="primary"):
                                st.session_state.nomina = st.session_state.nomina[st.session_state.nomina['Trabajador'] != trab_a_borrar].reset_index(drop=True)
                                guardar_datos("Nomina_Personal", st.session_state.nomina)
                                st.success(f"Trabajador {trab_a_borrar} dado de baja exitosamente.")
                                st.rerun()
                else:
                    df_nom_vis = st.session_state.nomina.drop(columns=["RUT"], errors="ignore").copy()
                    df_nom_vis = df_formateado_clp(df_nom_vis, ["Sueldo_Base", "Colacion", "Movilizacion", "Anticipo"])
                    st.dataframe(df_nom_vis, use_container_width=True)

            with st.container(border=True):
                st.subheader("Proyección de Liquidaciones")
                df_liquidaciones, total_nomina_empresa = calcular_liquidaciones(st.session_state.nomina)
                
                cols_liq = [
                    "Trabajador", "Cargo", "Sueldo Base", "Sueldo Base Diario",
                    "Imponible Calculado", "Total Prevision", "Anticipo", "Total a Pagar", "Costo Empresa",
                ]
                df_liq_visual = df_liquidaciones[[c for c in cols_liq if c in df_liquidaciones.columns]].copy()
                for col in [
                    "Sueldo Base", "Sueldo Base Diario", "Imponible Calculado",
                    "Total Prevision", "Anticipo", "Total a Pagar", "Costo Empresa",
                ]:
                    if col in df_liq_visual.columns:
                        df_liq_visual[col] = df_liq_visual[col].apply(formato_clp)
                    
                st.dataframe(df_liq_visual, use_container_width=True)
                st.info(f"**Costo Total Proyectado de Nómina:** {formato_clp(total_nomina_empresa)}")
                
                st.divider()
                st.markdown("#### 📄 Emisión de Liquidaciones Oficiales (PDF)")
                if FPDF_DISPONIBLE:
                    trab_lista = df_liquidaciones['Trabajador'].tolist()
                    if trab_lista:
                        col_sel, col_btn = st.columns([3, 1], vertical_alignment="bottom")
                        trab_seleccionado = col_sel.selectbox("Seleccione un trabajador para generar documento:", trab_lista)
                        datos_trabajador_pdf = df_liquidaciones[df_liquidaciones['Trabajador'] == trab_seleccionado].iloc[0]
                        pdf_generado_bytes = generar_pdf_liquidacion(datos_trabajador_pdf)
                        col_btn.download_button(
                            label="⬇️ Descargar PDF Oficial", data=pdf_generado_bytes,
                            file_name=f"Liquidacion_{trab_seleccionado.replace(' ', '_')}.pdf",
                            mime="application/pdf", type="primary", use_container_width=True
                        )
                else:
                    st.error("⚠️ La librería para crear PDFs no está instalada.")

        with tab_fijos:
            with st.container(border=True):
                st.subheader("Gastos Fijos Operativos")
                if st.session_state.acceso_finanzas == "admin":
                    res_fijos = st.data_editor(
                        st.session_state.gastos_fijos,
                        column_config={
                            "Descripción": st.column_config.TextColumn("Descripción"),
                            "Monto (CLP)": st.column_config.NumberColumn("Monto (CLP)", min_value=0, step=1000, format="%d"),
                        },
                        num_rows="dynamic",
                        use_container_width=True,
                    )
                    if st.button("💾 Guardar Cambios Fijos", type="primary"):
                        st.session_state.gastos_fijos = res_fijos
                        guardar_datos("Gastos_Fijos", res_fijos)
                        st.success("Gastos fijos actualizados.")
                else:
                    st.dataframe(
                        df_formateado_clp(st.session_state.gastos_fijos, ["Monto (CLP)"]),
                        use_container_width=True,
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
                        st.markdown("##### Borrador Contable Automático")
                        st.caption(f"📌 Referencia OC: {oc_fact}")
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
                st.caption(
                    "Días **asignados** = carga estimada en días hábiles según tareas **pendientes y en proceso** "
                    "(todos los proyectos). Los **días disponibles** son el balance frente al tope de días hábiles del mes."
                )
                lista_rend = st.session_state.nomina["Trabajador"].tolist()
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
                    st.dataframe(df_det, use_container_width=True, hide_index=True)

                    st.divider()
                    st.markdown("##### Estimación multi-mes (proyección de carga)")
                    st.caption(
                        "Misma lógica mes a mes: útil para anticipar picos. La fila inferior muestra los días hábiles de calendario por mes."
                    )
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
                    st.dataframe(df_ref, use_container_width=True, hide_index=True)

                    df_proj = tabla_proyeccion_carga_meses(
                        st.session_state.operaciones_tareas, lista_rend, y0, m0, int(n_meses_proj)
                    )
                    st.dataframe(df_proj, use_container_width=True, hide_index=True)

# ==========================================
# PANTALLA 2: PRESUPUESTOS Y COTIZACIONES
# ==========================================
elif st.session_state.menu_actual == "Presupuestos":
    st.markdown("### Gestión de Presupuestos y Cotizaciones")
    with st.container(border=True):
        with st.expander("➕ Crear Nueva Cotización / Presupuesto", expanded=False):
            tipo_pres = st.radio("Clasificación de la Venta:", ["Asociada a un Proyecto", "Venta de Productos (Independiente)"], horizontal=True)
            colP1, colP2 = st.columns(2)
            if tipo_pres == "Asociada a un Proyecto":
                proyectos_existentes = st.session_state.proyectos_resumen["Proyecto"].tolist()
                if proyectos_existentes:
                    ref_pres = colP1.selectbox("Seleccionar Proyecto:", proyectos_existentes)
                    idx_pres = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == ref_pres].index[0]
                    cliente_pres = st.session_state.proyectos_resumen.at[idx_pres, "Empresa"]
                    colP2.info(f"Cliente vinculado: **{cliente_pres}**")
                else:
                    st.warning("Aún no tienes proyectos creados.")
                    ref_pres, cliente_pres = None, None
            else:
                ref_pres = colP1.text_input("Nombre del Producto o Servicio:", placeholder="Ej: Venta de 50m cable eléctrico")
                cliente_pres = colP2.text_input("Nombre del Cliente:")
                
            colP3, colP4 = st.columns(2)
            if 'input_monto_presupuesto' not in st.session_state: st.session_state['input_monto_presupuesto'] = "0"
            colP3.text_input("Monto Total Cotizado (CLP):", key="input_monto_presupuesto", on_change=formatear_input, kwargs={'llave': 'input_monto_presupuesto'})
            monto_pres = float(st.session_state['input_monto_presupuesto'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
            
            fecha_pres = colP4.date_input("Fecha de Emisión:", format="DD/MM/YYYY")
            
            colP5, colP6, colP7 = st.columns(3)
            aprobacion_pres = colP5.selectbox("Estado de Aprobación:", ["⏳ Pendiente", "✅ Aprobada", "❌ No Aprobada"])
            orden_pres = colP6.selectbox("Respaldo de Orden:", ["Sin Orden", "Con Orden"])
            num_oc_pres = colP7.text_input("N° OC (Si aplica):", placeholder="Ej: OC-1234")
            if not num_oc_pres: num_oc_pres = "N/A"
            
            if st.button("Guardar Presupuesto", type="primary"):
                if ref_pres and cliente_pres and monto_pres > 0:
                    str_fecha = fecha_pres.strftime('%Y-%m-%d') if fecha_pres else ""
                    nuevo_presupuesto = pd.DataFrame([{
                        "Tipo": tipo_pres, "Referencia": ref_pres, "Cliente": cliente_pres,
                        "Monto": monto_pres, "Aprobacion": aprobacion_pres, "Orden_Compra": orden_pres,
                        "Num_OC": num_oc_pres, "Estado_Comercial": "📝 Presupuestada", "Fecha_Emision": str_fecha
                    }])
                    st.session_state.presupuestos = pd.concat([st.session_state.presupuestos, nuevo_presupuesto], ignore_index=True)
                    guardar_datos("Presupuestos", st.session_state.presupuestos)
                    st.session_state['input_monto_presupuesto'] = "0"
                    st.success("Presupuesto ingresado exitosamente.")
                    st.rerun()
                else:
                    st.error("Por favor, completa la referencia, el cliente y asegúrate de que el monto sea mayor a 0.")

    with st.container(border=True):
        st.subheader("Panel de Seguimiento Comercial")
        if st.session_state.presupuestos.empty:
            st.info("Aún no hay cotizaciones emitidas en el sistema.")
        else:
            opciones_estado = ["📝 Presupuestada", "🎯 Adjudicada", "🚀 En progreso", "📦 Entregada", "💳 Pagada"]
            opciones_aprobacion = ["⏳ Pendiente", "✅ Aprobada", "❌ No Aprobada", "Pendiente", "Aprobada", "No Aprobada"]
            opciones_orden = ["Sin Orden", "Con Orden"]
            
            df_pres_edit = st.data_editor(
                st.session_state.presupuestos,
                column_config={
                    "Monto": st.column_config.NumberColumn("Monto Total", min_value=0, step=1000, format="%d"),
                    "Aprobacion": st.column_config.SelectboxColumn("Aprobación", options=opciones_aprobacion),
                    "Orden_Compra": st.column_config.SelectboxColumn("Orden", options=opciones_orden),
                    "Num_OC": st.column_config.TextColumn("N° O.C."),
                    "Estado_Comercial": st.column_config.SelectboxColumn("Estado Comercial", options=opciones_estado),
                    "Fecha_Emision": st.column_config.TextColumn("Fecha Emisión")
                },
                disabled=["Tipo", "Referencia", "Cliente"], hide_index=True, use_container_width=True, key="ed_pres"
            )
            
            if st.button("💾 Guardar Estados Comerciales", type="primary"):
                st.session_state.presupuestos = df_pres_edit
                guardar_datos("Presupuestos", st.session_state.presupuestos)
                st.success("Estados actualizados.")
                
            with st.expander("🗑️ Eliminar un Presupuesto"):
                lista_borrar_pres = [f"[{row['Estado_Comercial']}] {row['Referencia']} - {row['Cliente']} ({formato_clp(row['Monto'])})" for i, row in st.session_state.presupuestos.iterrows()]
                if lista_borrar_pres:
                    pres_a_borrar = st.selectbox("Selecciona la cotización a eliminar:", lista_borrar_pres)
                    if st.button("Eliminar Presupuesto Definitivamente"):
                        idx_borrar = lista_borrar_pres.index(pres_a_borrar)
                        st.session_state.presupuestos = st.session_state.presupuestos.drop(st.session_state.presupuestos.index[idx_borrar]).reset_index(drop=True)
                        guardar_datos("Presupuestos", st.session_state.presupuestos)
                        st.success("Cotización eliminada correctamente.")
                        st.rerun()

# ==========================================
# PANTALLA 3: PROYECTOS
# ==========================================
elif st.session_state.menu_actual == "Proyectos":
    st.markdown("### Finanzas de Proyectos")
    if st.session_state.acceso_proyectos == "ninguno":
        with st.container(border=True):
            st.info("🔒 Ingresa credenciales de administrador para desbloquear este módulo.")
            col1, col2 = st.columns([1, 2])
            with col1:
                u_proy = st.text_input("Usuario (Proyectos)")
                p_proy = st.text_input("Clave", type="password", key="p_proy")
                if st.button("Desbloquear Módulo", type="primary"):
                    if (u_proy == "master" and p_proy == "123") or (u_proy == "admin_proy" and p_proy == "admin123"): st.session_state.acceso_proyectos = "admin"; st.rerun()
                    elif (u_proy == "obs_proy" and p_proy == "obs123"): st.session_state.acceso_proyectos = "observador"; st.rerun()
                    else: st.error("Credenciales incorrectas.")
    else:
        if st.session_state.acceso_proyectos == "admin":
            with st.container(border=True):
                with st.expander("➕ Crear Nueva Carpeta de Proyecto", expanded=False):
                    colA, colB = st.columns(2)
                    nombre_p = colA.text_input("Nombre de la Obra o Proyecto")
                    empresa_p = colB.text_input("Nombre de la Empresa / Cliente")
                    colC, colD = st.columns(2)
                    ciudad_p = colC.text_input("Ciudad de ejecución")
                    oc_p = colD.text_input("N° Orden de Compra (Si la tienes)", placeholder="Ej: OC-4567")
                    
                    if st.button("Crear Proyecto", type="primary"):
                        if nombre_p and nombre_p not in st.session_state.proyectos_resumen["Proyecto"].values:
                            ciudad_final = ciudad_p if ciudad_p else "No especificada"
                            oc_final = oc_p if oc_p else "Pendiente"
                            nuevo_resumen = pd.DataFrame([{
                                "Proyecto": nombre_p, "Empresa": empresa_p, "Ciudad": ciudad_final, 
                                "Num_OC": oc_final, "Cobro": 0, "Fecha_Inicio_Proy": "Pendiente", 
                                "Fecha_Termino_Proy": "Pendiente", "Duracion_Proy": "Pendiente"
                            }])
                            nuevo_gasto = pd.DataFrame([{"Proyecto": nombre_p, "Detalle_Gasto": "Materiales iniciales", "Monto": 0, "Dias_Asignados": 0}])
                            st.session_state.proyectos_resumen = pd.concat([st.session_state.proyectos_resumen, nuevo_resumen], ignore_index=True)
                            st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto], ignore_index=True)
                            guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                            guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                            st.success(f"Carpeta '{nombre_p}' creada en {ciudad_final}.")
                            st.rerun()

        proyectos_lista = st.session_state.proyectos_resumen["Proyecto"].tolist()
        if proyectos_lista:
            proyecto_seleccionado = st.selectbox("📂 Selecciona un proyecto para gestionar sus finanzas:", proyectos_lista)
            idx_proy = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_seleccionado].index[0]
            cobro_actual = st.session_state.proyectos_resumen.at[idx_proy, "Cobro"]
            oc_actual = st.session_state.proyectos_resumen.at[idx_proy, "Num_OC"]
            df_gastos_proy = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seleccionado].copy()

            tareas_de_este_proyecto = st.session_state.operaciones_tareas[st.session_state.operaciones_tareas["Proyecto"] == proyecto_seleccionado]
            if not tareas_de_este_proyecto.empty:
                terminadas = len(tareas_de_este_proyecto[tareas_de_este_proyecto["Estado"].str.contains("Listo|Terminada", na=False, case=False, regex=True)])
                total_t = len(tareas_de_este_proyecto)
                porc = int((terminadas / total_t) * 100)
                st.progress(porc / 100.0, text=f"Avance Operativo del Proyecto: {porc}% ({terminadas} de {total_t} tareas)")
            st.write("")

            with st.container(border=True):
                st.markdown("##### 📊 Capacidad del equipo por mes")
                lista_nom_cap = st.session_state.nomina["Trabajador"].tolist()
                render_panel_capacidad_trabajadores(st.session_state.operaciones_tareas, lista_nom_cap, key_suffix="fin_proy")
            st.write("")

            col_izq, col_der = st.columns([1, 2])
            with col_izq:
                with st.container(border=True):
                    st.write("#### Datos de Ingreso")
                    if st.session_state.acceso_proyectos == "admin":
                        llave_oc = f"oc_{proyecto_seleccionado}"
                        if llave_oc not in st.session_state: st.session_state[llave_oc] = str(oc_actual)
                        nueva_oc = st.text_input("N° Orden de Compra:", key=llave_oc)
                        
                        llave_cobro = f"cobro_{proyecto_seleccionado}"
                        if llave_cobro not in st.session_state: st.session_state[llave_cobro] = f"{int(cobro_actual):,}".replace(",", ".")
                        st.text_input("Valor total cobrado (CLP):", key=llave_cobro, on_change=formatear_input, kwargs={'llave': llave_cobro})
                        nuevo_cobro = float(st.session_state[llave_cobro].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                    else:
                        st.info(f"N° OC: {oc_actual}")
                        st.info(f"Cobro Total: {formato_clp(cobro_actual)}")
                        nueva_oc = oc_actual; nuevo_cobro = cobro_actual

            with col_der:
                with st.container(border=True):
                    st.write("#### Gastos Desglosados")
                    if st.session_state.acceso_proyectos == "admin":
                        # Alta rápida (forzada con key v2 para evitar estado corrupto)
                        st.markdown("##### ➕ Añadir gasto manual")
                        c_add1, c_add2, c_add3 = st.columns([3, 1, 1], vertical_alignment="bottom")
                        desc_manual = c_add1.text_input(
                            "Detalle de gasto",
                            value="",
                            placeholder="Ej: Compra materiales, arriendo herramienta, traslado, etc.",
                            key=f"desc_gasto_v2_{proyecto_seleccionado}",
                        )
                        with c_add2:
                            monto_manual = st.number_input(
                                "Monto (CLP)",
                                min_value=0,
                                step=1000,
                                value=0,
                                format="%d",
                                key=f"monto_gasto_v2_{proyecto_seleccionado}",
                            )
                            st.caption(formato_clp(int(monto_manual)))
                        dias_manual_g = c_add3.number_input(
                            "Días (opcional)",
                            min_value=0.0,
                            step=0.5,
                            value=0.0,
                            format="%.2f",
                            key=f"dias_gasto_v2_{proyecto_seleccionado}",
                        )
                        if st.button("Añadir gasto", type="primary", use_container_width=True, key=f"btn_add_gasto_v2_{proyecto_seleccionado}"):
                            if str(desc_manual).strip() == "":
                                st.error("Escribe un detalle de gasto para poder guardarlo.")
                            else:
                                nuevo_gasto_manual = pd.DataFrame([{
                                    "Proyecto": proyecto_seleccionado,
                                    "Detalle_Gasto": str(desc_manual).strip(),
                                    "Monto": int(monto_manual),
                                    "Dias_Asignados": float(dias_manual_g),
                                }])
                                st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto_manual], ignore_index=True)
                                ok = guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                                if ok:
                                    st.success("Gasto añadido correctamente en Google Sheets.")
                                st.rerun()

                        st.divider()
                        cols_g = ["Detalle_Gasto", "Monto", "Dias_Asignados"]
                        for c in cols_g:
                            if c not in df_gastos_proy.columns:
                                df_gastos_proy[c] = 0 if c == "Dias_Asignados" else ""
                        df_gastos_proy["Detalle_Gasto"] = df_gastos_proy["Detalle_Gasto"].astype(str)
                        df_gastos_editados = st.data_editor(
                            df_gastos_proy[cols_g],
                            column_config={
                                "Detalle_Gasto": st.column_config.TextColumn("Detalle de gasto"),
                                "Monto": st.column_config.NumberColumn("Monto (CLP)", min_value=0, step=1000, format="%d"),
                                "Dias_Asignados": st.column_config.NumberColumn("Días asignados", min_value=0.0, step=0.5, format="%.1f"),
                            },
                            num_rows="dynamic",
                            use_container_width=True,
                            key=f"ed_gastos_v2_{proyecto_seleccionado}",
                        )

                        c_gsave, c_gdel = st.columns([1, 1], vertical_alignment="bottom")
                        with c_gsave:
                            if st.button("💾 Guardar cambios de Gastos", type="primary", use_container_width=True, key=f"save_gastos_{proyecto_seleccionado}"):
                                # Persistir cambios (incluye eliminaciones hechas en el editor)
                                st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[
                                    st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado
                                ]
                                df_tmp = df_gastos_editados.copy()
                                df_tmp["Proyecto"] = proyecto_seleccionado
                                if "Dias_Asignados" not in df_tmp.columns:
                                    df_tmp["Dias_Asignados"] = 0
                                df_tmp["Dias_Asignados"] = pd.to_numeric(df_tmp["Dias_Asignados"], errors="coerce").fillna(0)
                                df_tmp["Monto"] = pd.to_numeric(df_tmp["Monto"], errors="coerce").fillna(0)
                                st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, df_tmp], ignore_index=True)
                                ok = guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                                if ok:
                                    st.success("Gastos actualizados correctamente en Google Sheets.")
                                st.rerun()

                        with c_gdel:
                            with st.popover("🗑️ Eliminar 1 gasto"):
                                st.caption("Eliminación inmediata en Google Sheets (evita que reaparezca al recargar).")
                                df_full = st.session_state.proyectos_gastos.reset_index(drop=True)
                                df_sel = df_full[df_full["Proyecto"] == proyecto_seleccionado].copy()
                                if df_sel.empty:
                                    st.info("No hay gastos para eliminar en este proyecto.")
                                else:
                                    df_sel = df_sel.reset_index(drop=False).rename(columns={"index": "_pos_full"})
                                    opciones = []
                                    for _, r in df_sel.iterrows():
                                        detalle = str(r.get("Detalle_Gasto", "")).strip()
                                        monto = float(r.get("Monto", 0) or 0)
                                        dias_a = float(r.get("Dias_Asignados", 0) or 0)
                                        opciones.append(f"[{int(r['_pos_full'])}] {detalle} — {formato_clp(monto)} — {dias_a:g} días")
                                    sel = st.selectbox("Selecciona gasto", opciones, key=f"del_gasto_sel_{proyecto_seleccionado}")
                                    confirmar = st.checkbox("Confirmo eliminación", key=f"del_gasto_ok_{proyecto_seleccionado}")
                                    if st.button("Eliminar definitivamente", type="primary", use_container_width=True, disabled=not confirmar, key=f"del_gasto_btn_{proyecto_seleccionado}"):
                                        pos_full = int(sel.split("]")[0].replace("[", "").strip())
                                        # row en Google Sheets: +2 (fila 1 = header, fila 2 = primer dato)
                                        row_sheet = pos_full + 2
                                        ok_api = eliminar_fila_google_sheet("Proyectos_Gastos", row_sheet)
                                        if ok_api:
                                            st.session_state.proyectos_gastos = df_full.drop(index=pos_full).reset_index(drop=True)
                                            st.success("Gasto eliminado correctamente en Google Sheets.")
                                            st.rerun()
                    else:
                        cols_show = [c for c in ["Detalle_Gasto", "Monto", "Dias_Asignados"] if c in df_gastos_proy.columns]
                        if not cols_show:
                            cols_show = ["Detalle_Gasto", "Monto"]
                        df_gastos_editados = df_gastos_proy[cols_show].copy()
                        df_gastos_vis = df_formateado_clp(df_gastos_editados, ["Monto"])
                        st.dataframe(df_gastos_vis, use_container_width=True)

            if st.session_state.acceso_proyectos == "admin":
                with st.container(border=True):
                    with st.expander("💸 Asignar Personal y Cargar al Gasto (Vínculo a Operaciones)", expanded=False):
                        st.info(
                            "💡 Imputación por **días** respecto a **22 días hábiles** de referencia: el costo mensual del trabajador se reparte "
                            f"proporcionalmente (100% = {DIAS_MES_REFERENCIA_ASIGNACION} días = mes completo). También puedes cargar por horas."
                        )
                        df_liq, _ = calcular_liquidaciones(st.session_state.nomina)
                        trabajadores = ["Seleccione..."] + df_liq["Trabajador"].tolist()
                        
                        colT1, colT2 = st.columns([1, 1])
                        with colT1:
                            trabajador_sel = st.selectbox("Trabajador", trabajadores, key=f"pers_sel_{proyecto_seleccionado}")
                            
                            if trabajador_sel != "Seleccione...":
                                costo_emp_trab = df_liq[df_liq["Trabajador"] == trabajador_sel]["Costo Empresa"].values[0]
                                row_trab = st.session_state.nomina[st.session_state.nomina['Trabajador'] == trabajador_sel].iloc[0]
                                jornada_t = float(row_trab.get('Jornada_Hrs', 44))
                                valor_hora_costo = (costo_emp_trab / 30) * 28 / jornada_t if jornada_t > 0 else 0
                                
                                st.info(
                                    f"**Costo mensual (referencia {DIAS_MES_REFERENCIA_ASIGNACION} días):** {formato_clp(costo_emp_trab)}\n\n"
                                    f"**Valor hora (aprox.):** {formato_clp(valor_hora_costo)}"
                                )
                        
                        with colT2:
                            if trabajador_sel != "Seleccione...":
                                tipo_asig = st.radio(
                                    "Método de asignación:",
                                    ["Por días al mes", "Por horas dedicadas"],
                                    key=f"pers_metodo_{proyecto_seleccionado}",
                                )
                                
                                if tipo_asig == "Por días al mes":
                                    asignar_full = st.checkbox(
                                        "Asignar al 100%",
                                        value=False,
                                        help=f"Equivale a {DIAS_MES_REFERENCIA_ASIGNACION} días hábiles de referencia y al costo mensual completo.",
                                        key=f"pers_100_{proyecto_seleccionado}",
                                    )
                                    dias_manual = st.number_input(
                                        "Días (manual)",
                                        min_value=0.5,
                                        max_value=366.0,
                                        step=0.5,
                                        value=10.0,
                                        disabled=asignar_full,
                                        key=f"pers_dias_{proyecto_seleccionado}",
                                    )
                                    dias_efectivos = float(DIAS_MES_REFERENCIA_ASIGNACION) if asignar_full else float(dias_manual)
                                    costo_dias = costo_emp_trab * (dias_efectivos / DIAS_MES_REFERENCIA_ASIGNACION)
                                    st.caption(
                                        f"Días utilizados en el cálculo: **{dias_efectivos:g}** (base {DIAS_MES_REFERENCIA_ASIGNACION} días hábiles)."
                                    )
                                    st.write(f"Costo a imputar: **{formato_clp(costo_dias)}**")
                                    if st.button("Añadir cargo por días al gasto", type="primary", use_container_width=True, key=f"btn_dias_{proyecto_seleccionado}"):
                                        nuevo_gasto_trab = pd.DataFrame([{
                                            "Proyecto": proyecto_seleccionado,
                                            "Detalle_Gasto": f"Mano de obra ({dias_efectivos:g} días): {trabajador_sel}",
                                            "Monto": costo_dias,
                                            "Dias_Asignados": dias_efectivos,
                                        }])
                                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto_trab], ignore_index=True)
                                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                                        st.rerun()
                                else:
                                    horas_input = st.number_input("Horas a imputar al proyecto:", min_value=0.5, step=0.5, value=10.0, key=f"pers_hrs_{proyecto_seleccionado}")
                                    costo_calc = horas_input * valor_hora_costo
                                    st.write(f"Costo a imputar: **{formato_clp(costo_calc)}**")
                                    if st.button("Añadir horas al gasto", type="primary", use_container_width=True, key=f"btn_hrs_{proyecto_seleccionado}"):
                                        nuevo_gasto_trab = pd.DataFrame([{
                                            "Proyecto": proyecto_seleccionado,
                                            "Detalle_Gasto": f"Mano de obra ({horas_input} hrs): {trabajador_sel}",
                                            "Monto": costo_calc,
                                            "Dias_Asignados": 0,
                                        }])
                                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto_trab], ignore_index=True)
                                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                                        st.rerun()

            gastos_totales = pd.to_numeric(df_gastos_editados["Monto"], errors='coerce').sum()
            ganancia_proyecto = nuevo_cobro - gastos_totales
            
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.metric("Cobro Acordado", formato_clp(nuevo_cobro))
                c2.metric("Gastos Totales", formato_clp(gastos_totales))
                c3.metric("Margen de Ganancia", formato_clp(ganancia_proyecto))

            if st.session_state.acceso_proyectos == "admin":
                col_save, col_del = st.columns(2)
                with col_save:
                    if st.button("💾 Guardar Finanzas de Proyecto", type="primary", use_container_width=True):
                        st.session_state.proyectos_resumen.at[idx_proy, "Cobro"] = nuevo_cobro
                        st.session_state.proyectos_resumen.at[idx_proy, "Num_OC"] = nueva_oc 
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado]
                        df_gastos_editados["Proyecto"] = proyecto_seleccionado
                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, df_gastos_editados], ignore_index=True)
                        ok1 = guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        ok2 = guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        if ok1 and ok2:
                            st.success("Guardado correctamente en Google Sheets.")
                with col_del:
                    if st.button("🗑️ Eliminar Proyecto Completo", use_container_width=True):
                        st.session_state.proyectos_resumen = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] != proyecto_seleccionado]
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado]
                        if 'proyectos_equipo' in st.session_state:
                            st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[st.session_state.proyectos_equipo["Proyecto"] != proyecto_seleccionado]
                            guardar_datos("Proyectos_Equipo", st.session_state.proyectos_equipo)
                        if 'operaciones_tareas' in st.session_state:
                            st.session_state.operaciones_tareas = st.session_state.operaciones_tareas[st.session_state.operaciones_tareas["Proyecto"] != proyecto_seleccionado]
                            guardar_datos("Operaciones_Tareas", st.session_state.operaciones_tareas)
                            limpiar_cache_streamlit()
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.rerun()

# ==========================================
# PANTALLA 4: OPERACIONES — TABLERO MONDAY
# ==========================================
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
                        gastos_asoc = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == row["Proyecto"]]["Monto"].sum()
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
            desc_metricas = "Rendimiento y proyección de los 12 meses del año actual."
        elif vista_balance == "Vista Mensual Específica":
            mes_actual_str = f"{current_year}-{str(datetime.datetime.now().month).zfill(2)}"
            idx_mes = meses_totales.index(mes_actual_str) if mes_actual_str in meses_totales else 0
            mes_seleccionado = col_f2.selectbox("Seleccionar Mes:", meses_totales, index=idx_mes)
            meses_filtrados = [mes_seleccionado]
            titulo_metricas = f"Balance del Mes: {mes_seleccionado}"
            desc_metricas = "Análisis aislado de ingresos y egresos para el mes seleccionado."
        else: 
            meses_filtrados = meses_totales
            titulo_metricas = "Balance Histórico Acumulado"
            desc_metricas = "Suma global de todos los meses y proyectos registrados."
            
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
        st.caption(desc_metricas)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Ingresos Acumulados", formato_clp(ingresos_totales))
        c2.metric("Egresos Acumulados", formato_clp(egresos_totales))
        c3.metric("Rentabilidad Neta", formato_clp(rentabilidad))
        
    st.write("") 
    
    with st.container(border=True):
        st.markdown("#### 📈 Estado de Resultado Mensualizado")
        st.caption("Las barras muestran el balance de ingresos y salidas de capital.")
        
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
        
        st.altair_chart(grafico_balance, use_container_width=True)
