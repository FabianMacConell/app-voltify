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

# Datos Fijos
if 'sueldos' not in st.session_state:
    df_sueldos_base = pd.DataFrame([
        {"Trabajador / Cargo": "Técnico Principal", "Monto (CLP)": 800000},
        {"Trabajador / Cargo": "Ayudante (cada visita consta de 2 dias)", "Monto (CLP)": 500000}
    ])
    st.session_state.sueldos = cargar_datos("Sueldos", df_sueldos_base)

if 'gastos_fijos' not in st.session_state:
    df_fijos_base = pd.DataFrame([
        {"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000},
        {"Descripción": "prioridad emergencias", "Monto (CLP)": 50000}
    ])
    st.session_state.gastos_fijos = cargar_datos("Gastos_Fijos", df_fijos_base)

# Nueva estructura de Proyectos
if 'proyectos_resumen' not in st.session_state:
    df_resumen_base = pd.DataFrame(columns=["Proyecto", "Empresa", "Cobro"])
    st.session_state.proyectos_resumen = cargar_datos("Proyectos_Resumen", df_resumen_base)

if 'proyectos_gastos' not in st.session_state:
    df_gastos_base = pd.DataFrame(columns=["Proyecto", "Detalle_Gasto", "Monto"])
    st.session_state.proyectos_gastos = cargar_datos("Proyectos_Gastos", df_gastos_base)

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
        return f"${int(valor):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "$0"

# --- PANTALLA FINANZAS ---
if menu == "🏢 Finanzas":
    st.header("Área de Finanzas (Fijos)")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("👥 Remuneraciones")
        if es_admin:
            res_sueldos = st.data_editor(st.session_state.sueldos, num_rows="dynamic", use_container_width=True, key="ed_sueldos")
            if st.button("💾 Guardar Cambios Sueldos"):
                st.session_state.sueldos = res_sueldos
                guardar_datos("Sueldos", res_sueldos)
                st.success("Guardado en la nube.")
        else:
            st.dataframe(st.session_state.sueldos, use_container_width=True)
    
    with col2:
        st.subheader("🏢 Gastos Fijos")
        if es_admin:
            res_fijos = st.data_editor(st.session_state.gastos_fijos, num_rows="dynamic", use_container_width=True, key="ed_fijos")
            if st.button("💾 Guardar Cambios Fijos"):
                st.session_state.gastos_fijos = res_fijos
                guardar_datos("Gastos_Fijos", res_fijos)
                st.success("Guardado en la nube.")
        else:
            st.dataframe(st.session_state.gastos_fijos, use_container_width=True)

# --- PANTALLA PROYECTOS ---
elif menu == "📁 Proyectos":
    st.header("Gestión de Proyectos (Carpetas)")
    
    # 1. Creación de Proyecto Nuevo
    if es_admin:
        with st.expander("➕ Crear Nueva Carpeta de Proyecto", expanded=False):
            colA, colB = st.columns(2)
            nombre_p = colA.text_input("Nombre de la Obra o Proyecto")
            empresa_p = colB.text_input("Nombre de la Empresa / Cliente")
            
            if st.button("Crear Proyecto", type="primary"):
                if nombre_p and nombre_p not in st.session_state.proyectos_resumen["Proyecto"].values:
                    # Guardar en Resumen
                    nuevo_resumen = pd.DataFrame([{"Proyecto": nombre_p, "Empresa": empresa_p, "Cobro": 0}])
                    st.session_state.proyectos_resumen = pd.concat([st.session_state.proyectos_resumen, nuevo_resumen], ignore_index=True)
                    
                    # Crear gasto inicial en 0
                    nuevo_gasto = pd.DataFrame([{"Proyecto": nombre_p, "Detalle_Gasto": "Materiales iniciales", "Monto": 0}])
                    st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto], ignore_index=True)
                    
                    guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                    guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                    st.success(f"Carpeta '{nombre_p}' creada exitosamente.")
                    st.rerun()
                elif nombre_p:
                    st.warning("Ya existe un proyecto con ese nombre.")

    st.divider()

    # 2. Edición y Vista de la Carpeta del Proyecto
    proyectos_lista = st.session_state.proyectos_resumen["Proyecto"].tolist()
    
    if proyectos_lista:
        st.subheader("📂 Abrir Carpeta de Proyecto")
        proyecto_seleccionado = st.selectbox("Selecciona un proyecto para ver sus detalles:", proyectos_lista)
        
        # Obtener los datos actuales del proyecto seleccionado
        idx_proy = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_seleccionado].index[0]
        empresa_actual = st.session_state.proyectos_resumen.at[idx_proy, "Empresa"]
        cobro_actual = st.session_state.proyectos_resumen.at[idx_proy, "Cobro"]
        
        # Filtrar solo los gastos de este proyecto
        df_gastos_proy = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seleccionado].copy()

        st.markdown(f"#### Empresa / Cliente: **{empresa_actual}**")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.write("### 💰 Ingreso (Cobro)")
            if es_admin:
                nuevo_cobro = st.number_input("Valor total cobrado al cliente (CLP):", min_value=0, value=int(cobro_actual), step=10000)
            else:
                st.info(f"Cobro Total: {formato_clp(cobro_actual)}")
                nuevo_cobro = cobro_actual

        with col2:
            st.write("### 💸 Gastos Desglosados")
            if es_admin:
                # Mostrar solo las columnas de Detalle y Monto para que sea más limpio
                df_edit = df_gastos_proy[["Detalle_Gasto", "Monto"]]
                df_gastos_editados = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True, key=f"gast_{proyecto_seleccionado}")
            else:
                st.dataframe(df_gastos_proy[["Detalle_Gasto", "Monto"]], use_container_width=True)
                df_gastos_editados = df_gastos_proy[["Detalle_Gasto", "Monto"]]

        # Cálculos de rentabilidad de la carpeta
        gastos_totales = pd.to_numeric(df_gastos_editados["Monto"], errors='coerce').sum()
        ganancia_proyecto = nuevo_cobro - gastos_totales
        
        st.write("---")
        st.write("### 📈 Resumen del Proyecto")
        c1, c2, c3 = st.columns(3)
        c1.metric("Cobro Acordado", formato_clp(nuevo_cobro))
        c2.metric("Gastos Totales", formato_clp(gastos_totales))
        c3.metric("Ganancia del Proyecto", formato_clp(ganancia_proyecto))

        if es_admin:
            if st.button("💾 Guardar Cambios de este Proyecto", type="primary"):
                # 1. Actualizar el Cobro en el Resumen
                st.session_state.proyectos_resumen.at[idx_proy, "Cobro"] = nuevo_cobro
                
                # 2. Actualizar la tabla de Gastos
                # Borrar los gastos antiguos de ESTE proyecto
                st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado]
                # Agregar la columna del nombre del proyecto a los nuevos datos editados
                df_gastos_editados["Proyecto"] = proyecto_seleccionado
                # Unir a la base de datos principal
                st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, df_gastos_editados], ignore_index=True)
                
                # Guardar todo en la nube
                guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                st.success("¡Carpeta actualizada y guardada en la base de datos!")
    else:
        st.info("No hay proyectos activos. Despliega el menú de arriba para crear tu primer proyecto.")

# --- PANTALLA BALANCE ---
elif menu == "📊 Balance Total":
    st.header("Balance General")
    
    # Sumar todo asegurando que sean números
    ingresos = pd.to_numeric(st.session_state.proyectos_resumen["Cobro"], errors='coerce').sum() if not st.session_state.proyectos_resumen.empty else 0
    costos_proy = pd.to_numeric(st.session_state.proyectos_gastos["Monto"], errors='coerce').sum() if not st.session_state.proyectos_gastos.empty else 0
    fijos = pd.to_numeric(st.session_state.sueldos["Monto (CLP)"], errors='coerce').sum() + pd.to_numeric(st.session_state.gastos_fijos["Monto (CLP)"], errors='coerce').sum()
    
    rentabilidad = ingresos - costos_proy - fijos
    
    c1, c2, c3 = st.columns(3)
    c1.metric("INGRESOS (Todos los proyectos)", formato_clp(ingresos))
    c2.metric("EGRESOS TOTALES (Materiales + Fijos)", formato_clp(costos_proy + fijos))
    c3.metric("UTILIDAD NETA EMPRESA", formato_clp(rentabilidad))
    
    st.write("---")
    if rentabilidad > 0:
        st.success("✅ **La empresa es rentable.** Estás cubriendo tus costos fijos y materiales con los cobros actuales.")
    elif rentabilidad < 0:
        st.error(f"⚠️ **Alerta:** Los gastos superan a los ingresos por {formato_clp(abs(rentabilidad))}.")
    else:
        st.info("⚖️ **Punto de equilibrio.** No hay ganancias ni pérdidas.")
