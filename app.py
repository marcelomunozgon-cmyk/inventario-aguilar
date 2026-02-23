import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime
import numpy as np
import io
import qrcode
from PIL import Image

# --- 1. CONFIGURACIÓN DE PÁGINA Y CONEXIONES ---
st.set_page_config(page_title="Lab Aguilar OS - Pro", layout="wide", page_icon="🔬")

# Inicialización de estados de sesión
if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if 'chat_history' not in st.session_state: st.session_state.chat_history = []

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash') # Modelo rápido y eficiente para inventario
except Exception as e:
    st.error(f"Error de configuración (Secrets): {e}")
    st.stop()

# --- 2. FUNCIONES DE APOYO ---
def cargar_datos():
    """Trae la data fresca de Supabase"""
    res = supabase.table("items").select("*").execute()
    return pd.DataFrame(res.data)

def registrar_movimiento(item_id, nombre, cantidad, tipo, usuario):
    """Registra log de cambios"""
    supabase.table("movimiento").insert({
        "item_id": item_id,
        "nombre_item": nombre,
        "cantidad_cambio": cantidad,
        "tipo": tipo,
        "usuario": usuario
    }).execute()

# --- 3. DISEÑO DE INTERFAZ ---
st.title("🔬 Lab Aguilar: Gestión de Inventario")
usuario_activo = st.sidebar.selectbox("👤 Usuario en turno:", ["Marcelo Muñoz", "Rodrigo Aguilar", "Equipo Lab"])

# Layout Principal: Chat (Izquierda) | Monitor (Derecha)
col_chat, col_mon = st.columns([1, 1.8], gap="medium")

# --- MONITOR (DERECHA) ---
with col_mon:
    # Recargar datos
    df = cargar_datos()
    
    tab_inv, tab_import, tab_edit, tab_qr = st.tabs(["📦 Inventario Real", "📥 Carga Año Cero", "⚙️ Ajustes", "🖨️ Etiquetas"])

    # TAB: INVENTARIO VISUAL
    with tab_inv:
        search_query = st.text_input("🔍 Buscar reactivo...", value=st.session_state.auto_search)
        
        if not df.empty:
            # Filtrado por búsqueda
            df_filtered = df[df['nombre'].str.contains(search_query, case=False)] if search_query else df
            
            # Ordenamiento: Categoría -> Nombre
            df_filtered = df_filtered.sort_values(by=['categoria', 'nombre'])
            
            for cat in df_filtered['categoria'].unique():
                with st.expander(f"📁 {cat.upper()}", expanded=True):
                    subset = df_filtered[df_filtered['categoria'] == cat]
                    # Solo mostramos columnas relevantes para el usuario
                    st.dataframe(
                        subset[["nombre", "cantidad_actual", "unidad", "ubicacion", "lote"]],
                        use_container_width=True,
                        hide_index=True
                    )
        else:
            st.warning("El inventario está vacío. Ve a la pestaña de 'Carga Año Cero'.")

    # TAB: CARGA Y RESET (LO QUE PEDISTE)
   # --- PESTAÑA: IMPORTAR Y ELIMINAR TODO ---
    with tab_import:
        st.subheader("🧹 Limpieza y Reinicio")
        with st.container(border=True):
            st.write("⚠️ **Zona de Peligro:** Esta acción es irreversible.")
            check_borrado = st.checkbox("Entiendo que esto eliminará TODOS los registros actuales.")
            
            if st.button("🗑️ ELIMINAR TODO EL INVENTARIO", type="primary", disabled=not check_borrado):
                with st.spinner("Vaciando base de datos (Esto puede tomar unos segundos)..."):
                    try:
                        # SOLUCIÓN: Usamos columnas de texto para evitar el error de formato numérico del ID
                        supabase.table("movimiento").delete().neq("tipo", "BORRADO_SEGURO").execute()
                        supabase.table("items").delete().neq("nombre", "BORRADO_SEGURO").execute()
                        
                        st.success("✅ ¡Base de datos reseteada completamente! Está lista para recibir el Excel.")
                        st.rerun()
                    except Exception as err_borrado:
                        st.error(f"Fallo al borrar la base de datos. Detalle técnico: {err_borrado}")

        st.divider()
        st.subheader("📥 Cargar Nuevo Inventario (Excel)")
        archivo = st.file_uploader("Sube tu archivo .xlsx", type=["xlsx"])
        if archivo:
            try:
                # Motor openpyxl activado para evitar errores de lectura
                df_excel = pd.read_excel(archivo, engine='openpyxl')
                st.write("Vista previa de columnas detectadas:", df_excel.columns.tolist())
                
                # Limpieza por si hay espacios invisibles en tu Excel
                df_excel.columns = df_excel.columns.str.strip()
                
                if st.button("🚀 Iniciar Carga Masiva", type="primary"):
                    # Mapeo exacto basado en tu lista: Nombre, Formato, cantidad, Detalle, ubicación, categoria
                    df_prep = df_excel.rename(columns={
                        "Nombre": "nombre",
                        "Formato": "unidad",
                        "cantidad": "cantidad_actual",
                        "Detalle": "lote",
                        "ubicación": "ubicacion",
                        "categoria": "categoria"
                    }).replace({np.nan: None})
                    
                    # Validar que las columnas necesarias existan
                    cols_necesarias = ["nombre", "unidad", "cantidad_actual", "lote", "ubicacion", "categoria"]
                    data_dict = df_prep[cols_necesarias].to_dict(orient="records")
                    
                    with st.spinner("Insertando registros en Supabase..."):
                        supabase.table("items").insert(data_dict).execute()
                        
                        # Guardar el registro de la acción
                        supabase.table("movimiento").insert({
                            "nombre_item": "Múltiples Reactivos", 
                            "cantidad_cambio": len(data_dict), 
                            "tipo": "Carga Masiva Excel Año Cero", 
                            "usuario": usuario_actual
                        }).execute()
                        
                        st.success(f"¡Carga completada! {len(data_dict)} artículos añadidos a tu Lab OS.")
                        st.rerun()
            except Exception as e:
                st.error(f"Error procesando el Excel: {e}")

    # TAB: EDICIÓN RÁPIDA
    with tab_edit:
        if not df.empty:
            st.write("Ajuste manual de stock o ubicación:")
            edit_df = st.data_editor(df[["id", "nombre", "cantidad_actual", "ubicacion", "unidad"]], hide_index=True)
            if st.button("Guardar Cambios Manuales"):
                for _, r in edit_df.iterrows():
                    supabase.table("items").update({
                        "nombre": r['nombre'], 
                        "cantidad_actual": r['cantidad_actual'],
                        "ubicacion": r['ubicacion'],
                        "unidad": r['unidad']
                    }).eq("id", r['id']).execute()
                st.success("Cambios guardados.")
                st.rerun()

    # TAB: QR
    with tab_qr:
        if not df.empty:
            sel_qr = st.selectbox("Elegir para imprimir QR:", df['nombre'].tolist())
            item_data = df[df['nombre'] == sel_qr].iloc[0]
            img_qr = qrcode.make(f"LAB_ID:{item_data['id']}")
            buf = io.BytesIO()
            img_qr.save(buf, format="PNG")
            st.image(buf, caption=f"QR para {sel_qr}", width=200)

# --- ASISTENTE (IZQUIERDA) ---
with col_chat:
    st.subheader("💬 Asistente de Voz y Texto")
    
    chat_container = st.container(height=450, border=True)
    for m in st.session_state.chat_history:
        chat_container.chat_message(m["role"]).write(m["content"])

    # Entrada de voz
    voz = speech_to_text(language='es-CL', start_prompt="🎤 Hablar al Secretario", key='voice_btn')
    # Entrada de texto
    texto = st.chat_input("Ej: Tengo 5 bolsas de puntas en el cajón 10")
    
    prompt = voz if voz else texto

    if prompt:
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        chat_container.chat_message("user").write(prompt)
        
        with st.chat_message("assistant"):
            # Contexto para la IA
            inv_context = df[['id', 'nombre', 'ubicacion', 'unidad']].to_json(orient='records')
            instrucciones = f"""
            Eres el Secretario de Inventario del Lab Aguilar. 
            Regla: Si el usuario dice que algo existe en un lugar, tú le crees.
            Inventario actual: {inv_context}
            Si el item existe, obtén su ID. Si no, usa 'NUEVO'.
            Responde estrictamente en este formato JSON:
            EJECUTAR_ACCION:{{"id":"...","nombre":"...","cantidad":...,"unidad":"...","ubicacion":"..."}}
            """
            
            try:
                response = model.generate_content(f"{instrucciones}\nUsuario: {prompt}").text
                
                if "EJECUTAR_ACCION:" in response:
                    json_str = re.search(r'\{.*\}', response).group()
                    data = json.loads(json_str)
                    
                    if data['id'] == "NUEVO":
                        res = supabase.table("items").insert({
                            "nombre": data['nombre'], "cantidad_actual": data['cantidad'],
                            "unidad": data['unidad'], "ubicacion": data['ubicacion'],
                            "categoria": "GENERAL"
                        }).execute()
                        id_final = res.data[0]['id']
                    else:
                        supabase.table("items").update({
                            "cantidad_actual": data['cantidad'],
                            "ubicacion": data['ubicacion'],
                            "unidad": data['unidad']
                        }).eq("id", data['id']).execute()
                        id_final = data['id']
                    
                    registrar_movimiento(id_final, data['nombre'], data['cantidad'], "CHAT_UPDATE", usuario_activo)
                    st.session_state.auto_search = data['nombre'] # Redirección visual
                    
                    msg = f"✅ Registro actualizado: **{data['nombre']}** ahora tiene {data['cantidad']} {data['unidad']} en {data['ubicacion']}."
                    st.write(msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": msg})
                    st.rerun()
                else:
                    st.write(response)
                    st.session_state.chat_history.append({"role": "assistant", "content": response})
            except Exception as e:
                st.error(f"Error procesando petición: {e}")
