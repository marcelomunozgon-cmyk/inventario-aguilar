import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd

# 1. CONFIGURACIÓN INICIAL
st.set_page_config(page_title="Lab Aguilar Pro", page_icon="🔬", layout="wide")

# 2. CARGA DE SEGURIDAD PARA SECRETS
try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except Exception:
    st.error("⚠️ Error: No se encontraron los Secrets. Configúralos en Streamlit Cloud.")
    st.stop()

# 3. CONEXIONES
genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def obtener_modelo():
    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        seleccionado = next((m for m in modelos if 'flash' in m), modelos[0])
        return genai.GenerativeModel(seleccionado)
    except Exception as e:
        st.error(f"Fallo de conexión con Google AI: {e}")
        return None

model = obtener_modelo()

# 4. LÓGICA DE PROCESAMIENTO CON BUSQUEDA BORROSA
def procesar_todo(texto, imagen=None):
    prompt = f"""
    Eres un gestor de inventario. Instrucción: "{texto}"
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
            imagen.thumbnail((1000, 1000))
            response = model.generate_content([prompt, imagen])
        else:
            response = model.generate_content(prompt)
            
        raw_text = response.text
        start = raw_text.find('{')
        end = raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        # --- BÚSQUEDA ULTRA-FLEXIBLE ---
        nombre_buscado = orden['producto'].lower()
        palabras = [p for p in nombre_buscado.split() if len(p) > 2]
        
        query = supabase.table("items").select("*")
        for p in palabras:
            query = query.ilike("nombre", f"%{p}%")
        
        res = query.execute()
        
        # Si no hay match exacto, buscamos por la palabra más larga
        if not res.data and palabras:
            p_clave = max(palabras, key=len)
            res = supabase.table("items").select("*").ilike("nombre", f"%{p_clave}%").execute()

        if not res.data:
            return f"❓ No encontré nada parecido a '{nombre_buscado}'."
        
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
            return f"✅ **{item['nombre']}** actualizado."
        return "⚠️ No se detectaron cambios."
    except Exception as e:
        return f"❌ Error: {str(e)}"

# 5. INTERFAZ DE USUARIO
st.title("🔬 Sistema Lab Aguilar")

tab1, tab2 = st.tabs(["🎙️ Registro Rápido", "📊 Inventario"])

with tab1:
    foto = st.camera_input("📷 Foto (Opcional)")
    instruccion = st.text_area("Comando:", placeholder="Ej: 'Suma 20 al Opti-MEM'")
    if st.button("🚀 Ejecutar", use_container_width=True):
        if instruccion:
            img_pil = Image.open(foto) if foto else None
            with st.spinner("Procesando..."):
                resultado = procesar_todo(instruccion, img_pil)
                st.info(resultado)

with tab2:
    res = supabase.table("items").select("*").order("nombre").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        
        def resaltar(row):
            actual = row.get('cantidad_actual')
            umbral = row.get('umbral_minimo')
            if pd.notnull(actual) and pd.notnull(umbral) and actual < umbral:
                return ['background-color: #ffcccc'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(resaltar, axis=1), use_container_width=True, hide_index=True)
