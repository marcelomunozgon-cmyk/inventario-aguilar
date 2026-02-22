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
    chat_box = st.container(height=400, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola. Presiona el botón para grabar y vuelve a presionarlo para enviar."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ MANUAL (START/STOP) ---
    st.write("🎙️ Control por voz:")
    scr = """
    <div style="display: flex; flex-direction: column; align-items: center;">
        <button id="voice-btn" style="width:100%; height:60px; border-radius:12px; border:none; background-color:#ff4b4b; color:white; font-weight:bold; cursor:pointer; font-size:18px; transition: 0.3s;">
            🎤 INICIAR GRABACIÓN
        </button>
        <p id="status" style="font-size:14px; color:#555; margin-top:8px; font-family:sans-serif;">Listo para escuchar</p>
    </div>

    <script>
        const btn = document.getElementById('voice-btn');
        const status = document.getElementById('status');
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.lang = 'es-CL';
            recognition.continuous = true; 
            recognition.interimResults = false;
            let isRecording = false;

            btn.onclick = () => {
                if (!isRecording) {
                    recognition.start();
                    isRecording = true;
                    btn.innerText = "🛑 DETENER Y ENVIAR";
                    btn.style.backgroundColor = "#28a745";
                    status.innerText = "Escuchando... hable ahora.";
                } else {
                    recognition.stop();
                    isRecording = false;
                    btn.innerText = "⌛ PROCESANDO...";
                    btn.style.backgroundColor = "#666";
                }
            };

            recognition.onresult = (event) => {
                const text = event.results[event.results.length - 1][0].transcript;
                // Redirección inmediata al padre con el texto
                window.parent.location.assign(window.parent.location.origin + window.parent.location.pathname + "?voice=" + encodeURIComponent(text));
            };

            recognition.onerror = (event) => {
                status.innerText = "Error: " + event.error;
                btn.style.backgroundColor = "#ff4b4b";
                btn.innerText = "🎤 REINTENTAR";
                isRecording = false;
            };
        } else {
            status.innerText = "Navegador no compatible.";
        }
    </script>
    """
    components.html(scr, height=110)
    
    # --- 4. PROCESAMIENTO ---
    voice_command = st.query_params.get("voice")
    manual_command = st.chat_input("O escribe aquí...")
    prompt = voice_command if voice_command else manual_command

    if prompt:
        st.query_params.clear()
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    full_p = f"Inventario: {ctx}\nInstrucción: {prompt}\nRegla: Si piden bolsa y la unidad es bolsa, suma 1. Responde con UPDATE_BATCH: [{{id:N, cantidad:N}}]"
                    res_ai = model.generate_content(full_p)
                    texto_ai = res_ai.text
                    
                    if "UPDATE_BATCH:" in texto_ai:
                        match = re.search(r'\[.*\]', texto_ai.replace("'", '"'), re.DOTALL)
                        if match:
                            for item in json.loads(match.group()):
                                supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                            st.markdown("✅ **Inventario actualizado.**")
                            st.rerun()
                    else:
                        st.markdown(texto_ai)
                        st.session_state.messages.append({"role": "assistant", "content": texto_ai})
                except Exception as e:
                    st.error(f"Error: {e}")
