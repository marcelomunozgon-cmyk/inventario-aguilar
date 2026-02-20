import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd

# 1. Configuración de la Interfaz
st.set_page_config(page_title="Lab Aguilar Inventario", layout="centered")
st.title("🔬 Inventario Lab Aguilar")

# 2. Conexión (Usar secretos de Streamlit para seguridad)
GENAI_KEY = st.secrets["GENAI_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

genai.configure(api_key=GENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- FUNCIONES LÓGICAS ---
def actualizar_stock(texto):
    prompt = f"Instrucción: '{texto}'. Responde solo JSON: {{'producto': 'nombre', 'valor': numero, 'accion': 'sumar'/'reemplazar'}}"
    response = model.generate_content(prompt)
    orden = pd.read_json(response.text.strip('`json\n')) # Simplificado para el ejemplo
    
    # Búsqueda flexible
    query = supabase.table("items").select("*").ilike("nombre", f"%{orden['producto'][0]}%").execute()
    if query.data:
        item = query.data[0]
        nueva_cant = (item['cantidad_actual'] + orden['valor'][0]) if orden['accion'][0] == 'sumar' else orden['valor'][0]
        supabase.table("items").update({"cantidad_actual": nueva_cant}).eq("id", item['id']).execute()
        return f"✅ {item['nombre']}: {nueva_cant}"
    return "❓ No encontrado"

# --- INTERFAZ DEL CELULAR ---

tab1, tab2 = st.tabs(["🎙️ Control Voz", "📊 Ver Inventario"])

with tab1:
    st.subheader("Dictar Movimiento")
    # En el celular, al tocar aquí se abre el dictado por voz automáticamente
    comando = st.text_input("Ej: 'Suma 10 al kit pcr'", placeholder="Toca y dicta...")
    
    if st.button("Procesar Instrucción", use_container_width=True):
        res = actualizar_stock(comando)
        st.success(res)

with tab2:
    st.subheader("Stock Actual")
    # Mostrar tabla simplificada para móvil
    res_db = supabase.table("items").select("nombre, cantidad_actual, ubicacion_detallada").execute()
    df = pd.DataFrame(res_db.data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# Botón flotante para refrescar
if st.button("🔄 Refrescar Datos"):
    st.rerun()
