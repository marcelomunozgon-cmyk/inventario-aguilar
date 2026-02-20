import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image
import pandas as pd

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Lab Aguilar Pro", page_icon="🔬", layout="wide")
st.title("🔬 Gestión Inteligente Lab Aguilar")

# Carga de Secrets
GENAI_KEY = st.secrets["GENAI_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# CONFIGURACIÓN DE GOOGLE AI (FORZANDO API V1)
genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def iniciar_modelo():
    # Usamos el nombre del modelo sin prefijos de versión para que la librería decida la mejor ruta
    try:
        # Intentamos con el nombre corto
        return genai.GenerativeModel('gemini-1.5-flash')
    except:
        # Si falla, buscamos manualmente el modelo que soporte generación
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return genai.GenerativeModel(m.name)
    return None

model = iniciar_modelo()

# --- FUNCIÓN DE PROCESAMIENTO ---
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
        # IMPORTANTE: Forzamos la respuesta de texto limpio
        if imagen:
            imagen.thumbnail((800, 800))
            response = model.generate_content([prompt, imagen])
        else:
            response = model.generate_content(prompt)
            
        # Limpieza de la respuesta para evitar el error de JSON
        texto_sucio = response.text
        # Buscamos el primer '{' y el último '}'
        inicio = texto_sucio.find('{')
        fin = texto_sucio.rfind('}') + 1
        orden = json.loads(texto_sucio[inicio:fin])
        
        # Búsqueda en Supabase
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
            return f"✅ **{item['nombre']}** actualizado: {updates}"
        return "⚠️ Sin cambios detectados."

    except Exception as e:
        # Si el error persiste, lo mostramos detallado para debuggear
        return f"❌ Error: {str(e)}"

# --- INTERFAZ ---
tab1, tab2 = st.tabs(["🎙️ Registro Rápido", "📊 Inventario Completo"])

with tab1:
    foto_archivo = st.camera_input("📷 Foto de etiqueta")
    instruccion = st.text_area("Comando:", placeholder="Ej: 'Suma 20 preparaciones al kit PCR'")
    
    if st.button("🚀 Ejecutar", use_container_width=True):
        if not instruccion and not foto_archivo:
            st.warning("Escribe una instrucción o toma una foto.")
        else:
            img_pil = Image.open(foto_archivo) if foto_archivo else None
            with st.spinner("Gemini analizando..."):
                st.write(procesar_todo(instruccion, img_pil))

with tab2:
    st.subheader("Estado actual")
    res = supabase.table("items").select("*").order("nombre").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        
        def resaltar(row):
            try:
                # Comparamos cantidad_actual vs umbral_minimo
                if pd.notnull(row['cantidad_actual']) and pd.notnull(row['umbral_minimo']):
                    if row['cantidad_actual'] < row['umbral_minimo']:
                        return ['background-color: #ffcccc'] * len(row)
            except: pass
            return [''] * len(row)

        st.dataframe(df.style.apply(resaltar, axis=1), use_container_width=True, hide_index=True)
