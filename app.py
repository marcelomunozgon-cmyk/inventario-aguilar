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
except:
    st.error("Error de configuración.")
    st.stop()

@st.cache_resource
def obtener_modelo():
    return genai.GenerativeModel('gemini-1.5-flash') # Usamos Flash que es más eficiente en cuotas

model = obtener_modelo()

# --- INTERFAZ ---
st.title("🔬 Monitor Lab Aguilar (Optimizado)")

col_control, col_monitor = st.columns([1, 2], gap="large")

with col_control:
    st.subheader("🎮 Control")
    with st.container(border=True):
        instruccion = st.text_area("🎙️ Instrucción:", placeholder="Ej: 'Se gastó 1 Etanol'")
        
        if st.button("🚀 Ejecutar", use_container_width=True, type="primary"):
            # Aquí procesarías el comando solo si la cuota lo permite
            st.info("Procesando comando...")

    # BOTÓN DE CLASIFICACIÓN INTELIGENTE (Solo lo que falta)
    if st.button("🤖 Clasificar pendientes (Ahorro de Cuota)"):
        # Buscamos solo los que NO tienen categoría
        res = supabase.table("items").select("id", "nombre").is_("categoria", "null").execute()
        items_pendientes = res.data
        
        if not items_pendientes:
            st.success("✅ ¡Todo el inventario ya está clasificado!")
        else:
            st.warning(f"Clasificando {len(items_pendientes)} ítems faltantes...")
            progreso = st.progress(0)
            for i, item in enumerate(items_pendientes):
                try:
                    # Prompt ultra-corto para ahorrar tokens
                    res_ai = model.generate_content(f"Clasifica: {item['nombre']}. Formato: CATEGORIA - TIPO")
                    cat = res_ai.text.strip().upper()
                    supabase.table("items").update({"categoria": cat}).eq("id", item['id']).execute()
                    time.sleep(3) # Pausa larga para no activar el error 429
                    progreso.progress((i+1)/len(items_pendientes))
                except Exception as e:
                    if "429" in str(e):
                        st.error("⚠️ Límite de Google alcanzado. Espera 1 minuto para continuar.")
                        break
            st.rerun()

with col_monitor:
    st.subheader("📊 Inventario")
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        df['categoria'] = df['categoria'].fillna("⚠️ SIN CLASIFICAR")
        
        # Filtro rápido
        busqueda = st.text_input("🔍 Buscar...")
        if busqueda:
            df = df[df['nombre'].str.contains(busqueda, case=False)]

        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}"):
                st.dataframe(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad']], 
                             use_container_width=True, hide_index=True)
