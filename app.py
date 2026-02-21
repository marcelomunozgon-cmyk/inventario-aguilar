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
    st.error("Error en Secrets.")
    st.stop()

# --- MODELO (Nombre corregido para máxima compatibilidad) ---
@st.cache_resource
def obtener_modelo():
    # Esta es la ruta más estable para la API de Google
    return genai.GenerativeModel('models/gemini-1.5-flash-latest')

model = obtener_modelo()

# --- MEMORIA DEL CHAT ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hola Rodrigo. Soy tu Agente del Lab Aguilar. ¿Qué vamos a gestionar hoy?"}
    ]

# --- FUNCIÓN DEL AGENTE ---
def ejecutar_agente(prompt_usuario, contexto_inventario):
    instrucciones = f"""
    Eres el Asistente del Lab Aguilar. Tienes acceso al inventario.
    Inventario Actual:
    {contexto_inventario}
    
    REGLAS:
    1. Si el usuario pide un cambio, verifica que el producto exista.
    2. Si hay dudas, pregunta.
    3. Si confirmas una acción, añade al final: UPDATE: {{"id": ID, "cantidad": N, "ubicacion": "U"}}
    4. Responde en español, de forma breve y profesional.
    """
    try:
        # Iniciamos el chat con el historial acumulado
        chat = model.start_chat(history=[])
        response = chat.send_message(f"{instrucciones}\n\nUsuario: {prompt_usuario}")
        return response.text
    except Exception as e:
        return f"Error de conexión (Cuota o API): {str(e)}"

# --- INTERFAZ EN DOS COLUMNAS ---
st.title("🔬 Monitor Inteligente Lab Aguilar")

col_chat, col_monitor = st.columns([1, 1.2], gap="large")

with col_monitor:
    st.subheader("📊 Inventario en Tiempo Real")
    res = supabase.table("items").select("*").execute()
    inventario_texto = ""
    if res.data:
        df = pd.DataFrame(res.data)
        # Resumen para la IA (ahorro de tokens)
        inventario_texto = df[['id', 'nombre', 'cantidad_actual', 'ubicacion_detallada']].to_string(index=False)
        
        # Vista para el Humano
        df['categoria'] = df['categoria'].fillna("GENERAL")
        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}"):
                st.dataframe(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']], 
                             use_container_width=True, hide_index=True)

with col_chat:
    # Mostrar el chat
    container_chat = st.container(height=500)
    with container_chat:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

    # Entrada de texto
    if prompt := st.chat_input("Dime qué hacer..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with container_chat:
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Consultando..."):
                    respuesta = ejecutar_agente(prompt, inventario_texto)
                    
                    # Lógica de actualización de DB
                    if "UPDATE:" in respuesta:
                        try:
                            json_data = respuesta.split("UPDATE:")[1].strip()
                            d = json.loads(json_data)
                            upd = {"cantidad_actual": d["cantidad"]}
                            if d["ubicacion"]: upd["ubicacion_detallada"] = d["ubicacion"]
                            
                            supabase.table("items").update(upd).eq("id", d["id"]).execute()
                            respuesta = respuesta.split("UPDATE:")[0] + "\n\n✅ *Inventario actualizado.*"
                        except: pass
                    
                    st.markdown(respuesta)
                    st.session_state.messages.append({"role": "assistant", "content": respuesta})
                    if "✅" in respuesta: st.rerun()
