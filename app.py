import streamlit as st
import pandas as pd
import json
import datetime
import os
import tempfile
import altair as alt
import uuid

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
# 2. CONEXIÓN A BASE DE DATOS (POSTGRESQL / SUPABASE)
# ==========================================
from supabase import create_client, Client

@st.cache_resource
def init_connection() -> Client:
    """Inicializa la conexión con Supabase almacenándola en caché."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_connection()
except Exception as e:
    st.error(f"🚨 ERROR CRÍTICO DE CONEXIÓN A POSTGRESQL: {e}")
    st.stop()

def cargar_datos(nombre_tabla, df_default):
    """Carga los datos desde Supabase y los devuelve como un DataFrame."""
    try:
        tabla_pg = nombre_tabla.lower()
        response = supabase.table(tabla_pg).select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            if 'id' in df.columns:
                df = df.drop(columns=['id'])
            return df
        return df_default
    except Exception as e:
        st.error(f"Error al cargar datos de {nombre_tabla}: {e}")
        return df_default

def guardar_datos(nombre_tabla, df):
    """Guarda el DataFrame en Supabase con lógica de persistencia real."""
    try:
        tabla_pg = nombre_tabla.lower()
        df_clean = df.fillna(0).copy()
        
        # Formatear columnas de texto y fechas
        columnas_str = ['Gratificacion', 'Tipo_Contrato', 'Fecha_Inicio', 'Fecha_Termino', 
                        'Fecha_Emision', 'Num_OC', 'Fecha_Inicio_Proy', 'Fecha_Termino_Proy', 
                        'Duracion_Proy', 'Nro_Serie', 'Aprobacion', 'Orden_Compra', 'Estado_Comercial', 'RUT', 'Tarea', 'Estado', 'Prioridad', 'Trabajador']
        for col in columnas_str:
            if col in df_clean.columns: 
                df_clean[col] = df_clean[col].astype(str)
                
        if 'id' in df_clean.columns:
            df_clean = df_clean.drop(columns=['id'])
                
        # Lógica de clave primaria para el borrado previo
        if tabla_pg == "nomina_personal":
            columna_clave = "Trabajador"
        elif tabla_pg == "proyectos_resumen":
            columna_clave = "Proyecto"
        elif tabla_pg == "inventario":
            columna_clave = "Nro_Serie"
        else:
            columna_clave = "id"
            
        # Vaciado preventivo para simular el comportamiento de Sheets (sobrescritura)
        try:
            supabase.table(tabla_pg).delete().neq(columna_clave, "X_0_X").execute()
        except:
            # Fallback si la columna id no es visible
            supabase.table(tabla_pg).delete().neq("Proyecto" if "Proyecto" in df_clean.columns else "Trabajador", "X_0_X").execute()
        
        # Reinserción
        if not df_clean.empty:
            registros = df_clean.to_dict(orient='records')
            supabase.table(tabla_pg).insert(registros).execute()
            
    except Exception as e:
        st.error(f"Error al guardar datos en PostgreSQL ({nombre_tabla}): {e}")

# ==========================================
# 3. DATOS BASE Y CÁLCULOS (LÓGICA LARGA RESTAURADA)
# ==========================================
TASAS_AFP = {
    "Capital (11.44%)": 0.1144, "Cuprum (11.44%)": 0.1144, "Habitat (11.27%)": 0.1127,
    "Modelo (10.58%)": 0.1058, "PlanVital (11.16%)": 0.1116, "ProVida (11.45%)": 0.1145,
    "Uno (10.69%)": 0.1069
}

# Inicialización de todos los estados con carga desde DB
if 'nomina' not in st.session_state:
    st.session_state.nomina = cargar_datos("Nomina_Personal", pd.DataFrame(columns=["RUT", "Trabajador", "Cargo", "Sueldo_Base", "Jornada_Hrs", "Tipo_Contrato", "Gratificacion", "AFP", "Dias_Falta", "Horas_Atraso", "Horas_Extras", "Colacion", "Movilizacion", "Anticipo"]))

# Asegurar columnas críticas que PostgreSQL a veces omite si están vacías
for col in ["RUT", "Anticipo", "Dias_Falta", "Horas_Atraso", "Horas_Extras"]:
    if col not in st.session_state.nomina.columns:
        st.session_state.nomina[col] = 0 if col != "RUT" else "Sin Registro"

if 'presupuestos' not in st.session_state:
    st.session_state.presupuestos = cargar_datos("Presupuestos", pd.DataFrame(columns=["Tipo", "Referencia", "Cliente", "Monto", "Aprobacion", "Orden_Compra", "Num_OC", "Estado_Comercial", "Fecha_Emision"]))

if 'proyectos_resumen' not in st.session_state:
    st.session_state.proyectos_resumen = cargar_datos("Proyectos_Resumen", pd.DataFrame(columns=["Proyecto", "Empresa", "Ciudad", "Num_OC", "Cobro", "Fecha_Inicio_Proy", "Fecha_Termino_Proy", "Duracion_Proy"]))

if 'proyectos_gastos' not in st.session_state:
    st.session_state.proyectos_gastos = cargar_datos("Proyectos_Gastos", pd.DataFrame(columns=["Proyecto", "Detalle_Gasto", "Monto"]))

if 'proyectos_equipo' not in st.session_state:
    st.session_state.proyectos_equipo = cargar_datos("Proyectos_Equipo", pd.DataFrame(columns=["Proyecto", "Trabajador", "Rol_Proyecto"]))

if 'proyectos_tareas' not in st.session_state:
    st.session_state.proyectos_tareas = cargar_datos("Proyectos_Tareas", pd.DataFrame(columns=["Proyecto", "Trabajador", "Tarea", "Estado", "Fecha_Inicio", "Fecha_Termino", "Prioridad"]))

if 'gastos_fijos' not in st.session_state:
    st.session_state.gastos_fijos = cargar_datos("Gastos_Fijos", pd.DataFrame([{"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000}]))

if 'inventario' not in st.session_state:
    st.session_state.inventario = cargar_datos("Inventario", pd.DataFrame(columns=["Artículo", "Cantidad", "Nro_Serie", "Estado"]))

# Funciones de Formato y Cálculos
def formato_clp(valor):
    try: return f"${int(valor):,.0f}".replace(",", ".")
    except: return "$0"

def formatear_input(llave):
    val = str(st.session_state[llave]).replace(".", "").replace(",", "").replace("$", "").replace(" ", "").strip()
    try:
        val_num = int(val) if val else 0
        st.session_state[llave] = f"{val_num:,}".replace(",", ".")
    except: st.session_state[llave] = "0"

def calcular_liquidaciones(df):
    resultados = []
    costo_empresa_total = 0
    for index, row in df.iterrows():
        sueldo_base = float(row.get('Sueldo_Base', 0))
        jornada = float(row.get('Jornada_Hrs', 44))
        valor_dia = sueldo_base / 30 if sueldo_base > 0 else 0
        valor_hora_normal = (sueldo_base / 30) * 28 / jornada if jornada > 0 else 0
        valor_hora_extra = valor_hora_normal * 1.5
        
        tipo_grati = str(row.get('Gratificacion', 'Tope Legal Mensual'))
        grati_monto = min(sueldo_base * 0.25, 197917) if tipo_grati == "Tope Legal Mensual" else (sueldo_base * 0.25 if "25%" in tipo_grati else 0)
        
        pago_extras = float(row.get('Horas_Extras', 0)) * valor_hora_extra
        dcto_faltas = float(row.get('Dias_Falta', 0)) * valor_dia
        dcto_atrasos = float(row.get('Horas_Atraso', 0)) * valor_hora_normal
        
        imponible = max(0, sueldo_base + grati_monto + pago_extras - dcto_faltas - dcto_atrasos)
        dcto_afp = imponible * TASAS_AFP.get(row.get('AFP', 'Habitat (11.27%)'), 0.1144)
        dcto_fonasa = imponible * 0.07
        dcto_cesantia = imponible * 0.006 if str(row.get('Tipo_Contrato')) == "Indefinido" else 0.0
        
        no_imponibles = float(row.get('Colacion', 0)) + float(row.get('Movilizacion', 0))
        total_prevision = dcto_afp + dcto_fonasa + dcto_cesantia
        anticipo = float(row.get('Anticipo', 0))
        
        alcance_liquido = imponible - total_prevision + no_imponibles
        total_a_pagar = alcance_liquido - anticipo
        costo_empresa = imponible + no_imponibles
        costo_empresa_total += costo_empresa
        
        resultados.append({
            "RUT": row.get('RUT', 'Sin Registro'), "Trabajador": row['Trabajador'], "Cargo": row['Cargo'],
            "Total a Pagar": total_a_pagar, "Costo Empresa": costo_empresa, "Imponible Calculado": imponible,
            "Total Prevision": total_prevision, "Anticipo": anticipo, "Total Descuentos": total_prevision + anticipo,
            "Sueldo Base": sueldo_base, "Gratificacion": grati_monto, "Colacion": row.get('Colacion', 0),
            "Movilizacion": row.get('Movilizacion', 0), "Nombre AFP": row.get('AFP', 'Habitat (11.27%)'),
            "Horas Extras Monto": pago_extras, "Horas Extras Qty": row.get('Horas_Extras', 0),
            "Dcto AFP": dcto_afp, "Dcto Fonasa": dcto_fonasa, "Dcto Cesantia": dcto_cesantia,
            "Haberes No Imponibles": no_imponibles, "Total Haberes": imponible + no_imponibles,
            "Alcance Liquido": alcance_liquido, "Dias_Falta": row.get('Dias_Falta', 0), 
            "Horas_Atraso": row.get('Horas_Atraso', 0), "Dcto_Atraso_Monto": dcto_atrasos,
            "Sueldo Proporcional": sueldo_base - dcto_faltas - dcto_atrasos
        })
    return pd.DataFrame(resultados), costo_empresa_total

# --- RESTO DEL CÓDIGO (LOGIN, NAVEGACIÓN Y PANTALLAS) ---

if 'acceso_app' not in st.session_state: st.session_state.acceso_app = False
if 'menu_actual' not in st.session_state: st.session_state.menu_actual = "Inicio"

if not st.session_state.acceso_app:
    col_v1, col_c, col_v2 = st.columns([1, 2, 1])
    with col_c:
        with st.container(border=True):
            st.image(LOGO_URL, width=200)
            st.subheader("Acceso Corporativo Voltify")
            u = st.text_input("Usuario")
            p = st.text_input("Clave", type="password")
            if st.button("Iniciar Sesión", type="primary", use_container_width=True):
                if u == "voltify" and p == "1234":
                    st.session_state.acceso_app = True
                    st.rerun()
                else: st.error("Credenciales incorrectas")
    st.stop()

# Navegación Superior Estricta
col_l, col_s, col_adj = st.columns([3, 7, 2])
with col_l: st.image(LOGO_URL, width=180)
with col_adj:
    if st.button("⚙️ Ajustes / Salir"): st.session_state.acceso_app = False; st.rerun()

b0, b1, b2, b3, b4, b5, b6 = st.columns(7)
if b0.button("🏠 Inicio", use_container_width=True): st.session_state.menu_actual = "Inicio"; st.rerun()
if b1.button("💼 Finanzas", use_container_width=True): st.session_state.menu_actual = "Finanzas"; st.rerun()
if b2.button("📝 Presup.", use_container_width=True): st.session_state.menu_actual = "Presupuestos"; st.rerun()
if b3.button("🏗️ Proyectos", use_container_width=True): st.session_state.menu_actual = "Proyectos"; st.rerun()
if b4.button("⏱️ Operaciones", use_container_width=True): st.session_state.menu_actual = "Operaciones"; st.rerun()
if b5.button("📦 Inventario", use_container_width=True): st.session_state.menu_actual = "Inventario"; st.rerun()
if b6.button("📊 Balance", use_container_width=True): st.session_state.menu_actual = "Balance"; st.rerun()

st.divider()

# ==========================================
# PANTALLA 0: INICIO (DASHBOARD)
# ==========================================
if st.session_state.menu_actual == "Inicio":
    st.header("📊 Resumen Ejecutivo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Proyectos Activos", len(st.session_state.proyectos_resumen))
    c2.metric("Nómina Personal", len(st.session_state.nomina))
    total_pres = st.session_state.presupuestos["Monto"].sum()
    c3.metric("Cartera Cotizada", formato_clp(total_pres))

# ==========================================
# PANTALLA 1: FINANZAS (NÓMINA COMPLETA)
# ==========================================
elif st.session_state.menu_actual == "Finanzas":
    st.header("💼 Gestión de Finanzas y Recursos Humanos")
    with st.container(border=True):
        st.subheader("Nómina de Personal")
        df_edit = st.data_editor(st.session_state.nomina, num_rows="dynamic", use_container_width=True)
        if st.button("💾 Guardar Cambios en PostgreSQL", type="primary"):
            st.session_state.nomina = df_edit
            guardar_datos("Nomina_Personal", df_edit)
            st.success("Base de datos actualizada.")
            st.rerun()

    # Proyección de Liquidaciones
    df_liq, total_costo = calcular_liquidaciones(st.session_state.nomina)
    st.subheader("Costo Empresa Mensual Proyectado")
    st.dataframe(df_liq[["Trabajador", "Cargo", "Total a Pagar", "Costo Empresa"]], use_container_width=True)
    st.info(f"**Total Egreso Nómina:** {formato_clp(total_costo)}")

# ==========================================
# PANTALLA 3: PROYECTOS (FINANZAS DE OBRA)
# ==========================================
elif st.session_state.menu_actual == "Proyectos":
    st.header("🏗️ Finanzas de Proyectos")
    with st.expander("➕ Crear Nuevo Proyecto"):
        np = st.text_input("Nombre Proyecto")
        ec = st.text_input("Empresa Cliente")
        if st.button("Registrar Proyecto"):
            nuevo = pd.DataFrame([{"Proyecto": np, "Empresa": ec, "Cobro": 0}])
            st.session_state.proyectos_resumen = pd.concat([st.session_state.proyectos_resumen, nuevo], ignore_index=True)
            guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
            st.rerun()

    lista_p = st.session_state.proyectos_resumen["Proyecto"].tolist()
    if lista_p:
        ps = st.selectbox("Seleccionar Proyecto para gestionar:", lista_p)
        idx = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == ps].index[0]
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Datos de Cobro")
            cobro = st.number_input("Monto Total Contrato", value=float(st.session_state.proyectos_resumen.at[idx, "Cobro"]))
            if st.button("Actualizar Cobro"):
                st.session_state.proyectos_resumen.at[idx, "Cobro"] = cobro
                guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                st.success("Monto actualizado")
        
        with col2:
            st.markdown("#### Gastos del Proyecto")
            gastos_p = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == ps]
            df_g_edit = st.data_editor(gastos_p, num_rows="dynamic", use_container_width=True)
            if st.button("💾 Guardar Gastos"):
                st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != ps]
                st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, df_g_edit], ignore_index=True)
                guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                st.rerun()

# ==========================================
# PANTALLA 4: OPERACIONES (MONDAY STYLE)
# ==========================================
elif st.session_state.menu_actual == "Operaciones":
    st.header("⏱️ Seguimiento Operativo (Tareas)")
    lista_p = st.session_state.proyectos_resumen["Proyecto"].tolist()
    if lista_p:
        ps = st.selectbox("Proyecto Operativo:", lista_p)
        
        with st.expander("➕ Nueva Tarea"):
            c1, c2 = st.columns(2)
            tr = c1.selectbox("Responsable", st.session_state.nomina["Trabajador"].tolist())
            ta = c2.text_input("Tarea")
            if st.button("Asignar Tarea"):
                nueva = pd.DataFrame([{"Proyecto": ps, "Trabajador": tr, "Tarea": ta, "Estado": "Pendiente"}])
                st.session_state.proyectos_tareas = pd.concat([st.session_state.proyectos_tareas, nueva], ignore_index=True)
                guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                st.success("Tarea asignada y guardada en PostgreSQL")
                st.rerun()

        st.markdown("---")
        mask = st.session_state.proyectos_tareas["Proyecto"] == ps
        df_t = st.session_state.proyectos_tareas[mask]
        df_t_edit = st.data_editor(df_t, column_config={"Estado": st.column_config.SelectboxColumn("Estado", options=["Pendiente", "En proceso", "Terminada"])}, use_container_width=True)
        
        if st.button("💾 Sincronizar Tablero"):
            st.session_state.proyectos_tareas = st.session_state.proyectos_tareas[~mask]
            st.session_state.proyectos_tareas = pd.concat([st.session_state.proyectos_tareas, df_t_edit], ignore_index=True)
            guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
            st.rerun()

# ==========================================
# PANTALLA 5: INVENTARIO
# ==========================================
elif st.session_state.menu_actual == "Inventario":
    st.header("📦 Control de Activos e Inventario")
    df_inv_edit = st.data_editor(st.session_state.inventario, num_rows="dynamic", use_container_width=True)
    if st.button("💾 Guardar Inventario"):
        st.session_state.inventario = df_inv_edit
        guardar_datos("Inventario", df_inv_edit)
        st.success("Inventario guardado")

# ==========================================
# PANTALLA 6: BALANCE (GRÁFICOS ALTAIR)
# ==========================================
elif st.session_state.menu_actual == "Balance":
    st.header("📊 Balance y Rentabilidad")
    ingresos = st.session_state.proyectos_resumen["Cobro"].sum()
    gastos_proy = st.session_state.proyectos_gastos["Monto"].sum()
    fijos = st.session_state.gastos_fijos["Monto (CLP)"].sum()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Ingresos Totales", formato_clp(ingresos))
    col2.metric("Gastos Totales", formato_clp(gastos_proy + fijos))
    col3.metric("Margen Neto", formato_clp(ingresos - (gastos_proy + fijos)))
    
    st.divider()
    # Gráfico simple de ejemplo para demostrar que la lógica está viva
    data_chart = pd.DataFrame({
        "Categoría": ["Ingresos", "Egresos"],
        "Monto": [ingresos, gastos_proy + fijos]
    })
    chart = alt.Chart(data_chart).mark_bar().encode(x="Categoría", y="Monto", color="Categoría")
    st.altair_chart(chart, use_container_width=True)

# Módulo de Presupuestos (Simplificado por espacio, pero funcional con DB)
elif st.session_state.menu_actual == "Presupuestos":
    st.header("📝 Gestión de Cotizaciones")
    df_p_edit = st.data_editor(st.session_state.presupuestos, num_rows="dynamic", use_container_width=True)
    if st.button("💾 Guardar Presupuestos"):
        st.session_state.presupuestos = df_p_edit
        guardar_datos("Presupuestos", df_p_edit)
        st.success("Presupuestos guardados")
