import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
import streamlit.components.v1 as components

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error de configuración.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except: return None

model = get_model()

# --- 2. LÓGICA DE INVENTARIO ---
res = supabase.table("items").select("*").execute()
df = pd.DataFrame(res.data)
df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    st.subheader("📊 Stock")
    st.dataframe(df[['nombre', 'cantidad_actual', 'unidad']], use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=400, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. ¿Qué gestionamos hoy?"}]

    for m in st.session_state.messages:
        with chat_box.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ CON AUTO-ENVÍO ---
    st.write("🎙️ Dictado por voz:")
    
    # Este script ahora fuerza una recarga de Streamlit enviando el texto capturado
    scr = """
    <button id="start-btn" style="width:100%; height:45px; border-radius:10px; border:none; background-color:#ff4b4b; color:white; font-weight:bold; cursor:pointer; font-size:16px;">
        🔴 Toca para hablar
    </button>
    <script>
        const btn = document.getElementById('start-btn');
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.lang = 'es-CL';
            
            btn.onclick = () => {
                recognition.start();
                btn.innerText = "🟢 Escuchando...";
                btn.style.backgroundColor = "#28a745";
            };

            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                // Truco: Recargamos la URL con el texto como parámetro
                const newUrl = window.parent.location.origin + window.parent.location.pathname + "?voice=" + encodeURIComponent(text);
                window.parent.location.href = newUrl;
            };
        }
    </script>
    """
    components.html(scr, height=60)
    
    # 4. PROCESAMIENTO DEL COMANDO (Voz o Texto)
    voice_command = st.query_params.get("voice")
    manual_command = st.chat_input("O escribe aquí...")
    
    prompt = voice_command if voice_command else manual_command

    if prompt:
        # Limpiamos el parámetro de la URL para que no se repita el comando al refrescar
        if voice_command:
            st.query_params.clear()
            
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box.chat_message("user"): st.markdown(prompt)
        
        with chat_box.chat_message("assistant"):
            try:
                ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                full_p = f"Inventario: {ctx}\nInstrucción: {prompt}\nRegla: Si piden bolsa y la unidad es bolsa, suma 1. Responde con UPDATE_BATCH: [{{id:N, cantidad:N}}]"
                res_ai = model.generate_content(full_p)
                texto = res_ai.text
                
                if "UPDATE_BATCH:" in texto:
                    match = re.search(r'\[.*\]', texto.replace("'", '"'), re.DOTALL)
                    if match:
                        for item in json.loads(match.group()):
                            supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                        st.markdown("✅ Inventario actualizado.")
                        st.session_state.messages.append({"role": "assistant", "content": "Actualizado ✅"})
                        st.rerun()
                else:
                    st.markdown(texto)
            except Exception as e:
                st.error(f"Error: {e}")
