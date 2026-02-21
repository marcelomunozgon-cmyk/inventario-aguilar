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
    st.error("Error en Secrets.")
    st.stop()

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    return genai.GenerativeModel(next((m for m in modelos if 'flash' in m), modelos[0]))

model = obtener_modelo()

# --- FUNCIÓN DE CLASIFICACIÓN JERÁRQUICA ---
def clasificar_jerarquico(nombre):
    prompt = f"""
    Clasifica este ítem de laboratorio en una estructura de Carpeta > Subcarpeta.
    Ítem: '{nombre}'
    Ejemplos:
    - Etanol -> 'Reactivos > Solventes'
    - Tips 200ul -> 'Consumibles > Plásticos'
    - Vaso de precipitado -> 'Vidriería > Vasos y Frascos'
    
    Responde SOLAMENTE la ruta (Máximo 2 niveles).
    """
    try:
        res = model.generate_content(prompt)
        return res.text.strip().replace("'", "").replace('"', '')
    except: return "Otros > Sin Clasificar"

# --- INTERFAZ ---
st.title("🔬 Sistema de Carpetas Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro Rápido", "📂 Explorador de Inventario"])

with tab1:
    instruccion = st.text_area("Comando:", placeholder="Ej: 'Usa 500ml de Etanol'")
    if st.button("🚀 Procesar", use_container_width=True):
        st.info("Procesando comando...")

with tab2:
    col_btn, col_search = st.columns([1, 2])
    
    with col_btn:
        if st.button("🤖 RE-CLASIFICAR TODO (Carpetas)", use_container_width=True, type="primary"):
            res_items = supabase.table("items").select("id", "nombre").execute()
            bar = st.progress(0)
            status = st.empty()
            
            for i, item in enumerate(res_items.data):
                nueva_ruta = clasificar_jerarquico(item['nombre'])
                supabase.table("items").update({"categoria": nueva_ruta}).eq("id", item['id']).execute()
                bar.progress((i + 1) / len(res_items.data))
                status.text(f"Organizando: {item['nombre']} -> {nueva_ruta}")
            
            st.success("✅ ¡Inventario organizado por carpetas!")
            st.rerun()

    with col_search:
        busqueda = st.text_input("🔍 Buscar en carpetas...")

    # --- LÓGICA DE CARPETAS ANIDADAS ---
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("Otros > Sin Clasificar")
        
        # Filtrar si hay búsqueda
        if busqueda:
            df = df[df['nombre'].str.contains(busqueda, case=False)]

        # Obtener carpetas principales (Nivel 1)
        df['carpeta_padre'] = df['categoria'].apply(lambda x: x.split('>')[0].strip())
        df['sub_carpeta'] = df['categoria'].apply(lambda x: x.split('>')[1].strip() if '>' in x else "General")

        for padre in sorted(df['carpeta_padre'].unique()):
            with st.expander(f"📁 {padre}", expanded=False):
                df_padre = df[df['carpeta_padre'] == padre]
                
                # Crear subcarpetas
                for sub in sorted(df_padre['sub_carpeta'].unique()):
                    st.markdown(f"**📂 {sub}**")
                    df_sub = df_padre[df_padre['sub_carpeta'] == sub]
                    st.dataframe(
                        df_sub[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                        use_container_width=True, 
                        hide_index=True
                    )
                    st.divider()
