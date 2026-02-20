import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar Pro", page_icon="🔬", layout="wide")
st.title("🔬 Gestión Inteligente Lab Aguilar")

# Carga de Secrets
GENAI_KEY = st.secrets["GENAI_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def cargar_modelo():
    return genai.GenerativeModel('gemini-1.5-flash')

model = cargar_modelo()

# --- FUNCIÓN DE PROCESAMIENTO MULTIMODAL ---
def procesar_todo(texto, imagen=None):
    prompt = f"""
    Instrucción: "{texto}"
    Eres un gestor de inventario de laboratorio. Extrae los datos y sé preciso con las UNIDADES (litros, ml, gramos, kits, preparaciones, botellas).
    
    Responde estrictamente un JSON:
    {{
      "producto": "nombre", 
      "valor": numero, 
      "unidad": "ml/g/unidades/preparaciones/etc",
      "accion": "sumar/reemplazar", 
      "ubicacion": "texto o null", 
      "stock_minimo": numero o null
    }}
    """
    
    try:
        if imagen:
            response = model.generate_content(["Identifica el producto y procesa esta instrucción: " + texto, imagen])
        else:
            response = model.generate_content(prompt)
            
        limpio = response.text.strip().replace('```json', '').replace('```', '')
        orden = json.loads(limpio)
        
        # Búsqueda en DB
        res = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto']}%").execute()
        
        if not res.data: return f"❓ No encontré '{orden['producto']}' en la base de datos."
        
        item = res.data[0]
        updates = {}
        
        # Lógica de Cantidad y Unidades
        if orden.get('valor') is not None:
            nueva_cant = (item['cantidad_actual'] or 0) + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
            updates['cantidad_actual'] = nueva_cant
            if orden.get('unidad'): updates['unidad'] = orden['unidad']
            
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('stock_minimo'): updates['stock_minimo'] = orden['stock_minimo']
        
        supabase.table("items").update(updates).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado correctamente."
    except Exception as e:
        return f"❌ Error: {e}"

# --- INTERFAZ DE USUARIO ---
tab1, tab2 = st.tabs(["📸 Registro Rápido (Voz/Foto)", "📊 Inventario Completo"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        foto = st.camera_input("📷 Foto de la etiqueta")
    with col2:
        st.info("💡 **Tip para Voz:** Toca el cuadro de abajo y usa el 🎙️ de tu teclado.")
        instruccion = st.text_area("¿Qué quieres hacer?", placeholder="Ej: 'Agrega 500ml de Etanol' o 'Quedan 20 preparaciones del Kit PCR'")
        
        if st.button("🚀 Ejecutar Instrucción", use_container_width=True):
            img_pil = Image.open(foto) if foto else None
            with st.spinner("Procesando..."):
                resultado = procesar_todo(instruccion, img_pil)
                st.success(resultado)

with tab2:
    st.subheader("Estado actual del laboratorio")
    res = supabase.table("items").select("*").order("nombre").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        # Resaltar en rojo si falta stock
        def resaltar_stock(row):
            if row['stock_minimo'] and row['cantidad_actual'] < row['stock_minimo']:
                return ['background-color: #ffcccc'] * len(row)
            return [''] * len(row)
        
        st.dataframe(df.style.apply(resaltar_stock, axis=1), use_container_width=True)
