import streamlit as st
import pandas as pd

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD VISUAL
# ==========================================
st.set_page_config(page_title="Panel Financiero", page_icon="⚡", layout="wide")

# Reemplaza este enlace por "logo.png" cuando subas tu propia imagen a GitHub
LOGO_URL = "logo.png"

# Función para mostrar la cabecera (Logo + Título de la sección)
def cabecera_corporativa(titulo_seccion):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image(LOGO_URL, use_container_width=True)
    with col2:
        st.title(titulo_seccion)
    st.divider()

def formato_clp(valor):
    try:
        return f"${int(valor):,.0f}".replace(",", ".")
    except ValueError:
        return "$0"

# ==========================================
# 2. SISTEMA DE LOGIN
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
    st.write("Bienvenido al sistema financiero. Ingresa tus credenciales para continuar.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
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
# 3. BASE DE DATOS (Memoria)
# ==========================================
es_admin = (st.session_state.rol_actual == "Administrador")

if 'sueldos' not in st.session_state:
    st.session_state.sueldos = pd.DataFrame([
        {"Trabajador / Cargo": "Sueldo Técnico Principal", "Monto (CLP)": 800000},
        {"Trabajador / Cargo": "Sueldo Ayudante", "Monto (CLP)": 500000},
        {"Trabajador / Cargo": "Administración", "Monto (CLP)": 400000}
    ])

if 'gastos_fijos' not in st.session_state:
    st.session_state.gastos_fijos = pd.DataFrame([
        {"Descripción": "Arriendo Oficina / Bodega", "Monto (CLP)": 350000},
        {"Descripción": "Pago Contador", "Monto (CLP)": 60000},
        {"Descripción": "Plan de Celular e Internet", "Monto (CLP)": 40000}
    ])

if 'proyectos' not in st.session_state:
    st.session_state.proyectos = {}

# ==========================================
# 4. BARRA LATERAL (Navegación)
# ==========================================
st.sidebar.image(LOGO_URL, use_container_width=True)
st.sidebar.info(f"👤 **{st.session_state.usuario_actual}**\n\n🔑 Nivel: {st.session_state.rol_actual}")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state.logeado = False
    st.rerun()

st.sidebar.divider()
menu = st.sidebar.radio("Navegación Principal:", [
    "🏢 1. Finanzas y Personal", 
    "📁 2. Gestión de Proyectos", 
    "📊 3. Flujo y Rentabilidad"
])

if not es_admin:
    st.sidebar.warning("Modo Observador activo (Solo lectura).")

# ==========================================
# 5. PANTALLAS DE LA APLICACIÓN
# ==========================================

# --- PANTALLA 1: FINANZAS ---
if menu == "🏢 1. Finanzas y Personal":
    cabecera_corporativa("Área de Finanzas (Fijos)")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("👥 Remuneraciones")
        if es_admin:
            st.session_state.sueldos = st.data_editor(st.session_state.sueldos, num_rows="dynamic", use_container_width=True)
        else:
            st.dataframe(st.session_state.sueldos, use_container_width=True) 
        st.info(f"**Total Sueldos: {formato_clp(st.session_state.sueldos['Monto (CLP)'].sum())}**")

    with col2:
        st.subheader("🏢 Otros Gastos Fijos")
        if es_admin:
            st.session_state.gastos_fijos = st.data_editor(st.session_state.gastos_fijos, num_rows="dynamic", use_container_width=True)
        else:
            st.dataframe(st.session_state.gastos_fijos, use_container_width=True) 
        st.info(f"**Total Otros Fijos: {formato_clp(st.session_state.gastos_fijos['Monto (CLP)'].sum())}**")

# --- PANTALLA 2: PROYECTOS ---
elif menu == "📁 2. Gestión de Proyectos":
    cabecera_corporativa("Área de Proyectos")
    
    if es_admin:
        st.markdown("### ➕ Registrar Nuevo Trabajo")
        colA, colB = st.columns([3, 1])
        nuevo_proyecto = colA.text_input("Nombre del Trabajo")
        if colB.button("Crear Carpeta", type="primary"):
            if nuevo_proyecto and nuevo_proyecto not in st.session_state.proyectos:
                st.session_state.proyectos[nuevo_proyecto] = {
                    "cobro": 0.0,
                    "gastos": pd.DataFrame([{"Material / Gasto": "Ej: Cables, Viáticos", "Costo (CLP)": 0}])
                }
                st.success(f"Trabajo '{nuevo_proyecto}' creado.")
                st.rerun()
        st.divider()

    if st.session_state.proyectos:
        st.markdown("### 🛠️ Detalles del Trabajo")
        proyecto_actual = st.selectbox("Seleccionar Proyecto:", list(st.session_state.proyectos.keys()))
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("💰 Cobro al Cliente")
            cobro_actual = st.session_state.proyectos[proyecto_actual]["cobro"]
            if es_admin:
                nuevo_cobro = st.number_input("Monto total (CLP):", min_value=0.0, value=float(cobro_actual), step=10000.0)
                st.session_state.proyectos[proyecto_actual]["cobro"] = nuevo_cobro
            else:
                st.write(f"**Monto cobrado:** {formato_clp(cobro_actual)}")
                nuevo_cobro = cobro_actual
            
        with col2:
            st.subheader("💸 Gastos Internos")
            if es_admin:
                df_gastos = st.data_editor(st.session_state.proyectos[proyecto_actual]["gastos"], num_rows="dynamic", use_container_width=True)
                st.session_state.proyectos[proyecto_actual]["gastos"] = df_gastos
            else:
                df_gastos = st.session_state.proyectos[proyecto_actual]["gastos"]
                st.dataframe(df_gastos, use_container_width=True)
                
            total_gastos = df_gastos["Costo (CLP)"].sum()
            st.write(f"**Suma de Gastos: {formato_clp(total_gastos)}**")
            
        st.success(f"**Margen del proyecto:** {formato_clp(nuevo_cobro - total_gastos)}")
    else:
        st.info("Sin proyectos activos.")

# --- PANTALLA 3: FLUJO TOTAL ---
elif menu == "📊 3. Flujo y Rentabilidad":
    cabecera_corporativa("Balance General Empresa")
    
    ingresos_proy = sum([d["cobro"] for d in st.session_state.proyectos.values()]) if st.session_state.proyectos else 0
    gastos_proy = sum([d["gastos"]["Costo (CLP)"].sum() for d in st.session_state.proyectos.values()]) if st.session_state.proyectos else 0
    total_fijos = st.session_state.sueldos["Monto (CLP)"].sum() + st.session_state.gastos_fijos["Monto (CLP)"].sum()
    
    total_entradas = ingresos_proy
    total_salidas = gastos_proy + total_fijos
    rentabilidad = total_entradas - total_salidas
    
    col1, col2, col3 = st.columns(3)
    col1.metric("ENTRADAS GLOBALES", formato_clp(total_entradas))
    col2.metric("SALIDAS GLOBALES", formato_clp(total_salidas))
    col3.metric("RENTABILIDAD NETA", formato_clp(rentabilidad))
    
    st.divider()
    st.markdown("### 🔍 Desglose")
    st.write(f"🟢 **+ {formato_clp(ingresos_proy)}** (Cobros de proyectos)")
    st.write(f"🔴 **- {formato_clp(gastos_proy)}** (Materiales de proyectos)")
    st.write(f"🔴 **- {formato_clp(total_fijos)}** (Sueldos y gastos de oficina)")
