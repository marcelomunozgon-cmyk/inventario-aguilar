import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar Business", page_icon="🔬", layout="wide")

GENAI_KEY = st.secrets["GENAI_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- USUARIO Y SESIÓN ---
st.sidebar.title("👤 Usuario")
usuario = st.sidebar.selectbox("Operador:", ["Rodrigo Aguilar", "Asistente 1", "Investigador A", "Admin"])

@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    seleccionado = next((m for m in modelos if 'flash' in m), modelos[0])
    return genai.GenerativeModel(seleccionado)

model = obtener_modelo()

# --- LÓGICA DE PROCESAMIENTO ---
def procesar_inteligente(texto, imagen=None):
    prompt = f"""
    Instrucción: "{texto}"
    Clasifica en: 'Reactivos', 'Consumibles', 'Vidriería', 'Equipos' o 'Buffers'.
    Responde JSON: {{"producto": "nombre", "valor": numero, "accion": "sumar/reemplazar", "categoria": "categoría", "ubicacion": "texto", "umbral_minimo": numero}}
    """
    try:
        response = model.generate_content([prompt, imagen] if imagen else prompt)
        raw_text = response.text
        start, end = raw_text.find('{'), raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        # Búsqueda borrosa
        palabras = [p for p in orden['producto'].lower().split() if len(p) > 2]
        query = supabase.table("items").select("*")
        for p in palabras: query = query.ilike("nombre", f"%{p}%")
        res = query.execute()

        if not res.data: return f"❓ No encontré '{orden['producto']}'."
        
        item = res.data[0]
        updates = {
            "ultimo_usuario": usuario,
            "ultima_actualizacion": datetime.now().isoformat(),
            "categoria": orden['categoria']
        }
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            updates['cantidad_actual'] = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral_minimo'): updates['umbral_minimo'] = orden['umbral_minimo']
        
        supabase.table("items").update(updates).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado en **{orden['categoria']}**."
    except Exception as e: return f"❌ Error: {str(e)}"

# --- INTERFAZ ---
tab1, tab2 = st.tabs(["🎙️ Registrar / Editar", "📂 Inventario Organizado"])

with tab1:
    foto = st.camera_input("Foto etiqueta")
    instruccion = st.text_area("¿Qué hiciste?", placeholder="Ej: 'Mueve el Etanol al Estante 2 y pon umbral 5'")
    if st.button("🚀 Ejecutar", use_container_width=True):
        with st.spinner("Procesando..."):
            img_pil = Image.open(foto) if foto else None
            st.info(procesar_inteligente(instruccion, img_pil))

with tab2:
    st.subheader("📦 Almacén por Categorías")
    
    # Buscador rápido dentro de la tabla
    busqueda = st.text_input("🔍 Buscar por nombre en todo el inventario...", "")
    
    res = supabase.table("items").select("*").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        
        # Filtro de búsqueda
        if busqueda:
            df = df[df['nombre'].str.contains(busqueda, case=False, na=False)]
        
        # Agrupar por categoría
        df['categoria'] = df['categoria'].fillna("Sin Clasificar")
        categorias = sorted(df['categoria'].unique())
        
        for cat in categorias:
            df_cat = df[df['categoria'] == cat]
            with st.expander(f"{cat} ({len(df_cat)} ítems)"):
                # Formatear tabla para que sea legible
                st.dataframe(
                    df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada', 'umbral_minimo']],
                    use_container_width=True,
                    hide_index=True
                )
    else:
        st.warning("No hay datos en la base de datos.")
