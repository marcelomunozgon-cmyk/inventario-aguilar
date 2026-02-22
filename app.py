import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from datetime import datetime
from streamlit_mic_recorder import mic_recorder

# 1. CONFIGURACIÓN
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error: Revisa los Secrets en Streamlit Cloud.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except:
        return None

model = get_model()

def aplicar_estilos(row):
    cant, umb = row['cantidad_actual'], row['umbral_minimo']
    umb = umb if pd.notnull(umb) else 0
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# 2. INTERFAZ
st.markdown("### 🔬 Lab Aguilar: Control de Inventario")
col_chat, col_mon = st.columns([1, 1.5], gap="large")

with col_mon:
    st.subheader("📊 Inventario")
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
    df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
    
    busqueda = st.text_input("🔍 Buscar producto...", "")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    for cat in sorted(df_show['categoria'].fillna("SIN CATEGORÍA").unique()):
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(subset.style.apply(aplicar_estilos, axis=1).format({"cantidad_actual": "{:.0f}", "umbral_minimo": "{:.0f}"}), use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=400, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. Entendido: trabajamos con las unidades de la tabla. ¿Qué agregamos?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    st.write("🎙️ Voz:")
    audio = mic_recorder(start_prompt="🔴 Hablar", stop_prompt="🟢 Enviar", key='recorder')
    input_text = st.chat_input("Escribe aquí...")
    
    prompt = None
    if audio and isinstance(audio, dict) and audio.get('text'):
        prompt = audio['text']
    elif input_text:
        prompt = input_text

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    
                    full_p = f"""
                    Inventario: {ctx}
                    Instrucción: "{prompt}"
                    REGLA: Usa las unidades que aparecen en la tabla. Si piden agregar 'una bolsa' y la unidad es 'bolsas', suma 1.
                    Responde SIEMPRE con este formato al final:
                    UPDATE_BATCH: [{{"id": ID, "cantidad": NUEVA_CANTIDAD}}]
                    """
                    
                    res_ai = model.generate_content(full_p)
                    texto = res_ai.text
                    
                    if "UPDATE_BATCH:" in texto:
                        # Buscamos el JSON con comillas dobles forzadas
                        match = re.search(r'\[.*\]', texto.replace("'", '"'), re.DOTALL)
                        if match:
                            data = json.loads(match.group())
                            for item in data:
                                supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                            
                            confirmacion = texto.split("UPDATE_BATCH:")[0]
                            st.markdown(confirmacion + "\n\n✅ **Actualizado.**")
                            st.session_state.messages.append({"role": "assistant", "content": confirmacion})
                            st.rerun()
                    else:
                        st.markdown(texto)
                        st.session_state.messages.append({"role": "assistant", "content": texto})
                except Exception as e:
                    st.error(f"Error: {e}")
