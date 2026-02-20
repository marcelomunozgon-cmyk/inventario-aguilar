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

# --- SOLUCIÓN AL ERROR 404: AUTO-DETECCIÓN DE MODELO ---
@st.cache_resource
def obtener_modelo_seguro():
    try:
        # Listamos los modelos y buscamos uno que soporte 'generateContent'
        modelos_disponibles = [m.name for m in genai.list_models() 
                               if 'generateContent' in m.supported_generation_methods]
        
        # Prioridad 1: Gemini 1.5 Flash (más rápido)
        # Prioridad 2: Gemini 1.5 Pro
        # Prioridad 3: El primero que aparezca en la lista
        seleccionado = next((m for m in modelos_disponibles if 'flash' in m), 
                            next((m for m in modelos_disponibles if 'pro' in m), 
                            modelos_disponibles[0]))
        
        return genai.GenerativeModel(seleccionado)
    except Exception as e:
        st.error(f"Error crítico de conexión: {e}")
        return None

model = obtener_modelo_seguro()

# --- PROCESAMIENTO ---
def procesar_todo(texto, imagen=None):
    prompt = f"""
    Analiza esta instrucción de inventario: "{texto}"
    Responde estrictamente un JSON válido:
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
        # Llamada a la IA
        if imagen:
            # Optimizamos la imagen para evitar errores de peso
            imagen.thumbnail((1000, 1000))
            response = model.generate_content([prompt, imagen])
        else:
            response = model.generate_content(prompt)
            
        # Limpieza quirúrgica de la respuesta JSON
        raw_text = response.text
        start = raw_text.find('{')
        end = raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        # Búsqueda en Supabase (Case-insensitive)
        res = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto']}%").execute()
        if not res.data: return f"❓ No encontré '{orden['producto']}' en el inventario."
        
        item = res.data[0]
        updates = {}
        
        # Lógica de Cantidad
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            nueva_cant = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
            updates['cantidad_actual'] = nueva_cant
            if orden.get('unidad'): updates['unidad'] = orden['unidad']
            
        # Lógica de Umbral y Ubicación
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral_minimo') is not None: updates['umbral_minimo'] = orden['umbral_minimo']
        
        if updates:
            supabase.table("items").update(updates).eq("id", item['id']).execute()
            return f"✅ **{item['nombre']}** actualizado correctamente."
        return "⚠️ No se detectaron cambios."

    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- INTERFAZ ---
tab1, tab2 = st.tabs(["🎙️ Registro Rápido", "📊 Inventario"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        foto = st.camera_input("📷 Foto de etiqueta")
    with col2:
        st.info("💡 Usa el micrófono de tu teclado para dictar.")
        instruccion = st.text_area("¿Qué deseas hacer?", placeholder="Ej: 'Fija el umbral mínimo en 10 para el kit PCR'")
        if st.button("🚀 Ejecutar", use_container_width=True):
            img_pil = Image.open(foto) if foto else None
            with st.spinner("Analizando..."):
                st.success(procesar_todo(instruccion, img_pil))

with tab2:
    st.subheader("Estado actual")
    res = supabase.table("items").select("*").order("nombre").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        
        def resaltar(row):
            # Comparamos cantidad vs umbral_minimo (nombre de tu columna)
            if pd.notnull(row.get('cantidad_actual')) and pd.notnull(row.get('umbral_minimo')):
                if row['cantidad_actual'] < row['umbral_minimo']:
                    return ['background-color: #ffcccc'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(resaltar, axis=1), use_container_width=True, hide_index=True)
