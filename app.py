import streamlit as st
import google.generativeai as genai
from supabase import create_client
import json
from PIL import Image

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar Pro", page_icon="🔬")
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

# --- FUNCIONES CORE ---
def procesar_todo(texto, imagen=None):
    # Prompt maestro que entiende actualización de múltiples variables
    prompt = f"""
    Instrucción: "{texto}"
    Tu tarea es extraer cambios para el inventario. 
    Campos posibles: nombre, cantidad (valor), accion (sumar/reemplazar), ubicacion, stock_minimo.
    Responde estrictamente un JSON:
    {{"producto": "nombre", "valor": numero, "accion": "sumar/reemplazar", "ubicacion": "texto o null", "stock_minimo": numero o null}}
    """
    
    try:
        if imagen:
            # Si hay imagen, Gemini lee la etiqueta primero
            response = model.generate_content(["Identifica el nombre del producto en esta etiqueta de laboratorio y luego ejecuta esta instrucción: " + texto, imagen])
        else:
            response = model.generate_content(prompt)
            
        limpio = response.text.strip().replace('```json', '').replace('```', '')
        orden = json.loads(limpio)
        
        # Búsqueda en DB
        res = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto']}%").execute()
        
        if not res.data: return f"❓ No encontré '{orden['producto']}'"
        
        item = res.data[0]
        updates = {}
        
        # Lógica de Cantidad
        if orden.get('valor') is not None:
            nueva_cant = (item['cantidad_actual'] or 0) + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
            updates['cantidad_actual'] = nueva_cant
            
        # Lógica de Otros Campos
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('stock_minimo'): updates['stock_minimo'] = orden['stock_minimo']
        
        if updates:
            supabase.table("items").update(updates).eq("id", item['id']).execute()
            return f"✅ **{item['nombre']}** actualizado: {updates}"
        return "⚠️ No se detectaron cambios."
    except Exception as e:
        return f"❌ Error: {e}"

# --- INTERFAZ ---
tab1, tab2, tab3 = st.tabs(["📸 Cámara/Voz", "📊 Stock Crítico", "📋 Todo"])

with tab1:
    foto = st.camera_input("Tomar foto a la etiqueta (Opcional)")
    instruccion = st.text_input("Comando (Voz/Texto)", placeholder="Ej: 'Cambia stock mínimo a 5 y mueve a estante 2'")
    
    if st.button("Ejecutar", use_container_width=True):
        img_pil = Image.open(foto) if foto else None
        resultado = procesar_todo(instruccion, img_pil)
        st.info(resultado)

with tab2:
    st.subheader("⚠️ Debes reponer:")
    # Filtrar donde cantidad < stock_minimo
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    if not df.empty and 'stock_minimo' in df.columns:
        criticos = df[df['cantidad_actual'] < df['stock_minimo']]
        st.table(criticos[['nombre', 'cantidad_actual', 'stock_minimo']])
    else:
        st.write("Todo en orden.")

with tab3:
    res_all = supabase.table("items").select("*").order("nombre").execute()
    st.dataframe(res_all.data, use_container_width=True)
