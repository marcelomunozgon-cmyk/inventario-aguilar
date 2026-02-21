import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
from PIL import Image
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", page_icon="🔬", layout="wide")

# Conexiones (Secrets)
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
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    return genai.GenerativeModel(next((m for m in modelos if 'flash' in m), modelos[0]))

model = obtener_modelo()

# --- LÓGICA DE PROCESAMIENTO ---
def procesar_comando(texto, imagen=None):
    prompt = f"""
    Eres el asistente del Lab Aguilar. Instrucción: "{texto}"
    Extrae un JSON:
    {{
      "producto": "nombre",
      "valor": numero,
      "accion": "sumar/reemplazar",
      "ubicacion": "texto o null"
    }}
    """
    try:
        response = model.generate_content([prompt, imagen] if imagen else prompt)
        orden = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
        
        # Búsqueda en DB
        res = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto']}%").execute()
        if not res.data: return f"❓ No encontré '{orden['producto']}'."
        
        item = res.data[0]
        actual = item.get('cantidad_actual') or 0
        nueva_qty = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
        
        updates = {"cantidad_actual": nueva_qty, "ultima_actualizacion": datetime.now().isoformat()}
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        
        supabase.table("items").update(updates).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado a **{nueva_qty} {item['unidad']}**."
    except Exception as e: return f"❌ Error: {str(e)}"

# --- INTERFAZ DASHBOARD (DOS COLUMNAS) ---
st.title("🔬 Monitor de Inventario en Vivo - Lab Aguilar")

col_control, col_monitor = st.columns([1, 2], gap="large")

# COLUMNA IZQUIERDA: ENTRADA DE DATOS
with col_control:
    st.subheader("🎮 Panel de Control")
    with st.container(border=True):
        foto = st.camera_input("📷 Cámara (Etiquetas)")
        instruccion = st.text_area("🎙️ Comando de voz o texto:", 
                                  placeholder="Ej: 'Se gastaron 2 kits de PCR' o 'Hay 5 de Etanol en el Estante B'",
                                  height=100)
        
        if st.button("🚀 Ejecutar Cambio", use_container_width=True, type="primary"):
            with st.spinner("Procesando..."):
                img_pil = Image.open(foto) if foto else None
                resultado = procesar_comando(instruccion, img_pil)
                st.toast(resultado) # Notificación rápida en la esquina
                st.info(resultado)

# COLUMNA DERECHA: MONITOR EN VIVO
with col_monitor:
    st.subheader("📊 Vista del Inventario")
    
    # Buscador rápido arriba de la tabla
    busqueda = st.text_input("🔍 Filtrar tabla al instante...", "")
    
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        
        # Aplicar filtro de búsqueda si existe
        if busqueda:
            df = df[df['nombre'].str.contains(busqueda, case=False, na=False)]
            
        # Organizar por Carpetas (Expanders)
        df['categoria'] = df['categoria'].fillna("GENERAL - SIN CLASIFICAR")
        for cat in sorted(df['categoria'].unique()):
            df_cat = df[df['categoria'] == cat]
            with st.expander(f"📁 {cat} ({len(df_cat)})", expanded=True if busqueda else False):
                st.dataframe(
                    df_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']],
                    use_container_width=True,
                    hide_index=True
                )
    else:
        st.info("No hay datos para mostrar.")
