import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime

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

# Cargar inventario
res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)
df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")

# NUEVO: Panel de Compras Urgentes (Nivel 2)
df_urgente = df[df['cantidad_actual'] <= df['umbral_minimo']]
if not df_urgente.empty:
    with st.expander("⚠️ **COMPRAS URGENTES (Stock bajo mínimo)**", expanded=True):
        st.dataframe(df_urgente[['nombre', 'cantidad_actual', 'umbral_minimo', 'unidad']].style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    # Pestañas para organizar mejor (Nivel 2)
    tab_inventario, tab_historial = st.tabs(["📦 Inventario", "⏱️ Historial de Movimientos"])
    
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        
        categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
        for cat in categorias:
            with st.expander(f"📁 {cat}"):
                subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad']]
                st.dataframe(subset, use_container_width=True, hide_index=True)
                
    with tab_historial:
        try:
            res_mov = supabase.table("movimientos").select("*").order("created_at", desc=True).limit(20).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                st.dataframe(df_mov[['Fecha', 'nombre_item', 'tipo', 'cantidad_cambio']], use_container_width=True, hide_index=True)
            else:
                st.info("No hay movimientos recientes.")
        except:
            st.warning("La tabla 'movimientos' aún no está creada en Supabase.")

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Marcelo. Prueba el botón de voz o escribe. Puedes pedirme agregar nuevos items o actualizar el stock."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # --- 4. MOTOR DE VOZ ---
    st.write("🎙️ **Dictado por Voz:**")
    v_in = speech_to_text(
        language='es-CL',
        start_prompt="🎤 INICIAR GRABACIÓN",
        stop_prompt="🛑 DETENER Y ENVIAR AL CHAT",
        just_once=True,
        key='voice_input'
    )
    
    m_in = st.chat_input("O escribe aquí...")
    prompt = v_in if v_in else m_in

    # --- 5. PROCESAMIENTO E IA AVANZADA (Nivel 1 y 3) ---
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad', 'categoria']].to_csv(index=False, sep="|")
                    
                    # Prompt enriquecido con jerga y nuevos comandos
                    sys_p = f"""
                    Inventario Actual:
                    {ctx}
                    
                    Instrucción del usuario: "{prompt}"
                    
                    Diccionario de jerga del Lab Aguilar:
                    - "eppendorf" o "tubo eppendorf" = tubos de 1.5mL
                    - "falcon" = tubos de 15mL o 50mL
                    - "tips amarillas" = puntas de 200uL
                    - "agua miliq" = agua ultrapura
                    - "bolsa" = si la unidad es bolsa, suma 1 a la cantidad.
                    
                    Reglas de respuesta (Elige SOLO UNA):
                    1. Si pide ACTUALIZAR stock existente, responde SOLO con: 
                       UPDATE_BATCH: [{{"id": N, "cantidad_final": N, "diferencia": N, "nombre": "texto"}}]
                       (Ej: Si había 10 y pide sacar 2, cantidad_final=8, diferencia=-2)
                    
                    2. Si pide AGREGAR un REACTIVO NUEVO que no está en la lista, responde SOLO con:
                       INSERT_NEW: {{"nombre": "texto", "categoria": "texto", "cantidad_actual": N, "unidad": "texto", "umbral_minimo": 0}}
                    
                    3. Si no es claro o falta información, responde con texto normal preguntando detalles.
                    """
                    
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai:
                        clean_json = res_ai.split("UPDATE_BATCH:")[1].strip().replace("'", '"')
                        updates = json.loads(clean_json)
                        
                        for item in updates:
                            # 1. Actualizar el stock
                            supabase.table("items").update({"cantidad_actual": int(item["cantidad_final"])}).eq("id", item["id"]).execute()
                            
                            # 2. Registrar el movimiento (Nivel 2)
                            tipo_mov = "Entrada" if item["diferencia"] > 0 else "Salida"
                            try:
                                supabase.table("movimientos").insert({
                                    "item_id": item["id"],
                                    "nombre_item": item["nombre"],
                                    "cantidad_cambio": item["diferencia"],
                                    "tipo": tipo_mov
                                }).execute()
                            except: pass # Ignorar si la tabla no existe aún
                            
                        st.markdown(f"✅ **Stock actualizado y registrado en historial.**")
                        st.session_state.messages.append({"role": "assistant", "content": "✅ **Inventario actualizado.**"})
                        st.rerun()
                        
                    elif "INSERT_NEW:" in res_ai:
                        # Lógica para agregar nuevos reactivos (Nivel 3)
                        clean_json = res_ai.split("INSERT_NEW:")[1].strip().replace("'", '"')
                        new_item = json.loads(clean_json)
                        
                        supabase.table("items").insert(new_item).execute()
                        st.markdown(f"✅ **Nuevo reactivo '{new_item['nombre']}' agregado al inventario.**")
                        st.session_state.messages.append({"role": "assistant", "content": f"✅ Nuevo item creado: {new_item['nombre']}"})
                        st.rerun()
                        
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error procesando la instrucción: {e}")
