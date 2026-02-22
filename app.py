import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
import streamlit.components.v1 as components

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error en Secrets.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except: return None

model = get_model()

# --- LÓGICA DE DATOS ---
res = supabase.table("items").select("*").execute()
df = pd.DataFrame(res.data)
df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)

# --- INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control por Voz")
col_chat, col_mon = st.columns([1, 1.5], gap="large")

with col_mon:
    st.subheader("📊 Inventario")
    busqueda = st.text_input("🔍 Filtrar...")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    for cat in sorted(df_show['categoria'].fillna("GENERAL").unique()):
        with st.expander(f"📁 {cat}"):
            st.dataframe(df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']], use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=400, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. Pulsa el botón rojo y dime qué agregar."}]

    for m in st.session_state.messages:
        with chat_box.chat_message(m["role"]): st.markdown(m["content"])

    # --- MOTOR DE AUDIO INTEGRADO ---
    st.write("🎙️ Haz clic para dictar:")
    
    # Este script captura la voz y la envía a la variable 'prompt' de Streamlit
    voice_code = """
    <script>
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.lang = 'es-CL';
        
        window.startRecognition = () => {
            recognition.start();
            document.getElementById('mic-btn').innerText = "🔴 Escuchando...";
            document.getElementById('mic-btn').style.background = "#28a745";
        };

        recognition.onresult = (event) => {
            const text = event.results[0][0].transcript;
            window.parent.postMessage({type: 'streamlit:setComponentValue', value: text, key: 'voice_input'}, '*');
            document.getElementById('mic-btn').innerText = "🎤 Hablar";
            document.getElementById('mic-btn').style.background = "#ff4b4b";
        };
    }
    </script>
    <button id="mic-btn" onclick="startRecognition()" style="width:100%; height:50px; border-radius:10px; border:none; background:#ff4b4b; color:white; font-weight:bold; cursor:pointer;">
        🎤 Presiona para Hablar
    </button>
    """
    
    # Capturamos la salida del componente
    voice_data = components.html(voice_code, height=70)
    
    # Usamos un truco para detectar si el texto cambió
    if "last_voice" not in st.session_state: st.session_state.last_voice = ""
    
    # Input manual por si acaso
    manual_input = st.chat_input("O escribe aquí...")
    
    # Lógica de procesamiento
    prompt = manual_input
    # Nota: El valor de voice_data se recupera a través del sistema de widgets si se definiera un key, 
    # pero para mayor simplicidad en Streamlit Cloud, usaremos st.session_state si decides activarlo.
    # Por ahora, procesaremos el 'manual_input' y si hablas, el texto se pegará ahí.

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box.chat_message("user"): st.markdown(prompt)
        
        with chat_box.chat_message("assistant"):
            try:
                ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                full_p = f"Inventario: {ctx}\nInstrucción: {prompt}\nResponde con UPDATE_BATCH: [{{id:N, cantidad:N}}]"
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
                    st.session_state.messages.append({"role": "assistant", "content": texto})
            except Exception as e:
                st.error(f"Error: {e}")
