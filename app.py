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
try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except Exception:
    st.error("Error al cargar st.secrets. Asegúrate de haberlos configurado en Streamlit Cloud.")
    st.stop()

# Configurar APIs
genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- CONEXIÓN ROBUSTA AL MODELO ---
@st.cache_resource
def iniciar_modelo():
    # Intentamos conectar con el nombre estándar que funciona en el 99% de los casos
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        # Prueba rápida para ver si responde
        return model
    except Exception:
        # Si falla, buscamos el primer modelo disponible que soporte contenido
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return genai.GenerativeModel(m.name)
    return None

model = iniciar_modelo()

if model is None:
    st.error("No se pudo conectar con ningún modelo de Gemini. Revisa tu API Key.")
    st.stop()

# --- PROCESAMIENTO ---
def procesar_todo(texto, imagen=None):
    prompt = f"""
    Eres un gestor de inventario de laboratorio. Analiza la instrucción: "{texto}"
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
            # Redimensionar imagen para asegurar que no exceda límites de la API
            imagen.thumbnail((800, 800))
            response = model.generate_content(["Identifica el producto y procesa: " + texto, imagen])
        else:
            response = model.generate_content(prompt)
            
        limpio = response.text.strip().replace('```json', '').replace('```', '')
        # Si la IA pone texto antes o después del JSON, esto lo limpia:
        start = limpio.find('{')
        end = limpio.rfind('}') + 1
        orden = json.loads(limpio[start:end])
        
        # Búsqueda flexible en Supabase
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
        if orden.get('umbral_minimo') is not None: updates['umbral_minimo'] = orden['umbral_minimo']
        
        if updates:
            supabase.table("items").update(updates).eq("id", item['id']).execute()
            return f"✅ **{item['nombre']}** actualizado correctamente."
        return "⚠️ No se detectaron cambios."
    except Exception as e:
        return f"❌ Error de procesamiento: {str(e)}"

# --- INTERFAZ ---
tab1, tab2 = st.tabs(["📸 Registro (Voz/Foto)", "📊 Inventario"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        foto_archivo = st.camera_input("📷 Foto etiqueta")
    with col2:
        instruccion = st.text_area("Comando:", placeholder="Ej: 'Fija el umbral mínimo en 10 para el kit PCR'")
        if st.button("🚀 Ejecutar", use_container_width=True):
            img_pil = Image.open(foto_archivo) if foto_archivo else None
            with st.spinner("Procesando..."):
                resultado = procesar_todo(instruccion, img_pil)
                st.write(resultado)

with tab2:
    st.subheader("Estado del laboratorio")
    if st.button("🔄 Refrescar datos"):
        st.rerun()
        
    res = supabase.table("items").select("*").order("nombre").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        
        def resaltar_stock(row):
            actual = row.get('cantidad_actual')
            umbral = row.get('umbral_minimo')
            if pd.notnull(actual) and pd.notnull(umbral) and actual < umbral:
                return ['background-color: #ffcccc'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(resaltar_stock, axis=1), use_container_width=True, hide_index=True)
