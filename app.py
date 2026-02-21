import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
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

# --- MOTOR DE CLASIFICACIÓN MASIVA ---
def clasificar_lote(lista_nombres):
    nombres_string = "\n".join(lista_nombres)
    prompt = f"""
    Eres un experto en inventario científico. Clasifica estos productos de laboratorio:
    {nombres_string}

    Reglas:
    1. Usa el formato: NOMBRE | CATEGORIA - SUBCATEGORIA
    2. Categorías permitidas: REACTIVOS, CONSUMIBLES, VIDRIERÍA, EQUIPOS.
    3. Responde SOLO con la lista clasificada, una por línea.
    """
    try:
        res = model.generate_content(prompt)
        lineas = res.text.strip().split('\n')
        resultado = {}
        for linea in lineas:
            if '|' in linea:
                partes = linea.split('|')
                resultado[partes[0].strip()] = partes[1].strip().upper()
        return resultado
    except:
        return {}

# --- INTERFAZ ---
st.title("🔬 Sistema Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro", "📂 Inventario Organizado"])

with tab1:
    st.write("Panel de registro activo.")

with tab2:
    if st.button("🤖 CLASIFICACIÓN MASIVA (Modo Lote)", use_container_width=True, type="primary"):
        res_items = supabase.table("items").select("id", "nombre").execute()
        items_db = res_items.data
        
        # Procesamos en lotes de 10 para no saturar la API
        lote_size = 10
        total = len(items_db)
        progreso = st.progress(0)
        status = st.empty()
        
        for i in range(0, total, lote_size):
            lote_actual = items_db[i:i+lote_size]
            nombres_lote = [item['nombre'] for item in lote_actual]
            
            status.text(f"🧠 IA Analizando lote {i//lote_size + 1}...")
            clasificaciones = clasificar_lote(nombres_lote)
            
            for item in lote_actual:
                nombre = item['nombre']
                if nombre in clasificaciones:
                    cat = clasificaciones[nombre]
                    supabase.table("items").update({"categoria": cat}).eq("id", item['id']).execute()
            
            progreso.progress(min((i + lote_size) / total, 1.0))
            time.sleep(2) # Pausa estratégica para evitar el baneo de Google
            
        st.success("✅ ¡Inventario organizado!")
        st.rerun()

    # Visualización
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("GENERAL - SIN CLASIFICAR")
        
        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}", expanded=False):
                st.dataframe(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad']], 
                             use_container_width=True, hide_index=True)
