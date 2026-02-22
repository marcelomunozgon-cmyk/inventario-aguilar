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

# --- 2. LÓGICA DE DATOS ---
def aplicar_estilos(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    if cant <= 0: return ['background-color: #ffcccc; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# Cargar inventario completo
res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

# Asegurar que las columnas clave existan aunque estén vacías
if 'cantidad_actual' not in df.columns: df['cantidad_actual'] = 0
if 'umbral_minimo' not in df.columns: df['umbral_minimo'] = 0
if 'subcategoria' not in df.columns: df['subcategoria'] = ""

df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
df['subcategoria'] = df['subcategoria'].fillna("")

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")

# Panel de Compras Urgentes
df_urgente = df[df['cantidad_actual'] <= df['umbral_minimo']]
if not df_urgente.empty:
    with st.expander("⚠️ **COMPRAS URGENTES (Stock bajo mínimo)**", expanded=False):
        cols_urgentes = [c for c in ['nombre', 'cantidad_actual', 'umbral_minimo', 'unidad'] if c in df.columns]
        st.dataframe(df_urgente[cols_urgentes].style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    tab_inventario, tab_historial, tab_editar = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar Catálogo"])
    
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        
        # Agrupación por Categoría y Subcategoría
        categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
        for cat in categorias:
            with st.expander(f"📁 {cat}"):
                subset_cat = df_show[df_show['categoria'] == cat]
                subcategorias = sorted(subset_cat['subcategoria'].unique())
                
                for subcat in subcategorias:
                    # Si tiene subcategoría, mostramos un subtítulo
                    if subcat != "":
                        st.markdown(f"<h5 style='color:#555;'>└ 📂 {subcat}</h5>", unsafe_allow_html=True)
                    
                    subset_sub = subset_cat[subset_cat['subcategoria'] == subcat]
                    # Ocultar ID y columnas de categoría para una vista más limpia
                    cols_vista = [c for c in subset_sub.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]
                    st.dataframe(subset_sub[cols_vista].style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)
                
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

    # --- PESTAÑA DE EDICIÓN AVANZADA ---
    with tab_editar:
        st.info("💡 **Tip:** Escribe un nombre nuevo en 'categoria' o 'subcategoria' para crear una nueva carpeta.")
        
        todas_las_columnas = df.columns.tolist()
        cols_default = [c for c in ['nombre', 'categoria', 'subcategoria', 'cantidad_actual', 'unidad', 'ubicacion'] if c in todas_las_columnas]
        
        # Selector para ocultar/mostrar columnas
        columnas_seleccionadas = st.multiselect(
            "👁️ Selecciona las columnas que deseas ver/editar:",
            options=todas_las_columnas,
            default=cols_default
        )
        
        # Forzamos que 'id' siempre esté presente para poder guardar, pero lo deshabilitamos
        if 'id' not in columnas_seleccionadas:
            columnas_seleccionadas.insert(0, 'id')
            
        df_edit = df[columnas_seleccionadas].copy()
        
        # Editor de datos interactivo
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "cantidad_actual": st.column_config.NumberColumn("Stock", min_value=0)
            },
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic" # Permite agregar o eliminar filas
        )
        
        if st.button("💾 Guardar Catálogo", type="primary"):
            with st.spinner("Guardando en la base de datos..."):
                try:
                    # Limpiamos los NaNs para evitar errores de JSON en Supabase
                    edited_df = edited_df.replace({np.nan: None})
                    
                    cambios = 0
                    for index, row in edited_df.iterrows():
                        # Si es una fila nueva o modificada
                        if index >= len(df_edit) or not row.equals(df_edit.loc[index]):
                            row_dict = row.dropna().to_dict()
                            
                            # Si es nuevo (no tiene ID), lo quitamos para que Supabase lo genere
                            if 'id' in row_dict and row_dict['id'] is None:
                                del row_dict['id']
                            elif 'id' in row_dict:
                                row_dict['id'] = int(row_dict['id'])
                                
                            supabase.table("items").upsert(row_dict).execute()
                            cambios += 1
                            
                    if cambios > 0:
                        st.success(f"¡{cambios} cambios guardados con éxito!")
                        st.rerun()
                    else:
                        st.warning("No se detectaron cambios.")
                except Exception as e:
                    st.error(f"Error al guardar: {e}")

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hola. Puedes usar la voz para actualizar stock, o la pestaña 'Editar Catálogo' para gestionar ubicaciones y subcategorías."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    st.write("🎙️ **Dictado por Voz:**")
    v_in = speech_to_text(language='es-CL', start_prompt="🎤 INICIAR GRABACIÓN", stop_prompt="🛑 DETENER Y ENVIAR AL CHAT", just_once=True, key='voice_input')
    m_in = st.chat_input("O escribe aquí...")
    prompt = v_in if v_in else m_in

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = df.to_csv(index=False, sep="|")
                    sys_p = f"""
                    Inventario Actual:
                    {ctx}
                    Instrucción: "{prompt}"
                    Diccionario: "eppendorf"=1.5mL, "falcon"=15mL/50mL, "bolsa"=suma 1.
                    Reglas:
                    1. ACTUALIZAR STOCK: UPDATE_BATCH: [{{"id": N, "cantidad_final": N, "diferencia": N, "nombre": "texto"}}]
                    2. NUEVO: INSERT_NEW: {{"nombre": "T", "categoria": "T", "subcategoria": "T", "cantidad_actual": N, "unidad": "T"}}
                    3. EDITAR: EDIT_ITEM: [{{"id": N, "cambios": {{"columna": "valor"}}}}]
                    """
                    
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai:
                        updates = json.loads(res_ai.split("UPDATE_BATCH:")[1].strip().replace("'", '"'))
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
                        new_item = json.loads(res_ai.split("INSERT_NEW:")[1].strip().replace("'", '"'))
                        supabase.table("items").insert(new_item).execute()
                        st.markdown("✅ **Nuevo reactivo agregado.**")
                        st.rerun()
                    elif "EDIT_ITEM:" in res_ai:
                        edits = json.loads(res_ai.split("EDIT_ITEM:")[1].strip().replace("'", '"'))
                        for edit in edits:
                            supabase.table("items").update(edit["cambios"]).eq("id", edit["id"]).execute()
                        st.markdown("✅ **Reactivo modificado.**")
                        st.rerun()
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error procesando la IA: {e}")
