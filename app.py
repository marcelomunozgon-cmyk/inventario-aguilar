import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date
import numpy as np
import PyPDF2
import io
import qrcode # NUEVA LIBRERÍA

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

# --- 2. LÓGICA DE DATOS Y ESTILOS ---
def aplicar_estilos(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    venc = row.get('fecha_vencimiento')
    
    if pd.notnull(venc) and venc != "":
        try:
            if datetime.strptime(str(venc), '%Y-%m-%d').date() < date.today():
                return ['background-color: #ffb3b3; color: #900; font-weight: bold'] * len(row)
        except: pass

    if cant <= 0: return ['background-color: #ffe6e6; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
for col in ['subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento']:
    if col not in df.columns: df[col] = ""

df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)

try:
    res_prot = supabase.table("protocolos").select("*").execute()
    df_prot = pd.DataFrame(res_prot.data)
except:
    df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

# --- 3. INTERFAZ SUPERIOR ---
col_logo, col_user = st.columns([3, 1])
with col_logo:
    st.markdown("## 🔬 Lab Aguilar: Control de Inventario")
with col_user:
    usuarios_lab = ["Marcelo Muñoz", "Rodrigo Aguilar", "Tesista / Estudiante", "Otro"]
    usuario_actual = st.selectbox("👤 Usuario Activo:", usuarios_lab, index=0)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción", type="secondary"):
            with st.spinner("Restaurando..."):
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
                except Exception as e: st.error(f"Error al restaurar: {e}")

    # --- NUEVA PESTAÑA AÑADIDA AQUÍ ---
    tab_inventario, tab_historial, tab_editar, tab_protocolos, tab_qr = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar Catálogo", "🧪 Protocolos", "🖨️ Etiquetas QR"])
    
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
                    st.dataframe(subset_sub[cols_vista].style.apply(aplicar_estilos, axis=1), column_config={"link_proveedor": st.column_config.LinkColumn("Proveedor", display_text="🌐 Ver")}, use_container_width=True, hide_index=True)
                
    with tab_historial:
        try:
            res_mov = supabase.table("movimientos").select("*").order("created_at", desc=True).limit(25).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                cols_hist = ['Fecha', 'usuario', 'nombre_item', 'tipo', 'cantidad_cambio']
                st.dataframe(df_mov[[c for c in cols_hist if c in df_mov.columns]], use_container_width=True, hide_index=True)
        except: st.info("No hay movimientos registrados.")

    with tab_editar:
        st.markdown("### ✍️ Edición Manual")
        columnas_visibles = st.multiselect("Columnas:", options=df.columns.tolist(), default=['nombre', 'categoria', 'cantidad_actual', 'unidad', 'lote', 'fecha_vencimiento'])
        if 'id' not in columnas_visibles: columnas_visibles.insert(0, 'id')
        
        edited_df = st.data_editor(df[columnas_visibles].copy(), column_config={"id": st.column_config.NumberColumn("ID", disabled=True), "fecha_vencimiento": st.column_config.DateColumn("Vencimiento")}, use_container_width=True, hide_index=True, num_rows="dynamic")
        
        if st.button("💾 Guardar Cambios"):
            crear_punto_restauracion(df)
            edited_df = edited_df.replace({np.nan: None})
            for index, row in edited_df.iterrows():
                row_dict = row.dropna().to_dict()
                if 'id' in row_dict:
                    if row_dict['id'] is not None: row_dict['id'] = int(row_dict['id'])
                    else: del row_dict['id']
                supabase.table("items").upsert(row_dict).execute()
            st.success("Cambios guardados.")
            st.rerun()

    with tab_protocolos:
        st.markdown("### ▶️ Ejecución Rápida (Sin Chat)")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            p_sel = st.selectbox("Protocolo:", df_prot['nombre'] if not df_prot.empty else ["Vacío"])
        with c2:
            n_muestras = st.number_input("N° Muestras:", min_value=1, value=1)
        with c3:
            st.write(" ")
            st.write(" ")
            if st.button("🚀 Ejecutar", type="primary", use_container_width=True):
                if not df_prot.empty:
                    with st.spinner("Calculando..."):
                        try:
                            info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                            # LÓGICA LOCAL PARA AHORRAR CUOTA DE IA
                            lineas = info_p.split('\n')
                            exitos = 0
                            for linea in lineas:
                                match = re.search(r'([^:-]+)[:\-]\s*(\d+)', linea)
                                if match:
                                    nombre_b = match.group(1).strip()
                                    cant_m = int(match.group(2))
                                    total_d = cant_m * n_muestras
                                    item_db = df[df['nombre'].str.contains(nombre_b, case=False, na=False)]
                                    if not item_db.empty:
                                        id_it = int(item_db.iloc[0]['id'])
                                        nueva_c = int(item_db.iloc[0]['cantidad_actual']) - total_d
                                        supabase.table("items").update({"cantidad_actual": nueva_c}).eq("id", id_it).execute()
                                        supabase.table("movimientos").insert({"item_id": id_it, "nombre_item": item_db.iloc[0]['nombre'], "cantidad_cambio": -total_d, "tipo": "Salida", "usuario": usuario_actual}).execute()
                                        exitos += 1
                            if exitos > 0:
                                st.success("¡Inventario descontado correctamente!")
                                st.rerun()
                            else:
                                st.warning("El protocolo no tiene el formato correcto de receta (Reactivo: Cantidad).")
                        except Exception as e: st.error(f"Error: {e}")

        st.markdown("---")
        st.markdown("### 🤖 Cargar PDF de Kit")
        file = st.file_uploader("Arrastra manual PDF", type=["pdf"])
        if file and st.button("✨ Analizar PDF"):
            with st.spinner("Analizando..."):
                try:
                    read = PyPDF2.PdfReader(file)
                    txt = "".join([read.pages[i].extract_text() for i in range(min(len(read.pages), 10))])
                    prompt_pdf = f"Extrae los reactivos de este kit. Responde estrictamente con este formato para que una calculadora lo lea: 'Reactivo: Cantidad'.\nTexto: {txt[:20000]}"
                    res_p = model.generate_content(prompt_pdf).text
                    supabase.table("protocolos").insert({"nombre": file.name, "materiales_base": res_p}).execute()
                    st.success("Guardado.")
                    st.rerun()
                except Exception as e: st.error(f"Error de cuota. Intenta luego: {e}")

    # --- PESTAÑA NUEVA: GENERADOR DE QR ---
    with tab_qr:
        st.markdown("### 🖨️ Generador de Etiquetas QR")
        st.info("Imprime estas etiquetas y pégalas en los frascos. Pronto habilitaremos la cámara para escanear y descontar reactivos al instante.")
        
        # Seleccionar el producto
        item_para_qr = st.selectbox("Selecciona un reactivo del inventario:", df['nombre'].tolist())
        
        if item_para_qr:
            fila_item = df[df['nombre'] == item_para_qr].iloc[0]
            
            # El "secreto" del QR: un string con el ID exacto de Supabase
            codigo_interno = f"LAB_AGUILAR_ID:{fila_item['id']}"
            
            # Crear la imagen QR
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(codigo_interno)
            qr.make(fit=True)
            img_qr = qr.make_image(fill_color="black", back_color="white")
            
            # Convertir a formato que Streamlit pueda mostrar/descargar
            buf = io.BytesIO()
            img_qr.save(buf, format="PNG")
            
            col_img, col_info = st.columns([1, 2])
            with col_img:
                st.image(buf, width=200)
            with col_info:
                st.markdown(f"**Reactivo:** {fila_item['nombre']}")
                st.markdown(f"**Categoría:** {fila_item['categoria']}")
                st.markdown(f"**Lote:** {fila_item.get('lote', 'N/A')}")
                st.markdown(f"**Venc. / Expira:** {fila_item.get('fecha_vencimiento', 'N/A')}")
                
                # Botón para descargar
                st.download_button(
                    label="⬇️ Descargar Etiqueta (PNG)", 
                    data=buf.getvalue(), 
                    file_name=f"QR_{fila_item['nombre'].replace(' ', '_')}.png", 
                    mime="image/png"
                )

with col_chat:
    st.subheader("💬 Asistente")
    chat_box = st.container(height=400, border=True)
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Hola {usuario_actual}. Recuerda usar la voz para consultas complejas y los botones para ahorrar cuota de IA."}]

    with chat_box:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎤 Hablar", stop_prompt="🛑 Enviar", just_once=True, key='voice')
    prompt = v_in if v_in else st.chat_input("Escribe aquí...")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            st.chat_message("user").markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    ctx = f"Usuario:{usuario_actual}\nInv:{df.to_csv(sep='|')}"
                    res_ai = model.generate_content(f"{ctx}\nHistorial: {st.session_state.messages[-4:]}\nPrompt: {prompt}\nResponde con texto o JSON (UPDATE_BATCH, INSERT_NEW, EDIT_ITEM)").text
                    
                    if any(x in res_ai for x in ["UPDATE_BATCH", "INSERT_NEW", "EDIT_ITEM"]):
                        crear_punto_restauracion(df)
                        if "UPDATE_BATCH:" in res_ai:
                            m = re.search(r'\[.*\]', res_ai, re.DOTALL)
                            for it in json.loads(m.group().replace("'", '"')):
                                supabase.table("items").update({"cantidad_actual": it["cantidad_final"]}).eq("id", it["id"]).execute()
                                supabase.table("movimientos").insert({"item_id": it["id"], "nombre_item": it["nombre"], "cantidad_cambio": it["diferencia"], "tipo": "Salida", "usuario": usuario_actual}).execute()
                        st.rerun()
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e: st.error(f"Límite de cuota IA. Espera un poco. {e}")
