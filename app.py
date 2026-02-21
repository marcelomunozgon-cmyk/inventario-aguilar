import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd
from datetime import datetime
import time

# --- 1. CONFIGURACIÓN ---
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

# --- 2. FUNCIONES DE INTELIGENCIA ---
def clasificar_jerarquico(nombre):
    # Prompt reforzado para español y términos técnicos
    prompt = f"""
    Como experto en laboratorio bilingüe, clasifica el ítem: '{nombre}'.
    Formato: 'Categoría Padre - Subcategoría'.
    Ejemplos: 
    - Ácido Clorhídrico -> 'Reactivos - Ácidos'
    - Puntas amarillas -> 'Consumibles - Plásticos'
    - Agitador magnético -> 'Equipos - Mezcla'
    - Vaso precipitado -> 'Vidriería - Recipientes'
    
    Responde solo el formato solicitado, sé breve.
    """
    try:
        res = model.generate_content(prompt)
        return res.text.strip().replace("'", "").replace('"', '').replace('>', '-')
    except: return "General - Sin clasificar"

def procesar_instruccion(texto, imagen=None):
    prompt = f"""
    Instrucción: "{texto}"
    Analiza y extrae los datos para el inventario en un JSON:
    {{
      "producto": "nombre del producto",
      "valor": numero,
      "accion": "sumar" (si dice 'llegaron/agregué') o "reemplazar" (si dice 'hay/quedan'),
      "ubicacion": "texto o null",
      "umbral": numero o null
    }}
    """
    try:
        response = model.generate_content([prompt, imagen] if imagen else prompt)
        raw_text = response.text
        start, end = raw_text.find('{'), raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        # Búsqueda borrosa en DB
        palabras = [p for p in orden['producto'].lower().split() if len(p) > 2]
        query = supabase.table("items").select("*")
        for p in palabras: query = query.ilike("nombre", f"%{p}%")
        res = query.execute()

        if not res.data: return f"❓ No encontré nada similar a '{orden['producto']}'."
        
        item = res.data[0]
        updates = {"ultima_actualizacion": datetime.now().isoformat()}
        
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            updates['cantidad_actual'] = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral'): updates['umbral_minimo'] = orden['umbral']
        
        supabase.table("items").update(updates).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado correctamente."
    except Exception as e: return f"❌ Error: {str(e)}"

# --- 3. INTERFAZ ---
st.title("🔬 Sistema Inteligente Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro de Actividad", "📂 Inventario por Carpetas"])

with tab1:
    col_cam, col_txt = st.columns(2)
    with col_cam:
        foto = st.camera_input("📷 Foto de etiqueta o reactivo")
    with col_txt:
        instruccion = st.text_area("¿Qué quieres registrar?", placeholder="Ej: 'Llegaron 5 botellas de Etanol' o 'Solo quedan 2 cajas de guantes'")
        if st.button("🚀 Ejecutar Registro", use_container_width=True):
            with st.spinner("Analizando..."):
                img_pil = Image.open(foto) if foto else None
                resultado = procesar_instruccion(instruccion, img_pil)
                st.info(resultado)

with tab2:
    col_btn, col_search = st.columns([1, 2])
    with col_btn:
        if st.button("🤖 RE-CLASIFICAR CARPETAS", use_container_width=True, type="primary"):
            res_items = supabase.table("items").select("id", "nombre").execute()
            items = res_items.data
            progreso = st.progress(0)
            status = st.empty()
            
            for i, item in enumerate(items):
                try:
                    ruta = clasificar_jerarquico(item['nombre'])
                    supabase.table("items").update({"categoria": ruta}).eq("id", item['id']).execute()
                    status.text(f"📁 {item['nombre']} -> {ruta}")
                except: continue
                progreso.progress((i + 1) / len(items))
            st.success("¡Clasificación terminada!")
            st.rerun()
    
    with col_search:
        busqueda = st.text_input("🔍 Buscar en inventario...")

    # Renderizado Jerárquico
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        if busqueda:
            df = df[df['nombre'].str.contains(busqueda, case=False)]
        
        df['categoria'] = df['categoria'].fillna("General - Sin clasificar")
        # Aseguramos formato 'Padre - Hijo'
        df[['Padre', 'Hijo']] = df['categoria'].str.split('-', n=1, expand=True).fillna("General")
        
        for p in sorted(df['Padre'].unique()):
            with st.expander(f"📁 {p.strip().upper()}", expanded=False):
                df_p = df[df['Padre'] == p]
                for h in sorted(df_p['Hijo'].unique()):
                    st.markdown(f"**📍 {h.strip()}**")
                    df_h = df_p[df_p['Hijo'] == h]
                    st.dataframe(df_h[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                                 use_container_width=True, hide_index=True)
