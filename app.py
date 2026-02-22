import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
from datetime import datetime
from streamlit_mic_recorder import mic_recorder # <--- Nueva Librería

# --- CONFIGURACIÓN Y CONEXIONES (Igual que antes) ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error: Revisa las llaves API.")
    st.stop()

@st.cache_resource
def get_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        m_name = next((m for m in available_models if '1.5-flash' in m), available_models[0])
        return genai.GenerativeModel(m_name)
    except Exception as e:
        st.error(f"Error IA: {e}"); return None

model = get_model()

def aplicar_estilos(row):
    cantidad = row['cantidad_actual']
    umbral = row['umbral_minimo']
    umbral = umbral if pd.notnull(umbral) else 0
    if cantidad <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    elif cantidad <= umbral: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# --- INTERFAZ ---
st.markdown("### 🔬 Lab Aguilar: Control por Voz e Inventario")
col_chat, col_mon = st.columns([1, 1.5], gap="large")

# --- MONITOR (DERECHA) ---
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

# --- CHAT Y VOZ (IZQUIERDA) ---
with col_chat:
    st.subheader("💬 Asistente (Voz/Texto)")
    chat_box = st.container(height=450, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Rodrigo. Pulsa el micrófono para hablar o escribe abajo."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

# --- BOTÓN DE MICRÓFONO CON DEPURACIÓN ---
    st.write("🎙️ Control por Voz:")
    audio = mic_recorder(
        start_prompt="🔴 Iniciar Grabación", 
        stop_prompt="🟢 Detener y Procesar", 
        key='recorder',
        use_container_width=True
    )
    
    input_text = st.chat_input("O escribe aquí...")
    
    prompt = None

    # Si hay una acción de audio
    if audio:
        if 'text' in audio and audio['text']:
            prompt = audio['text']
            st.toast(f"🎙️ Escuché: {prompt}") # Notificación rápida
        else:
            # Si el audio existe pero el texto no, mostramos aviso
            st.warning("⚠️ El micrófono capturó audio, pero la transcripción falló. Revisa tu conexión a internet o intenta hablar más claro.")
    elif input_text:
        prompt = input_text

    if prompt:
        # Aquí sigue el resto de tu lógica de st.session_state.messages...
    
    # LÓGICA DE DETECCIÓN DE ENTRADA
    prompt = None
    if audio and 'text' in audio and audio['text']:
        prompt = audio['text']  # Si hay voz, tomamos la voz
    elif input_text:
        prompt = input_text     # Si no, tomamos el teclado

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
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
                            # Mapeo seguro de campos
                            upd = {}
                            if "cantidad" in item: upd["cantidad_actual"] = item["cantidad"]
                            if "umbral" in item: upd["umbral_minimo"] = item["umbral"]
                            if "categoria" in item: upd["categoria"] = item["categoria"]
                            
                            if upd: # Solo si hay algo que actualizar
                                supabase.table("items").update(upd).eq("id", item["id"]).execute()
                        
                        texto = texto.split("UPDATE_BATCH:")[0] + "\n\n✅ **Inventario actualizado.**"
                    
                    st.markdown(texto)
                    st.session_state.messages.append({"role": "assistant", "content": texto})
                    if "✅" in texto: st.rerun()
                except Exception as e:
                    st.error(f"Error procesando: {e}")
