import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import time

# 1. CONFIGURACIÓN BÁSICA (Fuera de cualquier bucle)
st.set_page_config(page_title="Lab Aguilar OS", layout="wide")

# 2. CONEXIÓN SEGURA
@st.cache_resource
def inicializar_conexiones():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        ai_key = st.secrets["GENAI_KEY"]
        
        supabase = create_client(url, key)
        genai.configure(api_key=ai_key)
        
        # Intentar detectar modelo
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        modelo_nombre = next((m for m in modelos if '1.5-flash' in m), modelos[0])
        model = genai.GenerativeModel(modelo_nombre)
        
        return supabase, model
    except Exception as e:
        st.error(f"Error crítico de conexión: {e}")
        return None, None

supabase, model = inicializar_conexiones()

# 3. INTERFAZ
st.title("🔬 Lab Aguilar - Sistema de Control")

if supabase and model:
    # Columnas para el Dashboard
    col_control, col_monitor = st.columns([1, 1.5])

    with col_control:
        st.subheader("💬 Asistente")
        # Usamos un formulario para evitar que cada tecla cause un rerun
        with st.form("chat_form"):
            user_input = st.text_input("Escribe tu instrucción aquí:")
            submit = st.form_submit_button("Enviar")
            
            if submit and user_input:
                st.info(f"Procesando: {user_input}...")
                # Aquí iría la lógica del agente que ya teníamos

    with col_monitor:
        st.subheader("📊 Inventario")
        try:
            # Traer solo 20 ítems para probar que carga rápido
            res = supabase.table("items").select("*").limit(20).execute()
            if res.data:
                df = pd.DataFrame(res.data)
                st.dataframe(df[['nombre', 'cantidad_actual', 'unidad']], use_container_width=True)
            else:
                st.write("No hay datos.")
        except Exception as e:
            st.error(f"Error al leer tablas: {e}")
else:
    st.warning("El sistema no pudo iniciar. Revisa los 'Secrets' en Streamlit Cloud.")

# Botón de reset manual en la barra lateral
if st.sidebar.button("Limpiar Caché y Reiniciar"):
    st.cache_resource.clear()
    st.rerun()
