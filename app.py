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
    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        seleccionado = next((m for m in modelos if 'flash' in m), modelos[0])
        return genai.GenerativeModel(seleccionado)
    except: return None

model = obtener_modelo()

def clasificar_uno(nombre):
    prompt = f"Categoriza para inventario: '{nombre}'. Responde SOLO una palabra: Reactivos, Consumibles, Vidriería, Equipos, Buffers o Anticuerpos."
    try:
        res = model.generate_content(prompt)
        # Limpieza: quitamos puntos, espacios y pasamos a Capitalize
        return res.text.strip().replace(".", "").capitalize()
    except: return "Sin Clasificar"

# --- INTERFAZ ---
st.title("🔬 Gestión Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Nueva Acción", "📂 Inventario y Clasificación"])

with tab1:
    foto = st.camera_input("📷 Cámara")
    instruccion = st.text_area("Comando:", placeholder="Ej: 'Usa 2 del kit pcr'")
    if st.button("🚀 Procesar", use_container_width=True):
        st.info("Función de procesamiento activa.")

with tab2:
    st.header("📦 Control de Stock")
    
    # BOTÓN CON MANEJO DE ERRORES (TRY/EXCEPT)
    if st.button("🤖 CLASIFICAR INVENTARIO (Anti-Errores)", use_container_width=True, type="primary"):
        res_items = supabase.table("items").select("id", "nombre").execute()
        # Filtramos los que no tienen categoría o está vacía
        items_a_procesar = [i for i in res_items.data if not i.get('categoria') or i.get('categoria') == ""]
        
        if not items_a_procesar:
            st.success("✅ Todo está clasificado.")
        else:
            bar = st.progress(0)
            status = st.empty()
            exitos = 0
            
            for i, item in enumerate(items_a_procesar):
                cat = clasificar_uno(item['nombre'])
                try:
                    # Intentamos la actualización
                    supabase.table("items").update({"categoria": cat}).eq("id", item['id']).execute()
                    exitos += 1
                except Exception as e:
                    st.warning(f"No se pudo actualizar: {item['nombre']}. Error: {e}")
                
                bar.progress((i + 1) / len(items_a_procesar))
                status.text(f"Procesando {i+1}/{len(items_a_procesar)}: {item['nombre']}")
                time.sleep(0.2)
            
            st.success(f"🎉 ¡Terminado! {exitos} ítems clasificados.")
            time.sleep(1)
            st.rerun()

    # BUSCADOR Y TABLAS
    busqueda = st.text_input("🔍 Buscar reactivo...")
    res_db = supabase.table("items").select("*").execute()
    
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        # Aseguramos que la columna exista en el DataFrame para evitar KeyErrors
        if 'categoria' not in df.columns:
            df['categoria'] = "⚠️ Sin Clasificar"
        else:
            df['categoria'] = df['categoria'].fillna("⚠️ Sin Clasificar")
        
        for cat in sorted(df['categoria'].unique()):
            df_cat = df[df['categoria'] == cat]
            if busqueda:
                df_cat = df_cat[df_cat['nombre'].str.contains(busqueda, case=False)]
            
            if not df_cat.empty:
                with st.expander(f"📁 {cat} ({len(df_cat)})"):
                    st.dataframe(df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                                 use_container_width=True, hide_index=True)
