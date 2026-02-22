import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", page_icon="🔬", layout="wide")

try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    genai.configure(api_key=GENAI_KEY)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("Error en Secrets.")
    st.stop()

# --- DETECCIÓN DINÁMICA DE MODELO (Adiós al 404) ---
@st.cache_resource
def obtener_modelo_real():
    try:
        # Le preguntamos a la API qué modelos tienes permitidos
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # Buscamos el flash, y si no, cualquiera que sea gemini
        nombre_modelo = next((m for m in modelos if '1.5-flash' in m), modelos[0])
        return genai.GenerativeModel(nombre_modelo)
    except Exception as e:
        st.error(f"Error al detectar modelo: {e}")
        return None

model = obtener_modelo_real()

# --- MEMORIA DEL CHAT ---
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. Sistema listo. ¿Qué cambio haremos?"}]

# --- FUNCIÓN DEL AGENTE ---
def ejecutar_agente(prompt_usuario, contexto_inventario):
    instrucciones = f"""
    Eres el Asistente del Lab Aguilar.
    Inventario: {contexto_inventario}
    
    Si el usuario quiere cambiar una categoría o cantidad:
    1. Identifica el ID del producto.
    2. Responde confirmando y añade al final: UPDATE: {{"id": ID, "cantidad": N, "categoria": "CAT", "ubicacion": "U"}}
    """
    try:
        # Si el modelo no cargó bien, intentamos recargar
        if not model: return "Error: El modelo IA no está disponible."
        
        response = model.generate_content(f"{instrucciones}\n\nUsuario: {prompt_usuario}")
        return response.text
    except Exception as e:
        return f"Error de cuota o conexión: {str(e)}"

# --- INTERFAZ ---
st.title("🔬 Monitor Inteligente")

col_chat, col_monitor = st.columns([1, 1.2])

with col_monitor:
    st.subheader("📊 Inventario")
    res = supabase.table("items").select("*").execute()
    inventario_texto = ""
    if res.data:
        df = pd.DataFrame(res.data)
        inventario_texto = df[['id', 'nombre', 'categoria', 'cantidad_actual']].to_string(index=False)
        
        df['categoria'] = df['categoria'].fillna("SIN CLASIFICAR")
        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}"):
                st.dataframe(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                             use_container_width=True, hide_index=True)

with col_chat:
    container_chat = st.container(height=450)
    for m in st.session_state.messages:
        with container_chat.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Ej: Cambia la categoría de los Eppendorf a CONSUMIBLES-PLASTICOS"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with container_chat.chat_message("user"): st.markdown(prompt)
        
        with container_chat.chat_message("assistant"):
            respuesta = ejecutar_agente(prompt, inventario_texto)
            
            if "UPDATE:" in respuesta:
                try:
                    data = json.loads(respuesta.split("UPDATE:")[1].strip())
                    upd = {}
                    if "cantidad" in data: upd["cantidad_actual"] = data["cantidad"]
                    if "categoria" in data: upd["categoria"] = data["categoria"]
                    if "ubicacion" in data: upd["ubicacion_detallada"] = data["ubicacion"]
                    
                    supabase.table("items").update(upd).eq("id", data["id"]).execute()
                    respuesta = respuesta.split("UPDATE:")[0] + "\n\n✅ *Cambio aplicado.*"
                except: pass
            
            st.markdown(respuesta)
            st.session_state.messages.append({"role": "assistant", "content": respuesta})
            if "✅" in respuesta: st.rerun()
