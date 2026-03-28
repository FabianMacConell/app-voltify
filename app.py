import streamlit as st
import pandas as pd

# Configuración inicial de la página
st.set_page_config(page_title="Gestor Financiero Empresa", layout="wide")

# Función para dar formato de moneda chilena
def formato_clp(valor):
    try:
        return f"${int(valor):,.0f}".replace(",", ".")
    except ValueError:
        return "$0"

# ==========================================
# MEMORIA DE LA APLICACIÓN (Datos fijos y editables)
# ==========================================
# 1. Sueldos
if 'sueldos' not in st.session_state:
    st.session_state.sueldos = pd.DataFrame([
        {"Trabajador / Cargo": "Sueldo Técnico Principal", "Monto (CLP)": 800000},
        {"Trabajador / Cargo": "Sueldo Ayudante", "Monto (CLP)": 500000},
        {"Trabajador / Cargo": "Administración", "Monto (CLP)": 400000}
    ])

# 2. Otros Gastos Fijos (que considero importantes)
if 'gastos_fijos' not in st.session_state:
    st.session_state.gastos_fijos = pd.DataFrame([
        {"Descripción": "Arriendo Oficina / Bodega", "Monto (CLP)": 350000},
        {"Descripción": "Pago Contador", "Monto (CLP)": 60000},
        {"Descripción": "Plan de Celular e Internet", "Monto (CLP)": 40000},
        {"Descripción": "Seguros (Vehículos / Vida)", "Monto (CLP)": 35000}
    ])

# 3. Proyectos
if 'proyectos' not in st.session_state:
    st.session_state.proyectos = {}

# ==========================================
# BARRA LATERAL (Menú)
# ==========================================
st.sidebar.title("⚙️ Panel de Control")
menu = st.sidebar.radio("Navegación:", [
    "🏢 1. Área de Finanzas (Fijos)", 
    "📁 2. Área de Proyectos", 
    "📊 3. Flujo Total Empresa"
])

# ==========================================
# SECCIÓN 1: ÁREA DE FINANZAS
# ==========================================
if menu == "🏢 1. Área de Finanzas (Fijos)":
    st.title("🏢 Área de Finanzas y Personal")
    st.write("Aquí registramos los costos que la empresa debe pagar mensualmente de manera obligatoria, sin importar si hay o no hay trabajos activos.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("👥 Remuneraciones (Personal)")
        # Tabla editable de sueldos
        st.session_state.sueldos = st.data_editor(st.session_state.sueldos, num_rows="dynamic", key="tabla_sueldos", use_container_width=True)
        total_sueldos = st.session_state.sueldos["Monto (CLP)"].sum()
        st.info(f"**Total Sueldos: {formato_clp(total_sueldos)}**")

    with col2:
        st.subheader("🏢 Otros Gastos Fijos")
        # Tabla editable de otros gastos fijos
        st.session_state.gastos_fijos = st.data_editor(st.session_state.gastos_fijos, num_rows="dynamic", key="tabla_fijos", use_container_width=True)
        total_otros_fijos = st.session_state.gastos_fijos["Monto (CLP)"].sum()
        st.info(f"**Total Otros Fijos: {formato_clp(total_otros_fijos)}**")

# ==========================================
# SECCIÓN 2: ÁREA DE PROYECTOS
# ==========================================
elif menu == "📁 2. Área de Proyectos":
    st.title("📁 Gestión de Proyectos")
    
    # Crear proyecto nuevo
    st.markdown("### ➕ Ingresar Nuevo Trabajo")
    colA, colB = st.columns([3, 1])
    nuevo_proyecto = colA.text_input("Nombre del Proyecto o Trabajo")
    if colB.button("Crear Carpeta"):
        if nuevo_proyecto and nuevo_proyecto not in st.session_state.proyectos:
            st.session_state.proyectos[nuevo_proyecto] = {
                "cobro": 0.0,
                "gastos": pd.DataFrame([{"Material / Gasto": "Ej: Cables, canalización, viáticos", "Costo (CLP)": 0}])
            }
            st.success(f"Trabajo '{nuevo_proyecto}' creado.")
            st.rerun()
            
    st.divider()

    # Editar proyectos existentes
    if st.session_state.proyectos:
        st.markdown("### 🛠️ Detalles del Trabajo")
        proyecto_actual = st.selectbox("Selecciona un proyecto para evaluarlo:", list(st.session_state.proyectos.keys()))
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("💰 Ingreso (Lo que se cobra)")
            # Campo para actualizar el cobro total al cliente
            cobro_actual = st.session_state.proyectos[proyecto_actual]["cobro"]
            nuevo_cobro = st.number_input("Monto total cobrado al cliente por este trabajo (CLP):", min_value=0.0, value=float(cobro_actual), step=10000.0)
            st.session_state.proyectos[proyecto_actual]["cobro"] = nuevo_cobro
            
        with col2:
            st.subheader("💸 Gastos Específicos del Trabajo")
            # Tabla editable para los gastos directos del proyecto
            df_gastos = st.data_editor(st.session_state.proyectos[proyecto_actual]["gastos"], num_rows="dynamic", key=f"gastos_{proyecto_actual}", use_container_width=True)
            st.session_state.proyectos[proyecto_actual]["gastos"] = df_gastos
            total_gastos_proyecto = df_gastos["Costo (CLP)"].sum()
            st.write(f"**Total Gastos del Proyecto: {formato_clp(total_gastos_proyecto)}**")
            
        # Rentabilidad individual del proyecto
        utilidad_proyecto = nuevo_cobro - total_gastos_proyecto
        st.success(f"**Margen de este trabajo:** {formato_clp(utilidad_proyecto)}")
    else:
        st.info("Crea tu primer proyecto arriba para comenzar a evaluar.")

# ==========================================
# SECCIÓN 3: FLUJO TOTAL EMPRESA
# ==========================================
elif menu == "📊 3. Flujo Total Empresa":
    st.title("📊 Flujo Total y Rentabilidad")
    st.write("Esta sección cruza las entradas (Proyectos) y salidas (Gastos de Proyectos + Finanzas Fijas) para mostrar la salud real de tu empresa.")
    
    # Cálculos
    total_ingresos_proyectos = sum([datos["cobro"] for datos in st.session_state.proyectos.values()])
    total_gastos_proyectos = sum([datos["gastos"]["Costo (CLP)"].sum() for datos in st.session_state.proyectos.values()])
    total_sueldos_empresa = st.session_state.sueldos["Monto (CLP)"].sum()
    total_otros_fijos = st.session_state.gastos_fijos["Monto (CLP)"].sum()
    
    # Resumen general
    total_entradas = total_ingresos_proyectos
    total_salidas = total_gastos_proyectos + total_sueldos_empresa + total_otros_fijos
    rentabilidad = total_entradas - total_salidas
    
    # Tarjetas métricas
    col1, col2, col3 = st.columns(3)
    col1.metric("ENTRADAS (Cobros Totales)", formato_clp(total_entradas))
    col2.metric("SALIDAS (Todos los Gastos)", formato_clp(total_salidas))
    col3.metric("RENTABILIDAD NETA", formato_clp(rentabilidad))
    
    st.divider()
    
    # Desglose detallado
    st.markdown("### 🔍 Desglose del Flujo de Caja")
    st.write(f"🟢 **+ {formato_clp(total_ingresos_proyectos)}** (Ingresos por cobros de trabajos realizados)")
    st.write(f"🔴 **- {formato_clp(total_gastos_proyectos)}** (Costos directos de materiales/insumos de esos trabajos)")
    st.write(f"🔴 **- {formato_clp(total_sueldos_empresa)}** (Pago total de sueldos al personal)")
    st.write(f"🔴 **- {formato_clp(total_otros_fijos)}** (Pago de arriendos, contador y fijos)")
    
    st.divider()
    
    # Mensaje de evaluación automática
    if rentabilidad > 0:
        st.success("✅ **¡Excelente!** La empresa es rentable. Los trabajos están cubriendo sus propios materiales y además soportan toda la carga fija de la empresa (sueldos y oficinas).")
    elif rentabilidad < 0:
        st.error(f"⚠️ **Atención:** La empresa está en pérdida. Te faltan {formato_clp(abs(rentabilidad))} en ingresos de proyectos para cubrir tus costos fijos mensuales.")
    else:
        st.info("⚖️ **Punto de equilibrio:** No ganas ni pierdes, cubres exactamente tus costos.")
