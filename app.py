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

# --- 1. CONFIGURACIÓN Y LIMPIEZA ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

if 'model_initialized' not in st.session_state:
    st.cache_resource.clear()
    st.session_state.model_initialized = True

if 'index_orden' not in st.session_state:
    st.session_state.index_orden = 0

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except Exception as e:
    st.error(f"Error en Secrets: Verifica tus credenciales de Supabase y Gemini. Detalle: {e}")
    st.stop()

@st.cache_resource
def cargar_modelo_definitivo():
    # Usamos el modelo PRO de tu cuenta facturada para máxima inteligencia
    return genai.GenerativeModel('gemini-2.5-pro')

model = cargar_modelo_definitivo()

if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None

def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

# --- 2. LÓGICA DE DATOS, UBICACIONES Y ESTILOS ---
zonas_lab_fijas = ["Mesón", "Refrigerador 1 (4°C)", "Refrigerador 2 (4°C)", "Freezer -20°C", "Freezer -80°C", "Estante Químicos", "Estante Plásticos", "Gabinete Inflamables", "Otro"]
cajones = [f"Cajón {i}" for i in range(1, 42)]
zonas_lab = zonas_lab_fijas + cajones
unidades_list = ["unidades", "mL", "uL", "cajas", "kits", "g", "mg", "bolsas"]

def sugerir_ubicacion(nombre):
    n = str(nombre).lower()
    if any(sal in n for sal in ["cloruro", "sulfato", "fosfato", "sodio", "potasio", "nacl", "sal "]): return "Cajón 37"
    if any(bio in n for bio in ["primer", "oligo", "dnazima", "dna", "rna", "taq", "polimerasa"]): return "Freezer -20°C"
    if any(solv in n for solv in ["alcohol", "etanol", "metanol", "isopropanol", "fenol", "cloroformo"]): return "Gabinete Inflamables"
    if any(prot in n for prot in ["anticuerpo", "bsa", "suero", "fbs"]): return "Refrigerador 1 (4°C)"
    return "Mesón"

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

# Cargar Tablas
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
    # Botón de Deshacer Global
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
                    st.success("¡Inventario restaurado con éxito!")
                    st.rerun()
                except Exception as e: st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_historial, tab_editar, tab_orden, tab_protocolos, tab_qr = st.tabs(["📦 Inv", "⏱️ Hist", "⚙️ Edit", "🗂️ Orden", "🧪 Prot", "🖨️ QR"])
    
    # --- PESTAÑA: INVENTARIO ---
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(df_show['categoria'].unique())
        for cat in categorias:
            with st.expander(f"📁 {cat}"):
                subset_cat = df_show[df_show['categoria'] == cat]
                st.dataframe(subset_cat[[c for c in subset_cat.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]].style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)
                
    # --- PESTAÑA: HISTORIAL ---
    with tab_historial:
        try:
            res_mov = supabase.table("movimiento").select("*").order("created_at", desc=True).limit(25).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                st.dataframe(df_mov[['Fecha', 'usuario', 'nombre_item', 'tipo', 'cantidad_cambio']], use_container_width=True, hide_index=True)
        except: st.info("No hay movimientos registrados.")

    # --- PESTAÑA: EDICIÓN MASIVA Y RADAR ---
    with tab_editar:
        st.markdown("### ✍️ Edición Masiva y Radar de Duplicados")
        cat_disp = ["Todas"] + sorted(df['categoria'].unique().tolist())
        filtro_cat = st.selectbox("📍 Filtrar por Categoría:", cat_disp)
        df_filtro = df if filtro_cat == "Todas" else df[df['categoria'] == filtro_cat]
        
        df_edit_view = df_filtro.copy()
        df_edit_view['❌ Eliminar'] = False
        cols_finales = ['❌ Eliminar', 'id', 'nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'lote']
        
        st.info("💡 Marca la casilla roja 'Eliminar' y presiona Guardar para borrar reactivos.")
        edited_df = st.data_editor(df_edit_view[cols_finales].copy(), column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, use_container_width=True, hide_index=True, num_rows="dynamic")
        
        if st.button("💾 Guardar Cambios Generales"):
            crear_punto_restauracion(df)
            edited_df = edited_df.replace({np.nan: None})
            eliminados = edited_df[edited_df['❌ Eliminar'] == True]
            modificados = edited_df[edited_df['❌ Eliminar'] == False].drop(columns=['❌ Eliminar'])
            for _, row in eliminados.iterrows():
                if pd.notna(row['id']) and str(row['id']).strip() != "": supabase.table("items").delete().eq("id", str(row['id'])).execute()
            for _, row in modificados.iterrows():
                d = row.dropna().to_dict()
                if 'id' in d and str(d['id']).strip() != "": supabase.table("items").upsert(d).execute()
            st.success("Guardado exitoso.")
            st.rerun()

        st.markdown("---")
        if st.button("🔎 Radar de Duplicados (IA)"):
            with st.spinner("🧠 Buscando duplicados..."):
                try:
                    prompt_dup = f"Analiza: {df[['id', 'nombre', 'lote', 'ubicacion']].to_json(orient='records')}. Extrae duplicados reales (no 1X vs 10X). JSON: [{{'mantener_id':'id1', 'eliminar_id':'id2', 'razon':'...txt...'}}]"
                    res_dup = model.generate_content(prompt_dup).text
                    st.session_state.duplicados = json.loads(re.search(r'\[.*\]', res_dup, re.DOTALL).group())
                except: st.session_state.duplicados = []
        if "duplicados" in st.session_state and st.session_state.duplicados:
            for i, dup in enumerate(list(st.session_state.duplicados)):
                im = df[df['id'].astype(str) == str(dup['mantener_id'])].iloc[0] if not df[df['id'].astype(str) == str(dup['mantener_id'])].empty else None
                ie = df[df['id'].astype(str) == str(dup['eliminar_id'])].iloc[0] if not df[df['id'].astype(str) == str(dup['eliminar_id'])].empty else None
                if im is not None and ie is not None:
                    st.warning(f"**Detectado:** {dup.get('razon')}")
                    c1, c2 = st.columns(2)
                    c1.success(f"✅ MANTENER: {im['nombre']} ({im['lote']})")
                    c2.error(f"🗑️ ELIMINAR: {ie['nombre']} ({ie['lote']})")
                    b1, b2 = st.columns(2)
                    if b1.button("🗑️ Borrar", key=f"d_{i}"): supabase.table("items").delete().eq("id", str(dup['eliminar_id'])).execute(); st.session_state.duplicados.pop(i); st.rerun()
                    if b2.button("❌ Son distintos", key=f"k_{i}"): st.session_state.duplicados.pop(i); st.rerun()

    # --- PESTAÑA: MODO ORDEN 1 A 1 ---
    with tab_orden:
        st.markdown("### 🗂️ Modo Triage: Revisión 1 a 1 (Editable)")
        
        if df.empty:
            st.info("No hay reactivos en el inventario.")
        elif st.session_state.index_orden >= len(df):
            st.success("🎉 ¡Felicidades! Has revisado todo el inventario.")
            if st.button("🔄 Volver a empezar"):
                st.session_state.index_orden = 0
                st.rerun()
        else:
            item_actual = df.iloc[st.session_state.index_orden]
            sug = sugerir_ubicacion(item_actual['nombre'])
            
            c_prog, c_skip = st.columns([3, 1])
            c_prog.progress(st.session_state.index_orden / len(df))
            c_prog.caption(f"Revisando {st.session_state.index_orden + 1} de {len(df)}")
            
            if c_skip.button("✅ ¡Todo Perfecto! \n(Siguiente)", type="primary", use_container_width=True):
                st.session_state.index_orden += 1
                st.rerun()
                
            st.markdown("---")

            with st.container(border=True):
                st.markdown(f"#### Editando: **{item_actual['nombre']}**")
                
                with st.form(f"form_orden_abierto_{st.session_state.index_orden}"):
                    c1, c2 = st.columns(2)
                    n_nom = c1.text_input("Nombre del Reactivo", value=item_actual['nombre'])
                    n_cat = c2.text_input("Categoría", value=item_actual['categoria'])
                    
                    c3, c4 = st.columns(2)
                    n_lot = c3.text_input("Lote", value=item_actual['lote'])
                    
                    idx_ub = zonas_lab.index(item_actual['ubicacion']) if item_actual['ubicacion'] in zonas_lab else 0
                    n_ubi = c4.selectbox(f"Ubicación (Sugerencia IA: {sug})", zonas_lab, index=idx_ub)
                    
                    c5, c6 = st.columns(2)
                    n_can = c5.number_input("Cantidad Actual", value=int(item_actual['cantidad_actual']))
                    idx_un = unidades_list.index(item_actual['unidad']) if item_actual['unidad'] in unidades_list else 0
                    n_uni = c6.selectbox("Unidad", unidades_list, index=idx_un)
                    
                    if st.form_submit_button("💾 Guardar Cambios y Siguiente", use_container_width=True):
                        supabase.table("items").update({
                            "nombre": n_nom,
                            "categoria": n_cat,
                            "lote": n_lot,
                            "ubicacion": n_ubi,
                            "cantidad_actual": n_can,
                            "unidad": n_uni
                        }).eq("id", str(item_actual['id'])).execute()
                        st.session_state.index_orden += 1
                        st.rerun()

    # --- PESTAÑA: PROTOCOLOS ---
    with tab_protocolos:
        st.markdown("### ▶️ Ejecución de Protocolos")
        c1, c2 = st.columns([2, 1])
        with c1: p_sel = st.selectbox("Protocolo:", df_prot['nombre'] if not df_prot.empty else ["Vacío"])
        with c2: n_muestras = st.number_input("N° Muestras:", min_value=1, value=1)
        if st.button("🚀 Ejecutar Protocolo", type="primary"):
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

    # --- PESTAÑA: ETIQUETAS QR ---
    with tab_qr:
        st.markdown("### 🖨️ Etiquetas QR")
        item_para_qr = st.selectbox("Selecciona reactivo:", df['nombre'].tolist())
        if item_para_qr:
            fila_item = df[df['nombre'] == item_para_qr].iloc[0]
            qr = qrcode.QRCode(version=1, box_size=8, border=2); qr.add_data(f"LAB_ID:{fila_item['id']}"); qr.make(fit=True)
            buf = io.BytesIO(); qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
            st.image(buf, width=150)

# --- PANEL IZQUIERDO: CÁMARA Y ASISTENTE IA ---
with col_chat:
    
    # 1. ESCÁNER DE CÁMARA
    with st.expander("📸 Escanear Nuevo Reactivo (Foto)", expanded=False):
        foto = st.camera_input("📸 Tomar foto") or st.file_uploader("📂 Galería", type=["jpg", "jpeg", "png"])
        if foto is not None:
            img = Image.open(foto).convert('RGB')
            with st.spinner("🧠 Leyendo etiqueta con Gemini 2.5 Pro..."):
                try:
                    res_vision = model.generate_content(["Extrae nombre, categoria, lote, fecha_vencimiento (YYYY-MM-DD) en JSON exacto. Si no hay, usa ''.", img]).text
                    datos_ai = json.loads(re.search(r'\{.*\}', res_vision, re.DOTALL).group())
                except: datos_ai = {}
            with st.form("form_nuevo"):
                nombre_val = st.text_input("Nombre *", value=datos_ai.get("nombre", ""))
                ubicacion_val = st.selectbox("Ubicación *", zonas_lab, index=zonas_lab.index(sugerir_ubicacion(nombre_val)) if sugerir_ubicacion(nombre_val) in zonas_lab else 0)
                cantidad_val = st.number_input("Cantidad *", min_value=1, value=1)
                if st.form_submit_button("📥 Registrar", type="primary") and nombre_val:
                    res_insert = supabase.table("items").insert({"nombre": nombre_val, "ubicacion": ubicacion_val, "cantidad_actual": cantidad_val}).execute()
                    if res_insert.data:
                        id_real = str(res_insert.data[0]['id'])
                        supabase.table("movimiento").insert({"item_id": id_real, "nombre_item": nombre_val, "cantidad_cambio": cantidad_val, "tipo": "Ingreso", "usuario": usuario_actual}).execute()
                    st.success("Guardado!"); st.rerun()

    # 2. SECRETARIO DE INVENTARIO (Chat / Voz)
    st.subheader("💬 Secretario de Inventario")
    
    chat_box = st.container(height=450, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": f"Hola {usuario_actual}. Dime qué tienes en frente y lo registro o corrijo de inmediato en la base de datos."}
        ]

    for m in st.session_state.messages:
        with chat_box:
            st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎤 Dictar", stop_prompt="🛑 Parar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Hay 2 bolsas de eppendorf en el cajón 25")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            try:
                # Instrucciones estrictas para que sea un secretario obediente
                contexto_instrucciones = f"""
                Eres un secretario de inventario obediente. Tu REGLA DE ORO es: El usuario siempre tiene la razón sobre el mundo real.
                Si el usuario dice que hay algo en una ubicación, tú ACTUALIZAS la base de datos con esa info.
                
                NO discutas cantidades antiguas ni digas que la info es incorrecta.
                Tu trabajo es identificar:
                1. Nombre del reactivo (ej. Eppendorf 1.5).
                2. Cantidad (ej. 2).
                3. Unidad/Formato (ej. bolsas).
                4. Ubicación (ej. Cajón 25).
                
                Si falta algún dato (como la ubicación o cantidad), pregunta amablemente.
                Si tienes todos los datos, responde SOLO con este formato JSON:
                EJECUTAR_ACCION:{{"accion": "upsert", "nombre": "...", "cantidad": ..., "unidad": "...", "ubicacion": "..."}}
                """
                
                res_ai = model.generate_content(f"{contexto_instrucciones}\nInventario actual: {df[['id','nombre','ubicacion']].to_dict()}\nUsuario: {prompt}").text
                
                if "EJECUTAR_ACCION:" in res_ai:
                    m = re.search(r'\{.*\}', res_ai, re.DOTALL)
                    if m:
                        data = json.loads(m.group())
                        
                        # Buscar coincidencia flexible en la base de datos
                        item_match = df[df['nombre'].str.contains(data['nombre'], case=False, na=False)]
                        
                        registro = {
                            "nombre": data['nombre'],
                            "cantidad_actual": data['cantidad'],
                            "unidad": data['unidad'],
                            "ubicacion": data['ubicacion']
                        }
                        
                        if not item_match.empty:
                            id_match = str(item_match.iloc[0]['id'])
                            # Actualizar existente
                            supabase.table("items").update(registro).eq("id", id_match).execute()
                            # Registrar movimiento
                            supabase.table("movimiento").insert({"item_id": id_match, "nombre_item": data['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Actualización IA", "usuario": usuario_actual}).execute()
                            msg = f"✅ Entendido. He actualizado **{data['nombre']}**: ahora hay **{data['cantidad']} {data['unidad']}** en el **{data['ubicacion']}**."
                        else:
                            # Insertar nuevo
                            res_insert = supabase.table("items").insert(registro).execute()
                            if res_insert.data:
                                id_nuevo = str(res_insert.data[0]['id'])
                                supabase.table("movimiento").insert({"item_id": id_nuevo, "nombre_item": data['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Ingreso Nuevo IA", "usuario": usuario_actual}).execute()
                            msg = f"📦 Nuevo registro: **{data['nombre']}** guardado en el **{data['ubicacion']}**."
                        
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.rerun()
                else:
                    st.markdown(res_ai)
                    st.session_state.messages.append({"role": "assistant", "content": res_ai})
                    
            except Exception as e:
                st.error(f"Error IA: {e}")
