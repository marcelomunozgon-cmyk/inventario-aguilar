import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", page_icon="🔬", layout="wide")

try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("Error en Secrets.")
    st.stop()

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    return genai.GenerativeModel(next((m for m in modelos if 'flash' in m), modelos[0]))

model = obtener_modelo()

# --- FUNCIÓN DE CLASIFICACIÓN REFORZADA ---
def clasificar_robusto(nombre):
    # Forzamos a la IA a elegir de una lista para evitar errores de formato
    prompt = f"""
    Clasifica este objeto de laboratorio: '{nombre}'.
    Elige SOLO una de estas categorías:
    'REACTIVOS - Químicos', 'REACTIVOS - Biología', 'CONSUMIBLES - Plásticos', 'CONSUMIBLES - Guantes/Papel', 'VIDRIERÍA - Frascos', 'EQUIPOS - Instrumentos'.
    
    Responde ÚNICAMENTE la categoría elegida, nada más.
    """
    try:
        res = model.generate_content(prompt)
        # Limpiamos cualquier carácter extraño que devuelva la IA
        limpio = res.text.strip().replace("'", "").replace('"', '').replace(".", "")
        return limpio if len(limpio) > 3 else "GENERAL - Sin clasificar"
    except:
        return "GENERAL - Sin clasificar"

# --- INTERFAZ ---
st.title("🔬 Sistema Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro", "📂 Inventario Organizado"])

with tab1:
    col1, col2 = st.columns(2)
    with col1: foto = st.camera_input("Captura")
    with col2:
        instruccion = st.text_area("Comando:", placeholder="Ej: 'Se usaron 100ml de Etanol'")
        if st.button("🚀 Ejecutar", use_container_width=True):
            st.info("Procesando...")

with tab2:
    if st.button("🤖 CLASIFICAR TODO AHORA (Modo Forzado)", use_container_width=True, type="primary"):
        res_items = supabase.table("items").select("id", "nombre").execute()
        items = res_items.data
        
        progreso = st.progress(0)
        status = st.empty()
        
        for i, item in enumerate(items):
            nueva_cat = clasificar_robusto(item['nombre'])
            # Actualizamos la base de datos
            try:
                supabase.table("items").update({"categoria": nueva_cat}).eq("id", item['id']).execute()
                status.write(f"✅ {item['nombre']} -> {nueva_cat}")
            except Exception as e:
                status.write(f"❌ Error en {item['nombre']}: {e}")
            
            progreso.progress((i + 1) / len(items))
            time.sleep(0.3) # Pausa para asegurar que la API no nos bloquee
            
        st.success("¡Organización completada!")
        st.rerun()

    # Visualización de carpetas
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("GENERAL - Sin clasificar")
        
        # Agrupamos por lo que diga la columna categoria
        categorias_unicas = sorted(df['categoria'].unique())
        
        for cat in categorias_unicas:
            with st.expander(f"📁 {cat}", expanded=False):
                df_cat = df[df['categoria'] == cat]
                st.dataframe(df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                             use_container_width=True, hide_index=True)
