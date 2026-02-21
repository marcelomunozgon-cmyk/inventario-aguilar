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
    st.error("Error de configuración.")
    st.stop()

model = genai.GenerativeModel('gemini-1.5-flash')

# --- ESTADO DE LA SESIÓN (MEMORIA DEL CHAT) ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hola Rodrigo, soy tu asistente del Lab Aguilar. ¿Qué vamos a registrar hoy o en qué puedo ayudarte?"}
    ]

# --- FUNCIÓN DEL AGENTE ---
def ejecutar_agente(prompt_usuario):
    # Contexto del sistema para que sepa quién es y qué hace
    contexto = """
    Eres el Agente de Control del Lab Aguilar. 
    Tu objetivo es ayudar a gestionar el inventario y resolver dudas sobre la app.
    Si el usuario quiere registrar algo:
    1. Busca el producto en la DB.
    2. Si hay ambigüedad o falta información (como la ubicación), PREGUNTA antes de actuar.
    3. Si confirmas una acción, responde con el formato JSON al final: {"accion": "update", "id": ID, "cambios": {}}.
    4. Si te preguntan cómo funciona la app, explica que pueden usar voz/texto para sumar/restar stock o clasificar.
    """
    
    # Combinar historial para que tenga memoria
    historial = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
    
    try:
        response = model.generate_content(f"{contexto}\n\nHistorial:\n{historial}\n\nUsuario: {prompt_usuario}")
        texto_ai = response.text
        
        # Lógica para detectar si la IA decidió hacer un cambio en la DB
        if "{" in texto_ai and "accion" in texto_ai:
            try:
                # Extraer JSON y limpiar el texto para el usuario
                inicio_json = texto_ai.find('{')
                json_str = texto_ai[inicio_json:]
                datos = json.loads(json_str)
                
                if datos["accion"] == "update":
                    supabase.table("items").update(datos["cambios"]).eq("id", datos["id"]).execute()
                    texto_ai = texto_ai[:inicio_json] + "\n✅ Cambio realizado en la base de datos."
            except: pass
            
        return texto_ai
    except Exception as e:
        return f"Lo siento, hubo un error con la cuota de Google. Esperemos un momento. ({str(e)})"

# --- INTERFAZ DASHBOARD ---
col_chat, col_monitor = st.columns([1, 1.5], gap="medium")

with col_chat:
    st.subheader("💬 Asistente Conversacional")
    
    # Contenedor para el historial del chat
    container_chat = st.container(height=500, border=True)
    with container_chat:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Entrada del usuario
    if prompt := st.chat_input("Escribe o usa el dictado de tu PC..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with container_chat:
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                respuesta = ejecutar_agente(prompt)
                st.markdown(respuesta)
                st.session_state.messages.append({"role": "assistant", "content": respuesta})

with col_monitor:
    st.subheader("📊 Inventario en Tiempo Real")
    res_db = supabase.table("items").select("*").execute()
    if res_db.data:
        df = pd.DataFrame(res_db.data)
        # Mostrar tabla organizada
        df['categoria'] = df['categoria'].fillna("SIN CLASIFICAR")
        for cat in sorted(df['categoria'].unique()):
            with st.expander(f"📁 {cat}"):
                st.table(df[df['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'ubicacion_detallada']])
