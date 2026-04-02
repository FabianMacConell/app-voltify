import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD VISUAL
# ==========================================
st.set_page_config(page_title="Panel Financiero", page_icon="⚡", layout="wide")

ocultar_menu_estilo = """
            <style>
            [data-testid="stHeaderActionElements"] {visibility: hidden;}
            footer {visibility: hidden;}
            </style>
            """
st.markdown(ocultar_menu_estilo, unsafe_allow_html=True)

LOGO_URL = "logo.png"

# ==========================================
# 2. CONEXIÓN A GOOGLE SHEETS
# ==========================================
def conectar_google_sheets():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["google_credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("Base de Datos Voltify")

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
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df.columns.tolist())
        hoja.clear()
        hoja.update([df.columns.values.tolist()] + df.values.tolist())
    except Exception as e:
        st.error(f"Error al guardar: {e}")

def cargar_datos(nombre_hoja, df_default):
    try:
        libro = conectar_google_sheets()
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df_default.columns.tolist())
        datos = hoja.get_all_records()
        if not datos:
            return df_default
        return pd.DataFrame(datos)
    except Exception:
        return df_default

# ==========================================
# 3. SISTEMA DE LOGIN
# ==========================================
USUARIOS = {
    "admin": {"clave": "123", "rol": "Administrador"},
    "visita": {"clave": "abc", "rol": "Observador"}
}

if 'logeado' not in st.session_state:
    st.session_state.logeado = False
    st.session_state.usuario_actual = ""
    st.session_state.rol_actual = ""

if not st.session_state.logeado:
    st.image(LOGO_URL, width=350)
    st.title("🔒 Portal de Acceso")
    usuario_input = st.text_input("Usuario")
    clave_input = st.text_input("Contraseña", type="password")
    if st.button("Iniciar Sesión", type="primary"):
        if usuario_input in USUARIOS and USUARIOS[usuario_input]["clave"] == clave_input:
            st.session_state.logeado = True
            st.session_state.usuario_actual = usuario_input
            st.session_state.rol_actual = USUARIOS[usuario_input]["rol"]
            st.rerun()
        else:
            st.error("❌ Credenciales incorrectas.")
    st.stop()

# ==========================================
# 4. CARGA INICIAL DE DATOS DESDE NUBE
# ==========================================
es_admin = (st.session_state.rol_actual == "Administrador")

if 'sueldos' not in st.session_state:
    df_sueldos_base = pd.DataFrame([
        {"Trabajador / Cargo": "Técnico Principal", "Monto (CLP)": 800000},
        {"Trabajador / Cargo": "Ayudante (cada visita consta de 2 dias)", "Monto (CLP)": 500000}
    ])
    st.session_state.sueldos = cargar_datos("Sueldos", df_sueldos_base)

if 'gastos_fijos' not in st.session_state:
    df_fijos_base = pd.DataFrame([
        {"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000},
        {"Descripción": "Prioridad Emergencias", "Monto (CLP)": 50000}
    ])
    st.session_state.gastos_fijos = cargar_datos("Gastos_Fijos", df_fijos_base)

if 'proyectos_db' not in st.session_state:
    df_proy_base = pd.DataFrame(columns=["Nombre", "Cobro_Total", "Gastos_Totales"])
    st.session_state.proyectos_db = cargar_datos("Proyectos", df_proy_base)

# ==========================================
# 5. INTERFAZ Y NAVEGACIÓN
# ==========================================
st.sidebar.image(LOGO_URL, use_container_width=True)
st.sidebar.info(f"👤 **{st.session_state.usuario_actual}** | {st.session_state.rol_actual}")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state.logeado = False
    st.rerun()

menu = st.sidebar.radio("Navegación:", ["🏢 Finanzas", "📁 Proyectos", "📊 Balance Total"])

def formato_clp(valor):
    try:
        return f"${int(valor):,.0f}".replace
