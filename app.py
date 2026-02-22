import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide")

# Inicialización segura de conexiones
try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except:
    st.error("Error en Secrets.")
    st.stop()

# Auto-detección de modelo
@st.cache_resource
def get_model():
    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    m_name = next((m for m in models if '1.5-flash' in m), models[0])
    return genai.GenerativeModel(m_name)

model = get_model()

# --- LÓGICA DE ACTUALIZACIÓN MASIVA (El Corazón del Sistema) ---
def aplicar_cambios_db(json_str):
    try:
        # Limpiar posibles textos basura de la IA alrededor del JSON
        start = json_str.find('[')
        end = json_str.rfind(']') + 1
        data = json.loads(json_str[start:end])
        
        exitos = 0
        for item in data:
            upd = {}
            if "categoria" in item: upd["categoria"] = item["categoria"]
            if "cantidad" in item: upd["cantidad_actual"] = item["cantidad"]
            if "ubicacion" in item: upd["ubicacion_detallada"] = item["ubicacion"]
            
            # Ejecutar update en Supabase
            supabase.table("items").update(upd).eq("id", item["id"]).execute()
            exitos += 1
        return exitos
    except Exception as e:
        st.error(f"Error procesando JSON: {e}")
        return 0

# --- INTERFAZ ---
st.title("🔬 Lab Aguilar: Control de Inventario")

col_chat, col_mon = st.columns([1, 1.2])

# Monitor de Inventario (Derecha)
with col_mon:
    res = supabase.table("items").select("id, nombre, categoria, cantidad_actual, unidad").execute()
    df = pd.DataFrame(res.data)
    
    # Preparamos el contexto para la IA de forma ultra-compacta
    # ID | NOMBRE | CAT
    contexto_ia = df[['id', 'nombre', 'categoria']].to_csv(index=False, sep="|")
    
    st.subheader("📊 Inventario Actual")
    busqueda = st.text_input("Filtrar por nombre...")
    df_display = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
    
    for cat in sorted(df_display['categoria'].fillna("SIN CAT").unique()):
        with st.expander(f"📁 {cat}"):
            st.table(df_display[df_display['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad']])

# Chat (Izquierda)
with col_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Listo para cambios masivos. ¿Qué movemos?"}]

    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Ej: Cambia todos los Eppendorf a CONSUMIBLES"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # PROMO PARA LA IA
        full_prompt = f"""
        Actúa como administrador de base de datos.
        Inventario:
        {contexto_ia}
        
        Instrucción: "{prompt}"
        
        Si debes cambiar varios productos, genera una lista JSON con este formato:
        UPDATE_BATCH: [{{"id": 1, "categoria": "NUEVA"}}, {{"id": 2, "categoria": "NUEVA"}}]
        Responde confirmando los nombres y luego el código.
        """
        
        with st.chat_message("assistant"):
            try:
                response = model.generate_content(full_prompt)
                texto_ai = response.text
                
                if "UPDATE_BATCH:" in texto_ai:
                    n_cambios = aplicar_cambios_db(texto_ai.split("UPDATE_BATCH:")[1])
                    texto_ai = texto_ai.split("UPDATE_BATCH:")[0] + f"\n\n✅ **{n_cambios} ítems actualizados.**"
                
                st.markdown(texto_ai)
                st.session_state.messages.append({"role": "assistant", "content": texto_ai})
                if "✅" in texto_ai: st.rerun()
            except Exception as e:
                st.error(f"Error de cuota/API: {e}")
