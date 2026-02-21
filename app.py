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

# --- CEREBRO DE CLASIFICACIÓN TÉCNICA ---
def clasificar_cientifico(nombre):
    prompt = f"""
    Eres un experto en suministros de laboratorio (Sigma-Aldrich, Thermo Fisher, Bio-Rad).
    Analiza el producto: '{nombre}'
    
    Determina su categoría siguiendo esta lógica:
    - Si es una sustancia química, buffer, enzima, anticuerpo o kit: 'REACTIVOS - [Tipo]'
    - Si es plástico, descartable, guantes o puntas: 'CONSUMIBLES - [Tipo]'
    - Si es de vidrio o cuarzo: 'VIDRIERÍA - [Tipo]'
    - Si es un aparato eléctrico o mecánico: 'EQUIPOS - [Tipo]'
    
    Responde SOLAMENTE la categoría en formato: CATEGORIA - SUBCATEGORIA.
    Si no estás seguro, usa tu conocimiento de catálogos científicos para adivinar.
    Ejemplo: 'Opti-MEM' -> 'REACTIVOS - Medios de Cultivo'
    """
    try:
        res = model.generate_content(prompt)
        return res.text.strip().replace("'", "").replace('"', '').upper()
    except:
        return "GENERAL - SIN CLASIFICAR"

# --- INTERFAZ ---
st.title("🔬 Inteligencia de Inventario Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro Multimodal", "📂 Explorador Jerárquico"])

with tab1:
    col1, col2 = st.columns(2)
    with col1: foto = st.camera_input("Capturar etiqueta")
    with col2:
        instruccion = st.text_area("Instrucción rápida:", placeholder="Ej: 'Suma 10 a los frascos de glucosa'")
        if st.button("🚀 Ejecutar", use_container_width=True):
            st.info("Procesando con lógica científica...")

with tab2:
    st.subheader("📦 Organización del Almacén")
    
    if st.button("🤖 EJECUTAR CLASIFICACIÓN TÉCNICA (180 ítems)", use_container_width=True, type="primary"):
        res_items = supabase.table("items").select("id", "nombre").execute()
        items = res_items.data
        
        progreso = st.progress(0)
        status = st.empty()
        
        for i, item in enumerate(items):
            # Aquí es donde ocurre la magia técnica
            nueva_cat = clasificar_cientifico(item['nombre'])
            
            try:
                supabase.table("items").update({"categoria": nueva_cat}).eq("id", item['id']).execute()
                status.write(f"🔬 Identificado: **{item['nombre']}** como **{nueva_cat}**")
            except Exception as e:
                status.write(f"⚠️ Error al guardar {item['nombre']}")
            
            progreso.progress((i + 1) / len(items))
            time.sleep(0.5) # Pausa necesaria para que Google no bloquee la cuenta gratuita
            
        st.success("✅ Clasificación masiva terminada.")
        st.rerun()

    # Visualización organizada
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("GENERAL - SIN CLASIFICAR")
        
        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}", expanded=False):
                df_cat = df[df['categoria'] == cat]
                st.dataframe(df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                             use_container_width=True, hide_index=True)
