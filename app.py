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
    st.error("Error de configuración. Revisa los Secrets.")
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
def aplicar_estilos(row):
    cant, umb = row['cantidad_actual'], row['umbral_minimo']
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= (umb if pd.notnull(umb) else 0): return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

st.markdown("## 🔬 Lab Aguilar: Control de Inventario")
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    st.subheader("📊 Monitor de Stock")
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
    df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
    
    busqueda = st.text_input("🔍 Buscar producto...")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    for cat in sorted(df_show['categoria'].fillna("SIN CATEGORÍA").unique()):
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(subset.style.apply(aplicar_estilos, axis=1).format({"cantidad_actual": "{:.0f}", "umbral_minimo": "{:.0f}"}), use_container_width=True, hide_index=True)

# --- 3. CHAT Y CONTROL POR VOZ NATIVO ---
with col_chat:
    st.subheader("💬 Asistente Virtual")
    chat_box = st.container(height=400, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. ¿Qué gestionamos hoy?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ JS (Solución definitiva) ---
    st.write("🎙️ Dictado por voz:")
    
    # Este componente crea un botón real que usa el motor de voz de tu propio computador
    scr = """
    <button id="start-btn" style="width:100%; height:40px; border-radius:10px; border:none; background-color:#ff4b4b; color:white; font-weight:bold; cursor:pointer;">
        🔴 Toca para hablar
    </button>
    <p id="status" style="font-size:12px; color:gray; margin-top:5px;"></p>

    <script>
        const btn = document.getElementById('start-btn');
        const status = document.getElementById('status');
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!SpeechRecognition) {
            status.innerText = "Tu navegador no soporta dictado por voz.";
        } else {
            const recognition = new SpeechRecognition();
            recognition.lang = 'es-CL';
            
            btn.onclick = () => {
                recognition.start();
                status.innerText = "Escuchando...";
                btn.style.backgroundColor = "#28a745";
                btn.innerText = "🟢 Escuchando...";
            };

            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                // Enviamos el texto a Streamlit
                window.parent.postMessage({type: 'streamlit:setComponentValue', value: text}, '*');
                status.innerText = "Texto capturado: " + text;
                btn.style.backgroundColor = "#ff4b4b";
                btn.innerText = "🔴 Toca para hablar";
            };
        }
    </script>
    """
    # Capturamos el valor que viene del JavaScript
    voice_input = components.html(scr, height=100)
    
    prompt = st.chat_input("O escribe aquí...")

    # Si hay voz, la procesamos
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
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
                            st.markdown(texto.split("UPDATE_BATCH:")[0] + "\n\n✅ **Actualizado.**")
                            st.rerun()
                    else:
                        st.markdown(texto)
                except Exception as e:
                    st.error(f"Error: {e}")
