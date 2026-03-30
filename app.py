import streamlit as st
import pandas as pd

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD VISUAL
# ==========================================
st.set_page_config(page_title="Panel Financiero", page_icon="⚡", layout="wide")

# Reemplaza este enlace por "logo.png" cuando subas tu propia imagen a GitHub
LOGO_URL = "https://via.placeholder.com/600x150/005cba/FFFFFF?text=TU+LOGO+AQUI"

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
    st.
