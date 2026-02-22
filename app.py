import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime
import numpy as np

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

if "backup_inventario" not in st.session_state:
    st.session_state.backup_inventario = None

def crear_punto_restauracion(df_actual):
    st.session_state.backup_inventario = df_actual.copy()

# --- 2. LÓGICA DE DATOS ---
def aplicar_estilos(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
for col in ['subcategoria', 'link_proveedor']:
    if col not in df.columns: df[col] = ""

df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)

# Cargar Protocolos
try:
    res_prot = supabase.table("protocolos").select("*").execute()
    df_prot = pd.DataFrame(res_prot.data)
except:
    df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción (Restaurar Inventario)", type="secondary"):
            with st.spinner("Restaurando inventario..."):
                try:
                    backup_df = st.session_state.backup_inventario.replace({np.nan: None})
                    for index, row in backup_df.iterrows():
                        row_dict = row.dropna().to_dict()
                        if 'id' in row_dict and row_dict['id'] is not None:
                            row_dict['id'] = int(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                    st.session_state.backup_inventario = None
                    st.success("¡Inventario restaurado!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_historial, tab_editar, tab_protocolos = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar Catálogo", "🧪 Protocolos"])
    
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
        for cat in categorias:
            with st.expander(f"📁 {cat}"):
                subset_cat = df_show[df_show['categoria'] == cat]
                subcategorias = sorted(subset_cat['subcategoria'].unique())
                for subcat in subcategorias:
                    if subcat != "": st.markdown(f"<h5 style='color:#555;'>└ 📂 {subcat}</h5>", unsafe_allow_html=True)
                    subset_sub = subset_cat[subset_cat['subcategoria'] == subcat]
                    cols_vista = [c for c in subset_sub.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]
                    st.dataframe(subset_sub[cols_vista].style.apply(aplicar_estilos, axis=1), column_config={"link_proveedor": st.column_config.LinkColumn("Proveedor", display_text="🌐 Ver Proveedor")}, use_container_width=True, hide_index=True)
                
    with tab_historial:
        try:
            res_mov = supabase.table("movimientos").select("*").order("created_at", desc=True).limit(20).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                st.dataframe(df_mov[['Fecha', 'nombre_item', 'tipo', 'cantidad_cambio']], use_container_width=True, hide_index=True)
        except: pass

    with tab_editar:
        st.markdown("### ✍️ Edición Manual")
        todas_las_columnas = df.columns.tolist()
        columnas_seleccionadas = st.multiselect("👁️ Columnas visibles:", options=todas_las_columnas, default=[c for c in ['nombre', 'categoria', 'subcategoria', 'cantidad_actual', 'unidad'] if c in todas_las_columnas])
        if 'id' not in columnas_seleccionadas: columnas_seleccionadas.insert(0, 'id')
        df_edit = df[columnas_seleccionadas].copy()
        
        edited_df = st.data_editor(df_edit, column_config={"id": st.column_config.NumberColumn("ID", disabled=True)}, use_container_width=True, hide_index=True, num_rows="dynamic")
        if st.button("💾 Guardar Cambios Manuales"):
            with st.spinner("Guardando..."):
                crear_punto_restauracion(df)
                edited_df = edited_df.replace({np.nan: None})
                for index, row in edited_df.iterrows():
                    if index >= len(df_edit) or not row.equals(df_edit.loc[index]):
                        row_dict = row.dropna().to_dict()
                        if 'id' in row_dict and row_dict['id'] is None: del row_dict['id']
                        elif 'id' in row_dict: row_dict['id'] = int(row_dict['id'])
                        supabase.table("items").upsert(row_dict).execute()
                st.success("Guardado exitoso.")
                st.rerun()

    # --- NUEVA PESTAÑA: PROTOCOLOS ---
    with tab_protocolos:
        st.markdown("### 📋 Mis Experimentos (Recetas)")
        st.info("Escribe aquí los protocolos recurrentes del laboratorio. La IA los leerá para saber qué reactivos descontar y qué variaciones preguntarte.")
        
        if not df_prot.empty:
            df_prot_edit = df_prot[['id', 'nombre', 'materiales_base']].copy()
        else:
            df_prot_edit = pd.DataFrame(columns=["id", "nombre", "materiales_base"])
            
        edited_prot = st.data_editor(
            df_prot_edit,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "nombre": st.column_config.TextColumn("Nombre del Experimento", width="medium"),
                "materiales_base": st.column_config.TextColumn("Materiales Base y Variaciones", width="large")
            },
            use_container_width=True, hide_index=True, num_rows="dynamic"
        )
        
        if st.button("💾 Guardar Protocolos"):
            with st.spinner("Guardando..."):
                edited_prot = edited_prot.replace({np.nan: None})
                for index, row in edited_prot.iterrows():
                    if index >= len(df_prot_edit) or not row.equals(df_prot_edit.loc[index]):
                        row_dict = row.dropna().to_dict()
                        if 'id' in row_dict and row_dict['id'] is None: del row_dict['id']
                        elif 'id' in row_dict: row_dict['id'] = int(row_dict['id'])
                        supabase.table("protocolos").upsert(row_dict).execute()
                st.success("Protocolos actualizados.")
                st.rerun()

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola. Dime qué experimento hiciste hoy o actualiza reactivos directamente."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎤 INICIAR GRABACIÓN", stop_prompt="🛑 DETENER Y ENVIAR", just_once=True, key='voice_input')
    m_in = st.chat_input("O escribe aquí...")
    prompt = v_in if v_in else m_in

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx_inv = df.to_csv(index=False, sep="|")
                    ctx_prot = df_prot.to_csv(index=False, sep="|") if not df_prot.empty else "No hay protocolos."
                    
                    # Le pasamos a la IA los últimos 6 mensajes del chat para que tenga MEMORIA
                    historial_chat = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-6:]])
                    
                    sys_p = f"""
                    Eres el asistente del Lab Aguilar (biología molecular).
                    
                    Inventario Actual:
                    {ctx_inv}
                    
                    Protocolos Frecuentes:
                    {ctx_prot}
                    
                    Historial Reciente de la Conversación:
                    {historial_chat}
                    
                    MISIONES:
                    A) Si el usuario reporta un EXPERIMENTO de los protocolos:
                       1. Revisa qué materiales_base usa.
                       2. Si no ha especificado cantidades o variaciones (ej: tipo de placa, volumen de medio), RESPÓNDELE EN TEXTO NORMAL preguntándole esos detalles. ("¿Cuántas placas P100 ocupaste y cuántos mL de DMEM?").
                       3. NO EJECUTES EL DESCUENTO HASTA QUE EL USUARIO RESPONDA Y CONFIRME.
                    
                    B) Si el usuario ya confirmó las cantidades o da una instrucción directa de stock:
                       Responde ÚNICAMENTE con el formato JSON:
                       UPDATE_BATCH: [{{"id": N, "cantidad_final": N, "diferencia": N, "nombre": "texto"}}]
                    """
                    
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai:
                        crear_punto_restauracion(df)
                        
                        updates = json.loads(res_ai.split("UPDATE_BATCH:")[1].strip())
                        for item in updates:
                            supabase.table("items").update({"cantidad_actual": int(item["cantidad_final"])}).eq("id", item["id"]).execute()
                            try: supabase.table("movimientos").insert({"item_id": item["id"], "nombre_item": item["nombre"], "cantidad_cambio": item["diferencia"], "tipo": "Entrada" if item["diferencia"] > 0 else "Salida"}).execute()
                            except: pass
                                
                        mensaje_final = "✅ **Materiales descontados correctamente según tu experimento.**"
                        st.markdown(mensaje_final)
                        st.session_state.messages.append({"role": "assistant", "content": mensaje_final})
                        st.rerun()
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error procesando la solicitud: {e}")
