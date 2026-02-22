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
except Exception as e:
    st.error(f"Error en Secrets: {e}")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except: return None

model = get_model()

# --- 2. LÓGICA DE DATOS ---
def aplicar_estilos(row):
    cant = row['cantidad_actual']
    umb = row['umbral_minimo'] if pd.notnull(row['umbral_minimo']) else 0
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

res = supabase.table("items").select("*").execute()
df = pd.DataFrame(res.data)
df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    st.subheader("📊 Monitor de Stock")
    busqueda = st.text_input("🔍 Buscar producto...", placeholder="Ej: Eppendorf")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
    for cat in categorias:
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(subset.style.apply(aplicar_estilos, axis=1).format({"cantidad_actual": "{:.0f}", "umbral_minimo": "{:.0f}"}), use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola. Presiona el botón para grabar, habla y luego presiona detener."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ CON TRANSCRIPCIÓN EN VIVO ---
    st.write("🎙️ Control por voz:")
    scr = """
    <div style="display: flex; flex-direction: column; align-items: center; background: #f0f2f6; padding: 15px; border-radius: 15px;">
        <button id="voice-btn" style="width:100%; height:50px; border-radius:10px; border:none; background-color:#ff4b4b; color:white; font-weight:bold; cursor:pointer; font-size:16px;">
            🎤 INICIAR GRABACIÓN
        </button>
        <div style="margin-top: 10px; width: 100%; min-height: 40px; background: white; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-family: sans-serif; font-size: 14px; color: #333;">
            <strong>Transcripción:</strong> <span id="live-text">...</span>
        </div>
    </div>

    <script>
        const btn = document.getElementById('voice-btn');
        const liveText = document.getElementById('live-text');
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.lang = 'es-CL';
            recognition.continuous = true;
            recognition.interimResults = true; // Permite ver resultados parciales mientras habla
            let isRecording = false;
            let finalTranscript = '';

            btn.onclick = () => {
                if (!isRecording) {
                    recognition.start();
                    isRecording = true;
                    btn.innerText = "🛑 DETENER Y ENVIAR";
                    btn.style.backgroundColor = "#28a745";
                    liveText.innerText = "Escuchando...";
                } else {
                    recognition.stop();
                    isRecording = false;
                    btn.innerText = "⌛ PROCESANDO...";
                    btn.style.backgroundColor = "#666";
                    // Enviar el texto final recolectado
                    if(finalTranscript) {
                        const url = new URL(window.parent.location.href);
                        url.searchParams.set('voice', finalTranscript);
                        window.parent.location.href = url.toString();
                    }
                }
            };

            recognition.onresult = (event) => {
                let interimTranscript = '';
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }
                liveText.innerText = finalTranscript + interimTranscript;
            };

            recognition.onerror = (event) => {
                liveText.innerText = "Error: " + event.error;
                isRecording = false;
                btn.style.backgroundColor = "#ff4b4b";
                btn.innerText = "🎤 REINTENTAR";
            };
        }
    </script>
    """
    components.html(scr, height=160)
    
    # --- 4. PRO
