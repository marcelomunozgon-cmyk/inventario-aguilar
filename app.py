import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar AI", page_icon="🔬", layout="wide")

try:
    GENAI_KEY = st.secrets["GENAI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    genai.configure(api_key=GENAI_KEY)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("Error de configuración en los Secrets.")
    st.stop()

# --- MODELO (Nombre corregido para evitar el 404) ---
@st.cache_resource
def obtener_modelo():
    # Usamos gemini-1.5-flash que es el más rápido y económico
    return genai.GenerativeModel('gemini-1.5-flash')

model = obtener_modelo()

# --- MEMORIA DEL CHAT ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hola Rodrigo. Estoy listo. Puedo ayudarte a registrar reactivos, mover cosas de estante o explicarte cómo funciona la app. ¿Qué necesitas?"}
    ]

# --- FUNCIÓN DEL AGENTE CONVERSACIONAL ---
def ejecutar_agente(prompt_usuario, inventario_contexto):
    contexto_sistema = f"""
    Eres el Asistente Inteligente del Lab Aguilar.
    Tu objetivo es gestionar el inventario mediante una conversación natural.
    
    REGLAS:
    1. Si el usuario quiere actualizar algo, busca en este contexto: {inventario_contexto}
    2. Si no estás seguro de a qué producto se refiere, PREGUNTA (ej: ¿Es el Etanol de 1L o el de 500ml?).
    3. Si confirmas una acción técnica, incluye al final de tu respuesta este formato JSON: 
       DATA_UPDATE: {{"id": "ID_DEL_PRODUCTO", "cantidad": "NUEVA_CANTIDAD", "ubicacion": "NUEVA_UBICACION_O_NULL"}}
    4. Si te preguntan cómo funciona la app, explica que eres una IA conectada a Supabase.
    """
    
    try:
        # Generar respuesta
        chat = model.start_chat(history=[])
        response = chat.send_message(f"{contexto_sistema}\n\nUsuario dice: {prompt_usuario}")
        return response.text
    except Exception as e:
        return f"Ups, mi conexión con Google se cansó. Esperemos un minuto. Error: {str(e)}"

# --- INTERFAZ DASHBOARD ---
st.title("🔬 Lab Aguilar: Control Conversacional")

col_chat, col_monitor = st.columns([1, 1.2], gap="large")

with col_monitor:
    st.subheader("📊 Estado Actual del Inventario")
    res_db = supabase.table("items").select("*").execute()
    inventario_raw = ""
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        inventario_raw = df[['id', 'nombre', 'cantidad_actual', 'ubicacion_detallada']].to_string()
        
        # Vista organizada para el humano
        df['categoria'] = df['categoria'].fillna("SIN CLASIFICAR")
        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}"):
                st.dataframe(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Chat con el Lab")
    
    # Mostrar historial
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Entrada de texto
    if prompt := st.chat_input("Ej: 'Mueve el Etanol al Estante 3' o '¿Cómo agrego un nuevo ítem?'"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                respuesta = ejecutar_agente(prompt, inventario_raw)
                
                # Procesar si hay una actualización en la respuesta
                if "DATA_UPDATE:" in respuesta:
                    try:
                        json_parte = respuesta.split("DATA_UPDATE:")[1].strip()
                        datos = json.loads(json_parte)
                        update_data = {"cantidad_actual": datos["cantidad"]}
                        if datos["ubicacion"]:
                            update_data["ubicacion_detallada"] = datos["ubicacion"]
                        
                        supabase.table("items").update(update_data).eq("id", datos["id"]).execute()
                        respuesta = respuesta.split("DATA_UPDATE:")[0] + "\n\n✨ *Base de datos actualizada en tiempo real.*"
                    except:
                        pass
                
                st.markdown(respuesta)
                st.session_state.messages.append({"role": "assistant", "content": respuesta})
                
                # Refrescar para ver cambios en la tabla si hubo update
                if "✨" in respuesta:
                    st.rerun()
