import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
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
    st.error("Error en Secrets. Verifica la configuración.")
    st.stop()

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    return genai.GenerativeModel(next((m for m in modelos if 'flash' in m), modelos[0]))

model = obtener_modelo()

# --- FUNCIÓN DE CLASIFICACIÓN ---
def clasificar_jerarquico(nombre):
    # Usamos un separador más amigable: " - " en lugar de ">"
    prompt = f"Clasifica para inventario: '{nombre}'. Responde en formato: Carpeta - Subcarpeta. Ejemplo: 'Reactivos - Solventes'. Máximo 30 caracteres."
    try:
        res = model.generate_content(prompt)
        return res.text.strip().replace("'", "").replace('"', '').replace('>', '-')
    except: return "General - Sin clasificar"

# --- INTERFAZ ---
st.title("🔬 Explorador Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro", "📂 Inventario Jerárquico"])

with tab1:
    st.info("El sistema de registro multimodal está activo.")

with tab2:
    # Botón de re-clasificación con manejo de errores por fila
    if st.button("🤖 ORGANIZAR EN CARPETAS", use_container_width=True, type="primary"):
        res_items = supabase.table("items").select("id", "nombre").execute()
        items = res_items.data
        
        progreso = st.progress(0)
        status = st.empty()
        errores = 0
        
        for i, item in enumerate(items):
            try:
                nueva_ruta = clasificar_jerarquico(item['nombre'])
                # Intentamos actualizar solo este registro
                supabase.table("items").update({"categoria": nueva_ruta}).eq("id", item['id']).execute()
                status.text(f"✅ {item['nombre']} -> {nueva_ruta}")
            except Exception as e:
                errores += 1
                status.warning(f"❌ Error en: {item['nombre']}")
            
            progreso.progress((i + 1) / len(items))
            time.sleep(0.1) # Breve pausa para no saturar la API
            
        st.success(f"Proceso completado. Errores: {errores}")
        st.rerun()

    # --- RENDERIZADO DE CARPETAS ---
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("General - Sin clasificar")
        
        # Dividir la ruta en Padre e Hijo
        df[['Padre', 'Hijo']] = df['categoria'].str.split('-', n=1, expand=True).fillna("General")
        
        padres = sorted(df['Padre'].unique())
        
        for p in padres:
            with st.expander(f"📁 {p.strip().upper()}", expanded=False):
                df_p = df[df['Padre'] == p]
                hijos = sorted(df_p['Hijo'].unique())
                
                for h in hijos:
                    st.markdown(f"**📍 {h.strip()}**")
                    df_h = df_p[df_p['Hijo'] == h]
                    st.dataframe(
                        df_h[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']],
                        use_container_width=True,
                        hide_index=True
                    )
