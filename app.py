import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error en configuración de Secrets.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        # Listamos los modelos y buscamos el flash
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # CORRECCIÓN: Usamos el nombre correcto de la variable 'available_models'
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except Exception as e:
        st.error(f"No se pudo cargar el modelo de IA: {e}")
        return None

model = get_model()

# --- LÓGICA DE COLORES BASADA EN UMBRAL ---
def aplicar_estilos(row):
    cantidad = row['cantidad_actual']
    umbral = row['umbral_minimo']
    umbral = umbral if pd.notnull(umbral) else 0
    
    if cantidad <= 0:
        return ['background-color: #ffcccc; color: black'] * len(row)
    elif cantidad <= umbral:
        return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# --- INTERFAZ ---
st.markdown("### 🔬 Lab Aguilar: Control de Inventario")

col_chat, col_mon = st.columns([1, 1.5], gap="large")

with col_mon:
    st.subheader("📊 Inventario y Reposición")
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    
    contexto_ia = df[['id', 'nombre', 'cantidad_actual', 'umbral_minimo']].to_csv(index=False, sep="|")
    
    busqueda = st.text_input("🔍 Buscar por nombre...", "")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    for cat in sorted(df_show['categoria'].fillna("SIN CLASIFICAR").unique()):
        with st.expander(f"📁 {cat}"):
            # Columnas pedidas: Nombre, Cantidad, Unidad, Umbral
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            st.dataframe(subset.style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=520, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. Ya corregimos el error. ¿Qué gestionamos hoy?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Escribe aquí..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        full_prompt = f"Inventario:\n{contexto_ia}\n\nInstrucción: {prompt}\n\nResponde con UPDATE_BATCH: [{{id:N, cantidad:N, umbral:N}}]"
        
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    if model:
                        res_ai = model.generate_content(full_prompt)
                        texto = res_ai.text
                        
                        if "UPDATE_BATCH:" in texto:
                            json_str = texto.split("UPDATE_BATCH:")[1].strip()
                            data = json.loads(json_str)
                            for item in data:
                                upd = {}
                                if "cantidad" in item: upd["cantidad_actual"] = item["cantidad"]
                                if "umbral" in item: upd["umbral_minimo"] = item["umbral"]
                                if "categoria" in item: upd["categoria"] = item["categoria"]
                                supabase.table("items").update(upd).eq("id", item["id"]).execute()
                            texto = texto.split("UPDATE_BATCH:")[0] + f"\n\n✅ **Cambios aplicados.**"
                        
                        st.markdown(texto)
                        st.session_state.messages.append({"role": "assistant", "content": texto})
                        if "✅" in texto: st.rerun()
                    else:
                        st.error("IA no conectada.")
                except Exception as e:
                    st.error(f"Error: {e}")
