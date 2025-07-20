# CÓDIGO COMPLETO app.py v5
import os, re, io
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from datetime import datetime
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import numbers
from functools import wraps
import pdfplumber

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta-final'
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///local_db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'mudar_esta_senha')

class Chamado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_solicitante = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    razao_social = db.Column(db.String(150), nullable=False)
    codigo_fornecedor_pdf = db.Column(db.String(50))
    dados = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(30), default='Pendente')
    hora_envio = db.Column(db.DateTime, default=datetime.utcnow)
    hora_conclusao = db.Column(db.DateTime, nullable=True)
    pdf_filename = db.Column(db.String(255), nullable=True)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
def extrair_codigo_fornecedor(texto_pagina):
    match = re.search(r'C[oó]digo Fornecedor:\s*Igual a\s*(\S+)', texto_pagina)
    return match.group(1) if match else None
def processar_pdf(caminho_pdf, apenas_validar=False):
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto_p1 = pdf.pages[0].extract_text(x_tolerance=2)
            codigo = extrair_codigo_fornecedor(texto_p1)
            if not codigo: return None, None
            if apenas_validar: return codigo, None
            dados = []
            for page in pdf.pages:
                tabelas = page.extract_tables()
                for t in tabelas:
                    if t:
                        if "Código Fornecedor" in str(t[0]): dados.extend(t[1:])
                        else: dados.extend(t)
            cols = ['Código Fornecedor', 'Plu', 'Descrição dos Produtos', 'Código Barras', '% IPI', 'Atualizar NCM', 'Atualizar Quant. caixa', 'Preço Atual']
            df = pd.DataFrame(dados).dropna(how='all')
            if df.shape[1] < len(cols): df = df.reindex(columns=range(len(cols)))
            df.columns = cols
            df.dropna(subset=['Código Fornecedor'], inplace=True); df = df[df['Código Fornecedor'] != '']
            df['Descrição dos Produtos'] = df['Descrição dos Produtos'].str.replace('\n', ' ', regex=False)
            df.fillna('', inplace=True)
            return codigo, df
    except Exception: return None, None
def gerar_excel(dados):
    df = pd.DataFrame(dados)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        cabecalho = {'CÑdigo Interno do Fornecedor': [], 'Descri Üo do Produto': [], 'CÑdigo de Barras': [], ' Valor Unitário': [], '% IPI': [], 'NCM': [], 'Quantidade MÕnima': [], 'desconto': [], 'promoção': [], 'data desconto': [], 'extra': []}
        df_final = pd.DataFrame(cabecalho)
        df_final['CÑdigo Interno do Fornecedor'] = df['Código Fornecedor']
        df_final['Descri Üo do Produto'] = df['Descrição dos Produtos']
        df_final['CÑdigo de Barras'] = df['Código Barras']
        df_final[' Valor Unitário'] = df['Preço Atual']
        df_final['Quantidade MÕnima'] = df['Atualizar Quant. caixa']
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

@app.route('/')
def tela_x(): return render_template('tela_x.html')

@app.route('/validar-pdf', methods=['POST'])
def validar_pdf():
    f = request.files.get('pdf_file')
    if not f or not f.filename.lower().endswith('.pdf'): return jsonify({'success': False, 'message': 'Arquivo inválido.'})
    filename = secure_filename(f.filename); filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename); f.save(filepath)
    codigo, _ = processar_pdf(filepath, apenas_validar=True)
    if codigo: return jsonify({'success': True, 'codigo_fornecedor': codigo, 'filename': filename})
    else:
        try: os.remove(filepath)
        except OSError: pass
        return jsonify({'success': False, 'message': 'PDF inválido.'})

@app.route('/enviar-para-edicao', methods=['POST'])
def enviar_para_edicao():
    filename = request.form.get('pdf_filename')
    if not filename: flash("Erro: nome do arquivo PDF não encontrado."); return redirect(url_for('tela_x'))
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath): flash("Erro: PDF não encontrado. Envie novamente."); return redirect(url_for('tela_x'))
    codigo, df_produtos = processar_pdf(filepath)
    if df_produtos is None: flash("Erro fatal ao processar o PDF."); return redirect(url_for('tela_x'))
    novo_chamado = Chamado(nome_solicitante=request.form['nome_solicitante'], email=request.form['email'], razao_social=request.form['razao_social'], codigo_fornecedor_pdf=codigo, dados=df_produtos.to_dict('records'), status='Aguardando Edição', pdf_filename=filename)
    db.session.add(novo_chamado); db.session.commit()
    return redirect(url_for('tela_editar', chamado_id=novo_chamado.id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD: session['logged_in'] = True; flash('Login bem-sucedido!'); return redirect(url_for('tela_y'))
        else: flash('Senha inválida.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(url_for('login'))
@app.route('/sucesso')
def sucesso(): return render_template('sucesso.html')

@app.route('/admin')
@login_required
def tela_y():
    pendentes = Chamado.query.filter_by(status='Pendente').order_by(Chamado.hora_envio.desc()).all()
    concluidos = Chamado.query.filter_by(status='Concluído').order_by(Chamado.hora_conclusao.desc()).all()
    return render_template('tela_y.html', pendentes=pendentes, concluidos=concluidos)

@app.route('/editar/<int:chamado_id>')
@login_required
def tela_editar(chamado_id):
    chamado = db.session.get(Chamado, chamado_id) or abort(404)
    if chamado.status == 'Concluído': flash('Chamado concluído não pode ser editado.'); return redirect(url_for('tela_y'))
    return render_template('editar.html', chamado=chamado)

@app.route('/salvar/<int:chamado_id>', methods=['POST'])
@login_required
def salvar_chamado(chamado_id):
    chamado = db.session.get(Chamado, chamado_id) or abort(404); dados = []
    indices = [int(k.split('_')[-1]) for k in request.form if k.startswith('codigo_fornecedor_')]
    if not indices: flash('Nenhum dado recebido.', 'error'); return redirect(url_for('tela_y'))
    for i in range(max(indices) + 1):
        if f'remover_{i}' in request.form: continue
        linha = {'Código Fornecedor': request.form.get(f'codigo_fornecedor_{i}', '').upper(),'Descrição dos Produtos': request.form.get(f'descricao_{i}', '').upper(),'Código Barras': request.form.get(f'codigo_barras_{i}', ''),'Atualizar Quant. caixa': request.form.get(f'quant_caixa_{i}', '0,00'),'Preço Atual': request.form.get(f'preco_atual_{i}', '0,00')}
        if linha['Código Fornecedor'].strip() and linha['Descrição dos Produtos'].strip(): dados.append(linha)
    chamado.dados = dados; chamado.status = 'Pendente'; db.session.commit()
    return redirect(url_for('sucesso'))

@app.route('/download/<int:chamado_id>')
@login_required
def download_excel(chamado_id):
    chamado = db.session.get(Chamado, chamado_id) or abort(404); excel_file = gerar_excel(chamado.dados)
    nome_arquivo = f"relatorio_{chamado.razao_social.replace(' ','_')}_{chamado_id}.xlsx"
    return send_file(excel_file, as_attachment=True, download_name=nome_arquivo, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def apagar_pdf(chamado):
    if chamado.pdf_filename:
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], chamado.pdf_filename)
            if os.path.exists(filepath): os.remove(filepath)
        except OSError as e: print(f"Erro ao deletar arquivo {chamado.pdf_filename}: {e}")

@app.route('/concluir/<int:chamado_id>')
@login_required
def concluir_chamado(chamado_id):
    chamado = db.session.get(Chamado, chamado_id) or abort(404); apagar_pdf(chamado)
    chamado.status = 'Concluído'; chamado.hora_conclusao = datetime.utcnow(); db.session.commit()
    flash(f'Chamado #{chamado_id} concluído e PDF limpo.'); return redirect(url_for('tela_y'))

@app.route('/deletar/<int:chamado_id>')
@login_required
def deletar_chamado(chamado_id):
    chamado = db.session.get(Chamado, chamado_id) or abort(404); apagar_pdf(chamado)
    db.session.delete(chamado); db.session.commit()
    flash(f'Chamado #{chamado_id} deletado permanentemente.'); return redirect(url_for('tela_y'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)