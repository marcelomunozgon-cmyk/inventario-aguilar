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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. CONFIGURACIÓN Y ESTÉTICA ---
st.set_page_config(page_title="Stck", layout="wide", page_icon="🔬")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    div[data-testid="stContainer"] { border-radius: 10px; border-color: #f0f0f0; }
    .stTabs [data-baseweb="tab-list"] { gap: 15px; border-bottom: 1px solid #f0f0f0; }
    .stTabs [data-baseweb="tab"] { height: 50px; background-color: transparent; border-radius: 4px 4px 0px 0px; color: #666; font-weight: 500; }
    .stTabs [aria-selected="true"] { color: #000; border-bottom: 2px solid #000 !important; }
    .stButton>button { border-radius: 8px; transition: all 0.2s ease; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except Exception as e:
    st.error(f"Error en Secrets: {e}")
    st.stop()

@st.cache_resource
def cargar_modelo_rapido(): return genai.GenerativeModel('gemini-2.5-flash')
model = cargar_modelo_rapido()

# --- 2. SISTEMA DE AUTENTICACIÓN (MULTI-TENANT) ---
if "usuario_autenticado" not in st.session_state:
    st.session_state.usuario_autenticado = None
    st.session_state.lab_id = None

# PANTALLA DE LOGIN
if st.session_state.usuario_autenticado is None:
    st.markdown("<h1 style='text-align: center;'>🔬 Stck</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Gestión Inteligente de Inventario</p>", unsafe_allow_html=True)
    
    col_espacio1, col_login, col_espacio2 = st.columns([1, 2, 1])
    with col_login:
        tab_login, tab_reg = st.tabs(["🔐 Iniciar Sesión", "🏢 Registrar Laboratorio"])
        
        with tab_login:
            with st.container(border=True):
                email_login = st.text_input("Correo corporativo")
                pass_login = st.text_input("Contraseña", type="password")
                if st.button("Acceder a Stck", type="primary", use_container_width=True):
                    with st.spinner("Autenticando..."):
                        try:
                            res = supabase.auth.sign_in_with_password({"email": email_login, "password": pass_login})
                            st.session_state.usuario_autenticado = res.user.email
                            st.session_state.lab_id = res.user.id
                            st.rerun()
                        except Exception as e:
                            st.error("Credenciales incorrectas o usuario no registrado.")
                            
        with tab_reg:
            with st.container(border=True):
                st.info("Crea una cuenta para aislar los datos de tu laboratorio.")
                email_reg = st.text_input("Nuevo Correo")
                pass_reg = st.text_input("Crear Contraseña (mín 6 caracteres)", type="password")
                if st.button("Crear Cuenta", type="primary", use_container_width=True):
                    try:
                        res = supabase.auth.sign_up({"email": email_reg, "password": pass_reg})
                        st.success("¡Laboratorio registrado! Ya puedes iniciar sesión en la pestaña de al lado.")
                    except Exception as e:
                        st.error(f"Fallo al registrar: {e}")
    st.stop()

# --- VARIABLES DE SESIÓN ---
lab_id = st.session_state.lab_id

if 'index' in st.query_params: st.session_state.index_orden = int(st.query_params['index'])
elif 'index_orden' not in st.session_state: st.session_state.index_orden = 0
if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if 'triage_foto_procesada' not in st.session_state: st.session_state.triage_foto_procesada = -1
if 'triage_datos_ia' not in st.session_state: st.session_state.triage_datos_ia = {}
if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None
def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

def enviar_alerta_gmail(df_alertas, operador, titulo="Reporte de Laboratorio"):
    try:
        sender = st.secrets["EMAIL_SENDER"]
        password = st.secrets["EMAIL_PASSWORD"]
        receiver = st.secrets.get("EMAIL_RECEIVER", sender)
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = f"🔬 {titulo} - Stck"
        html_table = df_alertas[['nombre', 'ubicacion', 'posicion_caja', 'cantidad_actual', 'umbral_minimo', 'unidad']].to_html(index=False)
        body = f"<html><body><h2>{titulo}</h2>{html_table}<br><p><i>Reporte generado por: {operador} (Stck)</i></p></body></html>"
        msg.attach(MIMEText(body, 'html'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Fallo al enviar correo. Detalle: {e}")
        return False

# --- LÓGICA DE DATOS AISLADA (MULTI-TENANT) ---
zonas_lab_fijas = ["Mesón", "Refrigerador 1 (4°C)", "Refrigerador 2 (4°C)", "Freezer -20°C", "Freezer -80°C", "Estante Químicos", "Estante Plásticos", "Gabinete Inflamables", "Otro"]
cajones = [f"Cajón {i}" for i in range(1, 42)]
zonas_lab = zonas_lab_fijas + cajones
unidades_list = ["unidades", "mL", "uL", "cajas", "kits", "g", "mg", "bolsas"]

def aplicar_estilos_inv(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    if cant <= 0: return ['background-color: #ffeaea; color: #a00'] * len(row)
    if umb > 0 and cant <= umb: return ['background-color: #fff8e6; color: #850'] * len(row)
    return [''] * len(row)

res_items = supabase.table("items").select("*").eq("lab_id", lab_id).execute()
df = pd.DataFrame(res_items.data)

for col in ['id', 'nombre', 'categoria', 'subcategoria', 'lote', 'ubicacion', 'posicion_caja', 'unidad']:
    if col not in df.columns: df[col] = ""
    df[col] = df[col].astype(str).replace(["nan", "None"], "")

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

df['categoria'] = df['categoria'].replace("", "GENERAL")

try: 
    res_prot = supabase.table("protocolos").select("*").eq("lab_id", lab_id).execute()
    df_prot = pd.DataFrame(res_prot.data)
except: 
    df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

# --- INTERFAZ PRINCIPAL ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Stck")
with col_user: 
    # Menú de Trazabilidad Interna
    equipo = ["Marcelo Muñoz", "Rodrigo Aguilar", "Marjorie", "Adrián", "Tesista / Estudiante", "Otro"]
    operador_actual = st.selectbox("👤 Operador Actual:", equipo, index=0)
    
    if st.button("🚪 Cerrar Sesión del Lab"):
        st.session_state.usuario_autenticado = None
        st.session_state.lab_id = None
        st.rerun()

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción Masiva", type="secondary"):
            with st.spinner("Restaurando..."):
                try:
                    backup_df = st.session_state.backup_inventario.replace({np.nan: None})
                    for index, row in backup_df.iterrows():
                        row_dict = row.to_dict()
                        for key, value in row_dict.items():
                            if pd.isna(value) or str(value).strip() == "": row_dict[key] = None
                        if 'id' in row_dict and row_dict['id'] is not None:
                            row_dict['id'] = str(row_dict['id'])
                            row_dict['lab_id'] = lab_id 
                            supabase.table("items").upsert(row_dict).execute()
                    st.session_state.backup_inventario = None
                    st.success("Restaurado")
                    st.rerun()
                except: st.error("Error al restaurar")

    tab_inventario, tab_protocolos, tab_editar, tab_orden, tab_importar = st.tabs(["📦 Inv", "🧪 Protocolos", "⚙️ Edit", "🗂️ Triage", "📥 Carga"])
    
    with tab_inventario:
        df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0)]
        if not df_criticos.empty:
            st.error("🚨 **Reactivos Críticos**")
            st.dataframe(df_criticos[['nombre', 'ubicacion', 'posicion_caja', 'cantidad_actual', 'umbral_minimo', 'unidad']], use_container_width=True, hide_index=True)
            if st.button("📧 Enviar Alerta Crítica", type="primary"):
                if enviar_alerta_gmail(df_criticos, operador_actual, "Alerta de Stock Crítico"): st.success("Enviado")

        busqueda = st.text_input("🔍 Buscar...", value=st.session_state.auto_search)
        if busqueda != st.session_state.auto_search: st.session_state.auto_search = busqueda
            
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(list(set([str(c).strip() for c in df_show['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
        
        if df.empty: st.info("Inventario vacío.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}"):
                    subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                    st.dataframe(subset_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'posicion_caja', 'lote']].style.apply(aplicar_estilos_inv, axis=1), use_container_width=True, hide_index=True)

    with tab_protocolos:
        st.markdown("### 🧬 Ejecución de Kits")
        tab_ejecutar, tab_crear = st.tabs(["🚀 Ejecutar", "📝 Nuevo"])
        with tab_ejecutar:
            if df_prot.empty: st.info("Sin protocolos.")
            else:
                p_sel = st.selectbox("Protocolo:", df_prot['nombre'].tolist())
                n_muestras = st.number_input("Muestras:", min_value=1, value=1)
                if st.button("🔍 Previsualizar"):
                    info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                    descuentos = []
                    for linea in info_p.split('\n'):
                        if ":" in linea:
                            partes = linea.split(":")
                            item_db = df[df['nombre'].str.contains(partes[0].strip(), case=False, na=False)]
                            if not item_db.empty:
                                descuentos.append({"id": str(item_db.iloc[0]['id']), "Reactivo": item_db.iloc[0]['nombre'], "Stock": item_db.iloc[0]['cantidad_actual'], "Descuento": float(partes[1].strip()) * n_muestras, "Unidad": item_db.iloc[0]['unidad']})
                    if descuentos:
                        st.dataframe(pd.DataFrame(descuentos), hide_index=True)
                        if st.button("✅ Descontar del Inventario", type="primary"):
                            crear_punto_restauracion(df)
                            for d in descuentos:
                                supabase.table("items").update({"cantidad_actual": int(d["Stock"] - d["Descuento"])}).eq("id", d["id"]).execute()
                                # Registro con el Operador Físico
                                supabase.table("movimiento").insert({"item_id": d["id"], "nombre_item": d["Reactivo"], "cantidad_cambio": -d["Descuento"], "tipo": f"Uso Protocolo: {p_sel}", "usuario": operador_actual, "lab_id": lab_id}).execute()
                            st.rerun()

        with tab_crear:
            with st.form("form_nuevo_prot"):
                n_prot = st.text_input("Nombre (Ej: PCR Mix)")
                mat_base = st.text_area("Reactivos (Nombre : Cantidad)", placeholder="Taq Polimerasa : 0.5")
                if st.form_submit_button("💾 Guardar"):
                    supabase.table("protocolos").insert({"nombre": n_prot, "materiales_base": mat_base, "lab_id": lab_id}).execute()
                    st.rerun()

    with tab_editar:
        st.markdown("### ✍️ Acciones Masivas")
        if not df.empty:
            cat_disp = ["Todas"] + sorted(list(set([str(c).strip() for c in df['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
            filtro_cat = st.selectbox("Filtrar por Categoría:", cat_disp)
            
            df_edit_view = (df if filtro_cat == "Todas" else df[df['categoria'].astype(str).str.strip() == filtro_cat]).copy()
            df_edit_view.insert(0, '✅ Seleccionar', False)
            cols_finales = ['✅ Seleccionar', 'nombre', 'cantidad_actual', 'umbral_minimo', 'unidad', 'ubicacion', 'posicion_caja', 'lote', 'id']
            
            edited_df = st.data_editor(
                df_edit_view[cols_finales].copy(), 
                column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, 
                use_container_width=True, hide_index=True
            )
            
            seleccionados = edited_df[edited_df['✅ Seleccionar'] == True]
            
            if not seleccionados.empty:
                st.markdown("---")
                st.success(f"🛠️ **{len(seleccionados)} seleccionados:**")
                c_acc1, c_acc2, c_acc3 = st.columns([1, 1, 1.5])
                
                if c_acc1.button("🗑️ Eliminar Selección", use_container_width=True):
                    crear_punto_restauracion(df)
                    with st.spinner("Borrando..."):
                        for id_borrar in seleccionados['id']:
                            supabase.table("items").delete().eq("id", str(id_borrar)).execute()
                    st.rerun()
                
                if c_acc2.button("📧 Compartir Reporte", use_container_width=True):
                    if enviar_alerta_gmail(seleccionados, operador_actual, "Reporte Especial de Reactivos"):
                        st.success("Enviado.")

                nueva_ub = c_acc3.selectbox("📦 Mover todos a...", ["(Elige ubicación)"] + zonas_lab, label_visibility="collapsed")
                if nueva_ub != "(Elige ubicación)":
                    if c_acc3.button(f"Mover a {nueva_ub}", type="primary", use_container_width=True):
                        crear_punto_restauracion(df)
                        with st.spinner("Trasladando..."):
                            for id_mover in seleccionados['id']:
                                supabase.table("items").update({"ubicacion": nueva_ub}).eq("id", str(id_mover)).execute()
                        st.rerun()

            st.markdown("---")
            if st.button("💾 Guardar Ediciones Manuales"):
                crear_punto_restauracion(df)
                modificados = edited_df[edited_df['✅ Seleccionar'] == False].drop(columns=['✅ Seleccionar'])
                for _, row in modificados.iterrows():
                    d = row.replace({np.nan: None}).to_dict()
                    if 'id' in d and str(d['id']).strip(): 
                        d['lab_id'] = lab_id 
                        supabase.table("items").upsert(d).execute()
                st.rerun()

    with tab_orden:
        st.markdown("### 📸 Triage con IA")
        if df.empty: st.info("Inventario vacío.")
        elif st.session_state.index_orden >= len(df):
            if st.button("🔄 Reiniciar"): st.session_state.index_orden = 0; st.query_params['index'] = 0; st.rerun()
        else:
            item_actual = df.iloc[st.session_state.index_orden]
            if st.session_state.triage_foto_procesada != st.session_state.index_orden: st.session_state.triage_datos_ia = item_actual.to_dict()
            st.progress(st.session_state.index_orden / len(df))
            st.markdown(f"**Validando:** {item_actual['nombre']}")
            
            col_f, col_d = st.columns([1, 1.2], gap="large")
            with col_f:
                foto_ord = st.camera_input("Capturar Etiqueta", key=f"cam_{st.session_state.index_orden}")
                if st.button("⏭️ Saltar", use_container_width=True): st.session_state.index_orden += 1; st.query_params['index'] = st.session_state.index_orden; st.rerun()
                if foto_ord and st.session_state.triage_foto_procesada != st.session_state.index_orden:
                    with st.spinner("Leyendo..."):
                        try:
                            res_v = model.generate_content([f"Extrae de '{item_actual['nombre']}': categoria, lote, unidad, cantidad_actual. JSON: {{\"categoria\": \"\", \"lote\": \"\", \"unidad\": \"\", \"cantidad_actual\": 0}}", Image.open(foto_ord).convert('RGB')]).text
                            for k, v in json.loads(re.search(r'\{.*\}', res_v, re.DOTALL).group()).items():
                                if v and str(v).strip() not in ["", "0", "None"]: st.session_state.triage_datos_ia[k] = v
                            st.session_state.triage_foto_procesada = st.session_state.index_orden
                            st.rerun()
                        except: st.error("No se pudo leer.")

            with col_d:
                dat = st.session_state.triage_datos_ia
                with st.form(f"form_{st.session_state.index_orden}"):
                    n_n = st.text_input("Nombre", dat.get('nombre', ''))
                    c_1, c_2 = st.columns([1.5, 1])
                    n_u = c_1.selectbox("Zona", zonas_lab, index=zonas_lab.index(dat.get('ubicacion')) if dat.get('ubicacion') in zonas_lab else zonas_lab.index("Mesón"))
                    n_p = c_2.text_input("Caja", dat.get('posicion_caja', ''))
                    n_c = st.number_input("Cantidad", value=int(dat.get('cantidad_actual', 0)))
                    n_un = st.selectbox("Unidad", unidades_list, index=unidades_list.index(dat.get('unidad')) if dat.get('unidad') in unidades_list else 0)
                    if st.form_submit_button("💾 Guardar", type="primary", use_container_width=True):
                        supabase.table("items").update({"nombre": n_n, "ubicacion": n_u, "posicion_caja": n_p, "cantidad_actual": n_c, "unidad": n_un}).eq("id", str(item_actual['id'])).execute()
                        st.session_state.index_orden += 1; st.query_params['index'] = st.session_state.index_orden; st.rerun()

    with tab_importar:
        st.subheader("🧹 Limpieza")
        if st.button("🗑️ VACIAR INVENTARIO", type="primary", disabled=not st.checkbox("Confirmar")):
            supabase.table("movimiento").delete().eq("lab_id", lab_id).execute()
            supabase.table("items").delete().eq("lab_id", lab_id).execute()
            st.rerun()

        archivo_excel = st.file_uploader("Sube tu Excel", type=["xlsx", "csv"])
        if archivo_excel and st.button("🚀 Subir al Inventario"):
            df_n = pd.read_csv(archivo_excel) if archivo_excel.name.endswith('.csv') else pd.read_excel(archivo_excel, engine='openpyxl')
            df_s = df_n.rename(columns={"Nombre": "nombre", "Formato": "unidad", "cantidad": "cantidad_actual", "Detalle": "lote", "ubicación": "ubicacion", "categoria": "categoria"})
            if 'posicion_caja' not in df_s.columns: df_s['posicion_caja'] = ""
            df_s['cantidad_actual'] = df_s['cantidad_actual'].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)
            df_s['lab_id'] = lab_id 
            supabase.table("items").insert(df_s[["nombre", "unidad", "cantidad_actual", "lote", "ubicacion", "posicion_caja", "categoria", "lab_id"]].replace({np.nan: None}).to_dict(orient="records")).execute()
            st.rerun()

# --- PANEL IA ---
with col_chat:
    st.markdown("### 💬 Secretario IA")
    chat_box = st.container(height=500, border=False)
    
    if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "content": f"Conectado a la base segura. ¿Qué guardamos hoy?"}]
    for m in st.session_state.messages:
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎙️ Hablar", stop_prompt="⏹️ Enviar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Saqué 2 buffer...")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box: st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    d_ia = df[['id', 'nombre', 'cantidad_actual', 'ubicacion', 'posicion_caja']].to_json(orient='records') if not df.empty else "[]"
                    res_ai = model.generate_content(f"Inventario: {d_ia}\nUsa id si existe, si no 'NUEVO'. JSON: EJECUTAR_ACCION:{{\"id\":\"\",\"nombre\":\"\",\"cantidad\":0,\"unidad\":\"\",\"ubicacion\":\"\",\"posicion_caja\":\"\"}}\nUsuario: {prompt}").text
                    if "EJECUTAR_ACCION:" in res_ai:
                        data = json.loads(re.search(r'\{.*\}', res_ai, re.DOTALL).group())
                        id_ac = str(data.get('id', 'NUEVO'))
                        if id_ac != "NUEVO" and (not df.empty and id_ac in df['id'].astype(str).values):
                            supabase.table("items").update({"cantidad_actual": data['cantidad'], "ubicacion": data['ubicacion'], "posicion_caja": data.get('posicion_caja', '')}).eq("id", id_ac).execute()
                            itm = supabase.table("items").select("*").eq("id", id_ac).execute().data[0]
                            # Registro con el Operador Físico
                            supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": itm['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Acción IA", "usuario": operador_actual, "lab_id": lab_id}).execute()
                            msg = f"✅ **Actualizado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        else:
                            res_ins = supabase.table("items").insert({"nombre": data['nombre'], "cantidad_actual": data['cantidad'], "unidad": data['unidad'], "ubicacion": data['ubicacion'], "posicion_caja": data.get('posicion_caja', ''), "lab_id": lab_id}).execute()
                            if res_ins.data:
                                itm = res_ins.data[0]
                                # Registro con el Operador Físico
                                supabase.table("movimiento").insert({"item_id": str(itm['id']), "nombre_item": itm['nombre'], "cantidad_cambio": itm['cantidad_actual'], "tipo": "Nuevo IA", "usuario": operador_actual, "lab_id": lab_id}).execute()
                                msg = f"📦 **Creado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        
                        st.session_state.auto_search = itm['nombre']
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.rerun() 
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e: st.error(f"Error IA: {e}")
                    
