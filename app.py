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

# Panel de Compras Urgentes
df_urgente = df[df['cantidad_actual'] <= df['umbral_minimo']]
if not df_urgente.empty:
    with st.expander("⚠️ **COMPRAS URGENTES (Stock bajo mínimo)**", expanded=False):
        st.dataframe(df_urgente[['nombre', 'cantidad_actual', 'umbral_minimo', 'unidad']].style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    # --- NUEVO: 3 Pestañas ---
    tab_inventario, tab_historial, tab_editar = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar Catálogo"])
    
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        
        categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
        for cat in categorias:
            with st.expander(f"📁 {cat}"):
                subset = df_show[df_show['categoria'] == cat][['nombre', 'cantidad_actual', 'unidad', 'umbral_minimo']]
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

    # --- NUEVO: Pestaña de Edición Manual ---
    with tab_editar:
        st.info("Haz doble clic en cualquier celda para editar (nombres, categorías, unidades, etc.). Al terminar, presiona Guardar.")
        
        # Preparamos los datos para el editor (ocultamos columnas que no se deben tocar)
        df_edit = df[['id', 'nombre', 'categoria', 'cantidad_actual', 'unidad', 'umbral_minimo']].copy()
        
        # El editor interactivo
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True), # Bloqueamos el ID para no romper la base de datos
                "nombre": st.column_config.TextColumn("Nombre del Reactivo", required=True),
                "categoria": st.column_config.TextColumn("Categoría"),
                "cantidad_actual": st.column_config.NumberColumn("Stock", min_value=0),
                "unidad": st.column_config.TextColumn("Unidad"),
                "umbral_minimo": st.column_config.NumberColumn("Alerta Mínima", min_value=0)
            },
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic" # Permite incluso borrar o agregar filas manualmente
        )
        
        if st.button("💾 Guardar Cambios Manuales", type="primary"):
            with st.spinner("Guardando en base de datos..."):
                try:
                    # Buscamos qué filas cambiaron comparando el original con el editado
                    cambios_realizados = 0
                    for index, row in edited_df.iterrows():
                        # Si es una fila nueva o existente modificada
                        if index >= len(df_edit) or not row.equals(df_edit.loc[index]):
                            supabase.table("items").upsert({
                                "id": int(row["id"]) if pd.notna(row["id"]) else None,
                                "nombre": row["nombre"],
                                "categoria": row["categoria"],
                                "cantidad_actual": int(row["cantidad_actual"]),
                                "unidad": row["unidad"],
                                "umbral_minimo": int(row["umbral_minimo"])
                            }).execute()
                            cambios_realizados += 1
                    
                    if cambios_realizados > 0:
                        st.success(f"¡Se actualizaron {cambios_realizados} reactivos correctamente!")
                        st.rerun()
                    else:
                        st.warning("No detecté ningún cambio para guardar.")
                except Exception as e:
                    st.error(f"Hubo un problema al guardar: {e}")

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola Marcelo. Usa el micrófono para movimientos rápidos, o la pestaña 'Editar Catálogo' para correcciones de fondo."}]

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

    # --- 5. PROCESAMIENTO E IA AVANZADA ---
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df[['id', 'nombre', 'cantidad_actual', 'unidad', 'categoria', 'umbral_minimo']].to_csv(index=False, sep="|")
                    
                    sys_p = f"""
                    Inventario Actual:
                    {ctx}
                    
                    Instrucción del usuario: "{prompt}"
                    
                    Diccionario de jerga:
                    - "eppendorf" = tubos de 1.5mL
                    - "falcon" = tubos de 15mL o 50mL
                    - "tips amarillas" = puntas de 200uL
                    - "agua miliq" = agua ultrapura
                    - "bolsa" = suma 1.
                    
                    Reglas (Elige UNA y responde en JSON estricto):
                    1. ACTUALIZAR STOCK: 
                       UPDATE_BATCH: [{{"id": N, "cantidad_final": N, "diferencia": N, "nombre": "texto"}}]
                    2. AGREGAR NUEVO:
                       INSERT_NEW: {{"nombre": "texto", "categoria": "texto", "cantidad_actual": N, "unidad": "texto", "umbral_minimo": 0}}
                    3. EDITAR ITEM EXISTENTE:
                       EDIT_ITEM: [{{"id": N, "cambios": {{"unidad": "gramos"}}}}]
                    4. Si no es claro, responde con texto normal.
                    """
                    
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai:
                        clean_json = res_ai.split("UPDATE_BATCH:")[1].strip().replace("'", '"')
                        updates = json.loads(clean_json)
                        for item in updates:
                            supabase.table("items").update({"cantidad_actual": int(item["cantidad_final"])}).eq("id", item["id"]).execute()
                            try:
                                supabase.table("movimientos").insert({
                                    "item_id": item["id"], "nombre_item": item["nombre"],
                                    "cantidad_cambio": item["diferencia"], "tipo": "Entrada" if item["diferencia"] > 0 else "Salida"
                                }).execute()
                            except: pass
                        st.markdown("✅ **Stock actualizado.**")
                        st.rerun()
                        
                    elif "INSERT_NEW:" in res_ai:
                        clean_json = res_ai.split("INSERT_NEW:")[1].strip().replace("'", '"')
                        new_item = json.loads(clean_json)
                        supabase.table("items").insert(new_item).execute()
                        st.markdown(f"✅ **Nuevo reactivo agregado.**")
                        st.rerun()
                        
                    elif "EDIT_ITEM:" in res_ai:
                        clean_json = res_ai.split("EDIT_ITEM:")[1].strip().replace("'", '"')
                        edits = json.loads(clean_json)
                        for edit in edits:
                            supabase.table("items").update(edit["cambios"]).eq("id", edit["id"]).execute()
                        st.markdown("✅ **Propiedades actualizadas.**")
                        st.rerun()
                        
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error procesando la instrucción: {e}")
