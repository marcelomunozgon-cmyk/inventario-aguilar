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
    Eres un gestor de inventario de laboratorio. Analiza la instrucción: "{texto}"
    Identifica: producto, valor numérico, unidad (ml, g, preparaciones, etc), 
    acción (sumar/reemplazar), ubicación y umbral_minimo.
    
    Responde estrictamente un JSON:
    {{
      "producto": "nombre", 
      "valor": numero, 
      "unidad": "unidad o null",
      "accion": "sumar/reemplazar", 
      "ubicacion": "texto o null", 
      "umbral_minimo": numero o null
    }}
    """
    try:
        if imagen:
            response = model.generate_content(["Identifica el producto y su etiqueta, luego procesa: " + texto, imagen])
        else:
            response = model.generate_content(prompt)
            
        limpio = response.text.strip().replace('```json', '').replace('```', '')
        orden = json.loads(limpio)
        
        # Búsqueda flexible
        res = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto']}%").execute()
        if not res.data: return f"❓ No encontré nada parecido a '{orden['producto']}'"
        
        item = res.data[0]
        updates = {}
        
        # Lógica de Cantidad
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            nueva_cant = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
            updates['cantidad_actual'] = nueva_cant
            if orden.get('unidad'): updates['unidad'] = orden['unidad']
            
        # Lógica de Otros Campos (Ajustado a 'umbral_minimo')
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral_minimo') is not None: updates['umbral_minimo'] = orden['umbral_minimo']
        
        if updates:
            supabase.table("items").update(updates).eq("id", item['id']).execute()
            return f"✅ **{item['nombre']}** actualizado correctamente."
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
        instruccion = st.text_area("Comando:", placeholder="Ej: 'Fija el umbral mínimo en 10 para el kit PCR'")
        if st.button("🚀 Ejecutar", use_container_width=True):
            img_pil = Image.open(foto) if foto else None
            with st.spinner("Procesando..."):
                st.success(procesar_todo(instruccion, img_pil))

with tab2:
    st.subheader("Estado del laboratorio")
    res = supabase.table("items").select("*").order("nombre").execute()
    
    if res.data:
        df = pd.DataFrame(res.data)
        
        def resaltar_stock(row):
            try:
                actual = row.get('cantidad_actual')
                umbral = row.get('umbral_minimo') # Usamos el nombre real de tu DB
                if actual is not None and umbral is not None and actual < umbral:
                    return ['background-color: #ffcccc'] * len(row)
            except:
                pass
            return [''] * len(row)

        st.dataframe(df.style.apply(resaltar_stock, axis=1), use_container_width=True, hide_index=True)
    else:
        st.info("No hay datos cargados.")
