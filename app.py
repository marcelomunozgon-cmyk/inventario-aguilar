import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error de configuración.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except: return None

model = get_model()

# --- LÓGICA DE TABLA ---
def aplicar_estilos(row):
    cant = row['cantidad_actual']
    umb = row['umbral_minimo'] if pd.notnull(row['umbral_minimo']) else 0
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

st.markdown("## 🔬 Lab Aguilar: Control de Inventario")

col_chat, col_mon = st.columns([1, 1.5], gap="large")

with col_mon:
    st.subheader("📊 Stock Actual")
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
    df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
    
    busqueda = st.text_input("🔍 Buscar...", placeholder="Escribe el nombre del reactivo")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    for cat in sorted(df_show['categoria'].fillna("GENERAL").unique()):
        with st.expander(f"📁 {cat}"):
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(subset.style.apply(aplicar_estilos, axis=1).format({"cantidad_actual": "{:.0f}", "umbral_minimo": "{:.0f}"}), use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    
    # Notificación visual para el usuario
    st.info("💡 **Tip para Voz:** Haz clic en el cuadro de texto y usa el micrófono de tu teclado o presiona 'Dictado'.")
    
    chat_box = st.container(height=450, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. ¿Qué vamos a actualizar hoy?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # El input de chat de Streamlit es el mejor receptor para dictado nativo
    if prompt := st.chat_input("Escribe o dicta aquí..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad']].to_csv(index=False, sep="|")
                    full_p = f"""
                    Inventario: {ctx}
                    Instrucción: "{prompt}"
                    REGLA: Si piden 'bolsa', suma 1 a cantidad. 
                    Responde con UPDATE_BATCH: [{{"id": ID, "cantidad": NUEVA_CANTIDAD}}]
                    """
                    res_ai = model.generate_content(full_p)
                    texto = res_ai.text
                    
                    if "UPDATE_BATCH:" in texto:
                        match = re.search(r'\[.*\]', texto.replace("'", '"'), re.DOTALL)
                        if match:
                            for item in json.loads(match.group()):
                                supabase.table("items").update({"cantidad_actual": int(item["cantidad"])}).eq("id", item["id"]).execute()
                            
                            confirmacion = texto.split("UPDATE_BATCH:")[0] + "\n\n✅ **Inventario actualizado.**"
                            st.markdown(confirmacion)
                            st.session_state.messages.append({"role": "assistant", "content": confirmacion})
                            st.rerun()
                    else:
                        st.markdown(texto)
                        st.session_state.messages.append({"role": "assistant", "content": texto})
                except Exception as e:
                    st.error(f"Error: {e}")
