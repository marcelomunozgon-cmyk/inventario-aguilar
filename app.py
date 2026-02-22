import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text

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
        st.session_state.messages = [{"role": "assistant", "content": "Hola Marcelo. Prueba el botón de voz o escribe."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- 4. MOTOR DE VOZ NATIVO (EL CAMBIO CLAVE) ---
    st.write("🎙️ **Dictado por Voz:**")
    
    # Esta función crea un botón que se comunica directo con Python, sin bloqueos de Iframe
    v_in = speech_to_text(
        language='es-CL',
        start_prompt="🎤 INICIAR GRABACIÓN",
        stop_prompt="🛑 DETENER Y ENVIAR AL CHAT",
        just_once=True,
        key='voice_input'
    )
    
    m_in = st.chat_input("O escribe aquí...")
    
    # Tomamos la voz (si hay) o el texto manual
    prompt = v_in if v_in else m_in

    # --- 5. PROCESAMIENTO ---
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    sys_p = f"Inventario:\n{ctx}\nInstrucción: {prompt}\nRegla: Responde ÚNICAMENTE en este formato: UPDATE_BATCH: [{{'id': N, 'cantidad': N}}]"
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai:
                        # Limpieza extrema del texto para JSON
                        clean_json = res_ai.split("UPDATE_BATCH:")[1].strip()
                        clean_json = clean_json.replace("'", '"')
                        
                        updates = json.loads(clean_json)
                        for item in updates:
                            supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                        
                        st.markdown("✅ **Inventario actualizado.**")
                        st.session_state.messages.append({"role": "assistant", "content": "✅ **Inventario actualizado.**"})
                        st.rerun()
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error procesando la IA: {e}")
