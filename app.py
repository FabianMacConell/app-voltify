import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD VISUAL
# ==========================================
st.set_page_config(page_title="Panel Financiero Voltify", page_icon="logo.png", layout="wide")

ocultar_menu_estilo = """
            <style>
            [data-testid="stHeaderActionElements"] {display: none !important;}
            [data-testid="stToolbar"] {display: none !important;}
            .viewerBadge_container {display: none !important;}
            #viewerBadge {display: none !important;}
            iframe[src*="badge"] {display: none !important;}
            .stDeployButton {display: none !important;}
            footer {display: none !important;}
            [data-testid="stDecoration"] {display: none !important;}
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
        df_clean = df.fillna(0)
        # Forzar formato texto en gratificación para evitar errores de Google Sheets
        if 'Gratificacion' in df_clean.columns:
            df_clean['Gratificacion'] = df_clean['Gratificacion'].astype(str)
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df_clean.columns.tolist())
        hoja.clear()
        hoja.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
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
# 3. CONTROL DE ACCESOS
# ==========================================
if 'acceso_app' not in st.session_state: st.session_state.acceso_app = False
if 'acceso_finanzas' not in st.session_state: st.session_state.acceso_finanzas = "ninguno" 
if 'acceso_proyectos' not in st.session_state: st.session_state.acceso_proyectos = "ninguno" 

if not st.session_state.acceso_app:
    col_vacia1, col_centro, col_vacia2 = st.columns([1, 2, 1])
    with col_centro:
        st.image(LOGO_URL, use_container_width=True)
        st.title("Portal Corporativo")
        st.write("Ingresa las credenciales de la empresa para acceder a la plataforma.")
        
        u_gen = st.text_input("Usuario Corporativo")
        p_gen = st.text_input("Clave de Acceso", type="password")
        
        if st.button("Entrar a la Plataforma", type="primary", use_container_width=True):
            if u_gen == "voltify" and p_gen == "1234":
                st.session_state.acceso_app = True
                st.rerun()
            else:
                st.error("Credenciales de empresa incorrectas.")
    st.stop()

# ==========================================
# 4. DATOS BASE Y CÁLCULOS
# ==========================================
TASAS_AFP = {
    "Capital (11.44%)": 0.1144, "Cuprum (11.44%)": 0.1144, "Habitat (11.27%)": 0.1127,
    "Modelo (10.58%)": 0.1058, "PlanVital (11.16%)": 0.1116, "ProVida (11.45%)": 0.1145,
    "Uno (10.69%)": 0.1069
}

if 'nomina' not in st.session_state:
    df_nomina_base = pd.DataFrame([{
        "Trabajador": "Begoñia Mac-Conell Bacho", "Cargo": "Jefa de administracion y finanzas",
        "Sueldo_Base": 850000, "Jornada_Hrs": 44, "Gratificacion": "Tope Legal Mensual", "AFP": "Habitat (11.27%)",
        "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, "Colacion": 0, "Movilizacion": 0
    }])
    st.session_state.nomina = cargar_datos("Nomina_Personal", df_nomina_base)
    
    # FORZADOR DE ACTUALIZACIÓN DE COLUMNAS PARA GOOGLE SHEETS
    cambio_necesario = False
    if 'Bonos_No_Imponibles' in st.session_state.nomina.columns:
        st.session_state.nomina = st.session_state.nomina.drop(columns=['Bonos_No_Imponibles'])
        cambio_necesario = True
    for col in df_nomina_base.columns:
        if col not in st.session_state.nomina.columns:
            st.session_state.nomina[col] = df_nomina_base[col][0]
            cambio_necesario = True
    if cambio_necesario:
        guardar_datos("Nomina_Personal", st.session_state.nomina) # Obliga a Google a aceptar el nuevo formato

if 'gastos_fijos' not in st.session_state:
    df_fijos_base = pd.DataFrame([{"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000}, {"Descripción": "Prioridad emergencias", "Monto (CLP)": 50000}])
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
        try:
            sueldo_base = float(row['Sueldo_Base'])
            jornada = float(row['Jornada_Hrs'])
        except:
            sueldo_base = 0.0
            jornada = 44.0
        
        valor_dia = sueldo_base / 30 if sueldo_base > 0 else 0
        valor_hora_normal = (sueldo_base / 30) * 28 / jornada if jornada > 0 else 0
        valor_hora_extra = valor_hora_normal * 1.5
        
        # Gratificación
        tipo_grati = str(row.get('Gratificacion', 'Sin Gratificación'))
        if tipo_grati == "Tope Legal Mensual":
            grati_monto = min(sueldo_base * 0.25, 197917)
        elif tipo_grati == "25% del Sueldo (Sin Tope)":
            grati_monto = sueldo_base * 0.25
        else:
            grati_monto = 0
            
        pago_extras = float(row.get('Horas_Extras', 0)) * valor_hora_extra
        dcto_faltas = float(row.get('Dias_Falta', 0)) * valor_dia
        dcto_atrasos = float(row.get('Horas_Atraso', 0)) * valor_hora_normal
        
        sueldo_imponible = sueldo_base + grati_monto + pago_extras - dcto_faltas - dcto_atrasos
        if sueldo_imponible < 0: sueldo_imponible = 0
        
        dcto_afp = sueldo_imponible * TASAS_AFP.get(row.get('AFP', 'Habitat (11.27%)'), 0.1144)
        dcto_fonasa = sueldo_imponible * 0.07
        dcto_cesantia = sueldo_imponible * 0.006 
        
        colacion = float(row.get('Colacion', 0))
        movilizacion = float(row.get('Movilizacion', 0))
        no_imponibles = colacion + movilizacion
        
        sueldo_liquido = sueldo_imponible - dcto_afp - dcto_fonasa - dcto_cesantia + no_imponibles
        costo_real_empresa = sueldo_imponible + no_imponibles
        costo_empresa_total += costo_real_empresa
        
        resultados.append({
            "Trabajador": row['Trabajador'], "Cargo": row['Cargo'],
            "Imponible Calculado": sueldo_imponible, "Haberes No Imponibles": no_imponibles, 
            "Descuentos Ley": dcto_afp + dcto_fonasa + dcto_cesantia,
            "Líquido a Pagar": sueldo_liquido, "Costo Empresa": costo_real_empresa
        })
    return pd.DataFrame(resultados), costo_empresa_total

# ==========================================
# 5. BARRA LATERAL FIJA
# ==========================================
st.sidebar.image(LOGO_URL, use_container_width=True)

if st.sidebar.button("Salir de la Plataforma"):
    st.session_state.acceso_app = False
    st.session_state.acceso_finanzas = "ninguno"
    st.session_state.acceso_proyectos = "ninguno"
    st.rerun()

if st.sidebar.button("Bloquear Secciones"):
    st.session_state.acceso_finanzas = "ninguno"
    st.session_state.acceso_proyectos = "ninguno"
    st.rerun()

st.sidebar.divider()
menu = st.sidebar.radio("Navegación:", ["Finanzas y Nómina", "Proyectos", "Balance Total"])

# ==========================================
# PANTALLA 1: FINANZAS Y NÓMINA
# ==========================================
if menu == "Finanzas y Nómina":
    st.title("Área de Finanzas y Recursos Humanos")
    
    if st.session_state.acceso_finanzas == "ninguno":
        st.info("Ingresa credenciales para acceder a Finanzas.")
        col1, col2 = st.columns([1, 2])
        with col1:
            u_fin = st.text_input("Usuario (Finanzas)")
            p_fin = st.text_input("Clave", type="password", key="p_fin")
            if st.button("Desbloquear Finanzas", type="primary"):
                if (u_fin == "master" and p_fin == "123") or (u_fin == "admin_fin" and p_fin == "admin123"):
                    st.session_state.acceso_finanzas = "admin"
                    st.rerun()
                elif (u_fin == "obs_fin" and p_fin == "obs123"):
                    st.session_state.acceso_finanzas = "observador"
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")
    else:
        if st.session_state.acceso_finanzas == "observador": st.warning("MODO OBSERVADOR: Visualización en modo lectura.")
            
        tab_nomina, tab_fijos = st.tabs(["Nómina y Liquidaciones", "Gastos Fijos Operativos"])
        
        with tab_nomina:
            st.subheader("Control de Asistencia y Nómina")
            
            if st.session_state.acceso_finanzas == "admin":
                with st.expander("Ingresar Nuevo Trabajador", expanded=False):
                    colA, colB, colC = st.columns(3)
                    n_trabajador = colA.text_input("Nombre Completo")
                    n_cargo = colB.text_input("Cargo")
                    
                    if 'input_sueldo_base' not in st.session_state: st.session_state['input_sueldo_base'] = "0"
                    colC.text_input("Sueldo Base Mensual", key="input_sueldo_base", on_change=formatear_input, kwargs={'llave': 'input_sueldo_base'}, help="Escribe de corrido y presiona Enter")
                    n_sueldo = float(st.session_state['input_sueldo_base'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                    
                    colD, colE, colF = st.columns(3)
                    n_jornada = colD.number_input("Horas Semanales (Jornada)", value=44, max_value=45)
                    n_grati = colE.selectbox("Tipo de Gratificación", ["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"])
                    n_afp = colF.selectbox("Seleccione AFP", list(TASAS_AFP.keys()))
                    
                    colG, colH = st.columns(2)
                    if 'input_colacion' not in st.session_state: st.session_state['input_colacion'] = "0"
                    if 'input_movilizacion' not in st.session_state: st.session_state['input_movilizacion'] = "0"
                    
                    colG.text_input("Bono Colación (Opcional)", key="input_colacion", on_change=formatear_input, kwargs={'llave': 'input_colacion'})
                    n_cola = float(st.session_state['input_colacion'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                    
                    colH.text_input("Bono Movilización (Opcional)", key="input_movilizacion", on_change=formatear_input, kwargs={'llave': 'input_movilizacion'})
                    n_movi = float(st.session_state['input_movilizacion'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                    
                    if st.button("Guardar Perfil"):
                        if n_trabajador:
                            nuevo_perfil = pd.DataFrame([{
                                "Trabajador": n_trabajador, "Cargo": n_cargo, "Sueldo_Base": n_sueldo, 
                                "Jornada_Hrs": n_jornada, "Gratificacion": n_grati, "AFP": n_afp, 
                                "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, 
                                "Colacion": n_cola, "Movilizacion": n_movi
                            }])
                            st.session_state.nomina = pd.concat([st.session_state.nomina, nuevo_perfil], ignore_index=True)
                            guardar_datos("Nomina_Personal", st.session_state.nomina)
                            st.session_state['input_sueldo_base'] = "0"
                            st.session_state['input_colacion'] = "0"
                            st.session_state['input_movilizacion'] = "0"
                            st.success("Trabajador registrado exitosamente.")
                            st.rerun()

                st.write("Modifique datos, asistencia y bonos en la tabla interactiva:")
                df_nomina_edit = st.data_editor(
                    st.session_state.nomina,
                    column_config={
                        "Sueldo_Base": st.column_config.NumberColumn("Sueldo Base", min_value=0, step=10000, format="%,d"),
                        "Colacion": st.column_config.NumberColumn("Colación", min_value=0, step=5000, format="%,d"),
                        "Movilizacion": st.column_config.NumberColumn("Movilización", min_value=0, step=5000, format="%,d"),
                        "Gratificacion": st.column_config.SelectboxColumn("Gratificación", options=["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"]),
                        "AFP": st.column_config.SelectboxColumn("AFP", options=list(TASAS_AFP.keys())),
                    },
                    num_rows="dynamic", use_container_width=True, key="ed_nomina"
                )
                if st.button("Guardar Cambios de Nómina"):
                    st.session_state.nomina = df_nomina_edit
                    guardar_datos("Nomina_Personal", st.session_state.nomina)
                    st.success("Nómina y asistencia actualizadas en la base de datos.")
            else:
                df_nomina_view = st.session_state.nomina.copy()
                for col in ["Sueldo_Base", "Colacion", "Movilizacion"]:
                    df_nomina_view[col] = pd.to_numeric(df_nomina_view.get(col, 0), errors='coerce').apply(formato_clp)
                st.dataframe(df_nomina_view, use_container_width=True)

            st.write("---")
            st.subheader("Proyección de Liquidaciones de Sueldo")
            df_liquidaciones, total_nomina_empresa = calcular_liquidaciones(st.session_state.nomina)
            df_liq_format = df_liquidaciones.copy()
            for col in ["Imponible Calculado", "Haberes No Imponibles", "Descuentos Ley", "Líquido a Pagar", "Costo Empresa"]:
                df_liq_format[col] = df_liq_format[col].apply(formato_clp)
            st.dataframe(df_liq_format, use_container_width=True)
            st.info(f"Costo Total Proyectado de Nómina para la Empresa: {formato_clp(total_nomina_empresa)}")

        with tab_fijos:
            st.subheader("Gastos Fijos Operativos")
            if st.session_state.acceso_finanzas == "admin":
                res_fijos = st.data_editor(st.session_state.gastos_fijos, column_config={"Monto (CLP)": st.column_config.NumberColumn("Monto (CLP)", min_value=0, step=1000, format="%,d")}, num_rows="dynamic", use_container_width=True, key="ed_fijos")
                if st.button("Guardar Cambios Fijos"):
                    st.session_state.gastos_fijos = res_fijos
                    guardar_datos("Gastos_Fijos", res_fijos)
                    st.success("Gastos fijos actualizados.")
            else:
                df_fijos_view = st.session_state.gastos_fijos.copy()
                df_fijos_view["Monto (CLP)"] = pd.to_numeric(df_fijos_view["Monto (CLP)"], errors='coerce').apply(formato_clp)
                st.dataframe(df_fijos_view, use_container_width=True)

# ==========================================
# PANTALLA 2: PROYECTOS
# ==========================================
elif menu == "Proyectos":
    st.title("Gestión de Proyectos")
    
    if st.session_state.acceso_proyectos == "ninguno":
        st.info("Ingresa credenciales para acceder a Proyectos.")
        col1, col2 = st.columns([1, 2])
        with col1:
            u_proy = st.text_input("Usuario (Proyectos)")
            p_proy = st.text_input("Clave", type="password", key="p_proy")
            if st.button("Desbloquear Proyectos", type="primary"):
                if (u_proy == "master" and p_proy == "123") or (u_proy == "admin_proy" and p_proy == "admin123"):
                    st.session_state.acceso_proyectos = "admin"
                    st.rerun()
                elif (u_proy == "obs_proy" and p_proy == "obs123"):
                    st.session_state.acceso_proyectos = "observador"
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")
    else:
        if st.session_state.acceso_proyectos == "observador": st.warning("MODO OBSERVADOR: Visualización en modo lectura.")
            
        if st.session_state.acceso_proyectos == "admin":
            with st.expander("Crear Nueva Carpeta de Proyecto", expanded=False):
                colA, colB = st.columns(2)
                nombre_p = colA.text_input("Nombre de la Obra o Proyecto")
                empresa_p = colB.text_input("Nombre de la Empresa / Cliente")
                
                if st.button("Crear Proyecto", type="primary"):
                    if nombre_p and nombre_p not in st.session_state.proyectos_resumen["Proyecto"].values:
                        nuevo_resumen = pd.DataFrame([{"Proyecto": nombre_p, "Empresa": empresa_p, "Cobro": 0}])
                        nuevo_gasto = pd.DataFrame([{"Proyecto": nombre_p, "Detalle_Gasto": "Materiales iniciales", "Monto": 0}])
                        st.session_state.proyectos_resumen = pd.concat([st.session_state.proyectos_resumen, nuevo_resumen], ignore_index=True)
                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto], ignore_index=True)
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.success(f"Carpeta '{nombre_p}' creada.")
                        st.rerun()

        st.divider()
        proyectos_lista = st.session_state.proyectos_resumen["Proyecto"].tolist()
        
        if proyectos_lista:
            st.subheader("Abrir Carpeta de Proyecto")
            proyecto_seleccionado = st.selectbox("Selecciona un proyecto:", proyectos_lista)
            
            idx_proy = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_seleccionado].index[0]
            empresa_actual = st.session_state.proyectos_resumen.at[idx_proy, "Empresa"]
            cobro_actual = st.session_state.proyectos_resumen.at[idx_proy, "Cobro"]
            df_gastos_proy = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seleccionado].copy()

            st.markdown(f"#### Empresa / Cliente: **{empresa_actual}**")
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.write("### Ingreso (Cobro)")
                if st.session_state.acceso_proyectos == "admin":
                    llave_cobro = f"cobro_{proyecto_seleccionado}"
                    if llave_cobro not in st.session_state:
                        st.session_state[llave_cobro] = f"{int(cobro_actual):,}".replace(",", ".")
                        
                    st.text_input("Valor total cobrado (CLP):", key=llave_cobro, on_change=formatear_input, kwargs={'llave': llave_cobro}, help="Escribe de corrido y presiona Enter")
                    nuevo_cobro = float(st.session_state[llave_cobro].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                else:
                    st.info(f"Cobro Total: {formato_clp(cobro_actual)}")
                    nuevo_cobro = cobro_actual

            with col2:
                st.write("### Gastos Desglosados")
                if st.session_state.acceso_proyectos == "admin":
                    df_gastos_editados = st.data_editor(
                        df_gastos_proy[["Detalle_Gasto", "Monto"]], 
                        column_config={"Monto": st.column_config.NumberColumn("Monto", min_value=0, step=1000, format="%,d")}, 
                        num_rows="dynamic", use_container_width=True, key=f"gast_{proyecto_seleccionado}"
                    )
                else:
                    df_gastos_view = df_gastos_proy[["Detalle_Gasto", "Monto"]].copy()
                    df_gastos_view["Monto"] = pd.to_numeric(df_gastos_view["Monto"], errors='coerce').apply(formato_clp)
                    st.dataframe(df_gastos_view, use_container_width=True)
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
                    if st.button("Guardar Cambios", type="primary", use_container_width=True):
                        st.session_state.proyectos_resumen.at[idx_proy, "Cobro"] = nuevo_cobro
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado]
                        df_gastos_editados["Proyecto"] = proyecto_seleccionado
                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, df_gastos_editados], ignore_index=True)
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.success("Guardado correctamente.")
                with col_del:
                    if st.button("Eliminar Proyecto", use_container_width=True):
                        st.session_state.proyectos_resumen = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] != proyecto_seleccionado].reset_index(drop=True)
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado].reset_index(drop=True)
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.rerun()

# ==========================================
# PANTALLA 3: BALANCE TOTAL
# ==========================================
elif menu == "Balance Total":
    st.title("Balance General de la Empresa")
    
    if st.session_state.acceso_finanzas == "ninguno":
        st.warning("Esta sección consolida información confidencial.")
        st.info("Por favor, ve a la pestaña 'Finanzas y Nómina' e inicia sesión para desbloquear el Balance Total.")
    else:
        ingresos = pd.to_numeric(st.session_state.proyectos_resumen["Cobro"], errors='coerce').sum() if not st.session_state.proyectos_resumen.empty else 0
        costos_proy = pd.to_numeric(st.session_state.proyectos_gastos["Monto"], errors='coerce').sum() if not st.session_state.proyectos_gastos.empty else 0
        df_liq, costo_nomina_total = calcular_liquidaciones(st.session_state.nomina)
        fijos = pd.to_numeric(st.session_state.gastos_fijos["Monto (CLP)"], errors='coerce').sum()
        
        egresos_totales = costos_proy + costo_nomina_total + fijos
        rentabilidad = ingresos - egresos_totales
        
        c1, c2, c3 = st.columns(3)
        c1.metric("INGRESOS GLOBALES", formato_clp(ingresos))
        c2.metric("EGRESOS TOTALES (Proyectos + Nómina + Fijos)", formato_clp(egresos_totales))
        c3.metric("UTILIDAD NETA", formato_clp(rentabilidad))
        
        st.write("---")
        if rentabilidad > 0:
            st.success("La empresa es rentable.")
        elif rentabilidad < 0:
            st.error(f"Alerta: Los gastos superan a los ingresos por {formato_clp(abs(rentabilidad))}.")
        else:
            st.info("Punto de equilibrio.")
