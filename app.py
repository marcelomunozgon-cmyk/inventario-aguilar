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
df['subcategoria'] = df['subcategoria'].fillna("")
df['link_proveedor'] = df['link_proveedor'].fillna("")

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
                    
                    cols_vista = [c for c in subset_sub.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]
                    st.dataframe(
                        subset_sub[cols_vista].style.apply(aplicar_estilos, axis=1), 
                        column_config={"link_proveedor": st.column_config.LinkColumn("Proveedor", display_text="🌐 Ver Proveedor")},
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
        st.markdown("### 🤖 Asistente de IA para el Catálogo")
        st.info("La IA puede analizar todos tus reactivos actuales y asignarles automáticamente la mejor Categoría, Subcategoría y un Link de búsqueda hacia el proveedor.")
        if st.button("✨ Auto-Clasificar Todo con IA", type="primary"):
            with st.spinner("Analizando inventario... (Esto puede tardar hasta un minuto si hay muchos items)"):
                try:
                    # Pasamos un dataset limpio a la IA
                    ctx_clasificar = df[['id', 'nombre']].to_csv(index=False, sep="|")
                    sys_clasificar = f"""
                    Eres un sistema LIMS experto en biología molecular.
                    Base de datos actual de reactivos (IDs y nombres):
                    {ctx_clasificar}
                    
                    Tu tarea:
                    1. Asignar 'categoria'.
                    2. Asignar 'subcategoria'.
                    3. Crear 'link_proveedor' (búsqueda en Thermo Fisher, NEB, Sigma, etc).
                    
                    REGLA ESTRICTA DE FORMATO JSON:
                    - Devuelve ÚNICAMENTE un array de JSON válido.
                    - Las claves deben usar comillas dobles "".
                    - NO uses comillas dobles ni simples dentro de los valores de texto. Reemplázalas por espacios si es necesario.
                    - Formato exacto requerido:
                    [
                        {{"id": 1, "categoria": "Enzimas", "subcategoria": "Polimerasas", "link_proveedor": "https://..."}},
                        {{"id": 2, "categoria": "Plásticos", "subcategoria": "Tubos", "link_proveedor": "https://..."}}
                    ]
                    """
                    res_clasificacion = model.generate_content(sys_clasificar).text
                    
                    # Extraemos el JSON crudo sin hacer reemplazos peligrosos de comillas
                    match = re.search(r'\[.*\]', res_clasificacion, re.DOTALL)
                    
                    if match:
                        json_str = match.group()
                        nuevos_datos = json.loads(json_str)
                        crear_punto_restauracion(df)
                        
                        for item in nuevos_datos:
                            supabase.table("items").update({
                                "categoria": item.get("categoria", "General"),
                                "subcategoria": item.get("subcategoria", ""),
                                "link_proveedor": item.get("link_proveedor", "")
                            }).eq("id", item["id"]).execute()
                            
                        st.success("¡Inventario clasificado y actualizado con éxito!")
                        st.rerun()
                    else:
                        st.error("La IA no devolvió un formato válido. Intenta de nuevo.")
                        st.write("Respuesta cruda para depurar:", res_clasificacion)
                except json.JSONDecodeError as je:
                    st.error(f"Error de formato JSON: {je}")
                    st.write("Dile al desarrollador que la IA devolvió este texto mal formado:", json_str)
                except Exception as e:
                    st.error(f"Error general: {e}")

        st.markdown("---")
        st.markdown("### ✍️ Edición Manual")
        todas_las_columnas = df.columns.tolist()
        columnas_seleccionadas = st.multiselect("👁️ Columnas visibles:", options=todas_las_columnas, default=[c for c in ['nombre', 'categoria', 'subcategoria', 'cantidad_actual', 'unidad', 'link_proveedor'] if c in todas_las_columnas])
        if 'id' not in columnas_seleccionadas: columnas_seleccionadas.insert(0, 'id')
            
        df_edit = df[columnas_seleccionadas].copy()
        
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": st.column_config.Number
