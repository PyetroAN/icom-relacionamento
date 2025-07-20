# /api/main.py

import os
import re
import io
import json
import uuid
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, abort, session, jsonify)
from werkzeug.utils import secure_filename
from datetime import datetime
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import numbers
from functools import wraps
import pdfplumber
import firebase_admin
from firebase_admin import credentials, firestore, storage

# --- CONFIGURAÇÃO INICIAL (Firebase & Flask) ---
key_path = os.path.join(os.path.dirname(__file__), 'firebase-service-account.json')

# Pega o nome do "bucket" e a chave secreta de variáveis de ambiente (vamos configurar no Vercel)
FIREBASE_BUCKET_NAME = os.environ.get('FIREBASE_BUCKET_NAME')
FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'chave-local-para-teste')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'mudar_esta_senha')

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_BUCKET_NAME})

db = firestore.client() # Firestore Database
bucket = storage.bucket() # Firebase Storage

# Renomeamos `app` para `api` para o padrão do Vercel
api = Flask(__name__, template_folder='../templates', static_folder='../static')
api.config['SECRET_KEY'] = FLASK_SECRET_KEY

# --- MODELO LÓGICO ---
# Não temos mais a classe `Chamado(db.Model)`.
# As funções irão criar/ler dicionários (objetos) e enviá-los/buscá-los do Firestore.

# --- LÓGICA DE SEGURANÇA ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
    
# --- FUNÇÕES DE LÓGICA DE NEGÓCIO ---
def extrair_codigo_fornecedor(texto_pagina):
    #... (código inalterado)
    pass
def processar_pdf(caminho_pdf, apenas_validar=False):
    #... (código inalterado)
    pass
def gerar_excel(dados):
    #... (código inalterado)
    pass
    
# CÓDIGO COMPLETO DAS FUNÇÕES AUXILIARES
def extrair_codigo_fornecedor(texto_pagina):
    match = re.search(r'C[oó]digo Fornecedor:\s*Igual a\s*(\S+)', texto_pagina)
    return match.group(1) if match else None

def processar_pdf(temp_path, apenas_validar=False):
    try:
        with pdfplumber.open(temp_path) as pdf:
            codigo = extrair_codigo_fornecedor(pdf.pages[0].extract_text(x_tolerance=2))
            if not codigo: return None, None
            if apenas_validar: return codigo, None
            dados = []
            for page in pdf.pages:
                tabelas = page.extract_tables()
                for t in tabelas:
                    if t:
                        header_string = "".join(str(c) for c in t[0])
                        if "Código Fornecedor" in header_string: dados.extend(t[1:])
                        else: dados.extend(t)
            cols = ['Código Fornecedor', 'Plu', 'Descrição dos Produtos', 'Código Barras', '% IPI', 'Atualizar NCM', 'Atualizar Quant. caixa', 'Preço Atual']
            df = pd.DataFrame(dados); df.dropna(how='all', inplace=True)
            if df.shape[1] < len(cols): df = df.reindex(columns=range(len(cols)))
            df.columns = cols
            df.dropna(subset=['Código Fornecedor'], inplace=True); df = df[df['Código Fornecedor'] != '']
            df['Descrição dos Produtos'] = df['Descrição dos Produtos'].str.replace('\n', ' ', regex=False)
            df.fillna('', inplace=True)
            return codigo, df
    except Exception as e:
        print(f"Erro processando PDF: {e}")
        return None, None

def gerar_excel(dados):
    df = pd.DataFrame(dados); output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        cabecalho = {'CÑdigo Interno do Fornecedor': [], 'Descri Üo do Produto': [], 'CÑdigo de Barras': [], ' Valor Unitário': [], '% IPI': [], 'NCM': [], 'Quantidade MÕnima': [], 'desconto': [], 'promoção': [], 'data desconto': [], 'extra': []}
        df_final = pd.DataFrame(cabecalho)
        df_final['CÑdigo Interno do Fornecedor'] = df['Código Fornecedor']; df_final['Descri Üo do Produto'] = df['Descrição dos Produtos']; df_final['CÑdigo de Barras'] = df['Código Barras']; df_final[' Valor Unitário'] = df['Preço Atual']; df_final['Quantidade MÕnima'] = df['Atualizar Quant. caixa']
        df_final.to_excel(writer, sheet_name='Sheet1', index=False)
        ws = writer.sheets['Sheet1']
        for col in ['A', 'B', 'C']:
            for cell in ws[col]: cell.number_format = '# ?/?'
        for col in ['D', 'G']:
            for cell in ws[col][1:]:
                try: cell.value = float(str(cell.value).replace('.', '').replace(',', '.'))
                except (ValueError, TypeError): cell.value = 0.0
                cell.number_format = '#,##0.00'
    output.seek(0)
    return output


# --- ROTAS DO SITE ---

@api.route('/')
def tela_x(): return render_template('tela_x.html')

@api.route('/validar-pdf', methods=['POST'])
def validar_pdf():
    f = request.files.get('pdf_file')
    if not f or not f.filename.lower().endswith('.pdf'): return jsonify({'success': False, 'message': 'Arquivo inválido.'})
    
    filename_original = secure_filename(f.filename)
    
    # Criar um nome de arquivo único para evitar conflitos no Storage
    unique_id = str(uuid.uuid4())
    filename_no_storage = f"{unique_id}_{filename_original}"

    # Usa um stream em memória para não precisar salvar localmente no servidor serverless
    temp_stream = io.BytesIO(f.read())
    temp_stream.seek(0)
    
    codigo, _ = processar_pdf(temp_stream, apenas_validar=True)
    
    if codigo:
        temp_stream.seek(0)
        # Faz o upload do PDF para o Firebase Storage
        blob = bucket.blob(filename_no_storage)
        blob.upload_from_file(temp_stream, content_type='application/pdf')
        
        return jsonify({'success': True, 'codigo_fornecedor': codigo, 'storage_filename': filename_no_storage})
    else:
        return jsonify({'success': False, 'message': 'PDF inválido ou não foi possível ler o código do fornecedor.'})

@api.route('/enviar-para-edicao', methods=['POST'])
def enviar_para_edicao():
    storage_filename = request.form.get('storage_filename')
    if not storage_filename:
        flash("Erro: nome do arquivo não encontrado."); return redirect(url_for('tela_x'))

    blob = bucket.blob(storage_filename)
    if not blob.exists():
        flash("Erro: arquivo PDF não encontrado no servidor. Por favor, envie novamente."); return redirect(url_for('tela_x'))
    
    # Baixa o PDF do Storage para a memória para processar
    temp_stream = io.BytesIO(blob.download_as_bytes())
    
    codigo, df_produtos = processar_pdf(temp_stream)
    if df_produtos is None:
        flash("Erro fatal ao processar o PDF."); return redirect(url_for('tela_x'))
    
    novo_chamado_dados = {
        "nome_solicitante": request.form['nome_solicitante'], "email": request.form['email'],
        "razao_social": request.form['razao_social'], "codigo_fornecedor_pdf": codigo,
        "dados": df_produtos.to_dict('records'), "status": 'Aguardando Edição',
        "pdf_storage_path": storage_filename, # Salva o caminho do arquivo no Storage
        "hora_envio": datetime.utcnow()
    }
    
    # Adiciona os dados ao Firestore. A coleção é como uma tabela, e o document() cria um ID único.
    update_time, doc_ref = db.collection('chamados').add(novo_chamado_dados)
    
    return redirect(url_for('tela_editar', chamado_id=doc_ref.id))
    
# --- O resto das rotas... login, logout, salvar, admin, etc... precisam ser adaptadas ---
# Elas usarão `db.collection('chamados').document(chamado_id).get()` para buscar
# e `...document(chamado_id).set()` para atualizar.

# Código completo das rotas restantes
@api.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD: session['logged_in'] = True; flash('Login bem-sucedido!'); return redirect(url_for('tela_y'))
        else: flash('Senha inválida.', 'error')
    return render_template('login.html')

@api.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(url_for('login'))

@api.route('/sucesso')
def sucesso(): return render_template('sucesso.html')

@api.route('/admin')
@login_required
def tela_y():
    chamados_ref = db.collection('chamados')
    pendentes_query = chamados_ref.where('status', '==', 'Pendente').order_by('hora_envio', direction=firestore.Query.DESCENDING).stream()
    concluidos_query = chamados_ref.where('status', '==', 'Concluído').order_by('hora_conclusao', direction=firestore.Query.DESCENDING).stream()

    pendentes = [dict(id=doc.id, **doc.to_dict()) for doc in pendentes_query]
    concluidos = [dict(id=doc.id, **doc.to_dict()) for doc in concluidos_query]
    return render_template('tela_y.html', pendentes=pendentes, concluidos=concluidos)

@api.route('/editar/<string:chamado_id>')
@login_required
def tela_editar(chamado_id):
    doc = db.collection('chamados').document(chamado_id).get()
    if not doc.exists: abort(404)
    chamado = dict(id=doc.id, **doc.to_dict())
    if chamado.get('status') == 'Concluído': flash('Chamado concluído não pode ser editado.'); return redirect(url_for('tela_y'))
    return render_template('editar.html', chamado=chamado)

@api.route('/salvar/<string:chamado_id>', methods=['POST'])
@login_required
def salvar_chamado(chamado_id):
    doc_ref = db.collection('chamados').document(chamado_id); dados = []
    indices = [int(k.split('_')[-1]) for k in request.form if k.startswith('codigo_fornecedor_')]
    if not indices: flash('Nenhum dado recebido.', 'error'); return redirect(url_for('tela_y'))
    for i in range(max(indices) + 1):
        if f'remover_{i}' in request.form: continue
        linha = {'Código Fornecedor': request.form.get(f'codigo_fornecedor_{i}', '').upper(),'Descrição dos Produtos': request.form.get(f'descricao_{i}', '').upper(),'Código Barras': request.form.get(f'codigo_barras_{i}', ''),'Atualizar Quant. caixa': request.form.get(f'quant_caixa_{i}', '0,00'),'Preço Atual': request.form.get(f'preco_atual_{i}', '0,00')}
        if linha['Código Fornecedor'].strip() and linha['Descrição dos Produtos'].strip(): dados.append(linha)
    doc_ref.update({'dados': dados, 'status': 'Pendente'}); return redirect(url_for('sucesso'))

@api.route('/download/<string:chamado_id>')
@login_required
def download_excel(chamado_id):
    doc = db.collection('chamados').document(chamado_id).get()
    if not doc.exists: abort(404)
    chamado = doc.to_dict(); excel_file = gerar_excel(chamado.get('dados'))
    nome_arquivo = f"relatorio_{chamado.get('razao_social').replace(' ','_')}_{chamado_id}.xlsx"
    return send_file(excel_file, as_attachment=True, download_name=nome_arquivo, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def apagar_pdf(storage_path):
    if not storage_path: return
    try:
        blob = bucket.blob(storage_path)
        if blob.exists(): blob.delete()
    except Exception as e:
        print(f"Erro ao deletar arquivo {storage_path} do Storage: {e}")

@api.route('/concluir/<string:chamado_id>')
@login_required
def concluir_chamado(chamado_id):
    doc_ref = db.collection('chamados').document(chamado_id); doc = doc_ref.get()
    if not doc.exists: abort(404)
    chamado = doc.to_dict(); apagar_pdf(chamado.get('pdf_storage_path'))
    doc_ref.update({'status': 'Concluído', 'hora_conclusao': datetime.utcnow()}); flash(f'Chamado #{chamado_id[:6]}... concluído.'); return redirect(url_for('tela_y'))

@api.route('/deletar/<string:chamado_id>')
@login_required
def deletar_chamado(chamado_id):
    doc_ref = db.collection('chamados').document(chamado_id); doc = doc_ref.get()
    if not doc.exists: abort(404)
    chamado = doc.to_dict(); apagar_pdf(chamado.get('pdf_storage_path'))
    doc_ref.delete(); flash(f'Chamado #{chamado_id[:6]}... deletado.'); return redirect(url_for('tela_y'))