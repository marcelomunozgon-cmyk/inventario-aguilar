import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar Pro", page_icon="🔬", layout="wide")
st.title("🔬 Gestión Inteligente Lab Aguilar")

GENAI_KEY = st.secrets["GENAI_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def cargar_modelo():
    return genai.GenerativeModel('gemini-1.5-flash')

model = cargar_modelo()

# --- PROCESAMIENTO ---
def procesar_todo(texto, imagen=None):
    prompt = f"""
    Eres un gestor de inventario. Instrucción: "{texto}"
    Responde estrictamente un JSON:
    {{
      "producto": "nombre", 
      "valor": numero, 
      "unidad": "ml/g/unidades/preparaciones",
      "accion": "sumar/reemplazar", 
      "ubicacion": "texto o null", 
      "stock_minimo": numero o null
    }}
    """
    try:
        if imagen:
            response = model.generate_content(["Identifica el producto y procesa: " + texto, imagen])
        else:
            response = model.generate_content(prompt)
            
        limpio = response.text.strip().replace('```json', '').replace('```', '')
        orden = json.loads(limpio)
        
        res = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto']}%").execute()
        if not res.data: return f"❓ No encontré '{orden['producto']}'"
        
        item = res.data[0]
        updates = {}
        
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            nueva_cant = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
            updates['cantidad_actual'] = nueva_cant
            if orden.get('unidad'): updates['unidad'] = orden['unidad']
            
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('stock_minimo') is not None: updates['stock_minimo'] = orden['stock_minimo']
        
        if updates:
            supabase.table("items").update(updates).eq("id", item['id']).execute()
            return f"✅ **{item['nombre']}** actualizado."
        return "⚠️ No se detectaron cambios."
    except Exception as e:
        return f"❌ Error: {e}"

# --- INTERFAZ ---
tab1, tab2 = st.tabs(["📸 Registro (Voz/Foto)", "📊 Inventario"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        foto = st.camera_input("📷 Foto etiqueta")
    with col2:
        instruccion = st.text_area("Comando:", placeholder="Ej: 'Suma 20 preparaciones al kit PCR'")
        if st.button("🚀 Ejecutar", use_container_width=True):
            img_pil = Image.open(foto) if foto else None
            with st.spinner("Procesando..."):
                st.success(procesar_todo(instruccion, img_pil))

with tab2:
    st.subheader("Estado del laboratorio")
    res = supabase.table("items").select("*").order("nombre").execute()
    
    if res.data:
        df = pd.DataFrame(res.data)
        
        # Función de resaltado ultra-segura
        def resaltar_stock(row):
            # Verificamos que las columnas existan y no sean None
            try:
                actual = row.get('cantidad_actual')
                minimo = row.get('stock_minimo')
                if actual is not None and minimo is not None and actual < minimo:
                    return ['background-color: #ffcccc'] * len(row)
            except:
                pass
            return [''] * len(row)

        # Si el DataFrame no está vacío, lo mostramos con estilo
        st.dataframe(df.style.apply(resaltar_stock, axis=1), use_container_width=True)
    else:
        st.info("No hay datos para mostrar.")
