import streamlit as st
import pandas as pd

# 1. NOMBRE Y LOGO EN LA PESTAÑA DEL NAVEGADOR
st.set_page_config(page_title="Voltify - Finanzas", page_icon="⚡", layout="wide")

def formato_clp(valor):
    try:
        return f"${int(valor):,.0f}".replace(",", ".")
    except ValueError:
        return "$0"

# ==========================================
# SISTEMA DE LOGIN Y SEGURIDAD
# ==========================================
USUARIOS = {
    "admin": {"clave": "123", "rol": "Administrador"},
    "visita": {"clave": "abc", "rol": "Observador"}
}

if 'logeado' not in st.session_state:
    st.session_state.logeado = False
    st.session_state.usuario_actual = ""
    st.session_state.rol_actual = ""

# --- PANTALLA DE LOGIN ---
if not st.session_state.logeado:
    # Agregamos el logo en la pantalla de inicio
    st.image("https://via.placeholder.com/400x120/005cba/FFFFFF?text=VOLTIFY", width=300)
    st.title("🔒 Acceso al Sistema Financiero")
    st.write("Por favor, ingresa tus credenciales para continuar.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        usuario_input = st.text_input("Usuario")
        clave_input = st.text_input("Contraseña", type="password")
        
        if st.button("Iniciar Sesión"):
            if usuario_input in USUARIOS and USUARIOS[usuario_input]["clave"] == clave_input:
                st.session_state.logeado = True
                st.session_state.usuario_actual = usuario_input
                st.session_state.rol_actual = USUARIOS[usuario_input]["rol"]
                st.rerun() 
            else:
                st.error("❌ Usuario o contraseña incorrectos.")
    st.stop()

# ==========================================
# VARIABLES DE MEMORIA 
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
# BARRA LATERAL (Menú y Perfil)
# ==========================================
# 2. LOGO EN EL MENÚ LATERAL
st.sidebar.image("https://via.placeholder.com/400x120/005cba/FFFFFF?text=VOLTIFY", use_container_width=True)

st.sidebar.info(f"👤 **Usuario:** {st.session_state.usuario_actual}\n\n🔑 **Rol:** {st.session_state.rol_actual}")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state.logeado = False
    st.rerun()

st.sidebar.divider()
menu = st.sidebar.radio("Navegación:", [
    "🏢 1. Área de Finanzas (Fijos)", 
    "📁 2. Área de Proyectos", 
    "📊 3. Flujo Total Empresa"
])

if not es_admin:
    st.sidebar.warning("Modo Observador: Solo lectura. No puedes modificar los datos.")

# ==========================================
# SECCIÓN 1: ÁREA DE FINANZAS
# ==========================================
if menu == "🏢 1. Área de Finanzas (Fijos)":
    st.title("🏢 Área de Finanzas y Personal")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("👥 Remuneraciones")
        if es_admin:
            st.session_state.sueldos = st.data_editor(st.session_state.sueldos, num_rows="dynamic", use_container_width=True)
        else:
            st.dataframe(st.session_state.sueldos, use_container_width=True) 
            
        total_sueldos = st.session_state.sueldos["Monto (CLP)"].sum()
        st.info(f"**Total Sueldos: {formato_clp(total_sueldos)}**")

    with col2:
        st.subheader("🏢 Otros Gastos Fijos")
        if es_admin:
            st.session_state.gastos_fijos = st.data_editor(st.session_state.gastos_fijos, num_rows="dynamic", use_container_width=True)
        else:
            st.dataframe(st.session_state.gastos_fijos, use_container_width=True) 
            
        total_otros_fijos = st.session_state.gastos_fijos["Monto (CLP)"].sum()
        st.info(f"**Total Otros Fijos: {formato_clp(total_otros_fijos)}**")

# ==========================================
# SECCIÓN 2: ÁREA DE PROYECTOS
# ==========================================
elif menu == "📁 2. Área de Proyectos":
    st.title("📁 Gestión de Proyectos")
    
    if es_admin:
        st.markdown("### ➕ Ingresar Nuevo Trabajo")
        colA, colB = st.columns([3, 1])
        nuevo_proyecto = colA.text_input("Nombre del Proyecto o Trabajo")
        if colB.button("Crear Carpeta"):
            if nuevo_proyecto and nuevo_proyecto not in st.session_state.proyectos:
                st.session_state.proyectos[nuevo_proyecto] = {
                    "cobro": 0.0,
                    "gastos": pd.DataFrame([{"Material / Gasto": "Cables, viáticos, etc", "Costo (CLP)": 0}])
                }
                st.success(f"Trabajo '{nuevo_proyecto}' creado.")
                st.rerun()
        st.divider()

    if st.session_state.proyectos:
        st.markdown("### 🛠️ Detalles del Trabajo")
        proyecto_actual = st.selectbox("Selecciona un proyecto:", list(st.session_state.proyectos.keys()))
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("💰 Ingreso (Cobro)")
            cobro_actual = st.session_state.proyectos[proyecto_actual]["cobro"]
            if es_admin:
                nuevo_cobro = st.number_input("Monto cobrado (CLP):", min_value=0.0, value=float(cobro_actual), step=10000.0)
                st.session_state.proyectos[proyecto_actual]["cobro"] = nuevo_cobro
            else:
                st.write(f"**Monto cobrado:** {formato_clp(cobro_actual)}")
                nuevo_cobro = cobro_actual
            
        with col2:
            st.subheader("💸 Gastos del Trabajo")
            if es_admin:
                df_gastos = st.data_editor(st.session_state.proyectos[proyecto_actual]["gastos"], num_rows="dynamic", use_container_width=True)
                st.session_state.proyectos[proyecto_actual]["gastos"] = df_gastos
            else:
                df_gastos = st.session_state.proyectos[proyecto_actual]["gastos"]
                st.dataframe(df_gastos, use_container_width=True)
                
            total_gastos_proyecto = df_gastos["Costo (CLP)"].sum()
            st.write(f"**Total Gastos: {formato_clp(total_gastos_proyecto)}**")
            
        utilidad_proyecto = nuevo_cobro - total_gastos_proyecto
        st.success(f"**Margen del trabajo:** {formato_clp(utilidad_proyecto)}")
    else:
        st.info("No hay proyectos activos aún.")

# ==========================================
# SECCIÓN 3: FLUJO TOTAL EMPRESA
# ==========================================
elif menu == "📊 3. Flujo Total Empresa":
    st.title("📊 Flujo Total y Rentabilidad")
    
    total_ingresos_proyectos = sum([datos["cobro"] for datos in st.session_state.proyectos.values()]) if st.session_state.proyectos else 0
    total_gastos_proyectos = sum([datos["gastos"]["Costo (CLP)"].sum() for datos in st.session_state.proyectos.values()]) if st.session_state.proyectos else 0
    total_sueldos_empresa = st.session_state.sueldos["Monto (CLP)"].sum()
    total_otros_fijos = st.session_state.gastos_fijos["Monto (CLP)"].sum()
    
    total_entradas = total_ingresos_proyectos
    total_salidas = total_gastos_proyectos + total_sueldos_empresa + total_otros_fijos
    rentabilidad = total_entradas - total_salidas
    
    col1, col2, col3 = st.columns(3)
    col1.metric("ENTRADAS (Cobros Totales)", formato_clp(total_entradas))
    col2.metric("SALIDAS (Todos los Gastos)", formato_clp(total_salidas))
    col3.metric("RENTABILIDAD NETA", formato_clp(rentabilidad))
    
    st.divider()
    st.markdown("### 🔍 Desglose del Flujo de Caja")
    st.write(f"🟢 **+ {formato_clp(total_ingresos_proyectos)}** (Ingresos por proyectos)")
    st.write(f"🔴 **- {formato_clp(total_gastos_proyectos)}** (Costos de materiales de proyectos)")
    st.write(f"🔴 **- {formato_clp(total_sueldos_empresa)}** (Sueldos del personal)")
    st.write(f"🔴 **- {formato_clp(total_otros_fijos)}** (Gastos fijos y oficina)")
