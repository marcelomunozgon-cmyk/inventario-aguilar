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

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    st.subheader("📊 Monitor de Stock")
    busqueda = st.text_input("🔍 Buscar producto...", key="search")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
    for cat in categorias:
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad']]
            st.dataframe(subset, use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola. Presiona el botón para hablar y luego presiona detener para procesar."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- BOTÓN DE VOZ CORREGIDO ---
    st.write("🎙️ Control por voz:")
    scr = """
    <div style="background: #f0f2f6; padding: 15px; border-radius: 15px; text-align: center;">
        <button id="v-btn" style="width:100%; height:50px; border-radius:10px; border:none; background-color:#ff4b4b; color:white; font-weight:bold; cursor:pointer; font-size:16px;">
            🎤 INICIAR GRABACIÓN
        </button>
        <div style="margin-top:10px; background:white; padding:8px; border-radius:5px; font-size:14px; min-height:30px; border:1px solid #ccc; text-align: left;">
            <strong>Voz:</strong> <span id="t">...</span>
        </div>
    </div>

    <script>
        const btn = document.getElementById('v-btn');
        const txt = document.getElementById('t');
        const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
        
        if (Speech) {
            const rec = new Speech();
            rec.lang = 'es-CL';
            rec.continuous = true;
            rec.interimResults = true;
            let active = false;
            let finalResult = '';

            btn.onclick = () => {
                if (!active) {
                    finalResult = '';
                    rec.start();
                    active = true;
                    btn.innerText = "🛑 DETENER Y ENVIAR";
                    btn.style.backgroundColor = "#28a745";
                } else {
                    active = false;
                    rec.stop(); // Cerramos el micrófono
                    btn.innerText = "⌛ ENVIANDO...";
                    btn.style.backgroundColor = "#666";
                    
                    // Esperamos un instante a que se limpie el buffer y enviamos
                    setTimeout(() => {
                        if (finalResult.length > 0) {
                            const url = new URL(window.top.location.href);
                            url.searchParams.set('voice', finalResult);
                            window.top.location.href = url.toString();
                        } else {
                            btn.innerText = "🎤 REINTENTAR (No se oyó nada)";
                            btn.style.backgroundColor = "#ff4b4b";
                        }
                    }, 500);
                }
            };

            rec.onresult = (e) => {
                let interim = '';
                for (let i = e.resultIndex; i < e.results.length; ++i) {
                    if (e.results[i].isFinal) finalResult += e.results[i][0].transcript;
                    else interim += e.results[i][0].transcript;
                }
                txt.innerText = finalResult + interim;
            };
        }
    </script>
    """
    components.html(scr, height=160)
    
    # --- 4. PROCESAMIENTO ---
    v_in = st.query_params.get("voice")
    m_in = st.chat_input("Escribe aquí...")
    prompt = v_in if v_in else m_in

    if prompt:
        st.query_params.clear()
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    sys_p = f"Inventario:\n{ctx}\nInstrucción: {prompt}\nResponde con UPDATE_BATCH: [{{'id': N, 'cantidad': N}}]"
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai:
                        clean_json = res_ai.split("UPDATE_BATCH:")[1].strip()
                        clean_json = clean_json.replace("'", '"') # Fix para comillas simples
                        updates = json.loads(clean_json)
                        for item in updates:
                            supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                        st.markdown("✅ **Inventario actualizado.**")
                        st.rerun()
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error: {e}")
