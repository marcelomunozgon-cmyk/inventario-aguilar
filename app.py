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

# --- INICIALIZAR MEMORIA DE RESPALDO (UNDO) ---
if "backup_inventario" not in st.session_state:
    st.session_state.backup_inventario = None

# Función para guardar la "foto" antes de hacer un cambio
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

# Asegurar columnas
for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
for col in ['subcategoria', 'link_proveedor']:
    if col not in df.columns: df[col] = ""

df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)
df['subcategoria'] = df['subcategoria'].fillna("")
df['link_proveedor'] = df['link_proveedor'].fillna("")

# --- 3. INTERFAZ ---
st.markdown("## 🔬 Lab Aguilar: Control de Inventario")

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    # --- BOTÓN DE DESHACER ---
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción (Restaurar Inventario)", type="secondary"):
            with st.spinner("Restaurando inventario..."):
                try:
                    # Restauramos los datos desde el backup
                    backup_df = st.session_state.backup_inventario
                    backup_df = backup_df.replace({np.nan: None})
                    for index, row in backup_df.iterrows():
                        row_dict = row.dropna().to_dict()
                        if 'id' in row_dict and row_dict['id'] is not None:
                            row_dict['id'] = int(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                    
                    st.session_state.backup_inventario = None # Limpiamos el backup usado
                    st.success("¡Inventario restaurado a su estado anterior!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_historial, tab_editar = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar Catálogo"])
    
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
                    
                    # Mostrar la tabla configurando el link para que sea un botón limpio
                    cols_vista = [c for c in subset_sub.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]
                    st.dataframe(
                        subset_sub[cols_vista].style.apply(aplicar_estilos, axis=1), 
                        column_config={
                            "link_proveedor": st.column_config.LinkColumn(
                                "Proveedor",
                                display_text="🌐 Ver Proveedor" # Esto oculta la URL larga
                            )
                        },
                        use_container_width=True, hide_index=True
                    )
                
    with tab_historial:
        try:
            res_mov = supabase.table("movimientos").select("*").order("created_at", desc=True).limit(20).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                st.dataframe(df_mov[['Fecha', 'nombre_item', 'tipo', 'cantidad_cambio']], use_container_width=True, hide_index=True)
        except: pass

    with tab_editar:
        st.info("💡 Usa **Ctrl+Z** en tu teclado para deshacer un error mientras editas las celdas.")
        todas_las_columnas = df.columns.tolist()
        columnas_seleccionadas = st.multiselect("👁️ Columnas visibles:", options=todas_las_columnas, default=[c for c in ['nombre', 'categoria', 'subcategoria', 'cantidad_actual', 'unidad', 'link_proveedor'] if c in todas_las_columnas])
        if 'id' not in columnas_seleccionadas: columnas_seleccionadas.insert(0, 'id')
            
        df_edit = df[columnas_seleccionadas].copy()
        
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "link_proveedor": st.column_config.TextColumn("URL del Proveedor")
            },
            use_container_width=True, hide_index=True, num_rows="dynamic"
        )
        
        if st.button("💾 Guardar Catálogo", type="primary"):
            with st.spinner("Guardando..."):
                crear_punto_restauracion(df) # Tomamos la foto antes de guardar
                edited_df = edited_df.replace({np.nan: None})
                for index, row in edited_df.iterrows():
                    if index >= len(df_edit) or not row.equals(df_edit.loc[index]):
                        row_dict = row.dropna().to_dict()
                        if 'id' in row_dict and row_dict['id'] is None: del row_dict['id']
                        elif 'id' in row_dict: row_dict['id'] = int(row_dict['id'])
                        supabase.table("items").upsert(row_dict).execute()
                st.success("Guardado. Si te equivocaste, ve arriba y usa 'Deshacer'.")
                st.rerun()

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=350, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Pídeme que agregue reactivos. Buscaré automáticamente su categoría y el link de compra (Thermo, NEB, Sigma, etc)."}]

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
                    ctx = df.to_csv(index=False, sep="|")
                    sys_p = f"""
                    Inventario: {ctx}
                    Instrucción: "{prompt}"
                    
                    Eres un experto en biología molecular. Si te piden agregar un reactivo (enzimas, kits, químicos, plásticos), debes deducir la mejor "categoria", "subcategoria" y generar un "link_proveedor" real de búsqueda hacia Thermo Fisher, NEB, Sigma Aldrich, Promega o Qiagen.
                    
                    Reglas (Elige UNA):
                    1. ACTUALIZAR STOCK: UPDATE_BATCH: [{{"id": N, "cantidad_final": N, "diferencia": N, "nombre": "texto"}}]
                    2. NUEVO REACTIVO: INSERT_NEW: {{"nombre": "T", "categoria": "T", "subcategoria": "T", "cantidad_actual": N, "unidad": "T", "link_proveedor": "https://..."}}
                    3. EDITAR EXISTENTE: EDIT_ITEM: [{{"id": N, "cambios": {{"columna": "valor"}}}}]
                    """
                    
                    res_ai = model.generate_content(sys_p).text
                    
                    if "UPDATE_BATCH:" in res_ai or "INSERT_NEW:" in res_ai or "EDIT_ITEM:" in res_ai:
                        crear_punto_restauracion(df) # Guardar la foto antes de que la IA modifique todo
                        
                        if "UPDATE_BATCH:" in res_ai:
                            updates = json.loads(res_ai.split("UPDATE_BATCH:")[1].strip().replace("'", '"'))
                            for item in updates:
                                supabase.table("items").update({"cantidad_actual": int(item["cantidad_final"])}).eq("id", item["id"]).execute()
                                try: supabase.table("movimientos").insert({"item_id": item["id"], "nombre_item": item["nombre"], "cantidad_cambio": item["diferencia"], "tipo": "Entrada" if item["diferencia"] > 0 else "Salida"}).execute()
                                except: pass
                                
                        elif "INSERT_NEW:" in res_ai:
                            new_item = json.loads(res_ai.split("INSERT_NEW:")[1].strip().replace("'", '"'))
                            supabase.table("items").insert(new_item).execute()
                            
                        elif "EDIT_ITEM:" in res_ai:
                            edits = json.loads(res_ai.split("EDIT_ITEM:")[1].strip().replace("'", '"'))
                            for edit in edits:
                                supabase.table("items").update(edit["cambios"]).eq("id", edit["id"]).execute()
                                
                        st.markdown("✅ **Comando ejecutado.** (Puedes deshacerlo con el botón de arriba si hubo un error).")
                        st.rerun()
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error procesando: {e}")
