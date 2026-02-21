import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar Business", page_icon="🔬", layout="wide")

# Conexión Segura
try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("Revisa los Secrets en Streamlit Cloud.")
    st.stop()

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    seleccionado = next((m for m in modelos if 'flash' in m), modelos[0])
    return genai.GenerativeModel(seleccionado)

model = obtener_modelo()

# --- FUNCIONES ---
def clasificar_uno(nombre):
    prompt = f"Categoriza este ítem de laboratorio: '{nombre}'. Responde solo una palabra: Reactivos, Consumibles, Vidriería, Equipos, Buffers o Anticuerpos."
    try:
        res = model.generate_content(prompt)
        return res.text.strip()
    except: return "Sin Clasificar"

# --- INTERFAZ ---
st.title("🔬 Gestión Lab Aguilar")

# Selector de Usuario en la parte principal para que sea fácil en el móvil
usuario = st.selectbox("👤 Operador actual:", ["Rodrigo Aguilar", "Asistente 1", "Admin"])

tab1, tab2 = st.tabs(["🎙️ Nueva Acción", "📂 Inventario y Clasificación"])

with tab1:
    foto = st.camera_input("📷 Cámara")
    instruccion = st.text_area("Comando:", placeholder="Ej: 'Usa 2 del kit pcr'")
    if st.button("🚀 Procesar Acción", use_container_width=True):
        # (Aquí va la lógica de procesamiento que ya teníamos)
        st.write("Procesando...")

with tab2:
    st.header("📦 Control de Stock")
    
    # BOTÓN DE AUTO-CLASIFICACIÓN (AQUÍ ESTÁ EL BOTÓN QUE BUSCAS)
    if st.button("🤖 CLASIFICAR TODO EL INVENTARIO AHORA", use_container_width=True, type="primary"):
        # Buscamos ítems que NO tengan categoría
        res_items = supabase.table("items").select("id", "nombre").execute()
        items_a_procesar = [i for i in res_items.data if not i.get('categoria')]
        
        if not items_a_procesar:
            st.success("✅ ¡Todo el inventario ya está clasificado!")
        else:
            bar = st.progress(0)
            total = len(items_a_procesar)
            for i, item in enumerate(items_a_procesar):
                cat = clasificar_uno(item['nombre'])
                supabase.table("items").update({"categoria": cat}).eq("id", item['id']).execute()
                bar.progress((i + 1) / total)
                st.toast(f"Clasificando: {item['nombre']} -> {cat}")
            st.success("🎉 ¡Proceso terminado!")
            st.rerun()

    # VISUALIZACIÓN
    busqueda = st.text_input("🔍 Buscar reactivo...")
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("⚠️ Sin Clasificar")
        
        for cat in sorted(df['categoria'].unique()):
            df_cat = df[df['categoria'] == cat]
            if busqueda:
                df_cat = df_cat[df_cat['nombre'].str.contains(busqueda, case=False)]
            
            with st.expander(f"📁 {cat} ({len(df_cat)} ítems)"):
                st.dataframe(df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], use_container_width=True, hide_index=True)
