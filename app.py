import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from PIL import Image
from datetime import datetime
from streamlit_mic_recorder import mic_recorder

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error de conexión. Revisa los Secrets.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except: return None

model = get_model()

def aplicar_estilos(row):
    cant, umb = row['cantidad_actual'], row['umbral_minimo']
    umb = umb if pd.notnull(umb) else 0
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# --- 2. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Gestión de Inventario")
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    st.subheader("📊 Monitor de Stock")
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    
    # Limpieza de decimales
    df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
    df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
    
    busqueda = st.text_input("🔍 Buscar producto...")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    for cat in sorted(df_show['categoria'].fillna("SIN CATEGORÍA").unique()):
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(subset.style.apply(aplicar_estilos, axis=1).format({"cantidad_actual": "{:.0f}", "umbral_minimo": "{:.0f}"}), use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente Virtual")
    chat_box = st.container(height=450, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. ¿Qué gestionamos hoy?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- ENTRADA DE VOZ Y TEXTO ---
    st.write("🎙️ Control por Voz:")
    # Botón de micrófono integrado
    audio = mic_recorder(start_prompt="🔴 Hablar", stop_prompt="🟢 Detener y Enviar", key='recorder')
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
                    
                    # PROMPT REFORZADO PARA TOLERAR ERRORES DE VOZ
                    full_p = f"""
                    Contexto Inventario: {ctx}
                    Instrucción del usuario: "{prompt}"
                    
                    REGLAS CRÍTICAS:
                    1. Si el usuario dice "bolsa", "volsa" o similar, suma 1 a la cantidad.
                    2. La instrucción puede venir de un dictado de voz imperfecto, interpreta el nombre del producto más parecido.
                    3. Responde siempre con el formato JSON al final:
                    UPDATE_BATCH: [{{"id": ID, "cantidad": NUEVA_CANTIDAD}}]
                    """
                    
                    res_ai = model.generate_content(full_p)
                    texto = res_ai.text
                    
                    if "UPDATE_BATCH:" in texto:
                        # Limpieza de JSON con reemplazo de comillas simples por dobles
                        match = re.search(r'\[.*\]', texto.replace("'", '"'), re.DOTALL)
                        if match:
                            for item in json.loads(match.group()):
                                # Solo actualizamos cantidad para ser más seguros
                                supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                            
                            st.markdown(texto.split("UPDATE_BATCH:")[0] + "\n\n✅ **Inventario actualizado.**")
                            st.session_state.messages.append({"role": "assistant", "content": "Cambio realizado ✅"})
                            st.rerun()
                    else:
                        st.markdown(texto)
                        st.session_state.messages.append({"role": "assistant", "content": texto})
                except Exception as e:
                    st.error(f"Error: {e}")
