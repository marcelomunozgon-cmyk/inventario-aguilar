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
    busqueda = st.text_input("🔍 Buscar producto...", placeholder="Ej: Eppendorf", key="search")
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
        st.session_state.messages = [{"role": "assistant", "content": "Hola Marcelo. Presiona el botón para hablar y luego DETENER para procesar."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ REFORZADO ---
    st.write("🎙️ Control por voz:")
    scr = """
    <div style="display: flex; flex-direction: column; align-items: center; background: #f0f2f6; padding: 15px; border-radius: 15px;">
        <button id="voice-btn" style="width:100%; height:50px; border-radius:10px; border:none; background-color:#ff4b4b; color:white; font-weight:bold; cursor:pointer; font-size:16px;">
            🎤 INICIAR GRABACIÓN
        </button>
        <div style="margin-top: 10px; width: 100%; min-height: 40px; background: white; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-family: sans-serif; font-size: 14px; color: #333;">
            <strong>Voz capturada:</strong> <span id="live-text">...</span>
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
            recognition.interimResults = true;
            let isRecording = false;
            let finalTranscript = '';

            btn.onclick = () => {
                if (!isRecording) {
                    recognition.start();
                    isRecording = true;
                    btn.innerText = "🛑 DETENER Y PROCESAR";
                    btn.style.backgroundColor = "#28a745";
                } else {
                    recognition.stop();
                    isRecording = false;
                    btn.innerText = "⌛ ENVIANDO...";
                    btn.style.backgroundColor = "#666";
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
                const fullText = finalTranscript + interimTranscript;
                liveText.innerText = fullText;
                
                // Si la grabación se detuvo, forzamos la salida a Streamlit
                if (!isRecording && fullText.length > 0) {
                    const currentUrl = new URL(window.top.location.href);
                    currentUrl.searchParams.set('voice', fullText);
                    window.top.location.href = currentUrl.toString();
                }
            };
        }
    </script>
    """
    components.html(scr, height=160)
    
    # --- 4. PROCESAMIENTO DE VOZ Y CHAT ---
    voice_input = st.query_params.get("voice")
    manual_input = st.chat_input("O escribe aquí...")
    
    # Priorizamos la voz si existe en la URL
    prompt = voice_input if voice_input else manual_input

    if prompt:
        # Limpiar URL para que no se repita el comando
        st.query_params.clear()
        
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    full_p = f"Inventario: {ctx}\nInstrucción: {prompt}\nRegla: Si dicen bolsa y la unidad es bolsa, suma 1. Responde con UPDATE_BATCH: [{{id:ID, cantidad:N}}]"
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
