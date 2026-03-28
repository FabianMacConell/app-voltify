import streamlit as st
import pandas as pd

# Configuración de la página
st.set_page_config(page_title="Gestor Financiero Eléctrico", layout="wide")

def formato_clp(valor):
    return f"${int(valor):,.0f}".replace(",", ".")

# --- INICIALIZACIÓN DE MEMORIA (Para guardar proyectos y gastos) ---
if 'gastos_generales' not in st.session_state:
    st.session_state.gastos_generales = pd.DataFrame([
        {"Descripción": "Sueldo Técnico 1", "Monto (CLP)": 800000},
        {"Descripción": "Sueldo Ayudante", "Monto (CLP)": 500000},
        {"Descripción": "Arriendo de Oficina/Bodega", "Monto (CLP)": 350000},
        {"Descripción": "Contador y Software", "Monto (CLP)": 60000}
    ])

if 'proyectos' not in st.session_state:
    st.session_state.proyectos = {}  # Diccionario para guardar cada proyecto separado

# --- BARRA LATERAL (Navegación) ---
st.sidebar.title("⚡ Panel de Control")
menu = st.sidebar.radio("Ir a:", ["🏢 1. Finanzas Generales (Fijos)", "📁 2. Gestión de Proyectos", "📊 3. Flujo Total Empresa"])

# ==========================================
# SECCIÓN 1: FINANZAS GENERALES
# ==========================================
if menu == "🏢 1. Finanzas Generales (Fijos)":
    st.title("🏢 Finanzas Generales de la Empresa")
    st.write("Registra aquí los costos fijos mensuales que NO dependen de un proyecto específico (Sueldos fijos, arriendos, servicios básicos).")
    
    st.session_state.gastos_generales = st.data_editor(
        st.session_state.gastos_generales, num_rows="dynamic", use_container_width=True, key="tabla_generales"
    )
    
    total_fijos = st.session_state.gastos_generales["Monto (CLP)"].sum()
    st.info(f"**Total de Gastos Fijos Mensuales: {formato_clp(total_fijos)}**")

# ==========================================
# SECCIÓN 2: GESTIÓN DE PROYECTOS
# ==========================================
elif menu == "📁 2. Gestión de Proyectos":
    st.title("📁 Carpetas de Proyectos")
    
    # Crear un nuevo proyecto
    st.subheader("➕ Crear Nuevo Proyecto")
    col1, col2 = st.columns([3, 1])
    nuevo_nombre = col1.text_input("Nombre del Proyecto (Ej: Tableros Edificio Centro)")
    if col2.button("Crear Proyecto"):
        if nuevo_nombre and nuevo_nombre not in st.session_state.proyectos:
            # Creamos la carpeta del proyecto con sus tablas en blanco
            st.session_state.proyectos[nuevo_nombre] = {
                "ingresos": pd.DataFrame([{"Descripción": "Anticipo de obra", "Monto (CLP)": 0}]),
                "costos": pd.DataFrame([{"Descripción": "Materiales eléctricos", "Monto (CLP)": 0}])
            }
            st.success(f"Proyecto '{nuevo_nombre}' creado con éxito.")
            st.rerun()
        elif nuevo_nombre in st.session_state.proyectos:
            st.warning("Ese proyecto ya existe.")

    st.divider()

    # Seleccionar y editar un proyecto existente
    if st.session_state.proyectos:
        st.subheader("🛠️ Administrar Proyecto")
        proyecto_actual = st.selectbox("Selecciona un proyecto para ver/editar sus detalles:", list(st.session_state.proyectos.keys()))
        
        st.write(f"### Detalles: {proyecto_actual}")
        
        colA, colB = st.columns(2)
        
        with colA:
            st.write("**Ingresos del Proyecto (Cobros)**")
            df_ingresos = st.data_editor(st.session_state.proyectos[proyecto_actual]["ingresos"], num_rows="dynamic", key=f"ing_{proyecto_actual}")
            st.session_state.proyectos[proyecto_actual]["ingresos"] = df_ingresos
            total_ing_proy = df_ingresos["Monto (CLP)"].sum()
            st.write(f"Total Cobrado: {formato_clp(total_ing_proy)}")
            
        with colB:
            st.write("**Costos Directos (Materiales, Extras)**")
            df_costos = st.data_editor(st.session_state.proyectos[proyecto_actual]["costos"], num_rows="dynamic", key=f"cost_{proyecto_actual}")
            st.session_state.proyectos[proyecto_actual]["costos"] = df_costos
            total_cost_proy = df_costos["Monto (CLP)"].sum()
            st.write(f"Total Costos: {formato_clp(total_cost_proy)}")
            
        # Rentabilidad de ESTE proyecto
        utilidad_proyecto = total_ing_proy - total_cost_proy
        st.info(f"**Rentabilidad del proyecto '{proyecto_actual}': {formato_clp(utilidad_proyecto)}**")
        
    else:
        st.info("Aún no has creado ningún proyecto. Escribe un nombre arriba para empezar.")

# ==========================================
# SECCIÓN 3: FLUJO TOTAL EMPRESA
# ==========================================
elif menu == "📊 3. Flujo Total Empresa":
    st.title("📊 Balance General y Flujo Total")
    st.write("Esta sección suma todos los proyectos y resta los gastos generales para darte la utilidad real de la empresa.")
    
    # 1. Sumar todos los proyectos
    total_ingresos_proyectos = 0
    total_costos_proyectos = 0
    
    for proy, datos in st.session_state.proyectos.items():
        total_ingresos_proyectos += datos["ingresos"]["Monto (CLP)"].sum()
        total_costos_proyectos += datos["costos"]["Monto (CLP)"].sum()
        
    # 2. Sumar gastos generales
    total_gastos_generales = st.session_state.gastos_generales["Monto (CLP)"].sum()
    
    # 3. Cálculos finales
    ingresos_totales = total_ingresos_proyectos
    egresos_totales = total_costos_proyectos + total_gastos_generales
    utilidad_neta_empresa = ingresos_totales - egresos_totales
    
    # Mostrar tarjetas
    col1, col2, col3 = st.columns(3)
    col1.metric("Ingresos Totales (Todos los proyectos)", formato_clp(ingresos_totales))
    col2.metric("Egresos Totales (Proyectos + Fijos)", formato_clp(egresos_totales))
    col3.metric("UTILIDAD NETA (Ganancia Real)", formato_clp(utilidad_neta_empresa))
    
    st.divider()
    
    # Desglose visual
    st.subheader("Desglose del Flujo")
    st.write(f"➕ **Dinero que entró (Proyectos):** {formato_clp(total_ingresos_proyectos)}")
    st.write(f"➖ **Dinero que salió por materiales (Proyectos):** {formato_clp(total_costos_proyectos)}")
    st.write(f"➖ **Dinero que salió por costos de empresa (Sueldos, etc):** {formato_clp(total_gastos_generales)}")
    
    if utilidad_neta_empresa > 0:
        st.success("La empresa está generando ganancias después de pagar todos los sueldos e insumos.")
    else:
        st.error("La empresa está en pérdida. Los cobros de los proyectos no alcanzan a cubrir los materiales y los sueldos fijos.")