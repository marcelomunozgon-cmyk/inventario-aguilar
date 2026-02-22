import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
from datetime import datetime

# 1. CONFIGURACIÓN DE LA PÁGINA
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

# 2. CONEXIÓN A BASES DE DATOS (Secrets)
try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error: Revisa las llaves API en Streamlit Cloud.")
    st.stop()

# 3. CARGAR MODELO DE INTELIGENCIA ARTIFICIAL
@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except Exception as e:
        st.error(f"Error IA: {e}")
        return None

model = get_model()

# 4. FUNCIÓN PARA COLOREAR LA TABLA (Semáforo)
def aplicar_estilos(row):
    cantidad = row['cantidad_actual']
    umbral = row['umbral_minimo']
    umbral = umbral if pd.notnull(umbral) else 0
    
    if cantidad <= 0:
        return ['background-color: #ffcccc; color: black'] * len(row) # Rojo
    elif cantidad <= umbral:
        return ['background-color: #fff4cc; color: black'] * len(row) # Amarillo
    return [''] * len(row)

# 5. DISEÑO DE LA INTERFAZ (Columnas)
st.markdown("### 🔬 Lab Aguilar: Sistema de Inventario")
col_chat, col_mon = st.columns([1, 1.5], gap="large")

# --- COLUMNA DERECHA: MONITOR (TABLA) ---
with col_mon:
    st.subheader("📊 Inventario")
    res = supabase.table("items").select("*").execute()
    df = pd.DataFrame(res.data)
    
    # LIMPIEZA: Quitar decimales (.00000) de los números
    df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
    df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
    
    # Buscador
    busqueda = st.text_input("🔍 Buscar producto...", "")
    df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    # Mostrar por categorías
    for cat in sorted(df_show['categoria'].fillna("SIN CATEGORÍA").unique()):
        with st.expander(f"📁 {cat}"):
            # Seleccionar solo las columnas que quieres ver
            subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
            
            # Dibujar la tabla con colores y sin decimales
            st.dataframe(
                subset.style.apply(aplicar_estilos, axis=1).format({
                    "cantidad_actual": "{:.0f}",
                    "umbral_minimo": "{:.0f}"
                }), 
                use_container_width=True, 
                hide_index=True
            )

# --- COLUMNA IZQUIERDA: CHAT ---
with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=520, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. Inventario listo y sin decimales. ¿Qué hacemos?"}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Ej: 'Gaste 5 puntas' o 'Cambia el umbral a 10'"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Contexto para que la IA sepa qué hay en stock
        contexto_ia = df[['id', 'nombre', 'cantidad_actual', 'umbral_minimo']].to_csv(index=False, sep="|")
        
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    full_prompt = f"Inventario:\n{contexto_ia}\n\nInstrucción: {prompt}\n\nResponde con UPDATE_BATCH: [{{id:N, cantidad:N, umbral:N}}]"
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
                        texto = texto.split("UPDATE_BATCH:")[0] + "\n\n✅ **Base de datos actualizada.**"
                    
                    st.markdown(texto)
                    st.session_state.messages.append({"role": "assistant", "content": texto})
                    if "✅" in texto: st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
