import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
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
        
        # Añadido RUT a columnas string para evitar errores de formato en Sheets
        columnas_str = ['RUT', 'Gratificacion', 'Tipo_Contrato', 'Fecha_Inicio', 'Fecha_Termino', 'Fecha_Emision', 'Num_OC', 'Fecha_Inicio_Proy', 'Fecha_Termino_Proy', 'Duracion_Proy', 'Nro_Serie']
        for col in columnas_str:
            if col in df_clean.columns: df_clean[col] = df_clean[col].astype(str)
            
        hoja = obtener_o_crear_hoja(libro, nombre_hoja, df_clean.columns.tolist())
        hoja.clear()
        hoja.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")

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

if 'nomina' not in st.session_state:
    df_nomina_base = pd.DataFrame([{
        "RUT": "11.111.111-1",
        "Trabajador": "Begoñia Mac-Conell Bacho", "Cargo": "Jefa de administracion y finanzas",
        "Sueldo_Base": 850000, "Jornada_Hrs": 44, "Tipo_Contrato": "Indefinido", "Gratificacion": "Tope Legal Mensual", "AFP": "Habitat (11.27%)",
        "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, "Colacion": 0, "Movilizacion": 0
    }])
    st.session_state.nomina = cargar_datos("Nomina_Personal", df_nomina_base)

if 'presupuestos' not in st.session_state:
    df_presupuestos_base = pd.DataFrame(columns=["Tipo", "Referencia", "Cliente", "Monto", "Aprobacion", "Orden_Compra", "Num_OC", "Estado_Comercial", "Fecha_Emision"])
    st.session_state.presupuestos = cargar_datos("Presupuestos", df_presupuestos_base)

if 'proyectos_resumen' not in st.session_state:
    df_resumen_base = pd.DataFrame(columns=["Proyecto", "Empresa", "Ciudad", "Num_OC", "Cobro", "Fecha_Inicio_Proy", "Fecha_Termino_Proy", "Duracion_Proy"])
    st.session_state.proyectos_resumen = cargar_datos("Proyectos_Resumen", df_resumen_base)

if 'proyectos_gastos' not in st.session_state:
    df_gastos_base = pd.DataFrame(columns=["Proyecto", "Detalle_Gasto", "Monto"])
    st.session_state.proyectos_gastos = cargar_datos("Proyectos_Gastos", df_gastos_base)

if 'proyectos_equipo' not in st.session_state:
    df_equipo_base = pd.DataFrame(columns=["Proyecto", "Trabajador", "Rol_Proyecto"])
    st.session_state.proyectos_equipo = cargar_datos("Proyectos_Equipo", df_equipo_base)

if 'proyectos_tareas' not in st.session_state:
    df_tareas_base = pd.DataFrame(columns=["Proyecto", "Trabajador", "Tarea", "Estado"])
    st.session_state.proyectos_tareas = cargar_datos("Proyectos_Tareas", df_tareas_base)

if 'gastos_fijos' not in st.session_state:
    df_fijos_base = pd.DataFrame([{"Descripción": "Arriendo Oficina", "Monto (CLP)": 350000}, {"Descripción": "prioridad emergencias", "Monto (CLP)": 50000}])
    st.session_state.gastos_fijos = cargar_datos("Gastos_Fijos", df_fijos_base)

if 'inventario' not in st.session_state:
    df_inventario_base = pd.DataFrame(columns=["Artículo", "Cantidad", "Nro_Serie", "Estado"])
    st.session_state.inventario = cargar_datos("Inventario", df_inventario_base)

if 'ultima_etiqueta' not in st.session_state:
    st.session_state.ultima_etiqueta = None

def formato_clp(valor):
    try: return f"${int(valor):,.0f}".replace(",", ".")
    except (ValueError, TypeError): return "$0"

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
        try: sueldo_base = float(row['Sueldo_Base'])
        except: sueldo_base = 0.0
        try: jornada = float(row['Jornada_Hrs'])
        except: jornada = 44.0
        
        valor_dia = sueldo_base / 30 if sueldo_base > 0 else 0
        valor_hora_normal = (sueldo_base / 30) * 28 / jornada if jornada > 0 else 0
        valor_hora_extra = valor_hora_normal * 1.5
        
        tipo_grati = str(row.get('Gratificacion', 'Sin Gratificación'))
        if tipo_grati == "Tope Legal Mensual": grati_monto = min(sueldo_base * 0.25, 197917)
        elif tipo_grati == "25% del Sueldo (Sin Tope)": grati_monto = sueldo_base * 0.25
        else: grati_monto = 0
            
        pago_extras = float(row.get('Horas_Extras', 0)) * valor_hora_extra
        dcto_faltas = float(row.get('Dias_Falta', 0)) * valor_dia
        dcto_atrasos = float(row.get('Horas_Atraso', 0)) * valor_hora_normal
        
        sueldo_imponible = sueldo_base + grati_monto + pago_extras - dcto_faltas - dcto_atrasos
        if sueldo_imponible < 0: sueldo_imponible = 0
        
        dcto_afp = sueldo_imponible * TASAS_AFP.get(row.get('AFP', 'Habitat (11.27%)'), 0.1144)
        dcto_fonasa = sueldo_imponible * 0.07
        
        tipo_contrato = str(row.get('Tipo_Contrato', 'Indefinido'))
        dcto_cesantia = sueldo_imponible * 0.006 if tipo_contrato == "Indefinido" else 0.0
        
        colacion = float(row.get('Colacion', 0))
        movilizacion = float(row.get('Movilizacion', 0))
        no_imponibles = colacion + movilizacion
        
        sueldo_liquido = sueldo_imponible - dcto_afp - dcto_fonasa - dcto_cesantia + no_imponibles
        costo_real_empresa = sueldo_imponible + no_imponibles
        costo_empresa_total += costo_real_empresa
        
        # El RUT viaja invisible hasta el generador de PDF
        resultados.append({
            "RUT": str(row.get('RUT', 'Sin Registro')),
            "Trabajador": row['Trabajador'], "Cargo": row['Cargo'], "Contrato": tipo_contrato,
            "Sueldo Base": sueldo_base, "Horas Extras": pago_extras, "Gratificacion": grati_monto,
            "Colacion": colacion, "Movilizacion": movilizacion, 
            "Nombre AFP": row.get('AFP', 'Habitat (11.27%)'), "Dcto AFP": dcto_afp,
            "Dcto Fonasa": dcto_fonasa, "Dcto Cesantia": dcto_cesantia,
            "Imponible Calculado": sueldo_imponible, "Haberes No Imponibles": no_imponibles, 
            "Total Haberes": sueldo_imponible + no_imponibles,
            "Descuentos Ley": dcto_afp + dcto_fonasa + dcto_cesantia,
            "Líquido a Pagar": sueldo_liquido, "Costo Empresa": costo_real_empresa,
            "Dias_Falta": row.get('Dias_Falta', 0)
        })
    return pd.DataFrame(resultados), costo_empresa_total

def num2words(n):
    if n == 0: return "CERO"
    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIUN", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    centenas = ["", "CIEN", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    if n < 30: return unidades[n]
    if n < 100:
        return decenas[n // 10] + (" Y " + unidades[n % 10] if n % 10 != 0 else "")
    if n < 1000:
        if n == 100: return "CIEN"
        return (centenas[n // 100] if n // 100 != 1 else "CIENTO") + (" " + num2words(n % 100) if n % 100 != 0 else "")
    if n < 2000:
        return "MIL" + (" " + num2words(n % 1000) if n % 1000 != 0 else "")
    if n < 1000000:
        return num2words(n // 1000) + " MIL" + (" " + num2words(n % 1000) if n % 1000 != 0 else "")
    if n == 1000000: return "UN MILLON"
    if n < 2000000:
        return "UN MILLON " + num2words(n % 1000000)
    return num2words(n // 1000000) + " MILLONES " + num2words(n % 1000000)


# ==========================================
# MOTOR DE COORDENADAS PARA EL PDF
# ==========================================
def right_text(pdf, x, y, text):
    width = pdf.get_string_width(text)
    pdf.text(x - width, y, text)

def generar_pdf_liquidacion(datos):
    pdf = FPDF(unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.text(10, 15, "VOLTIFY SPA")
    pdf.set_font("Arial", '', 9)
    pdf.text(10, 20, "RUT : 77.871.702-6 JAVIERA CARRERA #1150 ARICA")
    pdf.text(10, 25, "Teléfono Cel 995635899")
    
    pdf.set_font("Arial", 'B', 12)
    pdf.text(120, 20, "Liquidación de Sueldo Mensual")
    
    pdf.rect(10, 30, 190, 25) 
    
    rut_trabajador = datos.get("RUT", "Sin Registro")
    trabajador_limpio = str(datos['Trabajador']).encode('latin-1', 'replace').decode('latin-1').upper()
    cargo_limpio = str(datos['Cargo']).encode('latin-1', 'replace').decode('latin-1').upper()
    
    meses_str = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes_actual = meses_str[datetime.datetime.now().month - 1]
    anio_actual = datetime.datetime.now().year
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(12, 35, "RUT:")
    pdf.set_font("Arial", '', 9)
    pdf.text(25, 35, rut_trabajador) # RUT INYECTADO AQUÍ
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(60, 35, "Nombre:")
    pdf.set_font("Arial", '', 9)
    pdf.text(75, 35, trabajador_limpio)
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(150, 35, "Fecha Contrato:")
    pdf.set_font("Arial", '', 9)
    pdf.text(175, 35, ": 16/03/2026")
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(12, 42, "Año:")
    pdf.set_font("Arial", '', 9)
    pdf.text(25, 42, str(anio_actual))
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(40, 42, "Mes:")
    pdf.set_font("Arial", '', 9)
    pdf.text(50, 42, mes_actual)
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(75, 42, "CC:")
    pdf.set_font("Arial", '', 9)
    pdf.text(85, 42, "OPERACIONES")
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(120, 42, "Sueldo Base:")
    pdf.set_font("Arial", '', 9)
    pdf.text(140, 42, formato_clp(datos["Sueldo Base"]).replace("$","").strip())
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(165, 42, "UF:")
    pdf.set_font("Arial", '', 9)
    pdf.text(175, 42, "39.841,72")
    
    pdf.set_font("Arial", 'B', 9)
    pdf.text(12, 49, "Cargo:")
    pdf.set_font("Arial", '', 9)
    pdf.text(25, 49, cargo_limpio)
    
    y_t = 60
    pdf.rect(10, y_t, 190, 115)
    pdf.line(105, y_t, 105, y_t + 115) 
    pdf.line(10, y_t + 7, 200, y_t + 7)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.text(45, y_t + 5, "HABERES")
    pdf.text(140, y_t + 5, "DESCUENTOS")
    
    pdf.set_font("Arial", '', 9)
    
    dias_trabajados = 30 - int(datos.get("Dias_Falta", 0))
    sueldo_prop = datos["Sueldo Base"] / 30 * dias_trabajados
    
    y_h = y_t + 13
    pdf.text(12, y_h, f"Días Trabajados: {dias_trabajados},00")
    pdf.text(45, y_h, "Sueldo:")
    right_text(pdf, 102, y_h, formato_clp(sueldo_prop).replace("$","").strip())
    
    y_h += 6
    pdf.text(12, y_h, "Horas : 0.0     50.00%")
    pdf.text(45, y_h, "Total Horas Extras:")
    right_text(pdf, 102, y_h, formato_clp(datos["Horas Extras"]).replace("$","").strip())
    
    y_h += 6
    pdf.text(45, y_h, "Gratificación:")
    right_text(pdf, 102, y_h, formato_clp(datos["Gratificacion"]).replace("$","").strip())
    
    y_h += 8
    pdf.line(10, y_h - 4, 105, y_h - 4) 
    pdf.set_font("Arial", 'B', 9)
    pdf.text(45, y_h, "Total Imponible:")
    right_text(pdf, 102, y_h, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    pdf.set_font("Arial", '', 9)
    
    y_h += 8
    pdf.text(12, y_h, "Cargas:")
    
    y_h += 6
    pdf.text(45, y_h, "Asignación Movilización:")
    right_text(pdf, 102, y_h, formato_clp(datos["Movilizacion"]).replace("$","").strip())
    
    y_h += 6
    pdf.text(45, y_h, "Asignación Colación:")
    right_text(pdf, 102, y_h, formato_clp(datos["Colacion"]).replace("$","").strip())
    
    y_h = y_t + 110
    pdf.line(10, y_h - 4, 105, y_h - 4)
    pdf.set_font("Arial", 'B', 9)
    pdf.text(45, y_h, "TOTAL HABERES:")
    right_text(pdf, 102, y_h, formato_clp(datos["Total Haberes"]).replace("$","").strip())
    pdf.set_font("Arial", '', 9)
    
    afp_nombre = datos["Nombre AFP"].split('(')[0].strip()
    afp_tasa = datos["Nombre AFP"].split('(')[1].replace(')', '').strip() if '(' in datos["Nombre AFP"] else ""
    
    y_d = y_t + 13
    pdf.text(107, y_d, f"AFP: {afp_nombre}")
    pdf.text(140, y_d, "Base AFP:")
    pdf.text(160, y_d, afp_tasa)
    right_text(pdf, 198, y_d, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_d += 6
    pdf.text(140, y_d, "Cotización AFP:")
    right_text(pdf, 198, y_d, formato_clp(datos["Dcto AFP"]).replace("$","").strip())
    
    y_d += 6
    pdf.text(107, y_d, "Isapre: Fonasa")
    
    y_d += 6
    pdf.text(107, y_d, "7% Obligatorio:")
    right_text(pdf, 198, y_d, formato_clp(datos["Dcto Fonasa"]).replace("$","").strip())
    
    y_d += 6
    pdf.text(107, y_d, "Cotización Pactado:")
    pdf.text(140, y_d, "0 UF")
    right_text(pdf, 198, y_d, formato_clp(datos["Dcto Fonasa"]).replace("$","").strip())
    
    y_d += 6
    if datos["Dcto Cesantia"] > 0:
        pdf.text(140, y_d, "Base AFC:")
        right_text(pdf, 198, y_d, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
        y_d += 6
        pdf.text(140, y_d, "Cotización AFC Trabajador:")
        right_text(pdf, 198, y_d, formato_clp(datos["Dcto Cesantia"]).replace("$","").strip())
        y_d += 6

    pdf.set_font("Arial", 'B', 9)
    pdf.text(140, y_d, "Total Previsión:")
    right_text(pdf, 198, y_d, formato_clp(datos["Descuentos Ley"]).replace("$","").strip())
    pdf.set_font("Arial", '', 9)
    
    y_d += 8
    pdf.text(107, y_d, "Días no Trabajador")
    y_d += 6
    pdf.text(107, y_d, "Licencia:")
    y_d += 6
    pdf.text(107, y_d, "Faltas:")
    pdf.text(125, y_d, str(int(datos.get("Dias_Falta", 0))))
    
    y_d += 6
    pdf.text(140, y_d, "Base Tributable:")
    base_trib = datos["Imponible Calculado"] - datos["Descuentos Ley"]
    if base_trib < 0: base_trib = 0
    right_text(pdf, 198, y_d, formato_clp(base_trib).replace("$","").strip())
    
    y_d = y_t + 110
    pdf.line(105, y_d - 4, 200, y_d - 4)
    pdf.set_font("Arial", 'B', 9)
    pdf.text(140, y_d, "TOTAL DESCUENTO")
    right_text(pdf, 198, y_d, formato_clp(datos["Descuentos Ley"]).replace("$","").strip())
    
    y_bottom = max(y_h, y_d) + 5
    pdf.line(10, y_bottom, 200, y_bottom)
    
    y_alcance = y_bottom + 6
    pdf.text(107, y_alcance, "ALCANCE LIQUIDO")
    right_text(pdf, 195, y_alcance, formato_clp(datos["Líquido a Pagar"]).replace("$","").strip())
    
    y_alcance += 8
    pdf.text(107, y_alcance, "TOTAL A PAGAR")
    right_text(pdf, 195, y_alcance, formato_clp(datos["Líquido a Pagar"]).replace("$","").strip())
    
    pdf.line(10, y_alcance + 4, 200, y_alcance + 4)
    
    y_palabras = y_alcance + 12
    pdf.set_font("Arial", '', 9)
    texto_son = num2words(int(datos['Líquido a Pagar'])).upper()
    pdf.text(10, y_palabras, f"SON: {texto_son} PESOS")
    
    y_palabras += 10
    pdf.text(10, y_palabras, "Certifico que he recibido conforme y no tengo cargos ni cobro alguno posterior que hacer, por ninguno de los")
    pdf.text(10, y_palabras + 4, "conceptos comprometidos en ella.")
    
    y_firmas = y_palabras + 25
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y_firmas, "FIRMA TRABAJADOR")
    
    y_final = y_firmas + 10
    pdf.set_font("Arial", '', 8)
    pdf.text(10, y_final, "La presente liquidación se emite en 2 copias quedando una en poder del trabajador y otra en poder del empleador.")
    
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
if 'menu_actual' not in st.session_state: st.session_state.menu_actual = "Finanzas"

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

b1, b2, b3, b4, b5, b6 = st.columns(6)

if b1.button("💼 Finanzas", type="primary" if st.session_state.menu_actual == "Finanzas" else "secondary", use_container_width=True): st.session_state.menu_actual = "Finanzas"; st.rerun()
if b2.button("📝 Presup.", type="primary" if st.session_state.menu_actual == "Presupuestos" else "secondary", use_container_width=True): st.session_state.menu_actual = "Presupuestos"; st.rerun()
if b3.button("🏗️ Proyectos", type="primary" if st.session_state.menu_actual == "Proyectos" else "secondary", use_container_width=True): st.session_state.menu_actual = "Proyectos"; st.rerun()
if b4.button("⏱️ Operaciones", type="primary" if st.session_state.menu_actual == "Operaciones" else "secondary", use_container_width=True): st.session_state.menu_actual = "Operaciones"; st.rerun()
if b5.button("📦 Inventario", type="primary" if st.session_state.menu_actual == "Inventario" else "secondary", use_container_width=True): st.session_state.menu_actual = "Inventario"; st.rerun()
if b6.button("📊 Balance", type="primary" if st.session_state.menu_actual == "Balance" else "secondary", use_container_width=True): st.session_state.menu_actual = "Balance"; st.rerun()

st.divider()

# ==========================================
# PANTALLA 1: FINANZAS Y NÓMINA
# ==========================================
if st.session_state.menu_actual == "Finanzas":
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
            
        tab_nomina, tab_fijos, tab_facturas = st.tabs(["👥 Nómina y Liquidaciones", "🏢 Gastos Fijos Operativos", "🧾 Emisión de Facturas"])
        
        with tab_nomina:
            with st.container(border=True):
                st.subheader("Control de Asistencia y Nómina")
                if st.session_state.acceso_finanzas == "admin":
                    with st.expander("➕ Ingresar Nuevo Trabajador", expanded=False):
                        # --- NUEVO: Formulario con campo RUT visible al ingresar ---
                        colRUT, colA, colB = st.columns([1, 2, 2])
                        n_rut = colRUT.text_input("RUT (Ej: 12.345.678-9)")
                        n_trabajador = colA.text_input("Nombre Completo")
                        n_cargo = colB.text_input("Cargo")
                        
                        if 'input_sueldo_base' not in st.session_state: st.session_state['input_sueldo_base'] = "0"
                        colC, colD, colE = st.columns([2, 1, 2])
                        colC.text_input("Sueldo Base Mensual", key="input_sueldo_base", on_change=formatear_input, kwargs={'llave': 'input_sueldo_base'})
                        n_sueldo = float(st.session_state['input_sueldo_base'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        n_jornada = colD.number_input("Hrs Semanales", value=44, max_value=45)
                        n_grati = colE.selectbox("Tipo de Gratificación", ["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"])
                        
                        colF, colG = st.columns(2)
                        n_contrato = colF.selectbox("Tipo de Contrato", ["Indefinido", "Plazo Fijo"])
                        n_afp = colG.selectbox("Seleccione AFP", list(TASAS_AFP.keys()))
                        
                        colH, colI = st.columns(2)
                        if 'input_colacion' not in st.session_state: st.session_state['input_colacion'] = "0"
                        if 'input_movilizacion' not in st.session_state: st.session_state['input_movilizacion'] = "0"
                        colH.text_input("Bono Colación (Opcional)", key="input_colacion", on_change=formatear_input, kwargs={'llave': 'input_colacion'})
                        n_cola = float(st.session_state['input_colacion'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        colI.text_input("Bono Movilización (Opcional)", key="input_movilizacion", on_change=formatear_input, kwargs={'llave': 'input_movilizacion'})
                        n_movi = float(st.session_state['input_movilizacion'].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        
                        if st.button("Guardar Perfil"):
                            if n_trabajador and n_rut:
                                nuevo_perfil = pd.DataFrame([{
                                    "RUT": n_rut, "Trabajador": n_trabajador, "Cargo": n_cargo, "Sueldo_Base": n_sueldo, 
                                    "Jornada_Hrs": n_jornada, "Tipo_Contrato": n_contrato, "Gratificacion": n_grati, 
                                    "AFP": n_afp, "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, 
                                    "Colacion": n_cola, "Movilizacion": n_movi
                                }])
                                st.session_state.nomina = pd.concat([st.session_state.nomina, nuevo_perfil], ignore_index=True)
                                guardar_datos("Nomina_Personal", st.session_state.nomina)
                                st.success("Trabajador registrado exitosamente.")
                                st.rerun()
                            else:
                                st.error("El RUT y el Nombre son obligatorios.")

                    st.caption("Modifique datos interactivos directamente en la tabla:")
                    df_nomina_edit = st.data_editor(
                        st.session_state.nomina,
                        column_config={
                            "RUT": None, # <--- ESTA ES LA MAGIA: El RUT existe pero es 100% invisible en la tabla.
                            "Sueldo_Base": st.column_config.NumberColumn("Sueldo Base", min_value=0, format="%,d"),
                            "Colacion": st.column_config.NumberColumn("Colación", min_value=0, format="%,d"),
                            "Movilizacion": st.column_config.NumberColumn("Movilización", min_value=0, format="%,d"),
                            "Tipo_Contrato": st.column_config.SelectboxColumn("Contrato", options=["Indefinido", "Plazo Fijo"]),
                            "Gratificacion": st.column_config.SelectboxColumn("Gratificación", options=["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"]),
                            "AFP": st.column_config.SelectboxColumn("AFP", options=list(TASAS_AFP.keys())),
                        },
                        num_rows="dynamic", use_container_width=True, key="ed_nomina"
                    )
                    if st.button("💾 Guardar Cambios de Nómina", type="primary"):
                        st.session_state.nomina = df_nomina_edit
                        guardar_datos("Nomina_Personal", st.session_state.nomina)
                        st.success("Nómina actualizada.")
                else:
                    # En modo lectura, aseguramos también ocultar el RUT para seguridad
                    st.dataframe(st.session_state.nomina.drop(columns=["RUT"], errors='ignore'), use_container_width=True)

            with st.container(border=True):
                st.subheader("Proyección de Liquidaciones")
                df_liquidaciones, total_nomina_empresa = calcular_liquidaciones(st.session_state.nomina)
                
                # Vista resumen (sin mostrar RUT)
                df_liq_visual = df_liquidaciones[["Trabajador", "Cargo", "Contrato", "Imponible Calculado", "Haberes No Imponibles", "Descuentos Ley", "Líquido a Pagar", "Costo Empresa"]].copy()
                for col in ["Imponible Calculado", "Haberes No Imponibles", "Descuentos Ley", "Líquido a Pagar", "Costo Empresa"]:
                    df_liq_visual[col] = df_liq_visual[col].apply(formato_clp)
                    
                st.dataframe(df_liq_visual, use_container_width=True)
                st.info(f"**Costo Total Proyectado de Nómina:** {formato_clp(total_nomina_empresa)}")
                
                st.divider()
                st.markdown("#### 📄 Emisión de Liquidaciones Oficiales (PDF)")
                if FPDF_DISPONIBLE:
                    trab_lista = df_liquidaciones['Trabajador'].tolist()
                    if trab_lista:
                        col_sel, col_btn = st.columns([3, 1], vertical_alignment="bottom")
                        trab_seleccionado = col_sel.selectbox("Seleccione un trabajador:", trab_lista)
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
                    res_fijos = st.data_editor(st.session_state.gastos_fijos, num_rows="dynamic", use_container_width=True)
                    if st.button("💾 Guardar Cambios Fijos", type="primary"):
                        st.session_state.gastos_fijos = res_fijos
                        guardar_datos("Gastos_Fijos", res_fijos)
                        st.success("Gastos fijos actualizados.")
                else:
                    st.dataframe(st.session_state.gastos_fijos, use_container_width=True)

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
            aprobacion_pres = colP5.selectbox("Estado de Aprobación:", ["Pendiente", "Aprobada", "No Aprobada"])
            orden_pres = colP6.selectbox("Respaldo de Orden:", ["Sin Orden", "Con Orden"])
            num_oc_pres = colP7.text_input("N° OC (Si aplica):", placeholder="Ej: OC-1234")
            if not num_oc_pres: num_oc_pres = "N/A"
            
            if st.button("Guardar Presupuesto", type="primary"):
                if ref_pres and cliente_pres and monto_pres > 0:
                    str_fecha = fecha_pres.strftime('%Y-%m-%d') if fecha_pres else ""
                    nuevo_presupuesto = pd.DataFrame([{
                        "Tipo": tipo_pres, "Referencia": ref_pres, "Cliente": cliente_pres,
                        "Monto": monto_pres, "Aprobacion": aprobacion_pres, "Orden_Compra": orden_pres,
                        "Num_OC": num_oc_pres, "Estado_Comercial": "Presupuestada", "Fecha_Emision": str_fecha
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
            opciones_estado = ["Presupuestada", "Adjudicada", "En progreso", "Entregada", "Pagada"]
            opciones_aprobacion = ["Pendiente", "Aprobada", "No Aprobada"]
            opciones_orden = ["Sin Orden", "Con Orden"]
            
            df_pres_edit = st.data_editor(
                st.session_state.presupuestos,
                column_config={
                    "Monto": st.column_config.NumberColumn("Monto Total", format="%,d"),
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
                            nuevo_gasto = pd.DataFrame([{"Proyecto": nombre_p, "Detalle_Gasto": "Materiales iniciales", "Monto": 0}])
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
                        df_gastos_editados = st.data_editor(df_gastos_proy[["Detalle_Gasto", "Monto"]], num_rows="dynamic", use_container_width=True)
                    else:
                        df_gastos_editados = df_gastos_proy[["Detalle_Gasto", "Monto"]]
                        st.dataframe(df_gastos_editados, use_container_width=True)

            if st.session_state.acceso_proyectos == "admin":
                with st.container(border=True):
                    with st.expander("💸 Asignar Personal y Cargar al Gasto (Vínculo a Operaciones)", expanded=False):
                        st.info("💡 Al asignarle presupuesto a un trabajador aquí, lo autorizas automáticamente para ser parte del equipo en la pestaña de 'Operaciones'.")
                        df_liq, _ = calcular_liquidaciones(st.session_state.nomina)
                        trabajadores = ["Seleccione..."] + df_liq["Trabajador"].tolist()
                        colT1, colT2, colT3 = st.columns([2, 1, 1])
                        trabajador_sel = colT1.selectbox("Trabajador", trabajadores)
                        if trabajador_sel != "Seleccione...":
                            costo_emp_trab = df_liq[df_liq["Trabajador"] == trabajador_sel]["Costo Empresa"].values[0]
                            colT2.info(f"Costo Mensual: \n**{formato_clp(costo_emp_trab)}**")
                            llave_costo = "costo_asignado"
                            if llave_costo not in st.session_state: st.session_state[llave_costo] = "0"
                            colT3.text_input("A imputar al proyecto:", key=llave_costo, on_change=formatear_input, kwargs={'llave': llave_costo})
                            monto_asig = float(st.session_state[llave_costo].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                            if st.button("Añadir al Gasto", type="secondary") and monto_asig > 0:
                                nuevo_gasto_trab = pd.DataFrame([{"Proyecto": proyecto_seleccionado, "Detalle_Gasto": f"Mano de obra: {trabajador_sel}", "Monto": monto_asig}])
                                st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto_trab], ignore_index=True)
                                guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                                st.session_state[llave_costo] = "0"
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
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.success("Guardado correctamente.")
                with col_del:
                    if st.button("🗑️ Eliminar Proyecto Completo", use_container_width=True):
                        st.session_state.proyectos_resumen = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] != proyecto_seleccionado]
                        st.session_state.proyectos_gastos = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] != proyecto_seleccionado]
                        if 'proyectos_equipo' in st.session_state:
                            st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[st.session_state.proyectos_equipo["Proyecto"] != proyecto_seleccionado]
                            guardar_datos("Proyectos_Equipo", st.session_state.proyectos_equipo)
                        if 'proyectos_tareas' in st.session_state:
                            st.session_state.proyectos_tareas = st.session_state.proyectos_tareas[st.session_state.proyectos_tareas["Proyecto"] != proyecto_seleccionado]
                            guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                        guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                        st.rerun()

# ==========================================
# PANTALLA 4: SEGUIMIENTO OPERATIVO
# ==========================================
elif st.session_state.menu_actual == "Operaciones":
    st.markdown("### ⏱️ Gestión Operativa del Proyecto")
    proyectos_lista_seg = st.session_state.proyectos_resumen["Proyecto"].tolist()
    if not proyectos_lista_seg:
        with st.container(border=True):
            st.warning("No hay proyectos creados. Ve a la pestaña 'Proyectos' para crear tu primera obra.")
    else:
        proyecto_seg = st.selectbox("Selecciona un Proyecto a gestionar:", proyectos_lista_seg)
        idx_p_seg = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_seg].index[0]
        
        with st.container(border=True):
            st.markdown("#### 1️⃣ Cronograma General del Proyecto")
            colF1, colF2, colF3 = st.columns(3)
            val_ini = st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Inicio_Proy"]
            val_fin = st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Termino_Proy"]
            val_dur = st.session_state.proyectos_resumen.at[idx_p_seg, "Duracion_Proy"]
            
            def parse_fecha(f_str):
                try:
                    if pd.isna(f_str) or str(f_str).strip() in ["", "Pendiente"]: 
                        return None
                    return pd.to_datetime(str(f_str)).date()
                except:
                    return None
            
            nuevo_ini = colF1.date_input("Fecha de Inicio:", value=parse_fecha(val_ini), format="DD/MM/YYYY")
            nuevo_fin = colF2.date_input("Fecha de Término:", value=parse_fecha(val_fin), format="DD/MM/YYYY")
            
            nueva_dur = colF3.text_input("Duración Estimada:", value="" if val_dur=="Pendiente" else val_dur, placeholder="Ej: 3 meses")
            if st.button("Guardar Fechas del Proyecto"):
                str_ini = nuevo_ini.strftime('%Y-%m-%d') if nuevo_ini else "Pendiente"
                str_fin = nuevo_fin.strftime('%Y-%m-%d') if nuevo_fin else "Pendiente"
                
                st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Inicio_Proy"] = str_ini
                st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Termino_Proy"] = str_fin
                st.session_state.proyectos_resumen.at[idx_p_seg, "Duracion_Proy"] = nueva_dur if nueva_dur else "Pendiente"
                guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                st.success("Cronograma actualizado.")
                
        with st.container(border=True):
            st.markdown("#### 2️⃣ Conformación del Equipo y Liderazgo")
            gastos_proy_seg = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seg]
            trabajadores_financiados = []
            for detalle in gastos_proy_seg["Detalle_Gasto"]:
                if str(detalle).startswith("Mano de obra: "):
                    nombre = str(detalle).replace("Mano de obra: ", "").strip()
                    if nombre not in trabajadores_financiados: trabajadores_financiados.append(nombre)
                        
            if not trabajadores_financiados:
                st.warning("⚠️ No has asignado presupuesto de personal a este proyecto.")
            else:
                equipo_actual = st.session_state.proyectos_equipo[st.session_state.proyectos_equipo["Proyecto"] == proyecto_seg]
                trabajadores_en_equipo = equipo_actual["Trabajador"].tolist()
                cambios_sync = False
                for trab in trabajadores_financiados:
                    if trab not in trabajadores_en_equipo:
                        nuevo_eq = pd.DataFrame([{"Proyecto": proyecto_seg, "Trabajador": trab, "Rol_Proyecto": "Por definir"}])
                        st.session_state.proyectos_equipo = pd.concat([st.session_state.proyectos_equipo, nuevo_eq], ignore_index=True)
                        cambios_sync = True
                mask_validos = st.session_state.proyectos_equipo["Trabajador"].isin(trabajadores_financiados) | (st.session_state.proyectos_equipo["Proyecto"] != proyecto_seg)
                if not mask_validos.all():
                    st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[mask_validos]
                    cambios_sync = True
                if cambios_sync: guardar_datos("Proyectos_Equipo", st.session_state.proyectos_equipo)
                
                mask_eq = st.session_state.proyectos_equipo["Proyecto"] == proyecto_seg
                df_eq_editar = st.session_state.proyectos_equipo[mask_eq]
                df_eq_mod = st.data_editor(
                    df_eq_editar,
                    column_config={"Rol_Proyecto": st.column_config.SelectboxColumn("Rol Operativo", options=["Por definir", "Líder de Proyecto", "Supervisor", "Técnico Especialista", "Operario", "Prevencionista"], required=True)},
                    disabled=["Proyecto", "Trabajador"], hide_index=True, use_container_width=True, key=f"ed_eq_{proyecto_seg}"
                )
                if st.button("💾 Guardar Roles del Equipo", type="primary"):
                    st.session_state.proyectos_equipo = st.session_state.proyectos_equipo[~mask_eq]
                    st.session_state.proyectos_equipo = pd.concat([st.session_state.proyectos_equipo, df_eq_mod], ignore_index=True)
                    guardar_datos("Proyectos_Equipo", st.session_state.proyectos_equipo)
                    st.success("Roles del equipo actualizados.")

        with st.container(border=True):
            st.markdown("#### 3️⃣ Asignación de Tareas Específicas")
            if not trabajadores_financiados:
                st.info("El equipo debe estar conformado para asignar tareas.")
            else:
                with st.expander("➕ Añadir Nueva Tarea", expanded=False):
                    colT1, colT2 = st.columns([1, 2])
                    encargado_tarea = colT1.selectbox("Asignar a:", trabajadores_financiados)
                    desc_tarea = colT2.text_input("Descripción de la Tarea:", placeholder="Ej: Instalar tablero eléctrico principal")
                    if st.button("Crear Tarea"):
                        if desc_tarea:
                            nueva_tarea = pd.DataFrame([{"Proyecto": proyecto_seg, "Trabajador": encargado_tarea, "Tarea": desc_tarea, "Estado": "Pendiente"}])
                            st.session_state.proyectos_tareas = pd.concat([st.session_state.proyectos_tareas, nueva_tarea], ignore_index=True)
                            guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                            st.success("Tarea asignada.")
                            st.rerun()
                        else: st.error("Escribe una descripción para la tarea.")

                mask_tareas = st.session_state.proyectos_tareas["Proyecto"] == proyecto_seg
                df_tareas_filtradas = st.session_state.proyectos_tareas[mask_tareas].copy()
                if df_tareas_filtradas.empty:
                    st.info("No hay tareas registradas para este equipo.")
                else:
                    df_tareas_editadas = st.data_editor(
                        df_tareas_filtradas,
                        column_config={"Estado": st.column_config.SelectboxColumn("Estado", options=["Pendiente", "En proceso", "Terminada"])},
                        disabled=["Proyecto", "Trabajador", "Tarea"], hide_index=True, use_container_width=True, key=f"ed_tar_{proyecto_seg}"
                    )
                    if st.button("💾 Guardar Progreso de Tareas", type="primary"):
                        st.session_state.proyectos_tareas = st.session_state.proyectos_tareas[~mask_tareas]
                        st.session_state.proyectos_tareas = pd.concat([st.session_state.proyectos_tareas, df_tareas_editadas], ignore_index=True)
                        guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                        st.success("Estados actualizados.")
                    with st.expander("🗑️ Eliminar una Tarea"):
                        lista_nombres_tareas = df_tareas_filtradas["Tarea"].tolist()
                        if lista_nombres_tareas:
                            tarea_a_eliminar = st.selectbox("Selecciona la tarea a eliminar:", lista_nombres_tareas)
                            if st.button("Eliminar Tarea Seleccionada"):
                                mask_eliminar = (st.session_state.proyectos_tareas["Proyecto"] == proyecto_seg) & (st.session_state.proyectos_tareas["Tarea"] == tarea_a_eliminar)
                                st.session_state.proyectos_tareas = st.session_state.proyectos_tareas[~mask_eliminar]
                                guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                                st.success("Tarea eliminada.")
                                st.rerun()

elif st.session_state.menu_actual == "Inventario":
    st.markdown("### 📦 Control de Inventario y Activos")
    with st.container(border=True):
        st.markdown("#### 🔍 Buscador Rápido")
        busqueda = st.text_input("Ingresa el Número de Serie o Nombre del Artículo para localizarlo rápidamente:", placeholder="Ej: VLT- o Taladro")
        if busqueda:
            mask = st.session_state.inventario["Nro_Serie"].astype(str).str.contains(busqueda, case=False, na=False) | st.session_state.inventario["Artículo"].astype(str).str.contains(busqueda, case=False, na=False)
            resultados = st.session_state.inventario[mask]
            if resultados.empty: st.warning("No se encontraron artículos con ese dato en la base de datos.")
            else:
                st.success(f"Se encontraron {len(resultados)} coincidencias:")
                st.dataframe(resultados, use_container_width=True)

    with st.container(border=True):
        with st.expander("➕ Añadir Nuevo Artículo al Inventario", expanded=False):
            colI1, colI2 = st.columns([3, 1])
            nuevo_art = colI1.text_input("Nombre del Artículo / Herramienta:")
            nueva_cant = colI2.number_input("Cantidad:", min_value=1, step=1)
            if st.button("Guardar en Inventario", type="primary"):
                if nuevo_art:
                    nuevo_serie = f"VLT-{uuid.uuid4().hex[:6].upper()}"
                    nuevo_item = pd.DataFrame([{"Artículo": nuevo_art, "Cantidad": nueva_cant, "Nro_Serie": nuevo_serie, "Estado": "Disponible"}])
                    st.session_state.inventario = pd.concat([st.session_state.inventario, nuevo_item], ignore_index=True)
                    guardar_datos("Inventario", st.session_state.inventario)
                    st.success(f"✅ Artículo añadido con éxito. **N° de Serie: {nuevo_serie}**")
                    st.rerun()
                else: st.error("Por favor completa el nombre del artículo.")
                    
    with st.container(border=True):
        st.markdown("#### 🖨️ Generador de Etiquetas de Código")
        if st.session_state.inventario.empty: st.info("Agrega artículos al inventario para imprimir sus etiquetas.")
        else:
            lista_etiquetas = [f"{row['Artículo']} (SN: {row['Nro_Serie']})" for i, row in st.session_state.inventario.iterrows()]
            item_seleccionado = st.selectbox("Selecciona el artículo para imprimir su etiqueta:", lista_etiquetas)
            if item_seleccionado:
                idx_str = lista_etiquetas.index(item_seleccionado)
                serie_a_imprimir = st.session_state.inventario.at[idx_str, 'Nro_Serie']
                if FPDF_DISPONIBLE:
                    pdf_etiqueta = generar_etiqueta_pdf(serie_a_imprimir)
                    st.download_button(
                        label=f"⬇️ Descargar Etiqueta ({serie_a_imprimir})",
                        data=pdf_etiqueta, file_name=f"Etiqueta_{serie_a_imprimir}.pdf",
                        mime="application/pdf", type="primary"
                    )
                else: st.error("⚠️ La librería FPDF no está instalada.")

    with st.container(border=True):
        st.markdown("#### 📋 Base de Datos de Inventario General")
        if st.session_state.inventario.empty: st.info("El inventario está actualmente vacío.")
        else:
            df_inv_edit = st.data_editor(
                st.session_state.inventario,
                column_config={
                    "Cantidad": st.column_config.NumberColumn("Cantidad", min_value=0),
                    "Estado": st.column_config.SelectboxColumn("Estado", options=["Disponible", "En Uso", "En Reparación", "Extraviado"]),
                    "Nro_Serie": st.column_config.TextColumn("N° de Serie (Automático)")
                },
                disabled=["Artículo", "Nro_Serie"], hide_index=True, use_container_width=True, key="ed_inv"
            )
            if st.button("💾 Guardar Cambios de Inventario", type="primary"):
                st.session_state.inventario = df_inv_edit
                guardar_datos("Inventario", st.session_state.inventario)
                st.success("Inventario actualizado correctamente.")
            with st.expander("🗑️ Dar de Baja / Eliminar Artículo"):
                lista_articulos = [f"{row['Artículo']} (SN: {row['Nro_Serie']})" for i, row in st.session_state.inventario.iterrows()]
                if lista_articulos:
                    art_a_borrar = st.selectbox("Selecciona el artículo a eliminar:", lista_articulos)
                    if st.button("Eliminar Definitivamente"):
                        idx_borrar = lista_articulos.index(art_a_borrar)
                        st.session_state.inventario = st.session_state.inventario.drop(st.session_state.inventario.index[idx_borrar]).reset_index(drop=True)
                        guardar_datos("Inventario", st.session_state.inventario)
                        st.success("Artículo dado de baja.")
                        st.rerun()

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
