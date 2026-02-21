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

GENAI_KEY = st.secrets["GENAI_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- MODELO ---
@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    seleccionado = next((m for m in modelos if 'flash' in m), modelos[0])
    return genai.GenerativeModel(seleccionado)

model = obtener_modelo()

# --- FUNCIONES DE CLASIFICACIÓN ---
def clasificar_texto(nombre_item):
    prompt = f"Clasifica este objeto de laboratorio: '{nombre_item}'. Responde SOLO la categoría (Reactivos, Consumibles, Vidriería, Equipos, Buffers o Anticuerpos)."
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return "Sin Clasificar"

def procesar_inteligente(texto, imagen=None):
    prompt = f"""
    Instrucción: "{texto}"
    Responde JSON: {{"producto": "nombre", "valor": numero, "accion": "sumar/reemplazar", "categoria": "categoría", "ubicacion": "texto", "umbral_minimo": numero}}
    """
    try:
        response = model.generate_content([prompt, imagen] if imagen else prompt)
        raw_text = response.text
        start, end = raw_text.find('{'), raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        palabras = [p for p in orden['producto'].lower().split() if len(p) > 2]
        query = supabase.table("items").select("*")
        for p in palabras: query = query.ilike("nombre", f"%{p}%")
        res = query.execute()

        if not res.data: return f"❓ No encontré '{orden['producto']}'."
        
        item = res.data[0]
        updates = {
            "ultima_actualizacion": datetime.now().isoformat(),
            "categoria": orden['categoria']
        }
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            updates['cantidad_actual'] = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral_minimo'): updates['umbral_minimo'] = orden['umbral_minimo']
        
        supabase.table("items").update(updates).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado."
    except Exception as e: return f"❌ Error: {str(e)}"

# --- INTERFAZ ---
tab1, tab2, tab3 = st.tabs(["🎙️ Registro", "📂 Inventario Organizado", "⚙️ Admin"])

with tab1:
    foto = st.camera_input("Foto etiqueta")
    instruccion = st.text_area("¿Qué hiciste?", placeholder="Ej: 'Llegaron 5 de Optimem'")
    if st.button("🚀 Ejecutar", use_container_width=True):
        img_pil = Image.open(foto) if foto else None
        st.info(procesar_inteligente(instruccion, img_pil))

with tab2:
    busqueda = st.text_input("🔍 Buscar reactivo...", "")
    res = supabase.table("items").select("*").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        if busqueda:
            df = df[df['nombre'].str.contains(busqueda, case=False, na=False)]
        
        df['categoria'] = df['categoria'].fillna("Sin Clasificar")
        for cat in sorted(df['categoria'].unique()):
            df_cat = df[df['categoria'] == cat]
            with st.expander(f"📁 {cat} ({len(df_cat)})"):
                st.dataframe(df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], use_container_width=True, hide_index=True)

with tab3:
    st.header("Herramientas de Inteligencia")
    if st.button("🤖 Auto-Clasificar Inventario Completo"):
        res = supabase.table("items").select("id", "nombre").is_("categoria", "null").execute()
        if not res.data:
            st.success("¡Todos los ítems ya tienen categoría!")
        else:
            progreso = st.progress(0)
            status = st.empty()
            total = len(res.data)
            
            for i, item in enumerate(res.data):
                nueva_cat = clasificar_texto(item['nombre'])
                supabase.table("items").update({"categoria": nueva_cat}).eq("id", item['id']).execute()
                progreso.progress((i + 1) / total)
                status.text(f"Clasificando: {item['nombre']} -> {nueva_cat}")
                time.sleep(0.1) # Evitar saturar la API
            
            st.success(f"✅ ¡Se han clasificado {total} ítems exitosamente!")
            st.rerun()
