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
    genai.configure(api_key=GENAI_KEY)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Error de configuración: {e}")
    st.stop()

@st.cache_resource
def obtener_modelo():
    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        return genai.GenerativeModel(next((m for m in modelos if 'flash' in m), modelos[0]))
    except: return None

model = obtener_modelo()

# --- DICCIONARIO DE RESPALDO (Si la IA falla) ---
DICCIONARIO_LAB = {
    "etanol": "REACTIVOS - Solventes",
    "puntas": "CONSUMIBLES - Plásticos",
    "tips": "CONSUMIBLES - Plásticos",
    "tubo": "CONSUMIBLES - Plásticos",
    "vaso": "VIDRIERÍA - Recipientes",
    "kit": "REACTIVOS - Kits",
    "pcr": "REACTIVOS - Biología Molecular",
    "guantes": "CONSUMIBLES - Protección",
    "buffer": "REACTIVOS - Buffers"
}

def clasificar_inteligente(nombre):
    # Primero intentamos con el diccionario local (instantáneo)
    nombre_min = nombre.lower()
    for clave, valor in DICCIONARIO_LAB.items():
        if clave in nombre_min:
            return valor
            
    # Si no está en el diccionario, le pedimos a la IA
    if model:
        try:
            prompt = f"Clasifica '{nombre}' en formato: CATEGORIA - SUBCATEGORIA. Solo 3 palabras máximo."
            res = model.generate_content(prompt)
            return res.text.strip().upper()
        except: pass
    return "GENERAL - OTROS"

# --- INTERFAZ ---
st.title("🔬 Sistema de Control Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro", "📂 Inventario Organizado"])

with tab2:
    st.subheader("📦 Clasificación Masiva")
    
    if st.button("🚀 INICIAR CLASIFICACIÓN (Modo Seguro)", use_container_width=True, type="primary"):
        # 1. Obtener datos
        res_items = supabase.table("items").select("id", "nombre").execute()
        items = res_items.data
        
        if not items:
            st.warning("No se encontraron ítems en la base de datos.")
        else:
            progreso = st.progress(0)
            status = st.empty()
            contador_exito = 0
            
            for i, item in enumerate(items):
                nombre_actual = item['nombre']
                status.info(f"Procesando ({i+1}/{len(items)}): {nombre_actual}")
                
                # Clasificar
                nueva_cat = clasificar_inteligente(nombre_actual)
                
                # Actualizar Supabase
                try:
                    update_res = supabase.table("items").update({"categoria": nueva_cat}).eq("id", item['id']).execute()
                    if update_res.data:
                        contador_exito += 1
                except Exception as db_error:
                    st.error(f"Error en base de datos para {nombre_actual}: {db_error}")
                
                progreso.progress((i + 1) / len(items))
                time.sleep(0.4) # Pausa para estabilidad
            
            st.success(f"✅ Proceso terminado. {contador_exito} ítems clasificados correctamente.")
            st.rerun()

    # --- RENDERIZADO DE TABLAS ---
    try:
        res_db = supabase.table("items").select("*").execute()
        if res_db.data:
            df = pd.DataFrame(res_db.data)
            df['categoria'] = df['categoria'].fillna("GENERAL - SIN CLASIFICAR")
            
            for cat in sorted(df['categoria'].unique()):
                with st.expander(f"📁 {cat}", expanded=False):
                    st.dataframe(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                                 use_container_width=True, hide_index=True)
        else:
            st.info("La tabla está vacía.")
    except Exception as e:
        st.error(f"Error al cargar la tabla: {e}")
