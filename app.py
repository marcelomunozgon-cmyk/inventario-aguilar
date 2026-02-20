import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Lab Aguilar", page_icon="🔬")
st.title("🔬 Inventario Lab Aguilar")

# --- CONEXIÓN A SECRETS ---
try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except Exception:
    st.error("Faltan los Secrets en Streamlit Cloud. Configúralos en Settings > Secrets.")
    st.stop()

# Configurar APIs
genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- AUTO-DETECTAR MODELO ---
@st.cache_resource
def cargar_modelo():
    modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    seleccionado = next((m for m in modelos if 'gemini-1.5-flash' in m), modelos[0])
    return genai.GenerativeModel(seleccionado)

model = cargar_modelo()

# --- LÓGICA DE NEGOCIO ---
def procesar_instruccion(texto):
    prompt = f"""
    Instrucción: "{texto}"
    Analiza si el usuario quiere SUMAR o REEMPLAZAR.
    Responde ÚNICAMENTE un JSON:
    {{"producto": "nombre aproximado", "valor": numero, "accion": "sumar" o "reemplazar"}}
    """
    try:
        response = model.generate_content(prompt)
        limpio = response.text.strip().replace('```json', '').replace('```', '')
        orden = json.loads(limpio)
        
        # Búsqueda flexible en Supabase
        palabras = orden['producto'].lower().split()
        query = supabase.table("items").select("*")
        for p in palabras:
            if len(p) > 2: query = query.ilike("nombre", f"%{p}%")
        
        res = query.execute()
        
        if not res.data:
            return f"❓ No encontré nada parecido a '{orden['producto']}'"
        
        item = res.data[0]
        nueva_cant = (item.get('cantidad_actual', 0) or 0) + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
        
        supabase.table("items").update({"cantidad_actual": nueva_cant}).eq("id", item['id']).execute()
        return f"✅ **{item['nombre']}** actualizado a **{nueva_cant}**"
    except Exception as e:
        return f"❌ Error: {e}"

# --- INTERFAZ MÓVIL ---
tab1, tab2 = st.tabs(["🎙️ Voz / Texto", "📊 Inventario"])

with tab1:
    st.write("Dicta o escribe tu instrucción:")
    # El móvil detecta automáticamente el micrófono aquí
    instruccion = st.text_input("Ej: 'Agrega 10 al kit pcr'", key="input_voz")
    
    if st.button("🚀 Ejecutar", use_container_width=True):
        if instruccion:
            with st.spinner("Interpretando..."):
                resultado = procesar_instruccion(instruccion)
                st.info(resultado)
        else:
            st.warning("Escribe algo primero.")

with tab2:
    if st.button("🔄 Actualizar Tabla", use_container_width=True):
        st.rerun()
    
    res_db = supabase.table("items").select("nombre, cantidad_actual, ubicacion_detallada").order("nombre").execute()
    if res_db.data:
        st.dataframe(res_db.data, use_container_width=True, hide_index=True)
