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
    st.error("Error de configuración en Secrets.")
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

# Carga de datos
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
    
    # RECUPERAMOS LOS ACORDEONES POR CATEGORÍA
    categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
    for cat in categorias:
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(
                subset.style.apply(aplicar_estilos, axis=1).format({
                    "cantidad_actual": "{:.0f}", 
                    "umbral_minimo": "{:.0f}"
                }), 
                use_container_width=True, 
                hide_index=True
            )

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=400, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. ¿Qué vamos a actualizar hoy?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ CON AUTO-CIERRE ---
    st.write("🎙️ Dictado por voz:")
    
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
            recognition.continuous = false; // Detenerse automáticamente al dejar de hablar
            recognition.interimResults = false;

            btn.onclick = () => {
                recognition.start();
                btn.innerText = "🟢 Escuchando...";
                btn.style.backgroundColor = "#28a745";
            };

            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                // Redirigir con el texto en la URL para procesar
                const url = new URL(window.parent.location.href);
                url.searchParams.set('voice', text);
                window.parent.location.href = url.href;
            };

            recognition.onspeechend = () => {
                recognition.stop();
                btn.innerText = "⌛ Procesando...";
            };

            recognition.onerror = () => {
                btn.innerText = "❌ Error (Reintenta)";
                btn.style.backgroundColor = "#ff4b4b";
            };
        }
    </script>
    """
    components.html(scr, height=60)
    
    # --- 4. PROCESAMIENTO ---
    voice_command = st.query_params.get("voice")
    manual_command = st.chat_input("O escribe aquí...")
    
    prompt = voice_command if voice_command else manual_command

    if prompt:
        if voice_command:
            st.query_params.clear() # Limpiar URL para evitar bucles
            
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    full_p = f"""
                    Inventario: {ctx}
                    Instrucción: "{prompt}"
                    REGLA: Si la unidad es 'bolsas' y dicen 'agrega una bolsa', suma 1 a la cantidad. 
                    Responde SIEMPRE al final con: UPDATE_BATCH: [{{"id": ID, "cantidad": NUEVA_CANTIDAD}}]
                    """
                    res_ai = model.generate_content(full_p)
                    texto_ai = res_ai.text
                    
                    if "UPDATE_BATCH:" in texto_ai:
                        match = re.search(r'\[.*\]', texto_ai.replace("'", '"'), re.DOTALL)
                        if match:
                            for item in json.loads(match.group()):
                                supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                            
                            confirm = texto_ai.split("UPDATE_BATCH:")[0] + "\n\n✅ **Actualizado.**"
                            st.markdown(confirm)
                            st.session_state.messages.append({"role": "assistant", "content": confirm})
                            st.rerun()
                    else:
                        st.markdown(texto_ai)
                        st.session_state.messages.append({"role": "assistant", "content": texto_ai})
                except Exception as e:
                    st.error(f"Error: {e}")
