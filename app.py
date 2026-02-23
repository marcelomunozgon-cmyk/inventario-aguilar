import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date
import numpy as np
import io
import qrcode
from PIL import Image

# --- 1. CONFIGURACIÓN Y LIMPIEZA ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

if 'model_initialized' not in st.session_state:
    st.cache_resource.clear()
    st.session_state.model_initialized = True

if 'index_orden' not in st.session_state: st.session_state.index_orden = 0
if 'auto_search' not in st.session_state: st.session_state.auto_search = ""

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except Exception as e:
    st.error(f"Error en Secrets. Detalle: {e}")
    st.stop()

@st.cache_resource
def cargar_modelo_definitivo():
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

# SEGURO ANTI-VACÍO
columnas_texto = ['id', 'nombre', 'categoria', 'subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento', 'ubicacion', 'unidad']
for col in columnas_texto:
    if col not in df.columns:
        df[col] = ""

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

df['categoria'] = df['categoria'].replace("", "GENERAL")

try: res_prot = supabase.table("protocolos").select("*").execute(); df_prot = pd.DataFrame(res_prot.data)
except: df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

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
                        if 'id' in row_dict and row_dict['id'] is not None and str(row_dict['id']).strip() != "":
                            row_dict['id'] = str(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                    st.session_state.backup_inventario = None
                    st.success("¡Inventario restaurado con éxito!")
                    st.rerun()
                except Exception as e: st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_historial, tab_editar, tab_orden, tab_importar, tab_qr = st.tabs(["📦 Inv", "⏱️ Hist", "⚙️ Edit", "🗂️ Orden", "📥 Importar", "🖨️ QR"])
    
    # --- PESTAÑA: INVENTARIO ---
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", value=st.session_state.auto_search, key="search")
        if busqueda != st.session_state.auto_search:
            st.session_state.auto_search = busqueda
            
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted([c for c in df_show['categoria'].unique() if str(c).strip() != ""])
        
        if df.empty or len(df) == 0:
            st.info("El inventario está completamente vacío. Ve a la pestaña '📥 Importar' para subir tu Excel.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}"):
                    subset_cat = df_show[df_show['categoria'] == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
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

    # --- PESTAÑA: EDICIÓN MASIVA ---
    with tab_editar:
        st.markdown("### ✍️ Edición Masiva y Radar de Duplicados")
        
        if df.empty or len(df) == 0:
            st.info("No hay datos para editar todavía.")
        else:
            cat_disp = ["Todas"] + sorted([c for c in df['categoria'].unique() if str(c).strip() != ""])
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
                st.session_state.auto_search = ""
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
        st.markdown("### 🗂️ Modo Triage: Revisión 1 a 1")
        if df.empty or len(df) == 0:
            st.info("No hay reactivos en el inventario.")
        elif st.session_state.index_orden >= len(df):
            st.success("🎉 ¡Felicidades! Has revisado todo el inventario.")
            if st.button("🔄 Volver a empezar"): st.session_state.index_orden = 0; st.rerun()
        else:
            item_actual = df.iloc[st.session_state.index_orden]
            sug = sugerir_ubicacion(item_actual['nombre'])
            
            c_prog, c_skip = st.columns([3, 1])
            c_prog.progress(st.session_state.index_orden / len(df))
            c_prog.caption(f"Revisando {st.session_state.index_orden + 1} de {len(df)}")
            
            if c_skip.button("✅ ¡Todo Perfecto! \n(Siguiente)", type="primary", use_container_width=True):
                st.session_state.index_orden += 1; st.rerun()
                
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
                        if str(item_actual['id']).strip() != "":
                            supabase.table("items").update({"nombre": n_nom, "categoria": n_cat, "lote": n_lot, "ubicacion": n_ubi, "cantidad_actual": n_can, "unidad": n_uni}).eq("id", str(item_actual['id'])).execute()
                        st.session_state.index_orden += 1; st.rerun()

    # --- NUEVA PESTAÑA: IMPORTAR EXCEL ---
    with tab_importar:
        st.subheader("🧹 Limpieza y Reinicio")
        with st.container(border=True):
            st.write("⚠️ **Zona de Peligro:** Esta acción es irreversible.")
            check_borrado = st.checkbox("Entiendo que esto eliminará TODOS los registros actuales.")
            
            if st.button("🗑️ ELIMINAR TODO EL INVENTARIO", type="primary", disabled=not check_borrado):
                with st.spinner("Vaciando base de datos (Esto puede tomar unos segundos)..."):
                    try:
                        supabase.table("movimiento").delete().neq("tipo", "BORRADO_SEGURO").execute()
                        supabase.table("items").delete().neq("nombre", "BORRADO_SEGURO").execute()
                        st.success("✅ ¡Base de datos reseteada completamente! Está lista para recibir el Excel.")
                        st.rerun()
                    except Exception as err_borrado:
                        st.error(f"Fallo al borrar la base de datos. Detalle técnico: {err_borrado}")

        st.divider()
        st.markdown("### 📥 Importación Masiva desde Excel")
        st.info("Sube tu archivo `.xlsx`. La aplicación leerá automáticamente tus columnas.")
        
        st.markdown("**Columnas requeridas en tu Excel:** `Nombre`, `Formato`, `cantidad`, `Detalle`, `ubicación`, `categoria`")
        
        archivo_excel = st.file_uploader("Arrastra tu Excel aquí", type=["xlsx", "csv"])
        
        if archivo_excel:
            try:
                if archivo_excel.name.endswith('.csv'):
                    df_nuevo = pd.read_csv(archivo_excel)
                else:
                    df_nuevo = pd.read_excel(archivo_excel, engine='openpyxl')
                
                df_nuevo.columns = df_nuevo.columns.str.strip()
                st.write("👀 Vista previa de lo que se va a cargar:")
                st.dataframe(df_nuevo.head(5))
                
                if st.button("🚀 Subir todo al Inventario", type="primary"):
                    with st.spinner("Limpiando números y guardando en la base de datos..."):
                        df_a_subir = df_nuevo.rename(columns={
                            "Nombre": "nombre",
                            "Formato": "unidad",
                            "cantidad": "cantidad_actual",
                            "Detalle": "lote",
                            "ubicación": "ubicacion",
                            "categoria": "categoria"
                        })
                        
                        df_a_subir = df_a_subir[["nombre", "unidad", "cantidad_actual", "lote", "ubicacion", "categoria"]]
                        
                        # --- EL ESCUDO ANTI-TEXTO EN CANTIDADES ---
                        # Extrae el primer número entero que encuentre en la celda. Si no hay, pone 0.
                        df_a_subir['cantidad_actual'] = df_a_subir['cantidad_actual'].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)
                        
                        df_a_subir = df_a_subir.replace({np.nan: None})
                        
                        records = df_a_subir.to_dict(orient="records")
                        supabase.table("items").insert(records).execute()
                        
                        supabase.table("movimiento").insert({
                            "nombre_item": "Múltiples Reactivos", 
                            "cantidad_cambio": len(records), 
                            "tipo": "Carga Masiva Excel", 
                            "usuario": usuario_actual
                        }).execute()
                        
                        st.success(f"✅ ¡Éxito! Se cargaron {len(records)} reactivos nuevos al inventario.")
                        st.rerun()
            except Exception as e:
                st.error(f"Error al leer el archivo: {e}")

    # --- PESTAÑA: ETIQUETAS QR ---
    with tab_qr:
        st.markdown("### 🖨️ Etiquetas QR")
        item_para_qr = st.selectbox("Selecciona reactivo:", df['nombre'].tolist()) if not df.empty else None
        if item_para_qr:
            fila_item = df[df['nombre'] == item_para_qr].iloc[0]
            if str(fila_item['id']).strip() != "":
                qr = qrcode.QRCode(version=1, box_size=8, border=2); qr.add_data(f"LAB_ID:{fila_item['id']}"); qr.make(fit=True)
                buf = io.BytesIO(); qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
                st.image(buf, width=150)

# --- PANEL IZQUIERDO: CÁMARA Y ASISTENTE IA ---
with col_chat:
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
                    st.success("Guardado!")
                    st.session_state.auto_search = nombre_val
                    st.rerun()

    st.subheader("💬 Secretario de Inventario")
    chat_box = st.container(height=450, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Hola {usuario_actual}. Dime qué tienes en frente y lo registro o corrijo de inmediato en la base de datos."}]

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
            with st.spinner("Procesando..."):
                try:
                    datos_para_ia = df[['id', 'nombre', 'cantidad_actual', 'ubicacion']].to_json(orient='records') if not df.empty else "[]"
                    
                    contexto_instrucciones = f"""
                    Eres un secretario de inventario obediente. REGLA DE ORO: El usuario manda.
                    Revisa este inventario actual: {datos_para_ia}
                    
                    Busca EXACTAMENTE si el reactivo que menciona el usuario ya existe.
                    Si existe, extrae su 'id' numérico. Si NO existe, usa "NUEVO" como id.
                    
                    Tu trabajo es identificar:
                    1. ID (Número existente o "NUEVO")
                    2. Nombre del reactivo
                    3. Cantidad
                    4. Unidad (unidades, bolsas, cajas, mL, g, etc.)
                    5. Ubicación (Cajón X, Mesón, etc.)
                    
                    Si tienes los datos, responde SOLO con este JSON:
                    EJECUTAR_ACCION:{{"id": "...", "nombre": "...", "cantidad": ..., "unidad": "...", "ubicacion": "..."}}
                    """
                    
                    res_ai = model.generate_content(f"{contexto_instrucciones}\nUsuario: {prompt}").text
                    
                    if "EJECUTAR_ACCION:" in res_ai:
                        m = re.search(r'\{.*\}', res_ai, re.DOTALL)
                        if m:
                            data = json.loads(m.group())
                            id_accion = str(data.get('id', 'NUEVO'))
                            
                            if id_accion != "NUEVO" and (not df.empty and id_accion in df['id'].astype(str).values):
                                supabase.table("items").update({
                                    "cantidad_actual": data['cantidad'],
                                    "unidad": data['unidad'],
                                    "ubicacion": data['ubicacion']
                                }).eq("id", id_accion).execute()
                                nombre_real = df[df['id'].astype(str) == id_accion].iloc[0]['nombre']
                                supabase.table("movimiento").insert({"item_id": id_accion, "nombre_item": nombre_real, "cantidad_cambio": data['cantidad'], "tipo": "Actualización IA", "usuario": usuario_actual}).execute()
                                msg = f"✅ ¡Listo! Modifiqué **{nombre_real}**: ahora hay **{data['cantidad']} {data['unidad']}** en el **{data['ubicacion']}**."
                                st.session_state.auto_search = nombre_real
                            else:
                                res_insert = supabase.table("items").insert({
                                    "nombre": data['nombre'],
                                    "cantidad_actual": data['cantidad'],
                                    "unidad": data['unidad'],
                                    "ubicacion": data['ubicacion']
                                }).execute()
                                if res_insert.data:
                                    id_nuevo = str(res_insert.data[0]['id'])
                                    supabase.table("movimiento").insert({"item_id": id_nuevo, "nombre_item": data['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Ingreso Nuevo IA", "usuario": usuario_actual}).execute()
                                msg = f"📦 Nuevo registro creado: **{data['nombre']}** ({data['cantidad']} {data['unidad']}) guardado en el **{data['ubicacion']}**."
                                st.session_state.auto_search = data['nombre']
                            
                            st.markdown(msg)
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            st.rerun() 
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                        
                except Exception as e:
                    st.error(f"Error IA: {e}")
