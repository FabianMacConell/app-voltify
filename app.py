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
        "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, "Colacion": 0, "Movilizacion": 0, "Anticipo": 0
    }])
    st.session_state.nomina = cargar_datos("Nomina_Personal", df_nomina_base)

columnas_obligatorias = ["Dias_Falta", "Horas_Atraso", "Horas_Extras", "Colacion", "Movilizacion", "Anticipo"]
for col in columnas_obligatorias:
    if col not in st.session_state.nomina.columns:
        st.session_state.nomina[col] = 0

if 'RUT' not in st.session_state.nomina.columns:
    st.session_state.nomina['RUT'] = "Sin Registro"

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
    df_tareas_base = pd.DataFrame(columns=["Proyecto", "Trabajador", "Tarea", "Estado", "Fecha_Inicio", "Fecha_Termino"])
    st.session_state.proyectos_tareas = cargar_datos("Proyectos_Tareas", df_tareas_base)

if 'Fecha_Inicio' not in st.session_state.proyectos_tareas.columns:
    st.session_state.proyectos_tareas['Fecha_Inicio'] = datetime.date.today().strftime('%Y-%m-%d')
if 'Fecha_Termino' not in st.session_state.proyectos_tareas.columns:
    st.session_state.proyectos_tareas['Fecha_Termino'] = datetime.date.today().strftime('%Y-%m-%d')

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
        try: sueldo_base = float(row.get('Sueldo_Base', 0))
        except: sueldo_base = 0.0
        try: jornada = float(row.get('Jornada_Hrs', 44))
        except: jornada = 44.0
        
        dias_falta = float(row.get('Dias_Falta', 0))
        horas_atraso = float(row.get('Horas_Atraso', 0))
        horas_extras_qty = float(row.get('Horas_Extras', 0))
        anticipo = float(row.get('Anticipo', 0))
        
        valor_dia = sueldo_base / 30 if sueldo_base > 0 else 0
        valor_hora_normal = (sueldo_base / 30) * 28 / jornada if jornada > 0 else 0
        valor_hora_extra = valor_hora_normal * 1.5
        
        tipo_grati = str(row.get('Gratificacion', 'Sin Gratificación'))
        if tipo_grati == "Tope Legal Mensual": grati_monto = min(sueldo_base * 0.25, 197917)
        elif tipo_grati == "25% del Sueldo (Sin Tope)": grati_monto = sueldo_base * 0.25
        else: grati_monto = 0
            
        pago_extras = horas_extras_qty * valor_hora_extra
        dcto_faltas = dias_falta * valor_dia
        dcto_atrasos = horas_atraso * valor_hora_normal
        
        sueldo_imponible = sueldo_base + grati_monto + pago_extras - dcto_faltas - dcto_atrasos
        if sueldo_imponible < 0: sueldo_imponible = 0
        
        dcto_afp = sueldo_imponible * TASAS_AFP.get(row.get('AFP', 'Habitat (11.27%)'), 0.1144)
        dcto_fonasa = sueldo_imponible * 0.07
        
        tipo_contrato = str(row.get('Tipo_Contrato', 'Indefinido'))
        dcto_cesantia = sueldo_imponible * 0.006 if tipo_contrato == "Indefinido" else 0.0
        
        colacion = float(row.get('Colacion', 0))
        movilizacion = float(row.get('Movilizacion', 0))
        no_imponibles = colacion + movilizacion
        
        total_prevision = dcto_afp + dcto_fonasa + dcto_cesantia
        total_descuentos = total_prevision + anticipo 
        
        alcance_liquido = sueldo_imponible - total_prevision + no_imponibles
        total_a_pagar = alcance_liquido - anticipo
        
        costo_real_empresa = sueldo_imponible + no_imponibles
        costo_empresa_total += costo_real_empresa
        
        resultados.append({
            "RUT": str(row.get('RUT', 'Sin Registro')),
            "Trabajador": row['Trabajador'], "Cargo": row['Cargo'], "Contrato": tipo_contrato,
            "Sueldo Base": sueldo_base, "Sueldo Proporcional": sueldo_base - dcto_faltas - dcto_atrasos,
            "Horas Extras Monto": pago_extras, "Horas Extras Qty": horas_extras_qty,
            "Gratificacion": grati_monto,
            "Colacion": colacion, "Movilizacion": movilizacion, 
            "Nombre AFP": row.get('AFP', 'Habitat (11.27%)'), "Dcto AFP": dcto_afp,
            "Dcto Fonasa": dcto_fonasa, "Dcto Cesantia": dcto_cesantia,
            "Imponible Calculado": sueldo_imponible, "Haberes No Imponibles": no_imponibles, 
            "Total Haberes": sueldo_imponible + no_imponibles,
            "Total Prevision": total_prevision,
            "Anticipo": anticipo,
            "Total Descuentos": total_descuentos, 
            "Alcance Liquido": alcance_liquido,
            "Total a Pagar": total_a_pagar,
            "Costo Empresa": costo_real_empresa,
            "Dias_Falta": dias_falta,
            "Horas_Atraso": horas_atraso,
            "Dcto_Atraso_Monto": dcto_atrasos
        })
    return pd.DataFrame(resultados), costo_empresa_total

def num2words(n):
    if n <= 0: return "CERO"
    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIUN", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    centenas = ["", "CIEN", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    if n < 30: return unidades[n]
    if n < 100: return decenas[n // 10] + (" Y " + unidades[n % 10] if n % 10 != 0 else "")
    if n < 1000:
        if n == 100: return "CIEN"
        return (centenas[n // 100] if n // 100 != 1 else "CIENTO") + (" " + num2words(n % 100) if n % 100 != 0 else "")
    if n < 2000: return "MIL" + (" " + num2words(n % 1000) if n % 1000 != 0 else "")
    if n < 1000000: return num2words(n // 1000) + " MIL" + (" " + num2words(n % 1000) if n % 1000 != 0 else "")
    if n == 1000000: return "UN MILLON"
    if n < 2000000: return "UN MILLON " + num2words(n % 1000000)
    return num2words(n // 1000000) + " MILLONES " + num2words(n % 1000000)

def right_text(pdf, x, y, text):
    width = pdf.get_string_width(text)
    pdf.text(x - width, y, text)


# ==========================================
# MOTOR PDF: LITERAR DEL DOCUMENTO WORD (¡BLOQUEADO - NO MODIFICAR!)
# ==========================================
def generar_pdf_liquidacion(datos):
    pdf = FPDF(unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    # 1. ENCABEZADO
    pdf.set_font("Arial", 'B', 10)
    pdf.text(10, 15, "VOLTIFY SPA")
    pdf.set_font("Arial", '', 9)
    pdf.text(10, 20, "RUT : 77.871.702-6")
    pdf.text(10, 25, "JAVIERA CARRERA #1150 ARICA")
    pdf.text(10, 30, "Teléfono Cel 995635899")
    
    pdf.set_font("Arial", 'B', 12)
    pdf.text(70, 40, "Liquidación de Sueldo Mensual")
    
    # 2. BLOQUE DE INFORMACIÓN DEL TRABAJADOR
    y = 50
    trabajador_limpio = str(datos['Trabajador']).encode('latin-1', 'replace').decode('latin-1').upper()
    cargo_limpio = str(datos['Cargo']).encode('latin-1', 'replace').decode('latin-1').upper()
    rut_trabajador = datos.get("RUT", "Sin Registro")
    
    meses_str = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes_actual = meses_str[datetime.datetime.now().month - 1]
    anio_actual = datetime.datetime.now().year

    pdf.set_font("Arial", '', 9)
    pdf.text(10, y, "RUT:")
    pdf.text(25, y, rut_trabajador)
    
    pdf.text(60, y, "Nombre:")
    pdf.text(75, y, trabajador_limpio)
    
    pdf.text(145, y, "Fecha Contrato :")
    pdf.text(172, y, "16/03/2026")
    
    y += 6
    pdf.text(10, y, "Año:")
    pdf.text(20, y, str(anio_actual))
    
    pdf.text(35, y, "Mes:")
    pdf.text(45, y, mes_actual)
    
    pdf.text(65, y, "CC:")
    pdf.text(75, y, "OPERACIONES")
    
    pdf.text(110, y, "Sueldo Base:")
    pdf.text(130, y, formato_clp(datos["Sueldo Base"]).replace("$","").strip())
    
    pdf.text(155, y, "UF:")
    pdf.text(165, y, "39.841,72")
    
    y += 6
    pdf.text(10, y, "Cargo:")
    pdf.text(25, y, cargo_limpio)

    # 3. TÍTULOS DE COLUMNAS
    y += 10
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y, "HABERES")
    pdf.text(110, y, "DESCUENTOS")

    y += 6
    pdf.set_font("Arial", '', 9)
    y_start_cols = y

    # --- COLUMNA IZQUIERDA ---
    y_l = y_start_cols
    dias_trabajados = 30 - int(datos.get("Dias_Falta", 0))
    pdf.text(10, y_l, f"Días Trabajados: {dias_trabajados},00")
    
    y_l += 6
    pdf.text(10, y_l, "Sueldo:")
    right_text(pdf, 95, y_l, formato_clp(datos["Sueldo Proporcional"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(10, y_l, f"Horas : {datos['Horas Extras Qty']}     50.00%")
    y_l += 6
    pdf.text(10, y_l, "Total Horas Extras:")
    right_text(pdf, 95, y_l, formato_clp(datos["Horas Extras Monto"]).replace("$","").strip())
    
    y_l += 24 
    pdf.text(10, y_l, "Gratificación")
    right_text(pdf, 95, y_l, formato_clp(datos["Gratificacion"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(10, y_l, "Total Imponible:")
    right_text(pdf, 95, y_l, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(10, y_l, "Cargas:")
    
    y_l += 6
    pdf.text(35, y_l, "Asignación Movilización:")
    right_text(pdf, 95, y_l, formato_clp(datos["Movilizacion"]).replace("$","").strip())
    
    y_l += 6
    pdf.text(35, y_l, "Asignación Colación:")
    right_text(pdf, 95, y_l, formato_clp(datos["Colacion"]).replace("$","").strip())
    
    y_l += 10
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y_l, "TOTAL HABERES:")
    right_text(pdf, 95, y_l, formato_clp(datos["Total Haberes"]).replace("$","").strip())
    pdf.set_font("Arial", '', 9)

    # --- COLUMNA DERECHA ---
    y_r = y_start_cols
    afp_nombre = datos["Nombre AFP"].split('(')[0].strip().upper()
    afp_tasa = datos["Nombre AFP"].split('(')[1].replace(')', '').strip() if '(' in datos["Nombre AFP"] else ""
    
    pdf.text(110, y_r, f"AFP:   {afp_nombre}")
    pdf.text(160, y_r, f"{afp_tasa}")
    
    y_r += 6
    pdf.text(130, y_r, "Base AFP:")
    right_text(pdf, 195, y_r, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(130, y_r, "Cotización AFP:")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto AFP"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(110, y_r, "Isapre:   Fonasa")
    
    y_r += 6
    pdf.text(110, y_r, "7% Obligatorio:")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto Fonasa"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(110, y_r, "Cotización Pactado:")
    pdf.text(145, y_r, "0 UF")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto Fonasa"]).replace("$","").strip()) 
    
    y_r += 6
    pdf.text(130, y_r, "Base AFC:")
    right_text(pdf, 195, y_r, formato_clp(datos["Imponible Calculado"]).replace("$","").strip())
    
    y_r += 6
    pdf.text(130, y_r, "Cotización AFC Trabajador:")
    right_text(pdf, 195, y_r, formato_clp(datos["Dcto Cesantia"]).replace("$","").strip() if datos["Dcto Cesantia"] > 0 else "")
    
    y_r += 6
    pdf.text(130, y_r, "Total Previsión:")
    right_text(pdf, 195, y_r, formato_clp(datos["Total Prevision"]).replace("$","").strip())
    
    y_r += 6
    if datos["Horas_Atraso"] > 0:
        pdf.text(110, y_r, f"Atraso ( {datos['Horas_Atraso']} Horas )")
        right_text(pdf, 160, y_r, f"(-{int(datos['Dcto_Atraso_Monto'])})")
        
    pdf.text(165, y_r, "Días no Trabajados")
    y_r += 4
    pdf.text(165, y_r, "Vacación:")
    y_r += 4
    pdf.text(165, y_r, "Licencia:")
    y_r += 4
    pdf.text(165, y_r, "Faltas:")
    if datos["Dias_Falta"] > 0:
        pdf.text(180, y_r, f"{int(datos['Dias_Falta'])} dia")
        
    y_r += 8
    pdf.text(130, y_r, "Base Tributable:")
    base_trib = datos["Imponible Calculado"] - datos["Total Prevision"]
    if base_trib < 0: base_trib = 0
    right_text(pdf, 195, y_r, formato_clp(base_trib).replace("$","").strip())
    
    if datos["Anticipo"] > 0:
        y_r += 6
        pdf.text(130, y_r, "Anticipo:")
        right_text(pdf, 195, y_r, formato_clp(datos["Anticipo"]).replace("$","").strip())

    # --- 4. TOTALES FINALES ---
    y_tot = max(y_l, y_r) + 15
    pdf.set_font("Arial", 'B', 9)
    
    pdf.text(110, y_tot, "TOTAL DESCUENTO")
    right_text(pdf, 195, y_tot, formato_clp(datos["Total Descuentos"]).replace("$","").strip())
    
    y_tot += 6
    pdf.text(110, y_tot, "ALCANCE LIQUIDO")
    right_text(pdf, 195, y_tot, formato_clp(datos["Alcance Liquido"]).replace("$","").strip())
    
    y_tot += 6
    pdf.text(110, y_tot, "TOTAL A PAGAR")
    right_text(pdf, 195, y_tot, formato_clp(datos["Total a Pagar"]).replace("$","").strip())
    
    # --- 5. TEXTO EN PALABRAS Y LEGAL ---
    y_words = y_tot + 10
    pdf.set_font("Arial", '', 9)
    texto_son = num2words(int(datos['Total a Pagar'])).upper()
    pdf.text(10, y_words, f"SON: {texto_son} PESOS")
    
    y_words += 10
    pdf.text(10, y_words, "Certifico que he recibido conforme y no tengo cargos ni cobro alguno posterior que hacer, por ninguno de los")
    pdf.text(10, y_words + 4, "conceptos comprometidos en ella.")
    
    y_firm = y_words + 25
    pdf.set_font("Arial", 'B', 9)
    pdf.text(10, y_firm, "FIRMA TRABAJADOR")
    
    pdf.set_font("Arial", '', 8)
    pdf.text(10, y_firm + 10, "La presente liquidación se emite en 2 copias quedando una en poder del trabajador y otra en poder del empleador.")
    
    # Render final
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
if 'menu_actual' not in st.session_state: st.session_state.menu_actual = "Inicio"

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

b0, b1, b2, b3, b4, b5, b6 = st.columns(7)

if b0.button("🏠 Inicio", type="primary" if st.session_state.menu_actual == "Inicio" else "secondary", use_container_width=True): st.session_state.menu_actual = "Inicio"; st.rerun()
if b1.button("💼 Finanzas", type="primary" if st.session_state.menu_actual == "Finanzas" else "secondary", use_container_width=True): st.session_state.menu_actual = "Finanzas"; st.rerun()
if b2.button("📝 Presup.", type="primary" if st.session_state.menu_actual == "Presupuestos" else "secondary", use_container_width=True): st.session_state.menu_actual = "Presupuestos"; st.rerun()
if b3.button("🏗️ Proyectos", type="primary" if st.session_state.menu_actual == "Proyectos" else "secondary", use_container_width=True): st.session_state.menu_actual = "Proyectos"; st.rerun()
if b4.button("⏱️ Operaciones", type="primary" if st.session_state.menu_actual == "Operaciones" else "secondary", use_container_width=True): st.session_state.menu_actual = "Operaciones"; st.rerun()
if b5.button("📦 Inventario", type="primary" if st.session_state.menu_actual == "Inventario" else "secondary", use_container_width=True): st.session_state.menu_actual = "Inventario"; st.rerun()
if b6.button("📊 Balance", type="primary" if st.session_state.menu_actual == "Balance" else "secondary", use_container_width=True): st.session_state.menu_actual = "Balance"; st.rerun()

st.divider()

# ==========================================
# PANTALLA 0: HOME DASHBOARD
# ==========================================
if st.session_state.menu_actual == "Inicio":
    st.markdown("## 📊 Panel de Control General")
    st.caption("Visión global del estado de Voltify SpA.")
    
    total_trabajadores = len(st.session_state.nomina)
    presupuestos_pendientes = st.session_state.presupuestos[st.session_state.presupuestos['Aprobacion'].str.contains('Pendiente', na=False)]['Monto'].sum()
    if pd.isna(presupuestos_pendientes): presupuestos_pendientes = 0
    proyectos_activos = len(st.session_state.proyectos_resumen)
    
    colA, colB, colC = st.columns(3)
    with colA:
        with st.container(border=True):
            st.metric("👥 Trabajadores Activos", total_trabajadores)
    with colB:
        with st.container(border=True):
            st.metric("🏗️ Proyectos en Curso", proyectos_activos)
    with colC:
        with st.container(border=True):
            st.metric("⏳ Presupuestos Pendientes", formato_clp(presupuestos_pendientes))

    st.write("")
    col_izq, col_der = st.columns(2)
    
    with col_izq:
        with st.container(border=True):
            st.markdown("#### 📈 Estado General de Proyectos")
            if st.session_state.proyectos_resumen.empty:
                st.info("No hay proyectos activos para medir.")
            else:
                for idx, row in st.session_state.proyectos_resumen.iterrows():
                    nombre_proy = row["Proyecto"]
                    tareas_proy = st.session_state.proyectos_tareas[st.session_state.proyectos_tareas["Proyecto"] == nombre_proy]
                    
                    if tareas_proy.empty:
                        st.write(f"**{nombre_proy}**: *Sin tareas asignadas*")
                        st.progress(0)
                    else:
                        terminadas = len(tareas_proy[tareas_proy["Estado"].str.contains('Terminada', na=False)])
                        total = len(tareas_proy)
                        porcentaje = int((terminadas / total) * 100)
                        st.write(f"**{nombre_proy}**")
                        st.progress(porcentaje / 100.0, text=f"Completado: {porcentaje}%")

    with col_der:
        with st.container(border=True):
            st.markdown("#### 🚨 Alertas y Urgencias")
            
            # Tareas Urgentes
            tareas_urgentes = st.session_state.proyectos_tareas[st.session_state.proyectos_tareas['Estado'].isin(['🔴 Pendiente', '🟡 En proceso', 'Pendiente', 'En proceso'])]
            if not tareas_urgentes.empty:
                st.write("**Tareas Pendientes en Terreno:**")
                st.dataframe(tareas_urgentes[['Proyecto', 'Tarea', 'Estado']], hide_index=True, use_container_width=True)
            else:
                st.success("¡Todo al día en terreno!")
            
            st.divider()
            # Inventario
            inventario_alerta = st.session_state.inventario[st.session_state.inventario['Estado'].isin(['🛠️ En Reparación', '❌ Extraviado', 'En Reparación', 'Extraviado'])]
            if not inventario_alerta.empty:
                st.write("**Herramientas Inoperativas:**")
                st.dataframe(inventario_alerta[['Artículo', 'Estado']], hide_index=True, use_container_width=True)
            else:
                st.success("Inventario 100% operativo.")

# ==========================================
# PANTALLA 1: FINANZAS Y NÓMINA
# ==========================================
def limpiar_form_nomina():
    st.session_state.form_id_nomina += 1

if 'form_id_nomina' not in st.session_state:
    st.session_state.form_id_nomina = 0

elif st.session_state.menu_actual == "Finanzas":
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
                    with st.expander("➕ Ingresar Nuevo Trabajador (Datos Fijos)", expanded=False):
                        fid = st.session_state.form_id_nomina
                        
                        colRUT, colA, colB = st.columns([1, 2, 2])
                        n_rut = colRUT.text_input("RUT (Ej: 12.345.678-9)", key=f"n_rut_{fid}")
                        n_trabajador = colA.text_input("Nombre Completo", key=f"n_trab_{fid}")
                        n_cargo = colB.text_input("Cargo", key=f"n_cargo_{fid}")
                        
                        llave_sueldo = f"sueldo_{fid}"
                        if llave_sueldo not in st.session_state: st.session_state[llave_sueldo] = "0"
                        
                        colC, colD, colE = st.columns([2, 1, 2])
                        colC.text_input("Sueldo Base Mensual", key=llave_sueldo, on_change=formatear_input, kwargs={'llave': llave_sueldo})
                        n_sueldo = float(st.session_state[llave_sueldo].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        
                        n_jornada = colD.number_input("Hrs Semanales", value=44, max_value=45, key=f"n_jor_{fid}")
                        n_grati = colE.selectbox("Tipo de Gratificación", ["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"], key=f"n_gra_{fid}")
                        
                        colF, colG = st.columns(2)
                        n_contrato = colF.selectbox("Tipo de Contrato", ["Indefinido", "Plazo Fijo"], key=f"n_con_{fid}")
                        n_afp = colG.selectbox("Seleccione AFP", list(TASAS_AFP.keys()), key=f"n_afp_{fid}")
                        
                        llave_col = f"colacion_{fid}"
                        llave_mov = f"movilizacion_{fid}"
                        if llave_col not in st.session_state: st.session_state[llave_col] = "0"
                        if llave_mov not in st.session_state: st.session_state[llave_mov] = "0"
                        
                        colH, colI = st.columns(2)
                        colH.text_input("Bono Colación Fijo", key=llave_col, on_change=formatear_input, kwargs={'llave': llave_col})
                        n_cola = float(st.session_state[llave_col].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        colI.text_input("Bono Movilización Fijo", key=llave_mov, on_change=formatear_input, kwargs={'llave': llave_mov})
                        n_movi = float(st.session_state[llave_mov].replace(".", "").replace(",", "").replace("$", "").strip() or 0)
                        
                        st.write("")
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("💾 Guardar Perfil Fijo", type="primary", use_container_width=True):
                                if n_trabajador and n_rut:
                                    nuevo_perfil = pd.DataFrame([{
                                        "RUT": n_rut, "Trabajador": n_trabajador, "Cargo": n_cargo, "Sueldo_Base": n_sueldo, 
                                        "Jornada_Hrs": n_jornada, "Tipo_Contrato": n_contrato, "Gratificacion": n_grati, 
                                        "AFP": n_afp, "Dias_Falta": 0, "Horas_Atraso": 0, "Horas_Extras": 0, 
                                        "Colacion": n_cola, "Movilizacion": n_movi, "Anticipo": 0
                                    }])
                                    st.session_state.nomina = pd.concat([st.session_state.nomina, nuevo_perfil], ignore_index=True)
                                    guardar_datos("Nomina_Personal", st.session_state.nomina)
                                    limpiar_form_nomina()
                                    st.success("Trabajador registrado exitosamente.")
                                    st.rerun()
                                else:
                                    st.error("⚠️ El RUT y el Nombre Completo son obligatorios.")
                        with col_btn2:
                            if st.button("🧹 Limpiar Campos", use_container_width=True):
                                limpiar_form_nomina()
                                st.rerun()

                    st.caption("Modifique las variables del mes directamente en la tabla (Anticipo y Faltas están junto al Sueldo):")
                    df_nomina_edit = st.data_editor(
                        st.session_state.nomina,
                        column_config={
                            "RUT": None, 
                            "Sueldo_Base": st.column_config.NumberColumn("Sueldo Base", min_value=0, format="%,d"),
                            "Colacion": st.column_config.NumberColumn("Colación", min_value=0, format="%,d"),
                            "Movilizacion": st.column_config.NumberColumn("Movilización", min_value=0, format="%,d"),
                            "Tipo_Contrato": st.column_config.SelectboxColumn("Contrato", options=["Indefinido", "Plazo Fijo"]),
                            "Gratificacion": st.column_config.SelectboxColumn("Gratificación", options=["Tope Legal Mensual", "25% del Sueldo (Sin Tope)", "Sin Gratificación"]),
                            "AFP": st.column_config.SelectboxColumn("AFP", options=list(TASAS_AFP.keys())),
                            "Dias_Falta": st.column_config.NumberColumn("Días Falta", min_value=0),
                            "Horas_Atraso": st.column_config.NumberColumn("Hrs Atraso", min_value=0),
                            "Horas_Extras": st.column_config.NumberColumn("Hrs Extras", min_value=0),
                            "Anticipo": st.column_config.NumberColumn("Anticipo ($)", min_value=0, format="%,d"),
                        },
                        column_order=["Trabajador", "Cargo", "Sueldo_Base", "Anticipo", "Dias_Falta", "Horas_Atraso", "Horas_Extras", "Colacion", "Movilizacion", "Jornada_Hrs", "Gratificacion", "AFP", "Tipo_Contrato"],
                        num_rows="dynamic", use_container_width=True, key="ed_nomina"
                    )
                    if st.button("💾 Guardar Cambios de Nómina / Mes", type="primary"):
                        st.session_state.nomina = df_nomina_edit
                        guardar_datos("Nomina_Personal", st.session_state.nomina)
                        st.success("Nómina actualizada.")
                        
                    with st.expander("🗑️ Dar de Baja / Eliminar Trabajador"):
                        lista_trabajadores = st.session_state.nomina['Trabajador'].tolist()
                        if lista_trabajadores:
                            trab_a_borrar = st.selectbox("Selecciona el trabajador a eliminar:", lista_trabajadores)
                            if st.button("Eliminar Definitivamente", type="primary"):
                                st.session_state.nomina = st.session_state.nomina[st.session_state.nomina['Trabajador'] != trab_a_borrar].reset_index(drop=True)
                                guardar_datos("Nomina_Personal", st.session_state.nomina)
                                st.success(f"Trabajador {trab_a_borrar} dado de baja exitosamente.")
                                st.rerun()
                else:
                    st.dataframe(st.session_state.nomina.drop(columns=["RUT"], errors='ignore'), use_container_width=True)

            with st.container(border=True):
                st.subheader("Proyección de Liquidaciones")
                df_liquidaciones, total_nomina_empresa = calcular_liquidaciones(st.session_state.nomina)
                
                df_liq_visual = df_liquidaciones[["Trabajador", "Cargo", "Imponible Calculado", "Total Prevision", "Anticipo", "Total a Pagar", "Costo Empresa"]].copy()
                for col in ["Imponible Calculado", "Total Prevision", "Anticipo", "Total a Pagar", "Costo Empresa"]:
                    df_liq_visual[col] = df_liq_visual[col].apply(formato_clp)
                    
                st.dataframe(df_liq_visual, use_container_width=True)
                st.info(f"**Costo Total Proyectado de Nómina:** {formato_clp(total_nomina_empresa)}")
                
                st.divider()
                st.markdown("#### 📄 Emisión de Liquidaciones Oficiales (PDF)")
                if FPDF_DISPONIBLE:
                    trab_lista = df_liquidaciones['Trabajador'].tolist()
                    if trab_lista:
                        col_sel, col_btn = st.columns([3, 1], vertical_alignment="bottom")
                        trab_seleccionado = col_sel.selectbox("Seleccione un trabajador para generar documento:", trab_lista)
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
            aprobacion_pres = colP5.selectbox("Estado de Aprobación:", ["⏳ Pendiente", "✅ Aprobada", "❌ No Aprobada"])
            orden_pres = colP6.selectbox("Respaldo de Orden:", ["Sin Orden", "Con Orden"])
            num_oc_pres = colP7.text_input("N° OC (Si aplica):", placeholder="Ej: OC-1234")
            if not num_oc_pres: num_oc_pres = "N/A"
            
            if st.button("Guardar Presupuesto", type="primary"):
                if ref_pres and cliente_pres and monto_pres > 0:
                    str_fecha = fecha_pres.strftime('%Y-%m-%d') if fecha_pres else ""
                    nuevo_presupuesto = pd.DataFrame([{
                        "Tipo": tipo_pres, "Referencia": ref_pres, "Cliente": cliente_pres,
                        "Monto": monto_pres, "Aprobacion": aprobacion_pres, "Orden_Compra": orden_pres,
                        "Num_OC": num_oc_pres, "Estado_Comercial": "📝 Presupuestada", "Fecha_Emision": str_fecha
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
            opciones_estado = ["📝 Presupuestada", "🎯 Adjudicada", "🚀 En progreso", "📦 Entregada", "💳 Pagada"]
            opciones_aprobacion = ["⏳ Pendiente", "✅ Aprobada", "❌ No Aprobada", "Pendiente", "Aprobada", "No Aprobada"]
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

            tareas_de_este_proyecto = st.session_state.proyectos_tareas[st.session_state.proyectos_tareas["Proyecto"] == proyecto_seleccionado]
            if not tareas_de_este_proyecto.empty:
                terminadas = len(tareas_de_este_proyecto[tareas_de_este_proyecto["Estado"].str.contains("Terminada", na=False)])
                total_t = len(tareas_de_este_proyecto)
                porc = int((terminadas / total_t) * 100)
                st.progress(porc / 100.0, text=f"Avance Operativo del Proyecto: {porc}% ({terminadas} de {total_t} tareas)")
            st.write("")

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
                        st.info("💡 Puedes asignar el 100% del costo mensual del trabajador, o ingresar las horas dedicadas para calcular su costo proporcional.")
                        df_liq, _ = calcular_liquidaciones(st.session_state.nomina)
                        trabajadores = ["Seleccione..."] + df_liq["Trabajador"].tolist()
                        
                        colT1, colT2 = st.columns([1, 1])
                        with colT1:
                            trabajador_sel = st.selectbox("Trabajador", trabajadores)
                            
                            if trabajador_sel != "Seleccione...":
                                costo_emp_trab = df_liq[df_liq["Trabajador"] == trabajador_sel]["Costo Empresa"].values[0]
                                row_trab = st.session_state.nomina[st.session_state.nomina['Trabajador'] == trabajador_sel].iloc[0]
                                jornada_t = float(row_trab.get('Jornada_Hrs', 44))
                                valor_hora_costo = (costo_emp_trab / 30) * 28 / jornada_t if jornada_t > 0 else 0
                                
                                st.info(f"**Costo Mensual (100%):** {formato_clp(costo_emp_trab)}\n\n**Valor Hora (Aprox):** {formato_clp(valor_hora_costo)}")
                        
                        with colT2:
                            if trabajador_sel != "Seleccione...":
                                tipo_asig = st.radio("Método de Asignación:", ["100% del Mes", "Por Horas Dedicadas"])
                                
                                if tipo_asig == "100% del Mes":
                                    st.write(f"Costo a imputar: **{formato_clp(costo_emp_trab)}**")
                                    if st.button("Añadir 100% al Gasto", type="primary", use_container_width=True):
                                        nuevo_gasto_trab = pd.DataFrame([{
                                            "Proyecto": proyecto_seleccionado, 
                                            "Detalle_Gasto": f"Mano de obra (100%): {trabajador_sel}", 
                                            "Monto": costo_emp_trab
                                        }])
                                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto_trab], ignore_index=True)
                                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
                                        st.rerun()
                                        
                                else:
                                    horas_input = st.number_input("Horas a imputar al proyecto:", min_value=0.5, step=0.5, value=10.0)
                                    costo_calc = horas_input * valor_hora_costo
                                    st.write(f"Costo a imputar: **{formato_clp(costo_calc)}**")
                                    if st.button("Añadir Horas al Gasto", type="primary", use_container_width=True):
                                        nuevo_gasto_trab = pd.DataFrame([{
                                            "Proyecto": proyecto_seleccionado, 
                                            "Detalle_Gasto": f"Mano de obra ({horas_input} hrs): {trabajador_sel}", 
                                            "Monto": costo_calc
                                        }])
                                        st.session_state.proyectos_gastos = pd.concat([st.session_state.proyectos_gastos, nuevo_gasto_trab], ignore_index=True)
                                        guardar_datos("Proyectos_Gastos", st.session_state.proyectos_gastos)
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
# PANTALLA 4: SEGUIMIENTO OPERATIVO (NUEVO REDISEÑO MONDAY)
# ==========================================
elif st.session_state.menu_actual == "Operaciones":
    st.markdown("### ⏱️ Work OS: Gestión Operativa")
    
    proyectos_lista_seg = st.session_state.proyectos_resumen["Proyecto"].tolist()
    if not proyectos_lista_seg:
        with st.container(border=True):
            st.warning("No hay proyectos creados. Ve a la pestaña 'Proyectos' para crear tu primera obra.")
    else:
        proyecto_seg = st.selectbox("📁 Espacio de Trabajo (Selecciona Proyecto):", proyectos_lista_seg)
        idx_p_seg = st.session_state.proyectos_resumen[st.session_state.proyectos_resumen["Proyecto"] == proyecto_seg].index[0]
        
        # --- HEADER DEL PROYECTO (Estilo Monday) ---
        tareas_proy = st.session_state.proyectos_tareas[st.session_state.proyectos_tareas["Proyecto"] == proyecto_seg]
        total_t = len(tareas_proy)
        terminadas = len(tareas_proy[tareas_proy["Estado"].str.contains('Terminada', na=False)]) if total_t > 0 else 0
        porc = int((terminadas / total_t) * 100) if total_t > 0 else 0
        
        st.markdown(f"#### 🚀 Proyecto: {proyecto_seg}")
        st.progress(porc / 100.0, text=f"Progreso Global: {porc}% ({terminadas}/{total_t} Tareas Completadas)")
        st.write("")
        
        # --- VISTAS (PESTAÑAS ESTILO MONDAY) ---
        tab_tablero, tab_gantt, tab_equipo, tab_config = st.tabs(["📌 Tablero de Tareas", "📅 Cronograma (Gantt)", "👥 Equipo de Trabajo", "⚙️ Ajustes de Proyecto"])

        # ==============================================
        # VISTA 1: TABLERO DE TAREAS (KANBAN & LISTA)
        # ==============================================
        with tab_tablero:
            lista_trabajadores_nomina = st.session_state.nomina["Trabajador"].tolist()
            if not lista_trabajadores_nomina:
                st.info("Agrega trabajadores en la pestaña de 'Finanzas' para poder asignarles tareas.")
            else:
                with st.expander("➕ Añadir Nueva Tarea al Tablero", expanded=False):
                    colT1, colT2 = st.columns([1, 2])
                    encargado_tarea = colT1.selectbox("Asignar a (Desde Nómina):", lista_trabajadores_nomina)
                    desc_tarea = colT2.text_input("Descripción de la Tarea:", placeholder="Ej: Instalar tablero eléctrico principal")
                    
                    colT3, colT4 = st.columns(2)
                    f_ini_tarea = colT3.date_input("Fecha Inicio Tarea", format="DD/MM/YYYY")
                    f_fin_tarea = colT4.date_input("Fecha Fin Tarea", format="DD/MM/YYYY")
                    
                    if st.button("Crear Tarea", use_container_width=True):
                        if desc_tarea:
                            str_ini_t = f_ini_tarea.strftime('%Y-%m-%d')
                            str_fin_t = f_fin_tarea.strftime('%Y-%m-%d')
                            nueva_tarea = pd.DataFrame([{
                                "Proyecto": proyecto_seg, 
                                "Trabajador": encargado_tarea, 
                                "Tarea": desc_tarea, 
                                "Estado": "🔴 Pendiente",
                                "Fecha_Inicio": str_ini_t,
                                "Fecha_Termino": str_fin_t
                            }])
                            st.session_state.proyectos_tareas = pd.concat([st.session_state.proyectos_tareas, nueva_tarea], ignore_index=True)
                            guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                            st.success("Tarea asignada.")
                            st.rerun()
                        else: st.error("Escribe una descripción para la tarea.")

                if tareas_proy.empty:
                    st.info("No hay tareas registradas para este proyecto en el tablero.")
                else:
                    col_filt1, col_filt2 = st.columns([1, 2])
                    trabajadores_con_tareas = tareas_proy['Trabajador'].unique().tolist()
                    filtro_trabajador = col_filt1.selectbox("🔍 Filtrar por Asignado:", ["👥 Todos"] + trabajadores_con_tareas)
                    
                    tipo_vista = col_filt2.radio("Modo de Vista:", ["📌 Kanban Interactivo", "📋 Edición en Lista"], horizontal=True)
                    st.divider()

                    if filtro_trabajador != "👥 Todos":
                        df_vista_filtrada = tareas_proy[tareas_proy['Trabajador'] == filtro_trabajador].copy()
                        mask_reemplazo = (st.session_state.proyectos_tareas["Proyecto"] == proyecto_seg) & (st.session_state.proyectos_tareas["Trabajador"] == filtro_trabajador)
                    else:
                        df_vista_filtrada = tareas_proy.copy()
                        mask_reemplazo = st.session_state.proyectos_tareas["Proyecto"] == proyecto_seg

                    if tipo_vista == "📌 Kanban Interactivo":
                        col_pend, col_proc, col_term = st.columns(3)
                        with col_pend:
                            st.markdown("<h4 style='text-align: center; color: #ef4444;'>🔴 Pendiente</h4>", unsafe_allow_html=True)
                            for idx, row in df_vista_filtrada[df_vista_filtrada['Estado'].str.contains('Pendiente', na=False)].iterrows():
                                with st.container(border=True):
                                    st.markdown(f"**{row['Tarea']}**")
                                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                                    if st.button("▶️ Iniciar", key=f"start_{idx}", use_container_width=True):
                                        st.session_state.proyectos_tareas.at[idx, 'Estado'] = '🟡 En proceso'
                                        guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                                        st.rerun()

                        with col_proc:
                            st.markdown("<h4 style='text-align: center; color: #eab308;'>🟡 En proceso</h4>", unsafe_allow_html=True)
                            for idx, row in df_vista_filtrada[df_vista_filtrada['Estado'].str.contains('proceso', na=False)].iterrows():
                                with st.container(border=True):
                                    st.markdown(f"**{row['Tarea']}**")
                                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                                    c1, c2 = st.columns(2)
                                    if c1.button("⏸️ Pausar", key=f"pause_{idx}", use_container_width=True):
                                        st.session_state.proyectos_tareas.at[idx, 'Estado'] = '🔴 Pendiente'
                                        guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                                        st.rerun()
                                    if c2.button("✅ Listo", key=f"done_{idx}", use_container_width=True):
                                        st.session_state.proyectos_tareas.at[idx, 'Estado'] = '🟢 Terminada'
                                        guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                                        st.rerun()

                        with col_term:
                            st.markdown("<h4 style='text-align: center; color: #22c55e;'>🟢 Terminada</h4>", unsafe_allow_html=True)
                            for idx, row in df_vista_filtrada[df_vista_filtrada['Estado'].str.contains('Terminada', na=False)].iterrows():
                                with st.container(border=True):
                                    st.markdown(f"**{row['Tarea']}**")
                                    st.caption(f"👤 {row['Trabajador']} | 📅 {row['Fecha_Termino']}")
                                    if st.button("↩️ Reabrir", key=f"revert_{idx}", use_container_width=True):
                                        st.session_state.proyectos_tareas.at[idx, 'Estado'] = '🟡 En proceso'
                                        guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                                        st.rerun()
                    else:
                        # VISTA LISTA
                        df_vista_filtrada['Fecha_Inicio'] = pd.to_datetime(df_vista_filtrada['Fecha_Inicio'], errors='coerce').dt.date
                        df_vista_filtrada['Fecha_Termino'] = pd.to_datetime(df_vista_filtrada['Fecha_Termino'], errors='coerce').dt.date

                        df_tareas_editadas = st.data_editor(
                            df_vista_filtrada,
                            column_config={
                                "Estado": st.column_config.SelectboxColumn("Estado", options=["🔴 Pendiente", "🟡 En proceso", "🟢 Terminada"]),
                                "Fecha_Inicio": st.column_config.DateColumn("Inicio"),
                                "Fecha_Termino": st.column_config.DateColumn("Fin")
                            },
                            disabled=["Proyecto", "Trabajador", "Tarea"], hide_index=True, use_container_width=True, key=f"ed_tar_{proyecto_seg}"
                        )
                        
                        if st.button("💾 Guardar Progreso de Tareas", type="primary"):
                            df_tareas_editadas['Fecha_Inicio'] = df_tareas_editadas['Fecha_Inicio'].astype(str)
                            df_tareas_editadas['Fecha_Termino'] = df_tareas_editadas['Fecha_Termino'].astype(str)
                            
                            st.session_state.proyectos_tareas = st.session_state.proyectos_tareas[~mask_reemplazo]
                            st.session_state.proyectos_tareas = pd.concat([st.session_state.proyectos_tareas, df_tareas_editadas], ignore_index=True)
                            guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                            st.success("Estados actualizados de forma segura.")
                    
                    st.write("")
                    with st.expander("🗑️ Zona de Peligro: Eliminar Tareas"):
                        lista_nombres_tareas = [f"{row['Tarea']} ({row['Trabajador']})" for index, row in df_vista_filtrada.iterrows()]
                        if lista_nombres_tareas:
                            tarea_a_eliminar = st.selectbox("Selecciona la tarea a eliminar:", lista_nombres_tareas)
                            if st.button("Eliminar Tarea Seleccionada", type="primary"):
                                nombre_tarea = tarea_a_eliminar.rsplit(" (", 1)[0]
                                nombre_trab = tarea_a_eliminar.rsplit(" (", 1)[1].replace(")", "")
                                
                                mask_eliminar = (st.session_state.proyectos_tareas["Proyecto"] == proyecto_seg) & (st.session_state.proyectos_tareas["Tarea"] == nombre_tarea) & (st.session_state.proyectos_tareas["Trabajador"] == nombre_trab)
                                st.session_state.proyectos_tareas = st.session_state.proyectos_tareas[~mask_eliminar]
                                guardar_datos("Proyectos_Tareas", st.session_state.proyectos_tareas)
                                st.success("Tarea eliminada.")
                                st.rerun()

        # ==============================================
        # VISTA 2: GANTT
        # ==============================================
        with tab_gantt:
            st.markdown("#### Línea de Tiempo del Proyecto")
            df_gantt = tareas_proy.copy()
            df_gantt['Fecha_Inicio'] = pd.to_datetime(df_gantt['Fecha_Inicio'], errors='coerce')
            df_gantt['Fecha_Termino'] = pd.to_datetime(df_gantt['Fecha_Termino'], errors='coerce')
            df_gantt = df_gantt.dropna(subset=['Fecha_Inicio', 'Fecha_Termino'])
            
            if not df_gantt.empty:
                gantt = alt.Chart(df_gantt).mark_bar(cornerRadius=4, height=20).encode(
                    x=alt.X('Fecha_Inicio:T', title='Fechas'),
                    x2=alt.X2('Fecha_Termino:T'),
                    y=alt.Y('Tarea:N', sort=alt.EncodingSortField(field='Fecha_Inicio', order='ascending'), title=''),
                    color=alt.Color('Estado:N', scale=alt.Scale(
                        domain=['🔴 Pendiente', '🟡 En proceso', '🟢 Terminada'], 
                        range=['#ef4444', '#eab308', '#22c55e']
                    )),
                    tooltip=['Tarea', 'Trabajador', 'Estado', 'Fecha_Inicio', 'Fecha_Termino']
                ).properties(height=350)
                st.altair_chart(gantt, use_container_width=True)
            else:
                st.info("Agrega tareas con fechas válidas en el Tablero para ver la Carta Gantt.")

        # ==============================================
        # VISTA 3: EQUIPO DE TRABAJO
        # ==============================================
        with tab_equipo:
            st.markdown("#### Conformación del Equipo y Liderazgo")
            gastos_proy_seg = st.session_state.proyectos_gastos[st.session_state.proyectos_gastos["Proyecto"] == proyecto_seg]
            trabajadores_financiados = []
            
            for detalle in gastos_proy_seg["Detalle_Gasto"]:
                detalle_str = str(detalle)
                if detalle_str.startswith("Mano de obra"):
                    if ":" in detalle_str:
                        nombre = detalle_str.split(":", 1)[1].strip()
                        if nombre not in trabajadores_financiados: 
                            trabajadores_financiados.append(nombre)
                        
            if not trabajadores_financiados:
                st.warning("⚠️ No has asignado personal a este proyecto en la pestaña Finanzas > Proyectos.")
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
                
                st.caption("Asigna los roles del equipo en terreno:")
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

        # ==============================================
        # VISTA 4: AJUSTES (CRONOGRAMA GENERAL)
        # ==============================================
        with tab_config:
            st.markdown("#### Configuración de Tiempos del Proyecto")
            val_ini = st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Inicio_Proy"]
            val_fin = st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Termino_Proy"]
            val_dur = st.session_state.proyectos_resumen.at[idx_p_seg, "Duracion_Proy"]
            
            def parse_fecha(f_str):
                try:
                    if pd.isna(f_str) or str(f_str).strip() in ["", "Pendiente"]: return None
                    return pd.to_datetime(str(f_str)).date()
                except: return None
            
            c_conf1, c_conf2, c_conf3 = st.columns(3)
            nuevo_ini = c_conf1.date_input("Fecha de Inicio Oficial:", value=parse_fecha(val_ini), format="DD/MM/YYYY")
            nuevo_fin = c_conf2.date_input("Fecha de Término Oficial:", value=parse_fecha(val_fin), format="DD/MM/YYYY")
            nueva_dur = c_conf3.text_input("Duración Estimada:", value="" if val_dur=="Pendiente" else val_dur, placeholder="Ej: 3 meses")
            
            if st.button("Guardar Fechas del Proyecto", type="primary"):
                str_ini = nuevo_ini.strftime('%Y-%m-%d') if nuevo_ini else "Pendiente"
                str_fin = nuevo_fin.strftime('%Y-%m-%d') if nuevo_fin else "Pendiente"
                st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Inicio_Proy"] = str_ini
                st.session_state.proyectos_resumen.at[idx_p_seg, "Fecha_Termino_Proy"] = str_fin
                st.session_state.proyectos_resumen.at[idx_p_seg, "Duracion_Proy"] = nueva_dur if nueva_dur else "Pendiente"
                guardar_datos("Proyectos_Resumen", st.session_state.proyectos_resumen)
                st.success("Configuración actualizada.")

elif st.session_state.menu_actual == "Inventario":
    st.markdown("### 📦 Control de Inventario y Activos")
    with st.container(border=True):
        st.markdown("#### 🔍 Buscador Rápido")
        busqueda = st.text_input("Ingresa el Número de Serie o Nombre del Artículo para localizarlo rápidamente:", placeholder="Ej: VLT- o Taladro")
        if busqueda:
            mask = st.session_state.inventario["Nro_Serie"].astype(str).str.contains(busqueda, case=False, na=False) | st.session_state.inventario["Artículo"].astype(str).str.contains(busqueda, case=False, na=False
