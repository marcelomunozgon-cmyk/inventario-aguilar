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

# --- BARRA LATERAL (TRAZABILIDAD) ---
st.sidebar.title("👤 Sesión")
usuario = st.sidebar.selectbox("¿Quién opera?", ["Rodrigo Aguilar", "Asistente 1", "Investigador A", "Admin"])

# --- MODELO ---
@st.cache_resource
def obtener_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    seleccionado = next((m for m in modelos if 'flash' in m), modelos[0])
    return genai.GenerativeModel(seleccionado)

model = obtener_modelo()

# --- LÓGICA DE CLASIFICACIÓN Y PROCESAMIENTO ---
def procesar_inteligente(texto, imagen=None):
    prompt = f"""
    Actúa como experto en logística de laboratorios. Instrucción: "{texto}"
    1. Identifica el producto.
    2. Clasifícalo en una de estas categorías: 'Reactivos', 'Material de Vidrio', 'Consumibles', 'Equipos', 'Citoquinas/Hormonas' o 'Buffers'.
    
    Responde estrictamente un JSON:
    {{
      "producto": "nombre", 
      "valor": numero, 
      "accion": "sumar/reemplazar", 
      "categoria": "categoría detectada",
      "ubicacion": "texto o null",
      "umbral_minimo": numero o null
    }}
    """
    try:
        response = model.generate_content([prompt, imagen] if imagen else prompt)
        raw_text = response.text
        start, end = raw_text.find('{'), raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        # Búsqueda flexible
        query = supabase.table("items").select("*")
        palabras = [p for p in orden['producto'].lower().split() if len(p) > 2]
        for p in palabras: query = query.ilike("nombre", f"%{p}%")
        res = query.execute()

        if not res.data: return f"❓ No encontré '{orden['producto']}'. ¿Deseas crearlo?"
        
        item = res.data[0]
        updates = {
            "ultimo_usuario": usuario,
            "ultima_actualizacion": datetime.now().isoformat(),
            "categoria": orden['categoria'] # La IA lo clasifica al momento
        }
        
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            updates['cantidad_actual'] = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
        
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral_minimo'): updates['umbral_minimo'] = orden['umbral_minimo']
        
        supabase.table("items").update(updates).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado por **{usuario}**. Categoría: {orden['categoria']}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- INTERFAZ ---
st.title("🔬 Gestión y Clasificación Lab Aguilar")

tab1, tab2, tab3 = st.tabs(["🎙️ Registrar Movimiento", "📊 Inventario Clasificado", "📈 Datos para Proveedores"])

with tab1:
    foto = st.camera_input("Capturar etiqueta")
    instruccion = st.text_area("Comando de voz o texto:", placeholder="Ej: 'Se usaron 2 de Optimem'")
    if st.button("🚀 Procesar", use_container_width=True):
        with st.spinner("Clasificando..."):
            img_pil = Image.open(foto) if foto else None
            st.info(procesar_inteligente(instruccion, img_pil))

with tab2:
    res = supabase.table("items").select("*").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        # ORGANIZACIÓN POR CATEGORÍA
        categorias = df['categoria'].unique()
        for cat in categorias:
            with st.expander(f"📁 {cat if cat else 'Sin Clasificar'}"):
                sub_df = df[df['categoria'] == cat]
                st.dataframe(sub_df[['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada', 'ultimo_usuario']], use_container_width=True)

with tab3:
    st.subheader("📊 Inteligencia de Consumo (Valor para Proveedores)")
    st.write("Esta sección muestra qué categorías tienen más rotación.")
    if res.data:
        # Aquí crearíamos un gráfico simple de qué se usa más
        conteo_cat = df['categoria'].value_counts()
        st.bar_chart(conteo_cat)
