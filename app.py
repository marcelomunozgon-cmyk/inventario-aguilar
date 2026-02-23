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
import qrcode
from PIL import Image

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
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        modelo_flash = next((m for m in modelos if 'flash' in m), None)
        
        if modelo_flash:
            nombre_limpio = modelo_flash.replace('models/', '')
            return genai.GenerativeModel(nombre_limpio)
        else:
            return genai.GenerativeModel(modelos[0].replace('models/', ''))
    except Exception as e:
        return None

model = get_model()

if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None

def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

# --- 2. LÓGICA DE DATOS Y ESTILOS ---
def aplicar_estilos(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    venc = row.get('fecha_vencimiento')
    if pd.notnull(venc) and venc != "":
        try:
            if datetime.strptime(str(venc), '%Y-%m-%d').date() < date.today(): return ['background-color: #ffb3b3; color: #900; font-weight: bold'] * len(row)
        except: pass
    if cant <= 0: return ['background-color: #ffe6e6; color: black'] * len(row)
    if umb > 0 and cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

for col in ['categoria', 'subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento', 'ubicacion', 'unidad']:
    if col not in df.columns: df[col] = ""
    df[col] = df[col].fillna("").astype(str)

df['categoria'] = df['categoria'].replace("", "GENERAL")

try: res_prot = supabase.table("protocolos").select("*").execute(); df_prot = pd.DataFrame(res_prot.data)
except: df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

try: res_muestras = supabase.table("muestras").select("*").execute(); df_muestras = pd.DataFrame(res_muestras.data)
except: df_muestras = pd.DataFrame(columns=["id", "codigo_muestra", "tipo", "ubicacion", "fecha_creacion", "notas"])

# --- 3. INTERFAZ SUPERIOR ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Lab Aguilar OS")
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
                            row_dict['id'] = str(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                    st.session_state.backup_inventario = None
                    st.success("¡Inventario restaurado!")
                    st.rerun()
                except Exception as e: st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_historial, tab_editar, tab_protocolos, tab_qr, tab_bioterio = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar", "🧪 Protocolos", "🖨️ QR", "❄️ Bioterio"])
    
    with tab_inventario:
        df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0)]
        if not df_criticos.empty:
            st.error("🚨 **ATENCIÓN: Reactivos con Stock Crítico**")
            st.dataframe(df_criticos[['nombre', 'categoria', 'cantidad_actual', 'umbral_minimo', 'unidad']], use_container_width=True, hide_index=True)
            st.markdown("---")

        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        
        categorias = sorted(df_show['categoria'].unique())
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
            res_mov = supabase.table("movimiento").select("*").order("created_at", desc=True).limit(25).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                cols_hist = ['Fecha', 'usuario', 'nombre_item', 'tipo', 'cantidad_cambio']
                st.dataframe(df_mov[[c for c in cols_hist if c in df_mov.columns]], use_container_width=True, hide_index=True)
        except: st.info("No hay movimientos registrados.")

    with tab_editar:
        st.markdown("### ✍️ Edición Manual de Inventario")
        cat_disp = ["Todas"] + sorted(df['categoria'].unique().tolist())
        filtro_cat = st.selectbox("📍 Filtrar por Categoría:", cat_disp)
        df_filtro = df if filtro_cat == "Todas" else df[df['categoria'] == filtro_cat]
        
        columnas_visibles = st.multiselect("Columnas:", options=df.columns.tolist(), default=['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'umbral_minimo'])
        if 'id' not in columnas_visibles: columnas_visibles.insert(0, 'id')
        
        edited_df = st.data_editor(df_filtro[columnas_visibles].copy(), column_config={"id": st.column_config.NumberColumn("ID", disabled=True)}, use_container_width=True, hide_index=True, num_rows="dynamic")
        
        if st.button("💾 Guardar Cambios"):
            crear_punto_restauracion(df)
            edited_df = edited_df.replace({np.nan: None})
            for index, row in edited_df.iterrows():
                row_dict = row.dropna().to_dict()
                if 'id' in row_dict:
                    if pd.isna(row_dict['id']) or str(row_dict['id']).strip() == "":
                        del row_dict['id'] 
                    else:
                        row_dict['id'] = str(row_dict['id'])
                supabase.table("items").upsert(row_dict).execute()
            st.success("Cambios guardados exitosamente.")
            st.rerun()

    with tab_protocolos:
        st.markdown("### ▶️ Ejecución Rápida (Sin Chat)")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1: p_sel = st.selectbox("Protocolo:", df_prot['nombre'] if not df_prot.empty else ["Vacío"])
        with c2: n_muestras = st.number_input("N° Muestras:", min_value=1, value=1)
        with c3:
            st.write(" "); st.write(" ")
            if st.button("🚀 Ejecutar", type="primary", use_container_width=True):
                if not df_prot.empty:
                    with st.spinner("Calculando..."):
                        try:
                            info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                            lineas = info_p.split('\n')
                            exitos = 0
                            for linea in lineas:
                                match = re.search(r'([^:-]+)[:\-]\s*(\d+)', linea)
                                if match:
                                    nombre_b = match.group(1).strip()
                                    total_d = int(match.group(2)) * n_muestras
                                    item_db = df[df['nombre'].str.contains(nombre_b, case=False, na=False)]
                                    if not item_db.empty:
                                        id_it = str(item_db.iloc[0]['id'])
                                        nueva_c = int(item_db.iloc[0]['cantidad_actual']) - total_d
                                        supabase.table("items").update({"cantidad_actual": nueva_c}).eq("id", id_it).execute()
                                        supabase.table("movimiento").insert({"item_id": id_it, "nombre_item": item_db.iloc[0]['nombre'], "cantidad_cambio": -total_d, "tipo": "Salida", "usuario": usuario_actual}).execute()
                                        exitos += 1
                            if exitos > 0:
                                st.success("¡Inventario descontado correctamente!")
                                st.rerun()
                        except Exception as e: st.error(f"Error: {e}")

        st.markdown("---")
        st.markdown("### 🤖 Cargar PDF de Kit")
        file = st.file_uploader("Arrastra manual PDF", type=["pdf"])
        if file and st.button("✨ Analizar PDF"):
            with st.spinner("Analizando..."):
                try:
                    read = PyPDF2.PdfReader(file)
                    txt = "".join([read.pages[i].extract_text() for i in range(min(len(read.pages), 10))])
                    prompt_pdf = f"Extrae los reactivos de este kit en formato 'Reactivo: Cantidad'.\nTexto: {txt[:20000]}"
                    res_p = model.generate_content(prompt_pdf).text
                    supabase.table("protocolos").insert({"nombre": file.name, "materiales_base": res_p}).execute()
                    st.success("Guardado.")
                    st.rerun()
                except Exception as e: st.error(f"Error: {e}")

    with tab_qr:
        st.markdown("### 🖨️ Generador de Etiquetas QR")
        item_para_qr = st.selectbox("Selecciona un reactivo:", df['nombre'].tolist())
        if item_para_qr:
            fila_item = df[df['nombre'] == item_para_qr].iloc[0]
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(f"LAB_AGUILAR_ID:{fila_item['id']}")
            qr.make(fit=True)
            buf = io.BytesIO()
            qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
            col_img, col_info = st.columns([1, 2])
            with col_img: st.image(buf, width=200)
            with col_info:
                st.download_button(label="⬇️ Descargar", data=buf.getvalue(), file_name=f"QR_{fila_item['nombre']}.png", mime="image/png")

    with tab_bioterio:
        st.markdown("### ❄️ Muestroteca y Almacenamiento")
        df_m_edit = df_muestras[['id', 'codigo_muestra', 'tipo', 'ubicacion', 'fecha_creacion', 'notas']].copy() if not df_muestras.empty else pd.DataFrame(columns=["id", "codigo_muestra", "tipo", "ubicacion", "fecha_creacion", "notas"])
        edited_muestras = st.data_editor(df_m_edit, column_config={"id": st.column_config.NumberColumn("ID", disabled=True)}, use_container_width=True, hide_index=True, num_rows="dynamic")
        if st.button("💾 Guardar Muestras"):
            edited_muestras = edited_muestras.replace({np.nan: None})
            for index, row in edited_muestras.iterrows():
                row_dict = row.dropna().to_dict()
                if 'id' in row_dict:
                    if pd.isna(row_dict['id']) or str(row_dict['id']).strip() == "":
                        del row_dict['id']
                    else:
                        row_dict['id'] = str(row_dict['id'])
                supabase.table("muestras").upsert(row_dict).execute()
            st.success("Muestras guardadas.")
            st.rerun()

with col_chat:
    with st.expander("📸 Escanear Nuevo Reactivo (Click aquí)", expanded=False):
        opcion_foto = st.radio("Método de captura:", ["Subir desde la galería", "Usar Webcam"])
        
        foto = None
        if opcion_foto == "Usar Webcam":
            foto = st.camera_input("📸 Tomar foto")
        else:
            foto = st.file_uploader("📂 Selecciona la foto", type=["jpg", "jpeg", "png"])
        
        if foto is not None:
            img = Image.open(foto).convert('RGB')
            
            with st.spinner("🧠 Leyendo etiqueta..."):
                res_vision = ""
                try:
                    if model is None: raise ValueError("Error de conexión con IA.")
                    prompt_vision = """
                    Analiza la etiqueta de este reactivo de laboratorio. 
                    Extrae los datos y responde EXCLUSIVAMENTE en formato JSON. No incluyas texto extra.
                    Estructura EXACTA:
                    {
                      "nombre": "Nombre del producto",
                      "categoria": "Reactivo",
                      "lote": "Lote",
                      "fecha_vencimiento": "YYYY-MM-DD"
                    }
                    Si no encuentras algo, déjalo así "".
                    """
                    response = model.generate_content([prompt_vision, img])
                    res_vision = response.text
                    match = re.search(r'\{.*\}', res_vision, re.DOTALL)
                    if match: datos_ai = json.loads(match.group())
                    else: raise ValueError("Formato JSON no encontrado.")
                except Exception as e:
                    st.error("⚠️ Problema procesando la imagen.")
                    datos_ai = {}
            
            with st.form("form_nuevo_reactivo_chat"):
                st.markdown("#### 📝 Completar Registro")
                nombre_val = st.text_input("Nombre del Reactivo *", value=datos_ai.get("nombre", ""))
                c1, c2 = st.columns(2)
                cat_val = c1.text_input("Categoría", value=datos_ai.get("categoria", "Reactivo"))
                lote_val = c2.text_input("Lote (Opcional)", value=datos_ai.get("lote", ""))
                
                # Se cargan los datos de la IA pero ahora lo que manda a la BD es lo que esté en estos cuadros de texto
                venc_val = st.text_input("Fecha Vencimiento (YYYY-MM-DD)", value=datos_ai.get("fecha_vencimiento", ""))
                
                zonas_lab = ["Refrigerador 1 (4°C)", "Refrigerador 2 (4°C)", "Freezer -20°C", "Freezer -80°C", "Estante Químicos", "Estante Plásticos", "Mesada", "Otro"]
                ubicacion_val = st.selectbox("Ubicación *", zonas_lab)
                
                c3, c4 = st.columns(2)
                cantidad_val = c3.number_input("Cantidad *", min_value=1, value=1)
                unidad_val = c4.selectbox("Unidad *", ["unidades", "mL", "uL", "cajas", "kits", "g", "mg"])
                
                umb_val = st.number_input("Umbral de alerta por correo", min_value=0, value=1)
                
                if st.form_submit_button("📥 Registrar", type="primary"):
                    if nombre_val:
                        try:
                            # EL TRUCO PARA EVITAR EL ERROR DE DATE
                            fecha_final = venc_val if venc_val.strip() != "" else None

                            nuevo_item = {
                                "nombre": nombre_val, 
                                "categoria": cat_val, 
                                "lote": lote_val, 
                                "fecha_vencimiento": fecha_final, # ¡Ahora envía None en vez de ""!
                                "ubicacion": ubicacion_val, 
                                "cantidad_actual": int(cantidad_val), 
                                "unidad": unidad_val, 
                                "umbral_minimo": int(umb_val)
                            }
                            res_insert = supabase.table("items").insert(nuevo_item).execute()
                            if res_insert.data:
                                id_real = str(res_insert.data[0]['id'])
                                supabase.table("movimiento").insert({
                                    "item_id": id_real, "nombre_item": nombre_val, "cantidad_cambio": int(cantidad_val),
                                    "tipo": "Ingreso (Nuevo)", "usuario": usuario_actual
                                }).execute()
                                st.success(f"✅ ¡Guardado en {ubicacion_val}!")
                                st.rerun()
                        except Exception as error_db:
                            st.error(f"🛑 Error de BD: {error_db}")
                    else:
                        st.error("⚠️ El nombre es obligatorio.")

    st.subheader("💬 Asistente IA")
    chat_box = st.container(height=400, border=True)
    if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "content": f"Hola {usuario_actual}. Listo para asistirte."}]

    with chat_box:
        for m in st.session_state.messages: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎤 Hablar", stop_prompt="🛑 Enviar", just_once=True, key='voice')
    prompt = v_in if v_in else st.chat_input("Escribe aquí o presiona el micrófono...")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").markdown(prompt)
        with st.chat_message("assistant"):
            try:
                ctx = f"Usuario:{usuario_actual}\nInv:{df[['id','nombre','cantidad_actual']].to_dict()}"
                res_ai = model.generate_content(f"Datos: {ctx}\nRUTAS JSON: UPDATE_BATCH, INSERT_NEW, INSERT_MUESTRA\nPrompt: {prompt}").text
                
                if "UPDATE_BATCH:" in res_ai or "INSERT_NEW:" in res_ai or "INSERT_MUESTRA:" in res_ai:
                    if "UPDATE_BATCH:" in res_ai:
                        crear_punto_restauracion(df)
                        m = re.search(r'\[.*\]', res_ai, re.DOTALL)
                        for it in json.loads(m.group().replace("'", '"')):
                            supabase.table("items").update({"cantidad_actual": it["cantidad_final"]}).eq("id", str(it["id"])).execute()
                            supabase.table("movimiento").insert({"item_id": str(it["id"]), "nombre_item": it["nombre"], "cantidad_cambio": it["diferencia"], "tipo": "Salida", "usuario": usuario_actual}).execute()
                        st.markdown("✅ **Inventario actualizado.**")
                    elif "INSERT_MUESTRA:" in res_ai:
                        m = re.search(r'\{.*\}', res_ai, re.DOTALL)
                        new_m = json.loads(m.group().replace("'", '"'))
                        new_m['fecha_creacion'] = str(date.today())
                        supabase.table("muestras").insert(new_m).execute()
                        st.markdown(f"❄️ **Muestra guardada.**")
                    st.rerun()
                else:
                    st.markdown(res_ai)
                    st.session_state.messages.append({"role": "assistant", "content": res_ai})
            except Exception as e: st.error(f"Error IA: {e}")
