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
# 3. CONTROL DE ACCESOS POR SECCIÓN (Memoria)
# ==========================================
if 'acceso_finanzas' not in st.session_state:
    st.session_state.acceso_finanzas = "ninguno" # Puede ser: "ninguno", "admin", "observador"
    
if 'acceso_proyectos' not in st.session_state:
    st.session_state.acceso_proyectos = "ninguno" # Puede ser: "ninguno", "admin", "observador"

# ==========================================
# 4. CARGA INICIAL DE DATOS DESDE NUBE
# ==========================================
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

if 'proyectos_resumen' not in st.session_state:
    df_resumen_base = pd.DataFrame(columns=["Proyecto", "Empresa", "Cobro"])
    st.session_state.proyectos_resumen = cargar_datos("Proyectos_Resumen", df_resumen_base)

if 'proyectos_gastos' not in st.session_state:
    df_gastos_base = pd.DataFrame(columns=["Proyecto", "Detalle_Gasto", "Monto"])
    st.session_state.proyectos_gastos = cargar_datos("Proyectos_Gastos", df_gastos_base)

def formato_clp(valor):
    try:
        return f"${int(valor):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "$0"

# ==========================================
# 5. BARRA LATERAL FIJA
# ==========================================
st.sidebar.image(LOGO_URL, use_container_width=True)

if st.sidebar.button("Cerrar Todas las Sesiones"):
    st.session_state.acceso_finanzas = "ninguno"
    st.session_state.acceso_proyectos = "ninguno"
    st.rerun()

st.sidebar.divider()
menu = st.sidebar.radio("Navegación:", ["🏢 Finanzas", "📁 Proyectos", "📊 Balance Total"])


# ==========================================
# PANTALLA 1: FINANZAS
# ==========================================
if menu == "🏢 Finanzas":
    st.title("🏢 Área de Finanzas (Fijos)")
    
    # Si está bloqueado, mostrar pantalla de Login
    if st.session_state.acceso_finanzas == "ninguno":
        st.info("🔒 Esta sección es confidencial. Ingresa tus credenciales de Finanzas.")
        col1, col2 = st.columns([1, 2])
        with col1:
            u_fin = st.text_input("Usuario (Finanzas)")
            p_fin = st.text_input("Clave", type="password", key="p_fin")
            if st.button("Desbloquear Finanzas", type="primary"):
                if (u_fin == "master" and p_fin == "123") or (u_fin == "finanzas" and p_fin == "fin123"):
                    st.session_state.acceso_finanzas = "admin"
                    st.rerun()
                elif u_fin == "visita" and p_fin == "abc":
                    st.session_state.acceso_finanzas = "observador"
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")
    
    # Si está desbloqueado, mostrar contenido
    else:
        if st.session_state.acceso_finanzas == "observador":
            st.warning("👁️ MODO OBSERVADOR: Solo lectura activada.")
            
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("👥 Remuneraciones")
            if st.session_state.acceso_finanzas == "admin":
                res_sueldos = st.data_editor(st.session_state.sueldos, num_rows="dynamic", use_container_width=True, key="ed_sueldos")
                if st.button("💾 Guardar Cambios Sueldos"):
                    st.session_state.sueldos = res_sueldos
                    guardar_datos("Sueldos", res_sueldos)
                    st.success("Guardado en la nube.")
            else:
                st.dataframe(st.session_state.sueldos, use_container_width=True)
        
        with col2:
            st.subheader("🏢 Gastos Fijos")
            if st.session_state.acceso_finanzas == "admin":
                res_fijos = st.data_editor(st.session_state.gastos_fijos, num_rows="dynamic", use_container_width=True, key="ed_fijos")
                if st.button("💾 Guardar Cambios Fijos"):
                    st.session_state.gastos_fijos = res_fijos
                    guardar_datos("Gastos_Fijos", res_fijos)
                    st.success("Guardado en la nube.")
            else:
                st.dataframe(st.session_state.gastos_fijos, use_container_width=True)

# ==========================================
# PANTALLA 2: PROYECTOS
# ==========================================
elif menu == "📁 Proyectos":
    st.title("📁 Gestión de Proyectos")
    
    # Si está bloqueado, mostrar pantalla de Login
    if st.session_state.acceso_proyectos == "ninguno":
        st.info("🔒 Sección protegida. Ingresa tus credenciales de Proyectos.")
        col1, col2 = st.columns([1, 2])
        with col1:
            u_proy = st.text_input("Usuario (Proyectos)")
            p_proy = st.text_input("Clave", type="password", key="p_proy")
            if st.button("Desbloquear Proyectos", type="primary"):
                if (u_proy == "master" and p_proy == "123") or (u_proy == "proyectos" and p_proy == "obras123"):
                    st.session_state.acceso_proyectos = "admin"
                    st.rerun()
                elif u_proy == "visita" and p_proy == "abc":
                    st.session_state.acceso_proyectos = "observador"
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")
    
    # Si está desbloqueado, mostrar contenido
    else:
        if st.session_state.acceso_proyectos == "observador":
            st.warning("👁️ MODO OBSERVADOR: Solo lectura activada.")
            
        if st.session_state.acceso_proyectos == "admin":
            with st.expander("➕ Crear Nueva Carpeta de Proyecto", expanded=False):
                colA, colB = st.columns(2)
                nombre_p = colA.text_input("Nombre de la Obra o Proyecto")
                empresa_p = colB.text_input("Nombre de la Empresa / Cliente")
                
                if st.button("Crear Proyecto", type="primary"):
                    if nombre_p and nombre_p not in st.session_state.proyectos_resumen["Proyecto"].values:
                        nuevo_resumen = pd.DataFrame([{"Proyecto": nombre_p, "Empresa": empresa_p, "Cobro": 0}])
                        st.session_state.proyectos_resumen = pd.concat([st.session_state.proyectos_resumen, nuevo_resumen], ignore_index=True)
                        
                        nuevo_gasto = pd.DataFrame([{"Proyecto": nombre_p, "Detalle_Gasto": "Materiales iniciales", "Monto": 0}])
                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto], ignore_index=True)
                        
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.success(f"Carpeta '{nombre_p}' creada.")
                        st.rerun()
                    elif nombre_p:
                        st.warning("Ya existe un proyecto con ese nombre.")

        st.divider()

        proyectos_lista = st.session_state.proyectos_resumen["Proyecto"].tolist()
        if proyectos_lista:
            st.subheader("📂 Abrir Carpeta de Proyecto")
            proyecto_seleccionado = st.selectbox("Selecciona un proyecto:", proyectos_lista)
            
            idx_proy = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_seleccionado].index[0]
            empresa_actual = st.session_state.proyectos_resumen.at[idx_proy, "Empresa"]
            cobro_actual = st.session_state.proyectos_resumen.at[idx_proy, "Cobro"]
            
            df_gastos_proy = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seleccionado].copy()

            st.markdown(f"#### Empresa / Cliente: **{empresa_actual}**")
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.write("### 💰 Ingreso (Cobro)")
                if st.session_state.acceso_proyectos == "admin":
                    nuevo_cobro = st.number_input("Valor total cobrado (CLP):", min_value=0, value=int(cobro_actual), step=10000)
                else:
                    st.info(f"Cobro Total: {formato_clp(cobro_actual)}")
                    nuevo_cobro = cobro_actual

            with col2:
                st.write("### 💸 Gastos Desglosados")
                if st.session_state.acceso_proyectos == "admin":
                    df_edit = df_gastos_proy[["Detalle_Gasto", "Monto"]]
                    df_gastos_editados = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True, key=f"gast_{proyecto_seleccionado}")
                else:
                    st.dataframe(df_gastos_proy[["Detalle_Gasto", "Monto"]], use_container_width=True)
                    df_gastos_editados = df_gastos_proy[["Detalle_Gasto", "Monto"]]

            gastos_totales = pd.to_numeric(df_gastos_editados["Monto"], errors='coerce').sum()
            ganancia_proyecto = nuevo_cobro - gastos_totales
            
            st.write("---")
            c1, c2, c3 = st.columns(3)
            c1.metric("Cobro Acordado", formato_clp(nuevo_cobro))
            c2.metric("Gastos Totales", formato_clp(gastos_totales))
            c3.metric("Ganancia del Proyecto", formato_clp(ganancia_proyecto))

            if st.session_state.acceso_proyectos == "admin":
                st.write("---")
                col_save, col_del = st.columns(2)
                with col_save:
                    if st.button("💾 Guardar Cambios", type="primary", use_container_width=True):
                        st.session_state.proyectos_resumen.at[idx_proy, "Cobro"] = nuevo_cobro
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado]
                        df_gastos_editados["Proyecto"] = proyecto_seleccionado
                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, df_gastos_editados], ignore_index=True)
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.success("Guardado.")
                with col_del:
                    if st.button("🗑️ Eliminar Proyecto", use_container_width=True):
                        st.session_state.proyectos_resumen = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] != proyecto_seleccionado].reset_index(drop=True)
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado].reset_index(drop=True)
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.rerun()
        else:
            st.info("No hay proyectos activos.")

# ==========================================
# PANTALLA 3: BALANCE TOTAL
# ==========================================
elif menu == "📊 Balance Total":
    st.title("📊 Balance General de la Empresa")
    
    # Se requiere acceso de Finanzas para ver el balance total de la empresa
    if st.session_state.acceso_finanzas == "ninguno":
        st.warning("🔒 Esta sección consolida información confidencial.")
        st.info("Por favor, ve a la pestaña '🏢 Finanzas' e inicia sesión para desbloquear el Balance Total.")
    else:
        ingresos = pd.to_numeric(st.session_state.proyectos_resumen["Cobro"], errors='coerce').sum() if not st.session_state.proyectos_resumen.empty else 0
        costos_proy = pd.to_numeric(st.session_state.proyectos_gastos["Monto"], errors='coerce').sum() if not st.session_state.proyectos_gastos.empty else 0
        fijos = pd.to_numeric(st.session_state.sueldos["Monto (CLP)"], errors='coerce').sum() + pd.to_numeric(st.session_state.gastos_fijos["Monto (CLP)"], errors='coerce').sum()
        
        rentabilidad = ingresos - costos_proy - fijos
        
        c1, c2, c3 = st.columns(3)
        c1.metric("INGRESOS GLOBALES", formato_clp(ingresos))
        c2.metric("EGRESOS TOTALES", formato_clp(costos_proy + fijos))
        c3.metric("UTILIDAD NETA", formato_clp(rentabilidad))
        
        st.write("---")
        if rentabilidad > 0:
            st.success("✅ **La empresa es rentable.**")
        elif rentabilidad < 0:
            st.error(f"⚠️ **Alerta:** Los gastos superan a los ingresos por {formato_clp(abs(rentabilidad))}.")
        else:
            st.info("⚖️ **Punto de equilibrio.**")
