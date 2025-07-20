# app.py

import os
import re
import pandas as pd
import pdfplumber
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, abort, session, jsonify) # Adicionado 'jsonify'
from werkzeug.utils import secure_filename
from datetime import datetime
import io
from openpyxl import Workbook
from openpyxl.styles import numbers
from functools import wraps

# --- Configuração Inicial ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-forte-para-as-sessoes'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ADMIN_PASSWORD = 'resenha123' # <-- TROQUE ESTA SENHA!

# --- "Banco de Dados" Simulado ---
chamados = []
chamado_id_counter = 0

# --- Lógica de Segurança ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Funções de Lógica de Negócio ---

def extrair_codigo_fornecedor(texto_pagina):
    match = re.search(r'C[oó]digo Fornecedor:\s*Igual a\s*(\S+)', texto_pagina) # Alterado para aceitar não-espaços
    return match.group(1) if match else None

def processar_pdf(caminho_pdf, apenas_validar=False):
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            primeira_pagina_texto = pdf.pages[0].extract_text(x_tolerance=2)
            codigo_fornecedor = extrair_codigo_fornecedor(primeira_pagina_texto)
            if not codigo_fornecedor:
                return None, None # PDF não parece ser válido

            if apenas_validar:
                return codigo_fornecedor, None

            dados_completos = []
            for page in pdf.pages:
                tabelas = page.extract_tables()
                for tabela in tabelas:
                    if tabela:
                        if "Código Fornecedor" in str(tabela[0]):
                            dados_completos.extend(tabela[1:])
                        else:
                            dados_completos.extend(tabela)
            colunas_pdf = [
                'Código Fornecedor', 'Plu', 'Descrição dos Produtos', 'Código Barras',
                '% IPI', 'Atualizar NCM', 'Atualizar Quant. caixa', 'Preço Atual'
            ]
            df = pd.DataFrame(dados_completos).dropna(how='all')
            if df.shape[1] < len(colunas_pdf):
                for i in range(df.shape[1], len(colunas_pdf)):
                    df[i] = None
            df.columns = colunas_pdf
            df = df[df['Código Fornecedor'].notna() & (df['Código Fornecedor'] != '')]
            df['Descrição dos Produtos'] = df['Descrição dos Produtos'].str.replace('\n', ' ', regex=False)
            df = df.fillna('')
            return codigo_fornecedor, df
    except Exception as e:
        print(f"Erro ao processar PDF: {e}")
        return None, None
        
def gerar_excel(dados_chamado):
    # (Código inalterado)
    df_produtos = pd.DataFrame(dados_chamado)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    cabecalho_final = {'CÑdigo Interno do Fornecedor': [], 'Descri Üo do Produto': [], 'CÑdigo de Barras': [],' Valor Unitário': [], '% IPI': [], 'NCM': [], 'Quantidade MÕnima': [], 'desconto': [], 'promoção': [], 'data desconto': [], 'extra': []}
    df_final = pd.DataFrame(cabecalho_final)
    df_final['CÑdigo Interno do Fornecedor'] = df_produtos['Código Fornecedor']
    df_final['Descri Üo do Produto'] = df_produtos['Descrição dos Produtos']
    df_final['CÑdigo de Barras'] = df_produtos['Código Barras']
    df_final[' Valor Unitário'] = df_produtos['Preço Atual']
    df_final['Quantidade MÕnima'] = df_produtos['Atualizar Quant. caixa']
    df_final.to_excel(writer, sheet_name='Sheet1', index=False)
    workbook = writer.book
    worksheet = writer.sheets['Sheet1']
    for col in ['A', 'B', 'C']:
        for cell in worksheet[col]:
            cell.number_format = '# ?/?'
    for col in ['D', 'G']:
        for cell in worksheet[col][1:]:
            valor_numerico = 0.0
            if isinstance(cell.value, str):
                try: valor_numerico = float(cell.value.replace('.', '').replace(',', '.'))
                except (ValueError, AttributeError): valor_numerico = 0.0
            elif isinstance(cell.value, (int, float)): valor_numerico = cell.value
            cell.value = valor_numerico
            cell.number_format = '#,##0.00'
    writer.close()
    output.seek(0)
    return output

# --- Rotas (Páginas do site) ---

@app.route('/', methods=['GET'])
def tela_x():
    return render_template('tela_x.html')

@app.route('/validar-pdf', methods=['POST'])
def validar_pdf():
    if 'pdf_file' not in request.files:
        return jsonify({'success': False, 'message': 'Nenhum arquivo enviado.'})
    file = request.files['pdf_file']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'message': 'Arquivo inválido. Apenas PDFs são permitidos.'})
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    codigo, _ = processar_pdf(filepath, apenas_validar=True)
    
    if codigo:
        return jsonify({'success': True, 'codigo_fornecedor': codigo, 'filename': filename})
    else:
        os.remove(filepath) # Limpa o arquivo inválido
        return jsonify({'success': False, 'message': 'PDF inválido ou não foi possível ler o código do fornecedor.'})

@app.route('/enviar-para-edicao', methods=['POST'])
def enviar_para_edicao():
    global chamado_id_counter, chamados
    filename = request.form.get('pdf_filename')
    if not filename:
        flash("Erro: nome do arquivo PDF não encontrado.")
        return redirect(url_for('tela_x'))

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        flash("Erro: arquivo PDF não encontrado no servidor. Por favor, envie novamente.")
        return redirect(url_for('tela_x'))

    codigo_fornecedor, df_produtos = processar_pdf(filepath)
    if df_produtos is None:
        flash("Erro ao processar o PDF. Tente novamente.")
        return redirect(url_for('tela_x'))
        
    chamado_id_counter += 1
    novo_chamado = {
        "id": chamado_id_counter,
        "nome_solicitante": request.form['nome_solicitante'], "email": request.form['email'],
        "razao_social": request.form['razao_social'], # Atualizado
        "codigo_fornecedor_pdf": codigo_fornecedor,
        "dados": df_produtos.to_dict('records'),
        "status": "Aguardando Edição", "hora_envio": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }
    chamados.append(novo_chamado)
    
    return redirect(url_for('tela_editar', chamado_id=novo_chamado['id']))

@app.route('/sucesso')
def sucesso():
    return render_template('sucesso.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('tela_y'))
        else:
            flash('Senha inválida.', 'error')
    return render_template('login.html')

# (O resto do código é o mesmo da versão anterior, começando por /logout até o final)
# Para evitar um bloco de código gigante, mantenha as rotas abaixo como estavam
# A rota /salvar/ foi ajustada para redirecionar para /sucesso

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def tela_y():
    pendentes = [c for c in chamados if c['status'] == 'Pendente']
    concluidos = [c for c in chamados if c['status'] == 'Concluído']
    return render_template('tela_y.html', pendentes=pendentes, concluidos=concluidos)

@app.route('/editar/<int:chamado_id>', methods=['GET'])
@login_required
def tela_editar(chamado_id):
    chamado = next((c for c in chamados if c['id'] == chamado_id), None)
    if not chamado or chamado['status'] == 'Concluído': 
        abort(404)
    return render_template('editar.html', chamado=chamado)

@app.route('/salvar/<int:chamado_id>', methods=['POST'])
@login_required
def salvar_chamado(chamado_id):
    chamado = next((c for c in chamados if c['id'] == chamado_id), None)
    if not chamado: abort(404)
        
    dados_processados = []
    indices = [int(k.split('_')[-1]) for k in request.form if k.startswith('codigo_fornecedor_')]
    if not indices:
        flash('Nenhum dado recebido.', 'error')
        return redirect(url_for('tela_y'))
    total_linhas = max(indices) + 1
    
    for i in range(total_linhas):
        if f'remover_{i}' in request.form:
            continue
        linha = {
            'Código Fornecedor': request.form.get(f'codigo_fornecedor_{i}', '').upper(),
            'Descrição dos Produtos': request.form.get(f'descricao_{i}', '').upper(),
            'Código Barras': request.form.get(f'codigo_barras_{i}', ''),
            'Atualizar Quant. caixa': request.form.get(f'quant_caixa_{i}', '0,00'),
            'Preço Atual': request.form.get(f'preco_atual_{i}', '0,00')
        }
        if linha['Código Fornecedor'].strip() and linha['Descrição dos Produtos'].strip():
            dados_processados.append(linha)
    
    chamado['dados'] = dados_processados
    chamado['status'] = 'Pendente'
    
    return redirect(url_for('sucesso')) # <<< MUDANÇA IMPORTANTE AQUI!

@app.route('/download/<int:chamado_id>')
@login_required
def download_excel(chamado_id):
    chamado = next((c for c in chamados if c['id'] == chamado_id), None)
    if not chamado: abort(404)
    excel_file = gerar_excel(chamado['dados'])
    nome_arquivo = f"relatorio_fornecedor_{chamado['codigo_fornecedor_pdf']}_{chamado_id}.xlsx"
    return send_file(excel_file, as_attachment=True, download_name=nome_arquivo, 
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/concluir/<int:chamado_id>')
@login_required
def concluir_chamado(chamado_id):
    chamado = next((c for c in chamados if c['id'] == chamado_id), None)
    if chamado:
        chamado['status'] = 'Concluído'
        chamado['hora_conclusao'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        flash(f'Chamado #{chamado_id} concluído.')
    return redirect(url_for('tela_y'))

@app.route('/deletar/<int:chamado_id>')
@login_required
def deletar_chamado(chamado_id):
    global chamados
    chamados = [c for c in chamados if c['id'] != chamado_id]
    flash(f'Chamado #{chamado_id} deletado permanentemente.')
    return redirect(url_for('tela_y'))

if __name__ == '__main__':
    app.run(debug=True)